"""Decide from a request's headers whether it is for this server and from its page.

Called by app.py for every request; nothing here touches a file or the network.
The page is reached on loopback or through `tailscale serve`, which forwards
the browser's Host, Origin and Sec-Fetch-Site as they are.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import urlsplit

LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
WILDCARD_BINDS = frozenset({"", "0.0.0.0", "::"})
TAILNET_SUFFIX = ".ts.net"

_HOST = re.compile(r"(?:\[(?P<v6>[0-9a-f:]+)\]|(?P<name>[a-z0-9.-]+))(?::[0-9]{1,5})?")


def is_own_host(host: str, bind_host: str) -> bool:
    """Whether a Host header names this server."""
    found = _HOST.fullmatch(host.lower())
    if not found:
        return False
    name = (found["v6"] or found["name"]).rstrip(".")
    if name in LOOPBACK_NAMES:
        return True
    if bind_host not in WILDCARD_BINDS and name == bind_host.lower():
        return True
    return name.endswith(TAILNET_SUFFIX)


def _is_own_url(url: str, host: str) -> bool:
    try:
        parts = urlsplit(url.lower())
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    default = ":443" if parts.scheme == "https" else ":80"
    return parts.netloc.removesuffix(default) == host.lower().removesuffix(default)


def may_read(headers: Mapping[str, str]) -> bool:
    """Whether a read may be answered.

    Native media players and command line tools send neither header, and an
    address typed into the browser is `none`.
    """
    if headers.get("sec-fetch-site", "none") not in ("same-origin", "none"):
        return False
    origin = headers.get("origin")
    return origin is None or _is_own_url(origin, headers.get("host", ""))


def may_change(headers: Mapping[str, str]) -> bool:
    """Whether a change may be made: the request must show it comes from the page."""
    site = headers.get("sec-fetch-site")
    if site not in (None, "same-origin"):
        return False
    host = headers.get("host", "")
    origin = headers.get("origin")
    if origin is not None:
        return _is_own_url(origin, host)
    if site is not None:
        return True
    # Browsers older than fetch metadata still name the page in Referer.
    referer = headers.get("referer")
    return referer is not None and _is_own_url(referer, host)
