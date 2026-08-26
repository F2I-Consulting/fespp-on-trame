"""Remote EPC/H5 import over HTTP(S).

SECURITY: the URL is user-supplied (the "Import from remote URL" field and
the `--remote-*-file-location` launcher params). Without guards this is a
classic SSRF: a visitor could point it at the cloud metadata endpoint
(169.254.169.254) or an internal-only service. `_assert_safe_url` allows only
http(s) to a PUBLIC address and is re-checked on EVERY redirect hop, and the
saved name is reduced to a safe basename so the write stays inside tmp_dir.
"""
import ipaddress
import re
import shutil
import socket
from pathlib import Path
from urllib.parse import urlparse

import requests

_MAX_REDIRECTS = 5


def _assert_safe_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("only http(s) URLs are allowed")
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no host")
    try:
        infos = socket.getaddrinfo(host, parsed.port or None)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve host: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError(f"blocked non-public address for host {host!r}")


def _safe_name(name: str) -> str:
    """Bare basename + extension allowlist for the download target."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    if not name or name in (".", ".."):
        name = "downloaded_file.epc"
    if not name.lower().endswith((".epc", ".h5")):
        raise ValueError("remote file must be a .epc or .h5")
    return name


def download_file_from_url(url: str, tmp_dir: str) -> str:
    """Stream-download a remote file into `tmp_dir` and return the
    final path. SSRF-guarded (every hop) and the saved name is
    sanitised so it can only land inside `tmp_dir`."""
    session = requests.Session()
    current = url
    response = None
    for _hop in range(_MAX_REDIRECTS + 1):
        _assert_safe_url(current)
        r = session.get(current, stream=True, timeout=60, allow_redirects=False)
        if r.is_redirect or r.is_permanent_redirect:
            location = r.headers.get("Location")
            r.close()
            if not location:
                raise ValueError("redirect without Location")
            current = requests.compat.urljoin(current, location)
            continue
        response = r
        break
    if response is None:
        raise ValueError("too many redirects")

    with response as r:
        r.raise_for_status()

        file_name = None
        if 'Content-Disposition' in r.headers:
            content_disposition = r.headers['Content-Disposition']
            fname_match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^";\n]+)["\']?', content_disposition)
            if fname_match:
                file_name = requests.utils.unquote(fname_match.group(1).strip())
        if not file_name:
            file_name = urlparse(current).path.split("/")[-1]
        file_name = _safe_name(file_name)

        base = Path(tmp_dir).resolve()
        file_path = base / file_name
        if base != file_path.resolve() and base not in file_path.resolve().parents:
            raise ValueError("resolved download path escapes tmp_dir")

        with open(file_path, 'wb') as f:
            shutil.copyfileobj(r.raw, f)

        return str(file_path)
