"""Settings for the PDP under test.

Everything is overridable from the environment so the same suite can point at
a local PDP, a staging PDP or the shared one.

    CERBOS_PDP_URL          base URL of the PDP          (default http://10.17.1.201:3592)
    CERBOS_ADMIN_USER       admin API basic-auth user    (default cerbos)
    CERBOS_ADMIN_PASSWORD   admin API basic-auth secret  (default cerbosAdmin)
    CERBOS_CA_FILE          CA bundle for an https PDP   (default: system trust store)
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_PDP_URL = "http://10.17.1.201:3592"
DEFAULT_ADMIN_USER = "cerbos"
DEFAULT_ADMIN_PASSWORD = "cerbosAdmin"

#: Repository root — src/cerbos_policy_tests/config.py -> parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The policy source of truth: schemas, resource policies, native test suites.
POLICY_DIR = REPO_ROOT / "policies"

#: The coverage plan, kept outside the policy directory so it never reaches a store.
COVERAGE_PLAN = REPO_ROOT / "coverage-plan.json"


def bypass_proxy(host: str | None = None) -> None:
    """Make sure httpx talks to the PDP directly instead of via the proxy.

    On Windows, `urllib.request.getproxies()` returns the proxy declared in
    the registry (`HKCU\\...\\Internet Settings\\ProxyServer`) whether or not
    the environment says anything about it. httpx reads that by default
    (`trust_env=True`) and would route the PDP call through it, which an
    internal host cannot reach — the request stalls until it times out.

    Adding the host to NO_PROXY keeps the proxy in place for everything else
    and exempts only the PDP.
    """
    target = host or pdp_url()
    hostname = urlsplit(target).hostname
    if not hostname:
        return

    entries: set[str] = set()
    for name in ("NO_PROXY", "no_proxy"):
        for value in os.environ.get(name, "").split(","):
            value = value.strip()
            if value:
                entries.add(value)

    if hostname not in entries:
        entries.add(hostname)
        os.environ["NO_PROXY"] = ",".join(sorted(entries))
        os.environ["no_proxy"] = os.environ["NO_PROXY"]


def pdp_url() -> str:
    """Base URL of the PDP under test, without a trailing slash."""
    return os.environ.get("CERBOS_PDP_URL", DEFAULT_PDP_URL).rstrip("/")


def admin_user() -> str:
    return os.environ.get("CERBOS_ADMIN_USER", DEFAULT_ADMIN_USER)


def admin_password() -> str:
    return os.environ.get("CERBOS_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)


def admin_headers() -> dict[str, str]:
    """Basic-auth headers for the PDP admin API."""
    raw = f"{admin_user()}:{admin_password()}".encode()
    token = base64.b64encode(raw).decode()
    return {"Authorization": f"Basic {token}"}


bypass_proxy()
