"""Download, validate and publish generated images without provider credentials."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import httpx
from PIL import Image, UnidentifiedImageError
from zhenzhen_gptimage.bootstrap.config import Limits
from zhenzhen_gptimage.providers.t8_star.client import parse_response
from .storage import ResourceLimitError, _directory


class ImageResultError(ValueError):
    """Image content or its requested dimensions are invalid."""

    def __init__(self, message: str, *, artifacts=()):
        super().__init__(message)
        self.artifacts = tuple(artifacts)


class ImageDownloadError(RuntimeError):
    """Download failed without including signed URLs in the error."""


@dataclass(frozen=True)
class PublishedImage:
    image_index: int
    local_path: str
    sha256: str
    mime_type: str
    bytes: int
    width: int
    height: int
    revised_prompt: str | None


def _safe_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError('invalid URL')
        # Accessing port validates its syntax as well.
        _ = parsed.port
        return url
    except ValueError as exc:
        raise ImageResultError('invalid image URL') from exc


def _inspect(data: bytes, limits: Limits) -> tuple[str, int, int]:
    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > limits.decoded_pixels:
                raise ResourceLimitError('image pixel limit exceeded')
            if max(width, height) > limits.output_long_edge:
                raise ResourceLimitError('image edge limit exceeded')
            mime = Image.MIME.get(image.format)
            if mime not in ('image/png', 'image/jpeg', 'image/webp'):
                raise ImageResultError('unsupported image type')
            image.verify()
        with Image.open(BytesIO(data)) as image:
            image.load()
        return mime, width, height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ImageResultError('invalid image content') from exc


class ArtifactMaterializer:
    """Own an unauthenticated HTTP client; caller persists response before use.

    `deadline` is an absolute asyncio loop.time() value; it is not reset by
    downloads or retries. Returned artifacts are not registered in SQLite.
    """
    def __init__(self, root: Path, *, limits: Limits | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.root = root
        self.limits = limits or Limits()
        self._downloads = asyncio.Semaphore(self.limits.download_concurrency)
        self._decode = asyncio.Semaphore(self.limits.decode_concurrency)
        self._client = httpx.AsyncClient(transport=transport, follow_redirects=False, trust_env=True)

    async def close(self) -> None:
        await self._client.aclose()

    async def _download(self, url: str, deadline: float) -> bytes:
        async with self._downloads:
            async with asyncio.timeout_at(deadline):
                for attempt in range(self.limits.download_attempts):
                    try:
                        return await self._download_once(url)
                    except (httpx.TransportError, httpx.HTTPStatusError):
                        if attempt + 1 >= self.limits.download_attempts:
                            raise ImageDownloadError('image download failed') from None
                raise AssertionError('unreachable')

    async def _download_once(self, url: str) -> bytes:
        current = _safe_url(url)
        for redirects in range(4):
            # Construct Request directly, not client.build_request: never merge
            # cookies, default auth or headers from the provider client.
            request = httpx.Request('GET', current, headers={'Accept': 'image/*'})
            response = await self._client.send(request, stream=True, follow_redirects=False, auth=None)
            try:
                if response.status_code in (301, 302, 303, 307, 308):
                    if redirects == 3 or not response.headers.get('location'):
                        raise ImageResultError('invalid or excessive image redirects')
                    current = _safe_url(urljoin(current, response.headers['location']))
                    continue
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > self.limits.output_bytes:
                        raise ResourceLimitError('image download too large')
                    content.extend(chunk)
                return bytes(content)
            finally:
                await response.aclose()
        raise ImageResultError('too many redirects')

    async def materialize(self, task_id: str, raw_response: bytes, *, channel: str,
                          expected_size: tuple[int, int] | None, deadline: float) -> list[PublishedImage]:
        if not re.fullmatch(r'[0-9a-fA-F-]{1,64}', task_id):
            raise ValueError('invalid task id')
        if channel not in ('images', 'flux', 'chat'):
            raise ValueError('invalid channel')
        if (channel == 'chat') != (expected_size is None):
            raise ValueError('expected size must be provided only for images/flux')
        async with asyncio.timeout_at(deadline):
            parsed = parse_response(channel, raw_response)
            if not parsed.images or len(parsed.images) > self.limits.output_count:
                raise ResourceLimitError('image count exceeded')
            validated = []
            total = 0
            mismatch = False
            # Serial processing bounds memory; semaphores remain shared across tasks.
            for image in parsed.images:
                if image.data is not None:
                    data = image.data
                elif image.url:
                    data = await self._download(image.url, deadline)
                else:
                    raise ImageResultError('image source missing')
                if len(data) > self.limits.output_bytes:
                    raise ResourceLimitError('image size exceeded')
                total += len(data)
                if total > self.limits.output_total_bytes:
                    raise ResourceLimitError('total image size exceeded')
                async with self._decode:
                    mime, width, height = await asyncio.to_thread(_inspect, data, self.limits)
                if expected_size is not None and (width, height) != expected_size:
                    mismatch = True
                validated.append((data, mime, width, height, image.revised_prompt))
            publication = asyncio.create_task(asyncio.to_thread(self._publish, task_id, validated))
            try:
                published = await asyncio.shield(publication)
            except asyncio.CancelledError:
                # Filesystem threads cannot be cancelled. Do not return control
                # while one can still publish files behind the recovery logic.
                await asyncio.shield(publication)
                raise
            if mismatch:
                raise ImageResultError('generated image dimensions differ from requested size', artifacts=published)
            return published

    def _publish(self, task_id: str, validated: list[tuple]) -> list[PublishedImage]:
        directory = _directory(self.root, 'images')
        staged: list[Path] = []
        published: list[Path] = []
        result = []
        try:
            for index, (data, mime, width, height, revised_prompt) in enumerate(validated):
                temporary = directory / f'.{task_id}.{index}.{uuid4()}.partial'
                staged.append(temporary)
                with temporary.open('xb') as file:
                    file.write(data)
                    file.flush()
                    os.fsync(file.fileno())
                suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}[mime]
                destination = directory / f'{task_id}.{index}{suffix}'
                # link is atomic and refuses to overwrite; same filesystem.
                digest = sha256(data).hexdigest()
                try:
                    os.link(temporary, destination)
                except FileExistsError:
                    if destination.is_symlink() or not destination.is_file():
                        raise ImageResultError('existing image path is not a regular file')
                    # Recovery after publication but before DB commit: reuse only
                    # an exact match, never overwrite or delete prior evidence.
                    with destination.open('rb') as existing:
                        existing_hash = sha256()
                        existing_size = 0
                        for chunk in iter(lambda: existing.read(1024 * 1024), b''):
                            existing_size += len(chunk)
                            if existing_size > len(data):
                                break
                            existing_hash.update(chunk)
                    if existing_size != len(data) or existing_hash.hexdigest() != digest:
                        raise ImageResultError('existing image content differs')
                else:
                    published.append(destination)
                result.append(PublishedImage(index, str(destination), digest, mime, len(data), width, height, revised_prompt))
            return result
        except BaseException:
            for path in published:
                path.unlink(missing_ok=True)
            raise
        finally:
            for path in staged:
                path.unlink(missing_ok=True)
