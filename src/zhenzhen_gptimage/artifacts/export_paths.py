"""Fail-closed preflight for user-selected local export paths.

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
    if not destination.is_absolute():
        raise ValueError('export paths must be absolute server-side paths')
    if '..' in destination.parts:
        raise ValueError('parent traversal is not permitted')
    destination = Path(os.path.abspath(destination))
    if destination == Path(destination.anchor):
        raise ValueError('destination must be a file')
    for part in reversed(destination.parent.parents):
        _check_component(part)
    _check_component(destination.parent)
    try:
        destination.lstat()
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError('export destination already exists')
    return destination
