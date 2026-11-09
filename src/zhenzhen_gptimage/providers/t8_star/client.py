"""T8 Star synchronous-generation wire adapter. It never retries a request."""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import ssl
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import httpx

from zhenzhen_gptimage.generation.models import MODELS
from zhenzhen_gptimage.generation.snapshot import RequestSnapshot

MAX_BODY = 64 * 1024 * 1024
MAX_IMAGES = 4
MAX_REFERENCE_BYTES = 20 * 1024 * 1024
MAX_REFERENCES_TOTAL = 40 * 1024 * 1024
_PNG = b'\x89PNG\r\n\x1a\n'

@dataclass(frozen=True)
class ImageSource:
    url: str | None = None
    data: bytes | None = None
    revised_prompt: str | None = None
    base64_invalid: bool = False

@dataclass(frozen=True)
class ParsedResponse:
    images: tuple[ImageSource, ...]
    metadata: dict

class ProviderError(Exception):
    """Never store upstream message, request bodies, URLs or credentials here."""
    def __init__(self, category: str, *, safe_retry: bool = False, status: int | None = None):
        super().__init__(category)
        self.category = category
        self.safe_retry = safe_retry
        self.status = status

def _url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme in ('http', 'https') and parsed.netloc else None

def _reference_url(data: bytes) -> str:
    if not isinstance(data, bytes) or not data.startswith(_PNG):
        raise ValueError('only frozen PNG reference bytes are supported')
    if len(data) > MAX_REFERENCE_BYTES:
        raise ValueError('reference image exceeds 20 MiB')
    return 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')

def build_request(snapshot: RequestSnapshot, references: tuple[bytes, ...] = ()) -> tuple[str, dict]:
    """Build the endpoint and a strict whitelist of provider fields from a frozen snapshot."""
    if snapshot.channel not in ('images', 'flux', 'chat') or snapshot.resolved_model not in MODELS:
        raise ValueError('invalid channel or model')
    if not snapshot.prompt or len(snapshot.prompt.encode('utf-8')) > 32768:
        raise ValueError('invalid prompt')
    if len(references) != len(snapshot.reference_hashes) or len(references) > 4:
        raise ValueError('references do not match snapshot')
    if any(not isinstance(data, bytes) for data in references):
        raise ValueError('reference data must be bytes')
    if sum(len(data) for data in references) > MAX_REFERENCES_TOTAL:
        raise ValueError('reference images exceed 40 MiB')
    if references and snapshot.channel == 'flux':
        raise ValueError('flux does not support reference images')
    # Refuse changed files: snapshot hashes identify the frozen bytes, not paths.
    import hashlib
    if any(hashlib.sha256(data).hexdigest() != digest for data, digest in zip(references, snapshot.reference_hashes)):
        raise ValueError('reference bytes do not match frozen snapshot')
    urls = [_reference_url(data) for data in references]
    if snapshot.channel == 'chat':
        if snapshot.width is not None or snapshot.height is not None:
            raise ValueError('chat does not accept dimensions')
        content = snapshot.prompt if not urls else [
            {'type':'text', 'text':snapshot.prompt},
            *({'type':'image_url', 'image_url':{'url':url}} for url in urls),
        ]
        return '/v1/chat/completions', {'model':snapshot.resolved_model,
            'messages':[{'role':'user', 'content':content}], 'stream':False}
    if snapshot.width is None or snapshot.height is None or not (1 <= snapshot.width <= 4096 and 1 <= snapshot.height <= 4096):
        raise ValueError('images and flux require valid dimensions')
    suffix = '' if max(snapshot.width, snapshot.height) <= 1024 else '-2k' if max(snapshot.width, snapshot.height) <= 2048 else '-4k'
    if not snapshot.resolved_model.endswith(suffix) or (not suffix and snapshot.resolved_model.endswith(('-2k','-4k'))):
        raise ValueError('snapshot model and dimensions disagree')
    # T8 Star's image endpoint appends the flare 4k suffix based on size.
    # Sending the suffix again produces the unavailable "-4k-4k" route.
    # Keep the internal model unchanged for routing, history and retries.
    wire_model = ('gpt-image-2.6-flare' if snapshot.resolved_model == 'gpt-image-2.6-flare-4k'
                  else snapshot.resolved_model)
    body = {'model':wire_model, 'prompt':snapshot.prompt, 'size':f'{snapshot.width}x{snapshot.height}'}
    if urls:
        body['image'] = urls
    return '/v1/images/generations', body

def parse_response(channel: Literal['images','flux','chat'], raw: bytes) -> ParsedResponse:
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError('expected object')
        images: list[ImageSource] = []
        if channel in ('images','flux'):
            entries = obj.get('data')
            if not isinstance(entries, list) or not entries or len(entries) > MAX_IMAGES:
                raise ValueError('invalid image list')
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError('invalid image entry')
                url = _url(entry.get('url'))
                encoded = entry.get('b64_json')
                content = None
                invalid = False
                if isinstance(encoded, str) and encoded:
                    try:
                        content = base64.b64decode(encoded, validate=True)
                        if not content:
                            raise ValueError('empty image')
                    except (binascii.Error, ValueError):
                        invalid = True
                if content is None and url is None:
                    raise ValueError('no usable image')
                revised = entry.get('revised_prompt')
                images.append(ImageSource(url=url, data=content,
                    revised_prompt=revised if isinstance(revised, str) else None, base64_invalid=invalid))
        elif channel == 'chat':
            choices = obj.get('choices')
            if not isinstance(choices, list):
                raise ValueError('invalid choices')
            seen: set[str] = set()
            for choice in choices:
                message = choice.get('message') if isinstance(choice, dict) else None
                content = message.get('content') if isinstance(message, dict) else None
                if not isinstance(content, str):
                    continue
                for match in re.finditer(r'!\[[^\]]*\]\((https?://[^\s)]+)\)', content):
                    url = _url(match.group(1))
                    if url and url not in seen:
                        images.append(ImageSource(url=url))
                        seen.add(url)
            if not images or len(images) > MAX_IMAGES:
                raise ValueError('invalid image list')
        else:
            raise ValueError('invalid channel')
        metadata = {key:obj[key] for key in ('id','model','created','usage') if key in obj}
        return ParsedResponse(tuple(images), metadata)
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError('RESPONSE_INVALID') from exc

def classify_http_status(status: int) -> ProviderError:
    if status in (400, 401, 403, 422):
        return ProviderError('PROVIDER_REJECTED', status=status)
    return ProviderError('SUBMISSION_UNKNOWN', status=status)

def classify_exception(exc: BaseException) -> ProviderError:
    # The transport must certify that no request bytes reached the provider.
    # ConnectError can also wrap TLS/configuration errors, which should not retry.
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, ssl.SSLError):
            return ProviderError('CONFIG_ERROR')
        current = current.__cause__ or current.__context__
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout)):
        return ProviderError('CONNECT_NOT_SENT', safe_retry=True)
    return ProviderError('SUBMISSION_UNKNOWN')

class T8StarClient:
    def __init__(self, client: httpx.AsyncClient, api_key: str, *, response_limit: int = MAX_BODY, request_limit: int = MAX_BODY):
        if not api_key.strip() or not 1 <= response_limit <= MAX_BODY or not 1 <= request_limit <= MAX_BODY:
            raise ValueError('invalid provider configuration')
        self._client = client
        self._key = api_key
        self._response_limit = response_limit
        self._request_limit = request_limit

    async def generate(self, snapshot: RequestSnapshot, references: tuple[bytes, ...] = (), *, remaining_seconds: float) -> bytes:
        """One request only. Returns complete raw response for durable storage before parsing."""
        path, body = build_request(snapshot, references)
        encoded = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(encoded) > self._request_limit:
            raise ValueError('provider request exceeds configured limit')
        if remaining_seconds <= 0:
            raise ProviderError('DEADLINE_EXCEEDED')
        try:
            async with asyncio.timeout(remaining_seconds):
                async with self._client.stream('POST', 'https://ai.t8star.org' + path,
                    headers={'Authorization':'Bearer ' + self._key, 'Content-Type':'application/json'},
                    content=encoded, timeout=httpx.Timeout(remaining_seconds), follow_redirects=False) as response:
                    if response.status_code != 200:
                        raise classify_http_status(response.status_code)
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(chunks) + len(chunk) > self._response_limit:
                            raise ProviderError('RESPONSE_INVALID', status=200)
                        chunks.extend(chunk)
                    return bytes(chunks)
        except ProviderError:
            raise
        except (httpx.HTTPError, TimeoutError) as exc:
            raise classify_exception(exc) from exc

    async def generate_stream(self, snapshot: RequestSnapshot, references: tuple[bytes, ...] = (), *, remaining_seconds: float, write_chunk) -> None:
        """One paid request, forwarding bounded decoded chunks to a durable sink."""
        path, body = build_request(snapshot, references)
        encoded = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(encoded) > self._request_limit:
            raise ValueError('provider request exceeds configured limit')
        if remaining_seconds <= 0:
            raise ProviderError('DEADLINE_EXCEEDED')
        try:
            async with asyncio.timeout(remaining_seconds):
                async with self._client.stream('POST', 'https://ai.t8star.org' + path,
                    headers={'Authorization':'Bearer ' + self._key, 'Content-Type':'application/json'},
                    content=encoded, timeout=httpx.Timeout(remaining_seconds), follow_redirects=False) as response:
                    if response.status_code != 200:
                        raise classify_http_status(response.status_code)
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self._response_limit:
                            raise ProviderError('RESPONSE_INVALID', status=200)
                        await write_chunk(chunk)
        except ProviderError:
            raise
        except (httpx.HTTPError, TimeoutError) as exc:
            raise classify_exception(exc) from exc
