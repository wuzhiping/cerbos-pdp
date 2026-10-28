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
def test_grpc_port_is_not_exposed(port):
    """Document why the HTTP client is used: this PDP exposes no gRPC listener.

    The Python SDK prefers gRPC, so the suite must not silently assume it.

    A closed port usually answers with a TCP refusal, which surfaces as
    ``ConnectError``. A firewall that drops the packet instead surfaces as
    ``ConnectTimeout`` — a sibling class, not a subclass — so accept both.
    """
    with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
        httpx.get(f"http://{pdp_url().split('//')[1].split(':')[0]}:{port}/", timeout=3.0)
