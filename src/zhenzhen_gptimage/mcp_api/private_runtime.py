"""Private runtime directory used for local backend discovery.

The directory is created with restrictive permissions before any secrets are
written. Existing permissions are verified, never silently repaired.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat


class UnsafeRuntimeDirectory(RuntimeError):
    pass


def _windows_current_sid():
    import win32api
    import win32con
    import win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        return win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()


def _windows_create(path: Path) -> None:
    import ntsecuritycon
    import pywintypes
    import win32file
    import win32security

    sid = _windows_current_sid()
    acl = win32security.ACL()
    flags = win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE
    acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, flags, ntsecuritycon.FILE_ALL_ACCESS, sid)
    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorOwner(sid, False)
    descriptor.SetSecurityDescriptorDacl(1, acl, 0)
    descriptor.SetSecurityDescriptorControl(win32security.SE_DACL_PROTECTED,
                                            win32security.SE_DACL_PROTECTED)
    attrs = pywintypes.SECURITY_ATTRIBUTES()
    attrs.SECURITY_DESCRIPTOR = descriptor
    try:
        win32file.CreateDirectory(str(path), attrs)
    except pywintypes.error as exc:
        if exc.winerror != 183:  # ERROR_ALREADY_EXISTS
            raise


def create_private_file(path: Path) -> int:
    """Create a new private file with the current user as its owner."""
    if os.name != 'nt':
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    import msvcrt
    import pywintypes
    import win32con
    import win32file
    import win32security

    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorOwner(_windows_current_sid(), False)
    attrs = pywintypes.SECURITY_ATTRIBUTES()
    attrs.SECURITY_DESCRIPTOR = descriptor
    handle = win32file.CreateFile(str(path), win32con.GENERIC_WRITE, 0, attrs,
                                  win32con.CREATE_NEW, win32con.FILE_ATTRIBUTE_NORMAL, None)
    raw_handle = handle.Detach()
    try:
        return msvcrt.open_osfhandle(raw_handle, os.O_WRONLY | os.O_BINARY)
    except BaseException:
        win32file.CloseHandle(raw_handle)
        raise


def _windows_verify(path: Path) -> None:
    import ntsecuritycon
    import win32security
    info = win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION
    descriptor = win32security.GetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT, info)
    sid = _windows_current_sid()
    acl = descriptor.GetSecurityDescriptorDacl()
    control, _ = descriptor.GetSecurityDescriptorControl()
    if descriptor.GetSecurityDescriptorOwner() != sid or not control & win32security.SE_DACL_PROTECTED:
        raise UnsafeRuntimeDirectory('runtime directory ownership or ACL protection is unsafe')
    if acl is None or acl.GetAceCount() != 1:
        raise UnsafeRuntimeDirectory('runtime directory ACL is not restricted to current user')
    ace = acl.GetAce(0)
    required_flags = win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE
    if (ace[0][0] != win32security.ACCESS_ALLOWED_ACE_TYPE or ace[2] != sid
            or ace[1] != ntsecuritycon.FILE_ALL_ACCESS
            or ace[0][1] & required_flags != required_flags
            or ace[0][1] & win32security.INHERIT_ONLY_ACE):
        raise UnsafeRuntimeDirectory('runtime directory ACL is not restricted to current user')


def private_runtime_dir(data_dir: Path) -> Path:
    """Return a verified per-user runtime directory or fail closed."""
    root = data_dir / '.shared-backend'
    data_dir.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        _windows_create(root)
    else:
        try:
            root.mkdir(mode=0o700)
        except FileExistsError:
            pass
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or root.is_symlink():
        raise UnsafeRuntimeDirectory('runtime directory is not a real directory')
    if os.name == 'nt':
        if getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise UnsafeRuntimeDirectory('runtime directory must not be a reparse point')
        _windows_verify(root)
    elif info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise UnsafeRuntimeDirectory('runtime directory ownership or mode is unsafe')
    return root


def verify_private_file(path: Path) -> None:
    """Reject an unsafe discovery file before it is read or populated."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise UnsafeRuntimeDirectory('discovery path is not a regular file')
    if os.name == 'nt':
        import ntsecuritycon
        import win32security
        if getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise UnsafeRuntimeDirectory('discovery file must not be a reparse point')
        flags = win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION
        descriptor = win32security.GetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT, flags)
        acl = descriptor.GetSecurityDescriptorDacl()
        sid = _windows_current_sid()
        if descriptor.GetSecurityDescriptorOwner() != sid or acl is None or acl.GetAceCount() != 1:
            raise UnsafeRuntimeDirectory('discovery file ownership or ACL is unsafe')
        ace = acl.GetAce(0)
        if (ace[0][0] != win32security.ACCESS_ALLOWED_ACE_TYPE or ace[2] != sid
                or ace[1] != ntsecuritycon.FILE_ALL_ACCESS
                or ace[0][1] & win32security.INHERIT_ONLY_ACE):
            raise UnsafeRuntimeDirectory('discovery file ACL is unsafe')
    elif info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise UnsafeRuntimeDirectory('discovery file ownership or mode is unsafe')
