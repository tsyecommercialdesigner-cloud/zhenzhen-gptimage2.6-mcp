"""Copy managed original bytes into an explicitly authorized directory."""
from contextlib import ExitStack, contextmanager
from hashlib import sha256
import os
from pathlib import Path
import stat
from uuid import uuid4

from .export_paths import validate_export_destination


@contextmanager
def _windows_locked_directories(root: Path, parent: Path):
    """Keep ancestors open without FILE_SHARE_DELETE while accessing paths."""
    import win32con
    import win32file
    import pywintypes

    handles = []
    try:
        # Open from the volume root down. An open directory without delete
        # sharing cannot be replaced while a descendant is being opened.
        chain = list(reversed(parent.parents)) + [parent]
        for path in chain:
            try:
                handle = win32file.CreateFile(
                    str(path), 0, win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                    None, win32con.OPEN_EXISTING,
                    win32con.FILE_FLAG_BACKUP_SEMANTICS | win32file.FILE_FLAG_OPEN_REPARSE_POINT, None)
            except pywintypes.error as exc:
                if exc.winerror not in (2, 3) or path == root or root not in path.parents:
                    raise
                path.mkdir()
                handle = win32file.CreateFile(
                    str(path), 0, win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                    None, win32con.OPEN_EXISTING,
                    win32con.FILE_FLAG_BACKUP_SEMANTICS | win32file.FILE_FLAG_OPEN_REPARSE_POINT, None)
            handles.append(handle)
            info = win32file.GetFileInformationByHandle(handle)
            if info[0] & win32con.FILE_ATTRIBUTE_REPARSE_POINT or not info[0] & win32con.FILE_ATTRIBUTE_DIRECTORY:
                raise ValueError('export directory is a reparse point or not a directory')
        yield
    finally:
        for handle in reversed(handles):
            handle.Close()


@contextmanager
def _posix_parent(root: Path, parent: Path):
    """Walk directories relative to held no-follow directory descriptors."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors = []
    try:
        fd = os.open(root.anchor, flags)
        descriptors.append(fd)
        for component in root.parts[1:] + parent.relative_to(root).parts:
            try:
                next_fd = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                # Never create the configured root or its ancestors implicitly.
                current = len(descriptors) - 1
                if current < len(root.parts) - 1:
                    raise
                os.mkdir(component, mode=0o700, dir_fd=fd)
                next_fd = os.open(component, flags, dir_fd=fd)
            descriptors.append(next_fd)
            fd = next_fd
        yield fd
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def export_original(row: dict, root: Path | None, destination: Path) -> dict:
    destination = validate_export_destination(root, destination)
    root = Path(os.path.abspath(root))
    expected_extension = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp',
                          'image/gif': '.gif', 'image/svg+xml': '.svg'}.get(row['mime_type'])
    suffix = destination.suffix.lower()
    if expected_extension is None or (suffix != expected_extension and not (expected_extension == '.jpg' and suffix == '.jpeg')):
        raise ValueError('destination extension does not match original format')
    source = Path(row['local_path'])
    if source.is_symlink() or not source.is_file():
        raise FileNotFoundError('original unavailable')
    temporary = f'.export-{uuid4().hex}.partial'
    digest = sha256()
    size = 0
    with ExitStack() as stack:
        if os.name == 'nt':
            stack.enter_context(_windows_locked_directories(root, destination.parent))
            temporary_path = destination.parent / temporary
            target = stack.enter_context(temporary_path.open('xb'))
        else:
            parent_fd = stack.enter_context(_posix_parent(root, destination.parent))
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
            target = stack.enter_context(os.fdopen(fd, 'wb'))
        try:
            with source.open('rb') as original:
                if not stat.S_ISREG(os.fstat(original.fileno()).st_mode):
                    raise ValueError('original is not a regular file')
                for chunk in iter(lambda: original.read(1024 * 1024), b''):
                    size += len(chunk)
                    if size > row['bytes']:
                        raise ValueError('original size differs from record')
                    digest.update(chunk)
                    target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
            if size != row['bytes'] or digest.hexdigest() != row['sha256']:
                raise ValueError('original checksum differs from record')
            target.close()
            if os.name == 'nt':
                copied = temporary_path.open('rb')
            else:
                copied = os.fdopen(os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd), 'rb')
            with copied:
                copied_digest = sha256()
                for chunk in iter(lambda: copied.read(1024 * 1024), b''):
                    copied_digest.update(chunk)
                if copied_digest.hexdigest() != row['sha256']:
                    raise OSError('export copy checksum mismatch')
                if os.name == 'nt':
                    os.link(temporary_path, destination)
                else:
                    os.link(temporary, destination.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
            return {'task_id': row['task_id'], 'image_index': row['image_index'],
                    'local_path': str(destination), 'sha256': digest.hexdigest(),
                    'bytes': size, 'mime_type': row['mime_type']}
        finally:
            if not target.closed:
                target.close()
            if os.name == 'nt':
                temporary_path.unlink(missing_ok=True)
            else:
                try: os.unlink(temporary, dir_fd=parent_fd)
                except FileNotFoundError: pass
