"""Fail-closed preflight for explicitly configured local export paths.

This is not a substitute for handle-relative operations at the point of write.
"""
from pathlib import Path
import os
import stat


def _check_component(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    attributes = getattr(info, 'st_file_attributes', 0)
    if stat.S_ISLNK(info.st_mode) or attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
        raise ValueError('export path contains a link or reparse point')
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('export path parent is not a directory')


def validate_export_destination(root: Path | None, destination: Path) -> Path:
    if root is None:
        raise ValueError('export root is not configured')
    if not root.is_absolute() or not destination.is_absolute():
        raise ValueError('export paths must be absolute server-side paths')
    if '..' in root.parts or '..' in destination.parts:
        raise ValueError('parent traversal is not permitted')
    root = Path(os.path.abspath(root))
    destination = Path(os.path.abspath(destination))
    try:
        relative = destination.relative_to(root)
    except ValueError:
        raise ValueError('destination is outside configured export root') from None
    if not relative.parts:
        raise ValueError('destination must be a file under export root')
    for part in reversed(root.parents):
        _check_component(part)
    _check_component(root)
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        _check_component(current)
    try:
        destination.lstat()
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError('export destination already exists')
    return destination
