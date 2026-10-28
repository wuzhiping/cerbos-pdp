"""Cerbos client construction.

The Python SDK offers a gRPC client (port 3593) and an HTTP client (port 3592).
The PDP under test exposes only HTTP, so the suite uses the HTTP client. The
choice is explicit here rather than an import-time accident.
"""

from __future__ import annotations

import os

from cerbos.sdk.client import CerbosClient

from cerbos_policy_tests.config import (
    admin_headers,
    admin_password,
    admin_user,
    bypass_proxy,
    pdp_url,
)

DEFAULT_TIMEOUT_SECS = 10.0


def build_client(
    host: str | None = None, timeout_secs: float = DEFAULT_TIMEOUT_SECS
) -> CerbosClient:
    """Build a client for the PDP under test.

    TLS verification stays on for https hops; a plaintext http hop has no
    certificate to verify. Point CERBOS_CA_FILE at a CA bundle when the PDP
    presents a certificate the system trust store does not know.
    """
    target = host or pdp_url()
    bypass_proxy(target)

    verify: bool | str = True
    if target.startswith("http://"):
        verify = False
    ca_file = os.environ.get("CERBOS_CA_FILE")
    if ca_file:
        verify = ca_file

    return CerbosClient(target, timeout_secs=timeout_secs, tls_verify=verify)


__all__ = [
    "DEFAULT_TIMEOUT_SECS",
    "admin_headers",
    "admin_password",
    "admin_user",
    "build_client",
    "pdp_url",
]
