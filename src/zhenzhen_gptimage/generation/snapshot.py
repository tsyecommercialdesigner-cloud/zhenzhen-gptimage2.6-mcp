"""Canonical request fingerprints and immutable resolved request snapshots."""
import hashlib
import json
from pydantic import BaseModel, ConfigDict, Field
from .models import GenerationRequest
from collections.abc import Callable

def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()

def input_digest(request: GenerationRequest) -> str:
    # The key identifies the operation and is deliberately not part of its input.
    return _digest(request.model_dump(exclude={'idempotency_key'}, mode='json'))

class RequestSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    input_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    resolved_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    channel: str
    resolved_model: str
    width: int | None
    height: int | None
    prompt: str
    template_code: str | None = None
    template_version: int | None = None
    reference_hashes: tuple[str, ...]

def create_snapshot(request: GenerationRequest, *, final_prompt: str, reference_hashes: tuple[str, ...],
                    template_version: int | None = None) -> RequestSnapshot:
    if not final_prompt or len(final_prompt.encode('utf-8')) > 32768:
        raise ValueError('resolved prompt must be 1–32768 UTF-8 bytes')
    if (request.template_code is None) != (template_version is None):
        raise ValueError('template version required only for template requests')
    if template_version is not None and template_version < 1:
        raise ValueError('invalid template version')
    if len(reference_hashes) != len(request.references) or any(len(h) != 64 or any(c not in '0123456789abcdef' for c in h) for h in reference_hashes):
        raise ValueError('reference digests must match inputs')
    resolved = {'provider':'t8-star', 'channel':request.channel, 'resolved_model':request.resolved_model(),
                'width':request.width, 'height':request.height, 'prompt':final_prompt,
                'template_code':request.template_code, 'template_version':template_version,
                'reference_hashes':reference_hashes}
    return RequestSnapshot(
        input_digest=input_digest(request), resolved_digest=_digest(resolved),
        **{k: v for k, v in resolved.items() if k != 'provider'})

class IdempotencyConflict(ValueError):
    """An existing key was used for different caller input."""

def resolve_existing_or_create(request: GenerationRequest, *, existing: RequestSnapshot | None,
                               build: Callable[[], RequestSnapshot]) -> tuple[RequestSnapshot, bool]:
    """Reuse before reading any mutable template or reference; caller owns atomicity."""
    if existing is not None:
        if existing.input_digest != input_digest(request):
            raise IdempotencyConflict('key already belongs to another input')
        return existing, True
    result = build()
    if result.input_digest != input_digest(request):
        raise ValueError('snapshot does not match input')
    return result, False
