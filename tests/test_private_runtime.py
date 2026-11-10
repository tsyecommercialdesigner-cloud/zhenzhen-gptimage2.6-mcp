import os

import pytest

from zhenzhen_gptimage.mcp_api.private_runtime import UnsafeRuntimeDirectory, private_runtime_dir


def test_private_runtime_directory_is_created_and_reused(tmp_path):
    root = private_runtime_dir(tmp_path)
    assert root == tmp_path / '.shared-backend'
    assert private_runtime_dir(tmp_path) == root


def test_rejects_existing_unprotected_runtime_directory(tmp_path):
    root = tmp_path / '.shared-backend'
    root.mkdir()
    if os.name != 'nt':
        root.chmod(0o755)
    with pytest.raises(UnsafeRuntimeDirectory):
        private_runtime_dir(tmp_path)


def test_rejects_non_directory(tmp_path):
    (tmp_path / '.shared-backend').write_text('not a directory')
    with pytest.raises((UnsafeRuntimeDirectory, OSError)):
        private_runtime_dir(tmp_path)


@pytest.mark.skipif(os.name != 'nt', reason='Windows ACL regression')
def test_rejects_acl_that_does_not_restrict_child_files(tmp_path):
    import ntsecuritycon
    import win32security
    from zhenzhen_gptimage.mcp_api.private_runtime import _windows_current_sid

    root = private_runtime_dir(tmp_path)
    acl = win32security.ACL()
    acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, 0,
                              ntsecuritycon.FILE_ALL_ACCESS, _windows_current_sid())
    win32security.SetNamedSecurityInfo(
        str(root), win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None, None, acl, None,
    )
    with pytest.raises(UnsafeRuntimeDirectory):
        private_runtime_dir(tmp_path)
