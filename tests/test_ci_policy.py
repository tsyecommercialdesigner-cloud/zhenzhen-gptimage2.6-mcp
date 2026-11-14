"""Exercise release verification decisions without calling GitHub."""
import json
import io
import zipfile
import runpy
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / '.github/scripts/verify_merge.py'

@pytest.mark.parametrize(('mode', 'expected'), [
    ('verified', 'reuse=true'),
    ('tree_mismatch', 'reuse=false'),
    ('no_artifact', 'reuse=false'),
    ('api_error', 'reuse=false'),
    ('wrong_base', 'reuse=false'),
])
def test_merge_reuse_requires_exact_evidence(monkeypatch, tmp_path, mode, expected):
    output = tmp_path / 'out'
    monkeypatch.setenv('GITHUB_OUTPUT', str(output))
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setenv('GITHUB_SHA', 'merged')
    pr = {'number': 12, 'merged_at': '2026-01-02T00:00:00Z', 'merge_commit_sha': 'merged',
          'base': {'ref': 'main', 'sha': 'old' if mode == 'wrong_base' else 'base'},
          'head': {'ref': 'dev', 'sha': 'head'}}
    def fake(cmd, **kwargs):
        if cmd[:2] == ['git', 'rev-list']:
            return 'merged base head\n'
        if cmd[:2] == ['git', 'merge-tree']:
            return 'candidate-tree\n'
        if cmd[:2] == ['git', 'rev-parse']:
            return ('different' if mode == 'tree_mismatch' else 'candidate-tree') + '\n'
        if cmd[:2] == ['gh', 'api']:
            if mode == 'api_error':
                raise subprocess.CalledProcessError(1, cmd)
            endpoint = cmd[-1]
            if endpoint.endswith('/pulls'):
                return json.dumps([pr])
            if endpoint.endswith('/zip'):
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, 'w') as archive:
                    archive.writestr('candidate-tree.txt', 'candidate-tree')
                return buf.getvalue()
            if '/artifacts' in endpoint:
                return json.dumps({'artifacts': [] if mode == 'no_artifact' else [{'id': 9, 'name': 'release-candidate-12', 'expired': False}]})
            return json.dumps({'workflow_runs': [{'id': 7, 'head_sha': 'head', 'conclusion': 'success', 'event': 'pull_request', 'run_started_at': '2026-01-01T00:00:00Z'}]})
        raise AssertionError(cmd)
    monkeypatch.setattr(subprocess, 'check_output', fake)
    runpy.run_path(str(SCRIPT))
    assert expected in output.read_text(encoding='utf-8')

CLASSIFIER = Path(__file__).parents[1] / '.github/scripts/classify_changes.py'

@pytest.mark.parametrize(('files', 'patch', 'expected'), [
    ('README.md\n', '+ordinary documentation\n', 'docs_only=true'),
    ('src/module.py\n', '+x = 1\n', 'docs_only=false'),
])
def test_change_classification(monkeypatch, tmp_path, files, patch, expected):
    output = tmp_path / 'out'
    monkeypatch.setenv('GITHUB_OUTPUT', str(output))
    monkeypatch.setenv('BASE_SHA', 'base')
    monkeypatch.setenv('HEAD_SHA', 'head')
    monkeypatch.chdir(tmp_path)
    def fake(cmd, **kwargs):
        return files if '--name-only' in cmd else patch
    monkeypatch.setattr(subprocess, 'check_output', fake)
    runpy.run_path(str(CLASSIFIER))
    assert expected in output.read_text(encoding='utf-8')

def test_credential_scan_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv('GITHUB_OUTPUT', str(tmp_path / 'out'))
    monkeypatch.setenv('BASE_SHA', 'base')
    monkeypatch.setenv('HEAD_SHA', 'head')
    def fake(cmd, **kwargs):
        return 'notes.md\n' if '--name-only' in cmd else '+Authorization: Bearer sk-' + 'x' * 20
    monkeypatch.setattr(subprocess, 'check_output', fake)
    with pytest.raises(SystemExit, match='Potential credential'):
        runpy.run_path(str(CLASSIFIER))
