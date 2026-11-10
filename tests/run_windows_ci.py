"""Run the full suite with the token owner used by ordinary user installs.

The GitHub runner defaults new objects to Administrators ownership. v0.1.2
rejects that owner, so its unmodified upgrade fixture needs a user-owner token.
The current runtime ACL tests also run separately with the unmodified token.
"""
import os
from pathlib import Path

import pytest
import win32api
import win32con
import win32security

token = win32security.OpenProcessToken(
    win32api.GetCurrentProcess(), win32con.TOKEN_QUERY | win32con.TOKEN_ADJUST_DEFAULT
)
try:
    user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    win32security.SetTokenInformation(token, win32security.TokenOwner, user)
    assert win32security.GetTokenInformation(token, win32security.TokenOwner) == user
finally:
    token.Close()

raise SystemExit(pytest.main(['-q', '--basetemp=' + str(Path(os.environ['RUNNER_TEMP']) / 'zhenzhen-tests')]))
