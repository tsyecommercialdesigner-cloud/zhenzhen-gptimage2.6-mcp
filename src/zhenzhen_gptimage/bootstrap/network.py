"""HTTP transport configuration; no requests are made here."""
import ssl
from pathlib import Path
import httpx

def create_http_client(*, ca_file: Path | None = None, proxy: str | None = None) -> httpx.AsyncClient:
    context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
    # trust_env preserves httpx's standard environment proxy settings when no proxy is specified.
    return httpx.AsyncClient(verify=context, proxy=proxy, trust_env=True,
                             transport=None, follow_redirects=False)
