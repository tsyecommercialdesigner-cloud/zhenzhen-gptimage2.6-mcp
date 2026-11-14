"""Classify PR changes and perform lightweight checks without exposing content."""
import os
import re
import subprocess
from pathlib import Path

base, head = os.environ['BASE_SHA'], os.environ['HEAD_SHA']
files = subprocess.check_output(['git', 'diff', '--name-only', '--diff-filter=ACMRD', base, head], text=True).splitlines()
if not files:
    raise SystemExit('No changed files; refusing to skip checks')
docs = all(p.endswith(('.md', '.txt', '.rst')) for p in files)
patch = subprocess.check_output(['git', 'diff', '--unified=0', base, head], text=True, encoding='utf-8')
patterns = [r'(?i)bearer\s+sk-[A-Za-z0-9_-]{16,}', r'(?i)(?:api[_-]?key|password)\s*[=:]\s*["\x27]sk-[A-Za-z0-9_-]{16,}']
if any(re.search(pattern, line) for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++') for pattern in patterns):
    raise SystemExit('Potential credential in added lines; inspect locally')
for name in files:
    path = Path(name)
    if not path.exists() or path.suffix.lower() != '.md':
        continue
    text = path.read_text(encoding='utf-8')
    for dest in re.findall(r'\]\(([^)]+)\)', text):
        dest = dest.strip().split('#', 1)[0]
        if not dest or '://' in dest or dest.startswith(('mailto:', '<')):
            continue
        if not (path.parent / dest).exists():
            raise SystemExit(f'Broken local link in {name}: {dest}')
with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
    output.write(f'docs_only={str(docs).lower()}\n')
print(f'Checked {len(files)} changed files; docs_only={docs}')
