import os

import pytest

from zhenzhen_gptimage.mcp_api.discovery import Endpoint, publish_endpoint, read_endpoint
from zhenzhen_gptimage.mcp_api.private_runtime import UnsafeRuntimeDirectory


def endpoint(token='test-token'):
    return Endpoint(port=12345, instance='instance', protocol=1, identity='identity', token=token)


def test_private_atomic_publication_and_read(tmp_path):
    assert read_endpoint(tmp_path) is None
    publish_endpoint(tmp_path, endpoint())
    assert read_endpoint(tmp_path) == endpoint()
    assert 'test-token' not in repr(read_endpoint(tmp_path))
    publish_endpoint(tmp_path, endpoint('second-token'))
    assert read_endpoint(tmp_path).token == 'second-token'
    assert not list((tmp_path / '.shared-backend').glob('*.tmp'))


def test_rejects_invalid_endpoint_without_creating_file(tmp_path):
    with pytest.raises(ValueError):
        publish_endpoint(tmp_path, Endpoint(port=0, instance='i', protocol=1, identity='x', token='t'))
    assert not (tmp_path / '.shared-backend' / 'endpoint.json').exists()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX file mode regression')
def test_refuses_to_read_unprotected_file(tmp_path):
    publish_endpoint(tmp_path, endpoint())
    path = tmp_path / '.shared-backend' / 'endpoint.json'
    path.chmod(0o644)
    with pytest.raises(UnsafeRuntimeDirectory):
        read_endpoint(tmp_path)
