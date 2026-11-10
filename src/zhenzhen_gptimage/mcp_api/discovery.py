"""Bounded, atomically published backend discovery information."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import secrets

from .private_runtime import create_private_file, private_runtime_dir, verify_private_file

MAX_DESCRIPTOR_BYTES = 4096


@dataclass(frozen=True)
class Endpoint:
    port: int
    instance: str
    protocol: int
    identity: str
    token: str = field(repr=False)

    def validate(self) -> None:
        if (type(self.port) is not int or not 1 <= self.port <= 65535
                or type(self.protocol) is not int or self.protocol <= 0
                or any(not isinstance(v, str) or not v or len(v) > 256
                       for v in (self.instance, self.identity, self.token))):
            raise ValueError('invalid backend discovery data')


def publish_endpoint(data_dir: Path, endpoint: Endpoint) -> None:
    """Publish only after the caller has acquired ownership and is ready."""
    endpoint.validate()
    root = private_runtime_dir(data_dir)
    payload = json.dumps({'port': endpoint.port, 'instance': endpoint.instance,
                          'protocol': endpoint.protocol, 'identity': endpoint.identity,
                          'token': endpoint.token}, separators=(',', ':')).encode('utf-8')
    if len(payload) > MAX_DESCRIPTOR_BYTES:
        raise ValueError('backend discovery data is too large')
    temporary = root / ('endpoint-' + secrets.token_hex(16) + '.tmp')
    fd = create_private_file(temporary)
    try:
        # Verify ACL before writing the token; the file inherits the private
        # directory ACL on Windows and is created with 0600 on POSIX.
        verify_private_file(temporary)
        with os.fdopen(fd, 'wb') as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, root / 'endpoint.json')
    finally:
        if fd != -1:
            os.close(fd)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def read_endpoint(data_dir: Path) -> Endpoint | None:
    root = private_runtime_dir(data_dir)
    path = root / 'endpoint.json'
    try:
        verify_private_file(path)
        with path.open('rb') as stream:
            payload = stream.read(MAX_DESCRIPTOR_BYTES + 1)
    except FileNotFoundError:
        return None
    if len(payload) > MAX_DESCRIPTOR_BYTES:
        raise ValueError('backend discovery data is too large')
    try:
        value = json.loads(payload)
        if not isinstance(value, dict) or set(value) != {'port', 'instance', 'protocol', 'identity', 'token'}:
            raise ValueError('invalid backend discovery data')
        endpoint = Endpoint(**value)
        endpoint.validate()
        return endpoint
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError('invalid backend discovery data') from None
