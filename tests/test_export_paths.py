import os
from pathlib import Path

import pytest

from zhenzhen_gptimage.artifacts.export_paths import validate_export_destination
from zhenzhen_gptimage.bootstrap.config import EXPORT_ROOT_NAME, KEY_NAME, load_config


def test_root_configuration_and_boundaries(tmp_path):
    root = tmp_path / 'workspace'
    root.mkdir()
    cfg = load_config(tmp_path, tmp_path, environ={KEY_NAME: 'test', EXPORT_ROOT_NAME: str(root)})
    assert cfg.export_root == root
    assert validate_export_destination(cfg.export_root, root / 'assets' / 'image.png') == root / 'assets' / 'image.png'
    assert validate_export_destination(root, tmp_path / 'outside.png') == tmp_path / 'outside.png'
    with pytest.raises(ValueError): validate_export_destination(root, root / '..' / 'outside.png')
    assert validate_export_destination(None, root / 'image.png') == root / 'image.png'
    with pytest.raises(ValueError): load_config(tmp_path, tmp_path, environ={KEY_NAME: 'test', EXPORT_ROOT_NAME: 'relative'})
    (root / 'exists.png').write_bytes(b'existing')
    with pytest.raises(FileExistsError): validate_export_destination(root, root / 'exists.png')


def test_linked_directory_rejected(tmp_path):
    root = tmp_path / 'root'; root.mkdir()
    outside = tmp_path / 'outside'; outside.mkdir()
    try:
        (root / 'link').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('symbolic links unavailable for this user')
    with pytest.raises(ValueError, match='link|reparse'):
        validate_export_destination(root, root / 'link' / 'image.png')


def test_inaccessible_destination_parent_is_not_created(tmp_path, monkeypatch):
    root = tmp_path / 'missing'
    original = Path.lstat
    def denied(path):
        if path == root:
            raise PermissionError('denied')
        return original(path)
    monkeypatch.setattr(Path, 'lstat', denied)
    with pytest.raises(PermissionError): validate_export_destination(root, root / 'image.png')
    assert not os.path.exists(root)
