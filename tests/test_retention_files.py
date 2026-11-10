import hashlib
import os

import pytest

from zhenzhen_gptimage.artifacts.retention import _managed_identity
from zhenzhen_gptimage.artifacts.retention_files import remove_verified


@pytest.mark.skipif(os.name != 'nt', reason='Windows handle deletion test')
def test_deletes_only_same_file_identity(tmp_path):
    images=tmp_path/'images';images.mkdir()
    path=images/'image.png';path.write_bytes(b'old')
    row={'task_id':'t','image_index':0,'local_path':str(path),'sha256':hashlib.sha256(b'old').hexdigest(),
         'bytes':3,'created_at':1}
    item=_managed_identity(tmp_path,row)
    path.write_bytes(b'new')
    with pytest.raises(ValueError): remove_verified(tmp_path,item)
    assert path.read_bytes()==b'new'
    row['sha256']=hashlib.sha256(b'new').hexdigest()
    item=_managed_identity(tmp_path,row)
    remove_verified(tmp_path,item)
    assert not path.exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows handle deletion test')
def test_rejects_substituted_symlink(tmp_path):
    images=tmp_path/'images';images.mkdir()
    path=images/'image.png';path.write_bytes(b'old')
    row={'task_id':'t','image_index':0,'local_path':str(path),'sha256':hashlib.sha256(b'old').hexdigest(),
         'bytes':3,'created_at':1}
    item=_managed_identity(tmp_path,row)
    other=tmp_path/'other.png';other.write_bytes(b'old')
    path.unlink()
    try: path.symlink_to(other)
    except OSError: pytest.skip('symbolic links unavailable')
    with pytest.raises(ValueError): remove_verified(tmp_path,item)
    assert other.read_bytes()==b'old'
