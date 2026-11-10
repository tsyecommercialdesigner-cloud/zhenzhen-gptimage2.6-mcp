import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastmcp import Client
from PIL import Image

from zhenzhen_gptimage.artifacts.export import export_original
from zhenzhen_gptimage.generation.task_locks import TaskLocks
from zhenzhen_gptimage.mcp_api.backend import ServiceBackend
from zhenzhen_gptimage.mcp_api.server import create_server


@pytest.mark.parametrize('name,mime', [
    ('a.png', 'image/png'),
    ('a.gif', 'image/gif'),
    ('a.svg', 'image/svg+xml'),
])
def test_export_original_bytes(tmp_path, name, mime):
    source = tmp_path / 'source'
    if mime == 'image/svg+xml':
        source.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 2"><path d="M0 0L2 2"/></svg>')
    elif mime == 'image/gif':
        Image.new('RGB',(2,2),'red').save(source,format='GIF',save_all=True,
            append_images=[Image.new('RGB',(2,2),'blue')],duration=[100,200],loop=0)
    else:
        Image.new('RGB',(2,2),'red').save(source,format='PNG')
    content = source.read_bytes()
    root = tmp_path / 'workspace'; root.mkdir()
    row = {'task_id':'t', 'image_index':0, 'local_path':str(source), 'mime_type':mime,
           'bytes':len(content), 'sha256':hashlib.sha256(content).hexdigest()}
    destination = root / 'nested' / name
    result = export_original(row, root, destination)
    assert destination.read_bytes() == content
    assert source.read_bytes() == content
    assert result['sha256'] == row['sha256']
    if mime == 'image/gif':
        with Image.open(destination) as animated:
            assert animated.n_frames == 2 and animated.info['loop'] == 0
    with pytest.raises(FileExistsError): export_original(row, root, destination)
    assert destination.read_bytes() == content


def test_copy_failures_leave_no_published_file(tmp_path, monkeypatch):
    source=tmp_path/'source'; source.write_bytes(b'original')
    root=tmp_path/'workspace';root.mkdir()
    row={'task_id':'t','image_index':0,'local_path':str(source),'mime_type':'image/png',
         'bytes':8,'sha256':hashlib.sha256(b'original').hexdigest()}
    target=root/'image.png'
    bad=dict(row,sha256='0'*64)
    with pytest.raises(ValueError): export_original(bad,root,target)
    assert list(root.iterdir()) == []
    import zhenzhen_gptimage.artifacts.export as module
    def fail(*args, **kwargs): raise OSError('simulated publication failure')
    monkeypatch.setattr(module.os,'link',fail)
    with pytest.raises(OSError): export_original(row,root,target)
    assert list(root.iterdir()) == []
    source.unlink()
    with pytest.raises(FileNotFoundError): export_original(row,root,target)


@pytest.mark.asyncio
@pytest.mark.parametrize('configured_root', [False, True])
async def test_mcp_export_schema_and_no_generation(tmp_path, configured_root):
    source=tmp_path/'source';source.write_bytes(b'original')
    root=tmp_path/'workspace';root.mkdir()
    row={'task_id':'t','image_index':0,'local_path':str(source),'mime_type':'image/png',
         'bytes':8,'sha256':hashlib.sha256(b'original').hexdigest()}
    class Worker:
        async def fetchone(self, sql, values): return row if values == ('t',0) else None
    recovery=SimpleNamespace(locks=TaskLocks())
    backend=ServiceBackend(Worker(),None,recovery,root if configured_root else None)
    async with Client(create_server(backend)) as client:
        target=root/'mug.png'
        result=await client.call_tool_mcp('export_image',{'task_id':'t','destination':str(target)})
        assert not result.isError and result.structuredContent['data']['sha256'] == row['sha256']
        assert target.read_bytes() == b'original'
        again=await client.call_tool_mcp('export_image',{'task_id':'t','destination':str(target)})
        assert again.isError and again.structuredContent['error']['code'] == 'STATE_CONFLICT'
        outside=tmp_path/'another-workspace'/'mug.png'
        other=await client.call_tool_mcp('export_image',{'task_id':'t','destination':str(outside)})
        assert not other.isError and outside.read_bytes() == b'original'
