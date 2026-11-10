"""Safe removal primitives for files selected by a cleanup plan."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from .export import _windows_locked_directories

_BUCKETS = {'image':'images', 'response_body':'responses',
            'response_manifest':'responses', 'reference_snapshot':'reference-staging'}


def _managed_bucket(root: Path, item: dict) -> Path:
    kind = item.get('kind', 'image')
    if kind not in _BUCKETS:
        raise ValueError('unknown artifact kind')
    return root.resolve() / _BUCKETS[kind]


def remove_verified(root: Path, item: dict) -> None:
    """Delete the verified file by its open handle on Windows.

    POSIX isolates the candidate in a private quarantine before verifying and
    removing it; unexpected substitutions are not deleted.
    """
    if os.name != 'nt':
        return _remove_posix(root, item)
    import ctypes
    import msvcrt
    import pywintypes
    import win32con
    import win32file

    images = _managed_bucket(root, item)
    path = Path(item['local_path'])
    if path.parent != images or not path.is_absolute():
        raise ValueError('unmanaged path')
    try:
        _remove_windows(images, path, item, root, win32file, win32con, msvcrt, ctypes)
    except pywintypes.error as exc:
        raise OSError('failed to open or remove managed artifact') from exc


def _remove_windows(images, path, item, root, win32file, win32con, msvcrt, ctypes):
    with _windows_locked_directories(root.resolve(), images):
        handle = win32file.CreateFile(
            str(path), win32con.GENERIC_READ | win32con.DELETE,
            win32con.FILE_SHARE_READ, None, win32con.OPEN_EXISTING,
            win32file.FILE_FLAG_OPEN_REPARSE_POINT, None)
        try:
            attributes = win32file.GetFileInformationByHandle(handle)[0]
            if attributes & (win32con.FILE_ATTRIBUTE_REPARSE_POINT | win32con.FILE_ATTRIBUTE_DIRECTORY):
                raise ValueError('not an ordinary file')
            fd = msvcrt.open_osfhandle(handle.Detach(), os.O_RDONLY | os.O_BINARY)
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                expected = (item['device'], item['inode'], item['bytes'], item['mtime_ns'])
                actual = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                if not stat.S_ISREG(info.st_mode) or actual != expected:
                    raise ValueError('artifact identity changed')
                digest = hashlib.sha256()
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(chunk)
                if digest.hexdigest() != item['sha256']:
                    raise ValueError('artifact content changed')
                # FileDispositionInfo: delete the already verified open file,
                # not whichever object might later occupy its pathname.
                fn = ctypes.WinDLL('kernel32', use_last_error=True).SetFileInformationByHandle
                fn.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
                fn.restype = ctypes.c_int
                disposition = ctypes.c_ubyte(1)
                if not fn(msvcrt.get_osfhandle(source.fileno()), 4,
                          ctypes.byref(disposition), ctypes.sizeof(disposition)):
                    raise ctypes.WinError(ctypes.get_last_error())
        finally:
            handle.Close()


def _remove_posix(root: Path, item: dict) -> None:
    import secrets

    images = _managed_bucket(root, item)
    path = Path(item['local_path'])
    if path.parent != images or not path.is_absolute():
        raise ValueError('unmanaged path')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    images_fd = os.open(images, flags)
    quarantine_fd = None
    try:
        try:
            os.mkdir('.cleanup-private', mode=0o700, dir_fd=images_fd)
        except FileExistsError:
            pass
        quarantine_fd = os.open('.cleanup-private', flags, dir_fd=images_fd)
        qstat = os.fstat(quarantine_fd)
        if qstat.st_uid != os.geteuid() or stat.S_IMODE(qstat.st_mode) != 0o700:
            raise PermissionError('cleanup quarantine is not private')
        # The unpredictable name is never a user-provided pathname.
        name = item.get('_cleanup_event_id') or secrets.token_hex(16)
        if len(name) != 32 or any(c not in '0123456789abcdef' for c in name):
            raise ValueError('invalid cleanup identity')
        try:
            os.stat(name, dir_fd=quarantine_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError('quarantine collision')
        os.rename(path.name, name, src_dir_fd=images_fd, dst_dir_fd=quarantine_fd)
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=quarantine_fd)
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                expected = (item['device'], item['inode'], item['bytes'], item['mtime_ns'])
                if not stat.S_ISREG(info.st_mode) or (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns) != expected:
                    raise ValueError('artifact identity changed')
                digest = hashlib.sha256()
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(chunk)
                if digest.hexdigest() != item['sha256']:
                    raise ValueError('artifact content changed')
                current = os.stat(name, dir_fd=quarantine_fd, follow_symlinks=False)
                if (current.st_dev,current.st_ino) != (info.st_dev,info.st_ino):
                    raise ValueError('quarantine identity changed')
                os.unlink(name, dir_fd=quarantine_fd)
        except BaseException:
            # Restore a substituted object only if its original name is still
            # free; otherwise preserve it in the quarantine for inspection.
            try:
                os.link(name, path.name, src_dir_fd=quarantine_fd, dst_dir_fd=images_fd, follow_symlinks=False)
                os.unlink(name, dir_fd=quarantine_fd)
            except OSError:
                pass
            raise
    finally:
        if quarantine_fd is not None:
            os.close(quarantine_fd)
        os.close(images_fd)


def restore_quarantined(root: Path, item: dict) -> bool:
    """Restore an interrupted POSIX quarantine without overwriting a path."""
    if os.name == 'nt':
        return False
    images = _managed_bucket(root, item)
    path = Path(item['local_path'])
    name = item['_cleanup_event_id']
    if path.parent != images or len(name) != 32 or any(c not in '0123456789abcdef' for c in name):
        raise ValueError('invalid recovery identity')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    images_fd = os.open(images, flags)
    try:
        try:
            qfd = os.open('.cleanup-private', flags, dir_fd=images_fd)
        except FileNotFoundError:
            return False
        try:
            qstat = os.fstat(qfd)
            if qstat.st_uid != os.geteuid() or stat.S_IMODE(qstat.st_mode) != 0o700:
                raise PermissionError('cleanup quarantine is not private')
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=qfd)
            except FileNotFoundError:
                return False
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                expected = (item['device'],item['inode'],item['bytes'],item['mtime_ns'])
                if not stat.S_ISREG(info.st_mode) or (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns) != expected:
                    raise ValueError('quarantine identity changed')
                digest = hashlib.sha256()
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(chunk)
                if digest.hexdigest() != item['sha256']:
                    raise ValueError('quarantine content changed')
                os.link(name, path.name, src_dir_fd=qfd, dst_dir_fd=images_fd, follow_symlinks=False)
                os.unlink(name, dir_fd=qfd)
                return True
        finally:
            os.close(qfd)
    finally:
        os.close(images_fd)
