from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
import pytest
from PIL import Image
from zhenzhen_gptimage.artifacts.storage import (ResourceLimitError, prepare_references,
    check_disk_budget, cleanup_unreferenced, write_response, inspect_response)
from zhenzhen_gptimage.bootstrap.config import Limits

def image_bytes(color='blue', size=(20, 20)):
    data = BytesIO()
    Image.new('RGB', size, color).save(data, format='PNG')
    return data.getvalue()

def test_freeze_and_metadata(tmp_path):
    source = tmp_path / 'source.png'
    original = image_bytes()
    source.write_bytes(original)
    root = tmp_path / 'data'
    asset = prepare_references([source], root)[0]
    source.write_bytes(image_bytes('red'))
    assert Path(asset.local_path).read_bytes() == original
    assert asdict(asset)['bytes'] == len(original)
    assert (asset.mime_type, asset.width, asset.height) == ('image/png', 20, 20)
    assert cleanup_unreferenced(root, {asset.local_path}) == []
    assert Path(asset.local_path).exists()
    assert cleanup_unreferenced(root, set()) == [asset.local_path]

def test_reference_limits_and_partial_cleanup(tmp_path):
    source = tmp_path / 'valid.png'
    source.write_bytes(image_bytes())
    root = tmp_path / 'data'
    with pytest.raises(ResourceLimitError): prepare_references([source] * 5, root)
    with pytest.raises(ValueError): prepare_references([Path('relative.png')], root)
    with pytest.raises(ResourceLimitError): prepare_references([source], root, Limits(reference_bytes=10))
    with pytest.raises(ResourceLimitError): prepare_references([source, source], root, Limits(reference_total_bytes=100, reference_bytes=100))
    with pytest.raises(ResourceLimitError): prepare_references([source], root, Limits(decoded_pixels=399))
    bad = tmp_path / 'bad.png'
    bad.write_bytes(b'not image')
    with pytest.raises(ValueError): prepare_references([source, bad], root)
    assert list((root/'reference-staging').glob('*.asset')) == []

def test_budget_enforces_reserve(tmp_path):
    usage = shutil_usage = __import__('shutil')._ntuple_diskusage(100, 50, 50)
    with patch('zhenzhen_gptimage.artifacts.storage.shutil.disk_usage', return_value=usage):
        with pytest.raises(ResourceLimitError): check_disk_budget(tmp_path, 2, Limits(free_disk_bytes=49))
        check_disk_budget(tmp_path, 1, Limits(free_disk_bytes=49))

def test_response_recovery_and_incomplete_stream(tmp_path):
    task = '0123-abcd'
    def broken():
        yield b'partial'
        raise OSError('network failed')
    with pytest.raises(OSError): write_response(tmp_path, task, 1, broken(), max_bytes=100)
    assert inspect_response(tmp_path, task, 1) is None
    result = write_response(tmp_path, task, 1, [b'part', b'two'], max_bytes=100)
    assert inspect_response(tmp_path, task, 1) == result
    with pytest.raises(FileExistsError): write_response(tmp_path, task, 1, [b'new'], max_bytes=100)
    Path(result.local_path).write_bytes(b'tampered')
    assert inspect_response(tmp_path, task, 1) is None

def test_response_size_and_crash_window(tmp_path):
    with pytest.raises(ResourceLimitError): write_response(tmp_path, 'abcd', 2, [b'12345'], max_bytes=4)
    assert inspect_response(tmp_path, 'abcd', 2) is None
    folder = tmp_path/'responses'
    (folder/'abcd.3.body').write_bytes(b'without manifest')
    assert inspect_response(tmp_path, 'abcd', 3) is None
    with pytest.raises(ValueError): write_response(tmp_path, '../escape', 1, [], max_bytes=10)
