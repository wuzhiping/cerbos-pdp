"""The PDP under test must be reachable and serving.

These are preconditions for every other test: if the PDP is down, the rest of
the suite is measuring nothing.
"""

from __future__ import annotations

import httpx
import pytest

from cerbos_policy_tests.client import admin_headers, pdp_url


def test_pdp_is_healthy(client):
    assert client.is_healthy() is True


def test_pdp_health_endpoint_reports_serving(client):
    response = httpx.get(f"{pdp_url()}/_cerbos/health", timeout=10.0)
    assert response.status_code == 200
    assert response.json()["status"] == "SERVING"


def test_admin_api_requires_credentials():
    """The admin API must not be readable without authentication."""
    response = httpx.get(f"{pdp_url()}/admin/policies", timeout=10.0)
    assert response.status_code == 401


def test_admin_api_accepts_credentials():
    response = httpx.get(
        f"{pdp_url()}/admin/policies", headers=admin_headers(), timeout=10.0
    )
    assert response.status_code == 200
    assert "policyIds" in response.json()


@pytest.mark.parametrize("port", [3593])
def test_the_grpc_port_does_not_serve_the_http_api(port):
    """Document why the HTTP client is used, whatever state the gRPC port is in.

    The Python SDK ships both an HTTP client (installed) and a gRPC client
    (needs the ``cerbos[grpc]`` extra), and the gRPC client is the one the
    SDK prefers. The suite must not silently assume either.

    What matters is not whether the port is open, but that **it never serves
    the HTTP API** — so nobody points an HTTP client at it and gets confused
    by a protocol error:

    * port closed (TCP refusal) → ``ConnectError``
    * port dropped by a firewall → ``ConnectTimeout``
    * port open and serving gRPC → the peer resets the connection
      (``ReadError``) or rejects the request line (``RemoteProtocolError``)

    All three are transport-level failures, and all three are subclasses of
    ``httpx.TransportError``. An HTTP response of any status would *not* be,
    which is exactly what this test is checking for.
    """
    url = f"http://{pdp_url().split('//')[1].split(':')[0]}:{port}/"
    with pytest.raises(httpx.TransportError):
        httpx.get(url, timeout=3.0)
