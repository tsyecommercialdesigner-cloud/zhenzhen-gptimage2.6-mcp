import json
import logging
import ssl
import httpx
from zhenzhen_gptimage.bootstrap.observability import configure_logging
from zhenzhen_gptimage.bootstrap.network import create_http_client

def test_stderr_only_and_redaction(capsys):
    logger = configure_logging()
    logger.error('secret-value data:image/png;base64,AAAA https://host/path?token=secret',
                 extra={'task_id': '1234-abcd', 'model': 'gpt-image-2.6-flare',
                        'error_category': 'bad-secret-value', 'prompt': 'private'})
    output = capsys.readouterr()
    assert output.out == ''
    assert 'secret' not in output.err and 'AAAA' not in output.err and 'https' not in output.err and 'private' not in output.err
    assert json.loads(output.err)['task_id'] == '1234-abcd'

def test_file_rotation(tmp_path):
    path = tmp_path / 'log.jsonl'
    logger = configure_logging(path, max_bytes=100, backup_count=5)
    for _ in range(20):
        logger.info('ignored', extra={'status': 'queued'})
    assert path.exists() and (tmp_path / 'log.jsonl.1').exists()
    assert len(list(tmp_path.glob('log.jsonl.*'))) <= 5
    configure_logging()

def test_tls_proxy_and_invalid_ca(tmp_path):
    client = create_http_client(proxy='http://127.0.0.1:8080')
    assert isinstance(client, httpx.AsyncClient)
    import asyncio
    asyncio.run(client.aclose())
    import pytest
    with pytest.raises((FileNotFoundError, ssl.SSLError)):
        create_http_client(ca_file=tmp_path / 'missing.pem')

def test_locked_httpx_default_and_proxy_transports_disable_retries(monkeypatch):
    # Check the actual locked httpx transport pools, including environment mounts.
    monkeypatch.setenv('HTTPS_PROXY','http://127.0.0.1:9876')
    client = create_http_client()
    pools = [client._transport._pool] + [t._pool for t in client._mounts.values() if t is not None]
    assert pools and all(pool._retries == 0 for pool in pools)
    import asyncio
    asyncio.run(client.aclose())
