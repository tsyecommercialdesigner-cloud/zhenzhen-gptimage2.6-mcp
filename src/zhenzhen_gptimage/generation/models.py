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
    provider: Literal['t8-star'] = 't8-star'
    execution_mode: Literal['sync', 'async'] = 'sync'
    output_format: Literal['gif', 'svg'] | None = None
    size: str | None = None
    size_policy: Literal['strict', 'accept_actual'] = 'strict'
    frame_count: int | None = Field(default=None, ge=2, le=16)
    frame_duration_ms: int | None = Field(default=None, ge=20)
    svg_model: str | None = Field(default=None, min_length=1, max_length=100)
    svg_reasoning_effort: Literal['none','minimal','low','medium','high','xhigh','max'] | None = None

    @model_validator(mode='before')
    @classmethod
    def normalize_format_size(cls, value):
        if not isinstance(value, dict) or value.get('output_format') not in ('gif','svg'):
            return value
        data=dict(value)
        if 'size' not in data and data.get('width') is None and data.get('height') is None:
            data['size']='auto'
        raw=data.get('size')
        if isinstance(raw,str):
            import re
            match=re.fullmatch(r'(\d+)x(\d+)',raw)
            if match:
                if data.get('width') is not None or data.get('height') is not None:
                    raise ValueError('size conflicts with width/height')
                data['width'],data['height']=int(match.group(1)),int(match.group(2))
                data['size']=None
        return data

    @model_validator(mode='after')
    def validate_request(self):
        if self.execution_mode == 'async' and (self.output_format != 'gif' or self.channel != 'images' or self.family != 'flare' or max(self.width or 0, self.height or 0) > 1024):
            raise ValueError('async mode is only available for base flare GIF on images channel')
        if self.output_format is None and (self.size is not None or self.size_policy != 'strict' or self.frame_count is not None or self.frame_duration_ms is not None or self.svg_model is not None or self.svg_reasoning_effort is not None):
            raise ValueError('format options require gif or svg')
        if self.output_format is not None:
            if self.output_format == 'svg' and self.resolved_model() != 'gpt-image-2.6-flare':
                raise ValueError('SVG is currently limited to the verified base flare model')
            if self.channel not in ('images', 'flux'):
                raise ValueError('SVG and GIF require an image generation channel')
            if self.references:
                raise ValueError('SVG and GIF reference images are not supported')
            if self.output_format == 'svg' and (self.frame_count is not None or self.frame_duration_ms is not None or self.size_policy != 'strict'):
                raise ValueError('GIF options cannot be used for SVG')
            if self.output_format == 'gif' and (self.svg_model is not None or self.svg_reasoning_effort is not None):
                raise ValueError('svg_model is only valid for SVG')
            if self.frame_duration_ms is not None and self.frame_duration_ms % 10:
                raise ValueError('GIF frame duration must be a multiple of 10 ms')
            if self.size is not None:
                allowed = {'auto','1:1','3:2','2:3','4:3','3:4','5:4','4:5','16:9','9:16','2:1','1:2','21:9','9:21','3:1','1:3'}
                if self.size not in allowed or self.width is not None or self.height is not None:
                    raise ValueError('size must be auto or a supported ratio without width/height')
            if self.width is not None and self.height is not None:
                w, h = self.width, self.height
                if w % 16 or h % 16:
                    raise ValueError('SVG/GIF dimensions must be multiples of 16')
                if self.output_format == 'svg':
                    if max(w,h)>3840 or not 655360 <= w*h <= 8294400 or max(w,h)>3*min(w,h):
                        raise ValueError('SVG dimensions outside supported limits')
                else:
                    count=self.frame_count or 9
                    cols,rows=(4,2) if count<=8 else (3,3) if count==9 else (4,3) if count<=12 else (4,4)
                    def fits(a,b):
                        return max(a,b)<=3840 and a*b<=8294400 and max(a,b)<=3*min(a,b)
                    if not (fits(cols*w,rows*h) or fits(rows*w,cols*h)):
                        raise ValueError('GIF frame sheet outside supported limits')
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
        elif (self.width is None or self.height is None) and not (self.output_format is not None and self.size is not None and self.width is None and self.height is None):
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
