"""Validated runtime settings. Construct before opening network clients."""
from pathlib import Path
import os
from collections.abc import Mapping
from dotenv.parser import parse_stream
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

MiB = 1024 * 1024

class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    max_concurrency: int = Field(default=6, ge=1, le=6)
    max_unfinished: int = Field(default=20, ge=1, le=20)
    max_attempts: int = Field(default=3, ge=1, le=3)
    task_timeout_seconds: int = Field(default=600, ge=1, le=600)
    prompt_bytes: int = Field(default=32 * 1024, ge=1)
    reference_count: int = Field(default=4, ge=1)
    reference_bytes: int = Field(default=20 * MiB, ge=1)
    reference_total_bytes: int = Field(default=40 * MiB, ge=1)
    decoded_pixels: int = Field(default=16_777_216, ge=1)
    output_long_edge: int = Field(default=4096, ge=1, le=4096)
    request_bytes: int = Field(default=64 * MiB, ge=1)
    response_bytes: int = Field(default=64 * MiB, ge=1)
    output_count: int = Field(default=4, ge=1)
    output_bytes: int = Field(default=32 * MiB, ge=1)
    output_total_bytes: int = Field(default=64 * MiB, ge=1)
    download_concurrency: int = Field(default=2, ge=1)
    decode_concurrency: int = Field(default=1, ge=1)
    preview_count: int = Field(default=1, ge=1, le=1)
    preview_long_edge: int = Field(default=1024, ge=1)
    preview_bytes: int = Field(default=MiB, ge=1)
    history_default: int = Field(default=20, ge=1)
    history_max: int = Field(default=100, ge=1)
    sqlite_busy_seconds: int = Field(default=5, ge=1)
    shutdown_seconds: int = Field(default=30, ge=1)
    download_attempts: int = Field(default=3, ge=1)
    log_bytes: int = Field(default=10 * MiB, ge=1)
    log_backups: int = Field(default=5, ge=1)
    free_disk_bytes: int = Field(default=2 * 1024 * MiB, ge=1)

    @model_validator(mode="after")
    def validate_relationships(self):
        if self.history_default > self.history_max:
            raise ValueError("history_default exceeds history_max")
        if self.reference_bytes > self.reference_total_bytes or self.output_bytes > self.output_total_bytes:
            raise ValueError("single image limit exceeds total limit")
        return self

class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str = "t8-star"
    base_url: str = "https://ai.t8star.org"
    env_file: Path
    data_dir: Path
    api_key: SecretStr = Field(exclude=True, repr=False)
    secret_source: str
    limits: Limits = Field(default_factory=Limits)

KEY_NAME = "ZHENZHEN_GPTIMAGEGEN_API_KEY"

def _user_key() -> str | None:
    if os.name != "nt":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, KEY_NAME)
            return value if isinstance(value, str) else None
    except FileNotFoundError:
        return None

def load_config(config_dir: Path, data_dir: Path, *, env_file: Path | None = None,
                environ: Mapping[str, str] | None = None,
                user_key: str | None = None, limits: Limits | None = None) -> RuntimeConfig:
    """Load the explicitly located file without modifying the process environment."""
    config_dir = config_dir.resolve()
    if env_file is not None and not env_file.is_absolute():
        raise ValueError("env_file must be absolute")
    path = env_file if env_file is not None else config_dir / '.env'
    values: dict[str, str | None] = {}
    if path.exists():
        with path.open(encoding='utf-8-sig') as stream:
            for binding in parse_stream(stream):
                if binding.error:
                    raise ValueError(f"Invalid .env syntax at line {binding.original.line}")
                if binding.key is not None:
                    values[binding.key] = binding.value
    process = os.environ if environ is None else environ
    candidates = [('dotenv', values.get(KEY_NAME)), ('process', process.get(KEY_NAME)),
                  ('user', _user_key() if user_key is None else user_key)]
    for source, value in candidates:
        if value and value.strip():
            return RuntimeConfig(env_file=path, data_dir=data_dir.resolve(), api_key=value.strip(),
                                 secret_source=source, limits=limits or Limits())
    raise ValueError(f"Missing {KEY_NAME}")
