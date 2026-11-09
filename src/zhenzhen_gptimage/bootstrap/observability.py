"""Structured, allowlisted diagnostic logging for stdio servers."""
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

_FIELDS = ('task_id', 'attempt', 'channel', 'model', 'duration_ms', 'status', 'error_category')

class SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Never serialize message, exception, arbitrary extras or their repr.
        result = {'level': record.levelname, 'event': 'diagnostic'}
        for field in _FIELDS:
            value = getattr(record, field, None)
            if field in ('attempt', 'duration_ms') and type(value) in (int, float):
                result[field] = value
            elif field == 'channel' and value in ('images', 'flux', 'chat'):
                result[field] = value
            elif field == 'status' and value in ('queued', 'submitting', 'retry_wait', 'materializing', 'recovery_pending', 'unknown', 'succeeded', 'failed', 'expired', 'cancelled', 'closed'):
                result[field] = value
            elif field == 'error_category' and value in ('invalid_argument', 'provider_rejected', 'submission_unknown', 'deadline_exceeded', 'response_invalid', 'artifact_unavailable', 'persistence_error', 'resource_limit'):
                result[field] = value
            elif field == 'model' and value in {f'gpt-image-2.6-{family}{suffix}' for family in ('flare', 'sunburst') for suffix in ('', '-2k', '-4k')}:
                result[field] = value
            elif field == 'task_id' and isinstance(value, str) and len(value) <= 64 and all(c in '0123456789abcdef-' for c in value):
                result[field] = value
        return json.dumps(result, ensure_ascii=True)

def configure_logging(log_file: Path | None = None, *, max_bytes: int = 10 * 1024 * 1024,
                      backup_count: int = 5) -> logging.Logger:
    logger = logging.getLogger('zhenzhen_gptimage')
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    handler = (logging.StreamHandler(sys.stderr) if log_file is None else
               RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'))
    handler.setFormatter(SafeFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
