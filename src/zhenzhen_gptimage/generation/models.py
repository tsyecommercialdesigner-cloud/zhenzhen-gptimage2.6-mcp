"""Validated request and stable routing primitives."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Channel = Literal['images', 'flux', 'chat']
Family = Literal['flare', 'sunburst']
CHAT_WARNING = 'Chat Completions 生成图像的尺寸由供应商决定，无法定制'
CHANNEL_PRIORITY = ('images', 'flux', 'chat')
MODELS = tuple(f'gpt-image-2.6-{f}{s}' for f in ('flare', 'sunburst') for s in ('', '-2k', '-4k'))

class ReferenceInput(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    local_path: str = Field(min_length=1)

class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    idempotency_key: str = Field(min_length=1, max_length=128)
    channel: Channel = 'images'
    family: Family
    width: int | None = Field(default=None, ge=1, le=4096)
    height: int | None = Field(default=None, ge=1, le=4096)
    explicit_model: str | None = None
    prompt: str | None = Field(default=None, min_length=1)
    template_code: str | None = Field(default=None, min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    template_variables: dict[str, str] | None = None
    references: list[ReferenceInput] = Field(default_factory=list, max_length=4)

    @model_validator(mode='after')
    def validate_request(self):
        if (self.prompt is None) == (self.template_code is None):
            raise ValueError('exactly one of prompt and template_code is required')
        if self.prompt is not None and self.template_variables is not None:
            raise ValueError('template variables require a template')
        if self.template_variables is not None:
            import re
            if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name) for name in self.template_variables):
                raise ValueError('invalid template variable name')
        if self.prompt is not None and len(self.prompt.encode('utf-8')) > 32768:
            raise ValueError('prompt exceeds 32 KiB')
        if self.channel == 'chat':
            if self.width is not None or self.height is not None:
                raise ValueError('chat cannot customize dimensions')
        elif self.width is None or self.height is None:
            raise ValueError('images and flux require dimensions')
        if self.channel == 'flux' and self.references:
            raise ValueError('flux reference images are unsupported')
        if self.explicit_model is not None and self.explicit_model != self.resolved_model():
            raise ValueError('explicit model does not match family and dimensions')
        return self

    def resolved_model(self) -> str:
        base = f'gpt-image-2.6-{self.family}'
        if self.channel == 'chat':
            if self.explicit_model is not None and self.explicit_model in (base, base+'-2k', base+'-4k'):
                return self.explicit_model
            return base
        edge = max(self.width or 0, self.height or 0)
        return base + ('' if edge <= 1024 else '-2k' if edge <= 2048 else '-4k')

    def warnings(self) -> list[str]:
        return [CHAT_WARNING] if self.channel == 'chat' else []

def validate_actual_dimensions(request: GenerationRequest, width: int, height: int) -> bool:
    return width > 0 and height > 0 and (request.channel == 'chat' or (width, height) == (request.width, request.height))
