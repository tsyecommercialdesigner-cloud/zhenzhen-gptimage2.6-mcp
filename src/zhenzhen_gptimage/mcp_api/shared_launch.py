"""Discover or start a compatible shared backend without exposing secrets."""
from __future__ import annotations

import asyncio
from importlib.metadata import version
import os
from pathlib import Path
import subprocess
import sys

from .discovery import read_endpoint
from .local_ipc import (
    HANDSHAKE_TIMEOUT, IPCError, IPCIncompatible, PROTOCOL_VERSION,
    configuration_identity, connect, read_frame, write_frame,
)
from .private_runtime import private_runtime_dir, verify_private_file
from .startup_coordinator import Probe, ensure_backend


def backend_identity(config, config_dir: Path, token: str) -> str:
    return configuration_identity(config, config_dir, token, version('zhenzhen-gptimage2-6-mcp'))


async def _probe_endpoint(endpoint) -> bool:
    reader, writer = await connect(endpoint, endpoint.identity)
    try:
        await write_frame(writer, {'op': 'ping'}, timeout=HANDSHAKE_TIMEOUT)
        return (await read_frame(reader, timeout=HANDSHAKE_TIMEOUT)).get('status') == 'ready'
    finally:
        writer.close()
        await writer.wait_closed()


def probe_backend(config, config_dir: Path) -> Probe:
    endpoint = read_endpoint(config.data_dir)
    if endpoint is None:
        return Probe.ABSENT
    try:
        ready = asyncio.run(_probe_endpoint(endpoint))
    except IPCIncompatible:
        return Probe.INCOMPATIBLE
    except (IPCError, OSError, TimeoutError):
        return Probe.ABSENT
    if not ready:
        return Probe.ABSENT
    if (endpoint.protocol != PROTOCOL_VERSION
            or endpoint.identity != backend_identity(config, config_dir, endpoint.token)):
        return Probe.INCOMPATIBLE
    return Probe.READY


def clear_stale_endpoint(data_dir: Path) -> None:
    path = private_runtime_dir(data_dir) / 'endpoint.json'
    try:
        verify_private_file(path)
        path.unlink()
    except FileNotFoundError:
        pass


def start_shared_process(config, config_dir: Path) -> None:
    args = [sys.executable, '-m', 'zhenzhen_gptimage.mcp_api.shared_process',
            '--config-dir', str(config_dir.resolve()), '--data-dir', str(config.data_dir),
            '--env-file', str(config.env_file.resolve())]
    if os.name == 'nt':
        _start_windows_detached(args, config_dir)
        return
    subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)


def _start_windows_detached(args, config_dir: Path) -> None:
    """Start outside the Host process tree using local WMI, without a window.

    WMI does not inherit the calling process environment. Pass only the
    runtime, credential and HTTP proxy/CA variables needed by the backend;
    values travel via local COM, never via command line or a temporary file.
    """
    import pythoncom
    import win32com.client

    allowed = {
        'SYSTEMROOT', 'WINDIR', 'PATH', 'PATHEXT', 'TEMP', 'TMP',
        'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'HOME', 'HOMEDRIVE', 'HOMEPATH',
        'PYTHONPATH', 'PYTHONHOME', 'PYTHONUTF8', 'PYTHONIOENCODING', 'VIRTUAL_ENV',
        'ZHENZHEN_GPTIMAGEGEN_API_KEY', 'ZHENZHEN_GPTIMAGEGEN_EXPORT_ROOT', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
        'NO_PROXY', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
    }
    values = [f'{key}={value}' for key, value in os.environ.items() if key.upper() in allowed]
    pythoncom.CoInitialize()
    service = startup = process = parameters = result = None
    try:
        service = win32com.client.GetObject('winmgmts:')
        startup = service.Get('Win32_ProcessStartup').SpawnInstance_()
        startup.ShowWindow = 0
        startup.EnvironmentVariables = values
        process = service.Get('Win32_Process')
        parameters = process.Methods_('Create').InParameters.SpawnInstance_()
        parameters.CommandLine = subprocess.list2cmdline(args)
        parameters.CurrentDirectory = str(config_dir.resolve())
        parameters.ProcessStartupInformation = startup
        result = service.ExecMethod('Win32_Process', 'Create', parameters)
        if result.ReturnValue != 0:
            raise RuntimeError(f'Windows backend launch failed (WMI code {result.ReturnValue})')
    except Exception:
        # COM exceptions can include method inputs; do not expose them.
        raise RuntimeError('Windows backend launch failed; check local WMI availability and permissions') from None
    finally:
        # Release COM proxies while this thread is still COM-initialized.
        result = parameters = process = startup = service = None
        pythoncom.CoUninitialize()


def ensure_shared_backend(config, config_dir: Path, *, timeout=20.0):
    ensure_backend(config.data_dir, lambda: probe_backend(config, config_dir),
                   lambda: start_shared_process(config, config_dir),
                   lambda: clear_stale_endpoint(config.data_dir), timeout=timeout)
    endpoint = read_endpoint(config.data_dir)
    if endpoint is None:
        raise RuntimeError('backend discovery disappeared after startup')
    return endpoint
