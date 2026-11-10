"""Protocol data contracts, independent of the eventual MCP registration."""
from enum import StrEnum
from typing import Generic, Literal, TypeVar
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .models import GenerationRequest, Channel

class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class ErrorCode(StrEnum):
    INVALID_ARGUMENT = 'INVALID_ARGUMENT'
    NOT_FOUND = 'NOT_FOUND'
    IDEMPOTENCY_CONFLICT = 'IDEMPOTENCY_CONFLICT'
    TEMPLATE_VERSION_CONFLICT = 'TEMPLATE_VERSION_CONFLICT'
    QUEUE_FULL = 'QUEUE_FULL'
    RESOURCE_LIMIT = 'RESOURCE_LIMIT'
    CONFIG_ERROR = 'CONFIG_ERROR'
    PROVIDER_REJECTED = 'PROVIDER_REJECTED'
    SUBMISSION_UNKNOWN = 'SUBMISSION_UNKNOWN'
    DEADLINE_EXCEEDED = 'DEADLINE_EXCEEDED'
    RESPONSE_INVALID = 'RESPONSE_INVALID'
    ARTIFACT_UNAVAILABLE = 'ARTIFACT_UNAVAILABLE'
    PERSISTENCE_ERROR = 'PERSISTENCE_ERROR'
    STATE_CONFLICT = 'STATE_CONFLICT'

TaskStatus = Literal['queued','submitting','retry_wait','materializing','recovery_pending','unknown','succeeded','failed','expired','cancelled','closed']
ModelId = Literal['gpt-image-2.6-flare','gpt-image-2.6-flare-2k','gpt-image-2.6-flare-4k','gpt-image-2.6-sunburst','gpt-image-2.6-sunburst-2k','gpt-image-2.6-sunburst-4k']
Code = str
T = TypeVar('T')

class ErrorDetail(Contract):
    code: ErrorCode
    message: str
    retryable: bool
    task_id: str | None = None
    next_action: str

class Result(Contract, Generic[T]):
    ok: bool
    warnings: list[str] = Field(default_factory=list)
    data: T | None = None
    error: ErrorDetail | None = None

    @model_validator(mode='after')
    def check_result(self):
        if self.ok == (self.error is not None):
            raise ValueError('ok and error disagree')
        return self

class ImageView(Contract):
    task_id: str
    image_index: int = Field(ge=0, le=3)
    local_path: str
    sha256: str
    mime_type: str
    bytes: int = Field(ge=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    available: bool
    cleaned: bool = False
    cleanup_uncertain: bool = False
    metadata: dict | None = None

class RemoteTaskView(Contract):
    remote_id: str
    remote_status: str | None

class TaskView(Contract):
    task_id: str
    batch_id: str | None = None
    idempotency_key: str
    status: TaskStatus
    resolved_model: ModelId
    channel: Channel
    width: int | None
    height: int | None
    created_at: str
    deadline_at: str
    attempt_count: int = Field(ge=0, le=3)
    images: list[ImageView]
    error_category: str | None = None
    allowed_actions: list[str]
    remote_task: RemoteTaskView | None = None

class BatchItem(Contract):
    input_index: int = Field(ge=0, le=19)
    task: TaskView
    reused: bool

class BatchView(Contract):
    batch_id: str
    items: list[BatchItem]
    succeeded_count: int
    unresolved_count: int
    failed_count: int

class TaskPage(Contract):
    items: list[TaskView]
    next_cursor: str | None

class TemplateVariable(Contract):
    name: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    required: bool
    default: str | None = None
    @model_validator(mode='after')
    def check_default(self):
        if self.required and self.default is not None:
            raise ValueError('required variable cannot have a default')
        return self

class TemplateView(Contract):
    code: str
    version: int
    content: str
    variables: list[TemplateVariable]
    created_at: str
    updated_at: str

class TemplatePage(Contract):
    items: list[TemplateView]
    next_cursor: str | None

class RenderedPrompt(Contract):
    code: str
    version: int
    prompt: str

class Capabilities(Contract):
    models: list[ModelId]
    routing: dict
    limits: dict
    channels: dict
    evidence: dict
    formats: dict = Field(default_factory=dict)

class EmptyInput(Contract): pass
class GenerateInput(Contract): request: GenerationRequest
class BatchInput(Contract): requests: list[GenerationRequest] = Field(min_length=1, max_length=20)
class TaskLookupInput(Contract):
    task_id: str | None = None
    idempotency_key: str | None = None
    @model_validator(mode='after')
    def one_key(self):
        if (self.task_id is None) == (self.idempotency_key is None):
            raise ValueError('exactly one lookup key required')
        return self
class TaskListInput(Contract):
    status: TaskStatus | None = None
    batch_id: str | None = None
    model: ModelId | None = None
    created_from: str | None = None
    created_to: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None
class ImageInput(Contract):
    task_id: str
    image_index: int = Field(default=0, ge=0, le=3)
    include_preview: bool = True
class ExportImageInput(Contract):
    task_id: str = Field(min_length=1, max_length=128)
    image_index: int = Field(default=0, ge=0, le=3)
    destination: str = Field(min_length=1, max_length=4096)
class PreviewCleanupInput(Contract):
    before: str | None = None
    keep_latest: int | None = Field(default=None, ge=0, le=1_000_000)
    @model_validator(mode='after')
    def one_filter(self):
        if (self.before is None) == (self.keep_latest is None):
            raise ValueError('exactly one cleanup filter required')
        return self
class ExecuteCleanupInput(Contract):
    plan_id: str = Field(pattern=r'^[0-9a-f]{32}$')
class SetRetentionPolicyInput(Contract):
    enabled: bool
class TaskInput(Contract): task_id: str
class AcceptGifSizeInput(Contract):
    task_id: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    width: int = Field(ge=1)
    height: int = Field(ge=1)
class CloseInput(Contract):
    task_id: str
    expected_status: Literal['unknown','recovery_pending']
    reason: str = Field(min_length=1, max_length=1024)
class TemplateInput(Contract): code: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
class SaveTemplateInput(TemplateInput):
    content: str = Field(min_length=1)
    variables: list[TemplateVariable]
    expected_version: int | None = Field(default=None, ge=1)
    @model_validator(mode='after')
    def validate_template(self):
        if len(self.content.encode('utf-8')) > 32768 or len({v.name for v in self.variables}) != len(self.variables):
            raise ValueError('invalid template content or duplicate variables')
        return self
class TemplateListInput(Contract):
    query: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None
class RenderTemplateInput(TemplateInput): variables: dict[str, str]

TOOL_INPUTS = {
    'get_capabilities': EmptyInput, 'generate_image': GenerateInput, 'generate_batch': BatchInput,
    'get_task': TaskLookupInput, 'list_tasks': TaskListInput, 'get_image': ImageInput,
    'export_image': ExportImageInput,
    'preview_cleanup': PreviewCleanupInput,
    'execute_cleanup': ExecuteCleanupInput,
    'authorize_cleanup': ExecuteCleanupInput,
    'get_retention_policy': EmptyInput, 'set_retention_policy': SetRetentionPolicyInput,
    'recover_task': TaskInput, 'close_task': CloseInput, 'save_prompt_template': SaveTemplateInput,
    'accept_gif_size': AcceptGifSizeInput,
    'get_prompt_template': TemplateInput, 'list_prompt_templates': TemplateListInput,
    'render_prompt_template': RenderTemplateInput,
}
