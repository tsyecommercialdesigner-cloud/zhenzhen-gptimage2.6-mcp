import pytest
from pydantic import ValidationError
from zhenzhen_gptimage.bootstrap.config import Limits, RuntimeConfig, load_config, KEY_NAME

def test_defaults_and_secret_exclusion(tmp_path):
    cfg = RuntimeConfig(env_file=tmp_path / '.env', data_dir=tmp_path, api_key='secret-value', secret_source='env')
    assert (cfg.limits.max_concurrency, cfg.limits.max_unfinished, cfg.limits.max_attempts) == (6, 20, 3)
    assert cfg.limits.free_disk_bytes == 2 * 1024**3
    assert 'secret-value' not in repr(cfg) and 'api_key' not in cfg.model_dump()

@pytest.mark.parametrize('changes', [dict(max_concurrency=7), dict(max_unfinished=21), dict(max_attempts=4), dict(task_timeout_seconds=601), dict(history_default=101), dict(reference_bytes=41*1024**2), dict(max_attempts=0), dict(unknown=1)])
def test_invalid_limits_fail_during_construction(changes):
    with pytest.raises(ValidationError):
        Limits(**changes)

def test_sources_and_no_parent_search(tmp_path):
    parent = tmp_path / 'parent'
    parent.mkdir()
    (parent / '.env').write_text(f'{KEY_NAME}=parent\n')
    child = parent / 'child'
    child.mkdir()
    assert load_config(child, child, environ={}, user_key='user').secret_source == 'user'
    (child / '.env').write_text(f'{KEY_NAME}=file\n')
    cfg = load_config(child, child, environ={KEY_NAME: 'process'}, user_key='user')
    assert cfg.api_key.get_secret_value() == 'file' and cfg.secret_source == 'dotenv'
    (child / '.env').write_text(f'{KEY_NAME}=  \n')
    assert load_config(child, child, environ={KEY_NAME: 'process'}, user_key='user').secret_source == 'process'

def test_missing_invalid_and_absolute_override(tmp_path):
    with pytest.raises(ValueError, match='Missing'):
        load_config(tmp_path, tmp_path, environ={}, user_key='')
    with pytest.raises(ValueError, match='absolute'):
        load_config(tmp_path, tmp_path, env_file=__import__('pathlib').Path('other.env'), environ={}, user_key='')
    bad = tmp_path / 'bad.env'
    bad.write_text('this is not valid = "unterminated\n')
    with pytest.raises(ValueError, match='syntax'):
        load_config(tmp_path, tmp_path, env_file=bad, environ={KEY_NAME: 'process'}, user_key='')
