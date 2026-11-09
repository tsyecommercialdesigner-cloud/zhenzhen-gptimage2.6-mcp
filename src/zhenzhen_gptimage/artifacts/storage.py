"""Durable local input snapshots and response recovery artifacts."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from zhenzhen_gptimage.bootstrap.config import Limits


class ResourceLimitError(ValueError):
    """A configured storage or image limit was exceeded."""


@dataclass(frozen=True)
class ReferenceAsset:
    asset_id: str
    local_path: str
    sha256: str
    mime_type: str
    bytes: int
    width: int
    height: int
    source_kind: str = 'local_file'


@dataclass(frozen=True)
class ResponseArtifact:
    task_id: str
    attempt_no: int
    local_path: str
    sha256: str
    bytes: int


def _directory(root: Path, name: str) -> Path:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    if path.is_symlink():
        raise ValueError('storage directory must not be a symlink')
    path.mkdir(exist_ok=True)
    if path.resolve().parent != root:
        raise ValueError('storage directory escaped data root')
    return path


def check_disk_budget(root: Path, reserved_bytes: int, limits: Limits = Limits()) -> None:
    """Require reserve plus all declared outstanding file budgets on this volume."""
    if reserved_bytes < 0:
        raise ValueError('negative budget')
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < limits.free_disk_bytes + reserved_bytes:
        raise ResourceLimitError('insufficient disk space')


def _image_metadata(content: bytes, max_pixels: int) -> tuple[str, int, int]:
    try:
        with Image.open(BytesIO(content)) as img:
            width, height = img.size
            if width <= 0 or height <= 0 or width * height > max_pixels:
                raise ResourceLimitError('reference pixel limit exceeded')
            mime = Image.MIME.get(img.format)
            if mime not in ('image/png', 'image/jpeg', 'image/webp'):
                raise ValueError('unsupported image type')
            img.verify()
        # verify checks container structure; load checks truncated pixel data.
        with Image.open(BytesIO(content)) as img:
            img.load()
        return mime, width, height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('invalid reference image') from exc


def prepare_references(paths: list[Path], root: Path, limits: Limits = Limits()) -> list[ReferenceAsset]:
    """Freeze validated inputs. The caller owns accepted references until cleanup."""
    if len(paths) > limits.reference_count:
        raise ResourceLimitError('reference count exceeded')
    stage = _directory(root, 'reference-staging')
    prepared: list[ReferenceAsset] = []
    total = 0
    try:
        for input_path in paths:
            if not input_path.is_absolute():
                raise ValueError('reference path must be absolute')
            with input_path.open('rb') as source:
                content = source.read(limits.reference_bytes + 1)
            if len(content) > limits.reference_bytes:
                raise ResourceLimitError('reference size exceeded')
            total += len(content)
            if total > limits.reference_total_bytes:
                raise ResourceLimitError('total reference size exceeded')
            mime, width, height = _image_metadata(content, limits.decoded_pixels)
            asset_id = str(uuid4())
            destination = stage / f'{asset_id}.asset'
            try:
                with destination.open('xb') as target:
                    target.write(content)
                    target.flush()
                    os.fsync(target.fileno())
            except BaseException:
                destination.unlink(missing_ok=True)
                raise
            prepared.append(ReferenceAsset(asset_id, str(destination), sha256(content).hexdigest(), mime, len(content), width, height))
        return prepared
    except BaseException:
        for asset in prepared:
            Path(asset.local_path).unlink(missing_ok=True)
        raise


def cleanup_unreferenced(root: Path, referenced_paths: set[str]) -> list[str]:
    """Remove only unreferenced managed staging files, under the caller's lock.

    The caller MUST hold the same lock used for snapshot preparation and DB
    admission, and pass a fresh complete set of persisted and in-flight paths.
    """
    stage = _directory(root, 'reference-staging')
    protected = {os.path.normcase(str(Path(p).resolve())) for p in referenced_paths}
    removed = []
    for path in stage.glob('*.asset'):
        if path.is_symlink() or not path.is_file():
            continue
        if os.path.normcase(str(path.resolve())) not in protected:
            path.unlink()
            removed.append(str(path))
    return removed


def _response_name(task_id: str, attempt_no: int) -> str:
    if not re.fullmatch(r'[0-9a-fA-F-]{1,64}', task_id) or attempt_no not in (1, 2, 3):
        raise ValueError('invalid task or attempt')
    return f'{task_id}.{attempt_no}'


class ResponseWriter:
    """Bounded incremental response file; incomplete streams never gain a manifest."""
    def __init__(self, root: Path, task_id: str, attempt_no: int, max_bytes: int):
        if max_bytes < 1:
            raise ValueError('max_bytes must be positive')
        directory = _directory(root, 'responses')
        stem = _response_name(task_id, attempt_no)
        self.body = directory / f'{stem}.body'
        self.manifest = directory / f'{stem}.json'
        self.temporary = directory / f'{stem}.{uuid4()}.partial'
        if self.body.exists() or self.manifest.exists():
            raise FileExistsError('response attempt already exists')
        self.task_id, self.attempt_no, self.max_bytes = task_id, attempt_no, max_bytes
        self.digest = sha256()
        self.size = 0
        self.output = self.temporary.open('xb')

    def write(self, chunk: bytes) -> None:
        if not isinstance(chunk, bytes):
            raise TypeError('response chunks must be bytes')
        if self.size + len(chunk) > self.max_bytes:
            raise ResourceLimitError('response size exceeded')
        self.output.write(chunk)
        self.digest.update(chunk)
        self.size += len(chunk)

    def finish(self) -> ResponseArtifact:
        self.output.flush()
        os.fsync(self.output.fileno())
        self.output.close()
        artifact = ResponseArtifact(self.task_id, self.attempt_no, str(self.body), self.digest.hexdigest(), self.size)
        with self.body.open('xb') as output, self.temporary.open('rb') as source:
            shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
        with self.manifest.open('x', encoding='utf-8') as meta:
            json.dump({'task_id': self.task_id, 'attempt_no': self.attempt_no, 'sha256': artifact.sha256, 'bytes': self.size}, meta)
            meta.flush()
            os.fsync(meta.fileno())
        self.temporary.unlink(missing_ok=True)
        return artifact

    def abort(self) -> None:
        if not self.output.closed:
            self.output.close()
        self.temporary.unlink(missing_ok=True)


def write_response(root: Path, task_id: str, attempt_no: int, chunks, *, max_bytes: int) -> ResponseArtifact:
    """Publish response and checksum manifest only after complete stream receipt."""
    if max_bytes < 1:
        raise ValueError('max_bytes must be positive')
    directory = _directory(root, 'responses')
    stem = _response_name(task_id, attempt_no)
    body = directory / f'{stem}.body'
    manifest = directory / f'{stem}.json'
    temporary = directory / f'{stem}.{uuid4()}.partial'
    if body.exists() or manifest.exists():
        raise FileExistsError('response attempt already exists')
    digest = sha256()
    size = 0
    try:
        with temporary.open('xb') as output:
            for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise TypeError('response chunks must be bytes')
                size += len(chunk)
                if size > max_bytes:
                    raise ResourceLimitError('response size exceeded')
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        artifact = ResponseArtifact(task_id, attempt_no, str(body), digest.hexdigest(), size)
        # Exclusive creation prevents overwriting an earlier attempt. A body
        # without its complete manifest is intentionally not recoverable.
        with body.open('xb') as output, temporary.open('rb') as source:
            shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
        with manifest.open('x', encoding='utf-8') as meta:
            json.dump({'task_id': task_id, 'attempt_no': attempt_no, 'sha256': artifact.sha256, 'bytes': size}, meta)
            meta.flush()
            os.fsync(meta.fileno())
        return artifact
    finally:
        temporary.unlink(missing_ok=True)


def inspect_response(root: Path, task_id: str, attempt_no: int) -> ResponseArtifact | None:
    """Return recovery evidence only for a complete, matching manifest and body."""
    directory = _directory(root, 'responses')
    stem = _response_name(task_id, attempt_no)
    body, manifest = directory / f'{stem}.body', directory / f'{stem}.json'
    if body.is_symlink() or manifest.is_symlink() or not body.is_file() or not manifest.is_file():
        return None
    try:
        metadata = json.loads(manifest.read_text(encoding='utf-8'))
        digest = sha256()
        size = 0
        with body.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
                size += len(chunk)
        if metadata != {'task_id': task_id, 'attempt_no': attempt_no, 'sha256': digest.hexdigest(), 'bytes': size}:
            return None
        return ResponseArtifact(task_id, attempt_no, str(body), digest.hexdigest(), size)
    except (OSError, ValueError, TypeError):
        return None
