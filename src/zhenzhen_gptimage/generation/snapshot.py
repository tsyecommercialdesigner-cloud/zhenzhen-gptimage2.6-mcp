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
    data = request.model_dump(exclude={'idempotency_key'}, mode='json')
    if request.execution_mode == 'sync':
        data.pop('execution_mode')
    if request.output_format is None and request.provider == 't8-star':
        for name in ('provider','output_format','size','size_policy','frame_count','frame_duration_ms','svg_model','svg_reasoning_effort'):
            data.pop(name)
    return _digest(data)

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
    snapshot_version: int = 1
    provider: str = 't8-star'
    execution_mode: str = 'sync'
    output_format: str | None = None
    size: str | None = None
    size_policy: str = 'strict'
    frame_count: int | None = None
    frame_duration_ms: int | None = None
    svg_model: str | None = None
    svg_reasoning_effort: str | None = None

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
    if request.output_format is not None or request.provider != 't8-star':
        resolved.update({'provider':request.provider, 'snapshot_version':2,
                         'output_format':request.output_format,'size':request.size,
                         'size_policy':request.size_policy,'frame_count':request.frame_count,
                         'frame_duration_ms':request.frame_duration_ms,'svg_model':request.svg_model or ('gpt-6-luna' if request.output_format=='svg' else None),
                         'svg_reasoning_effort':request.svg_reasoning_effort})
    if request.execution_mode == 'async':
        resolved['execution_mode'] = 'async'
    return RequestSnapshot(
        input_digest=input_digest(request), resolved_digest=_digest(resolved),
        **resolved)

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
