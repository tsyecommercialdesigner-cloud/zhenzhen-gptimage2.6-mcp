"""Choose related tests; unknown code changes fall back to the full suite."""
import os
import subprocess
from pathlib import Path

files = subprocess.check_output(['git', 'diff', '--name-only', '--diff-filter=ACMRD', os.environ['BASE_SHA'], os.environ['HEAD_SHA']], text=True).splitlines()
tests = set()
full = False
for name in files:
    path = Path(name)
    if name.endswith(('.md', '.rst', '.txt')):
        continue
    if name.startswith('tests/test_') and name.endswith('.py'):
        tests.add(name)
    elif name.startswith('src/') and name.endswith('.py'):
        found = list(Path('tests').glob(f'test_*{path.stem}*.py'))
        if found and path.stem not in {'__init__', 'main', 'server', 'config'}:
            tests.update(p.as_posix() for p in found)
        else:
            full = True
    else:
        full = True
if full or not tests:
    tests = {'tests'}
subprocess.run(['python', '-m', 'compileall', '-q', 'src'], check=True)
import pytest
import win32api
import win32con
import win32security
token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY | win32con.TOKEN_ADJUST_DEFAULT)
try:
    user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    win32security.SetTokenInformation(token, win32security.TokenOwner, user)
finally:
    token.Close()
raise SystemExit(pytest.main(['-q', *sorted(tests)]))
