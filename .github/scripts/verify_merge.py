"""Fail closed unless merged tree matches a successful release PR candidate."""
import json
import io
import zipfile
import os
import subprocess

def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()

def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', path], text=True))

try:
    repo = os.environ['GITHUB_REPOSITORY']
    commit = os.environ['GITHUB_SHA']
    parents = git('rev-list', '--parents', '-n', '1', commit).split()
    if len(parents) != 3:
        raise ValueError('not a two-parent merge')
    _, base, head = parents
    prs = api(f'repos/{repo}/commits/{commit}/pulls')
    matches = [p for p in prs if p.get('merged_at') and p.get('merge_commit_sha') == commit and p['base']['ref'] == 'main' and p['head']['ref'] == 'dev' and p['head']['sha'] == head and p['base']['sha'] == base]
    if len(matches) != 1:
        raise ValueError('cannot identify exact dev to main PR and base')
    merge_tree = git('merge-tree', '--write-tree', base, head).splitlines()[0]
    if merge_tree != git('rev-parse', f'{commit}^{{tree}}'):
        raise ValueError('merged tree differs from release candidate')
    runs = api(f'repos/{repo}/actions/workflows/ci.yml/runs?event=pull_request&head_sha={head}&status=success&per_page=100')['workflow_runs']
    candidates = [run for run in runs if run['head_sha'] == head and run['conclusion'] == 'success' and run['event'] == 'pull_request' and run['run_started_at'] < matches[0]['merged_at']]
    artifact = f"release-candidate-{matches[0]['number']}"
    verified = False
    for run in candidates:
        artifacts = api(f"repos/{repo}/actions/runs/{run['id']}/artifacts")['artifacts']
        for item in artifacts:
            if item['name'] != artifact or item['expired']:
                continue
            payload = subprocess.check_output(['gh', 'api', f"repos/{repo}/actions/artifacts/{item['id']}/zip"])
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = [name for name in archive.namelist() if name == 'candidate-tree.txt']
                if len(names) == 1 and archive.read(names[0]).decode('utf-8-sig').strip() == merge_tree:
                    verified = True
    if not verified:
        raise ValueError('no matching successful release candidate tree')
    reuse = True
except (ValueError, KeyError, subprocess.CalledProcessError, OSError, IndexError, zipfile.BadZipFile, UnicodeError) as error:
    print(f'Full verification required: {error}')
    reuse = False
with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
    output.write(f'reuse={str(reuse).lower()}\n')
print(f'Release candidate evidence reusable: {reuse}')
