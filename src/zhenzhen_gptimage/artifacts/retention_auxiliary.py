"""Identify registered completed-task recovery materials for review."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re

from .storage import inspect_response
from .retention import _managed_identity


def collect_auxiliary(root: Path, task_id: str, response_refs: list[str], references: list[dict], created_at: int,
                      deleted_responses: dict[str, tuple[str, int]] | None = None) -> list[dict]:
    """Return only files proven to belong to this task; never remove files."""
    root = root.resolve()
    items = []
    for ref in sorted(set(response_refs)):
        path = Path(ref)
        if not path.is_absolute() or path.parent != root / 'responses':
            continue
        match = re.fullmatch(re.escape(task_id) + r'\.([123])\.body', path.name, flags=re.IGNORECASE)
        if match is None:
            continue
        attempt = int(match.group(1))
        try:
            manifest = path.with_suffix('.json')
            if manifest.is_symlink() or manifest.stat().st_size > 4096:
                continue
            artifact = inspect_response(root, task_id, attempt)
            with manifest.open('rb') as source:
                manifest_bytes = source.read(4097)
            if len(manifest_bytes) > 4096:
                continue
            targets = []
            if artifact is not None and Path(artifact.local_path) == path:
                targets.append(('response_body', path, artifact.bytes, artifact.sha256))
            else:
                known = (deleted_responses or {}).get(str(path))
                if known is None or json.loads(manifest_bytes) != {
                    'task_id':task_id,'attempt_no':attempt,'sha256':known[0],'bytes':known[1]
                }:
                    continue
            targets.append(('response_manifest', manifest, len(manifest_bytes), sha256(manifest_bytes).hexdigest()))
            for kind, target, size, digest in targets:
                row={'task_id':task_id,'image_index':None,'local_path':str(target),
                     'sha256':digest,'bytes':size,'created_at':created_at}
                identity=_managed_identity(root,row,'responses')
                identity['kind']=kind
                items.append(identity)
        except (OSError,ValueError,TypeError):
            continue
    for row in references:
        path=Path(row['local_path'])
        if not path.is_absolute() or path.parent != root/'reference-staging' or path.suffix != '.asset':
            continue
        try:
            info={'task_id':task_id,'image_index':None,'local_path':str(path),
                  'sha256':row['sha256'],'bytes':row['bytes'],'created_at':created_at}
            identity=_managed_identity(root,info,'reference-staging')
            identity['kind']='reference_snapshot'
            items.append(identity)
        except (OSError,ValueError):
            continue
    return items
