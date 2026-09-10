"""Network environment fixes applied at startup."""

from __future__ import annotations

import os

_PROXY_VARS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
)


def normalize_proxy_env() -> dict[str, str]:
    """Rewrite `socks://` proxy URLs to `socks5://` so httpx accepts them.

    Tools like v2rayN export `socks://host:port`, which httpx rejects with
    'Unknown scheme for proxy URL'. `socks5://` is the scheme it understands.
    Returns the changed variables.
    """
    changed: dict[str, str] = {}
    for name in _PROXY_VARS:
        value = os.environ.get(name)
        if value and value.lower().startswith("socks://"):
            fixed = "socks5://" + value[len("socks://"):]
            os.environ[name] = fixed
            changed[name] = fixed
    return changed
