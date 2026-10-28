"""Cerbos policy tests against a remote PDP.

The suite is run with pytest:

    uv run pytest

The console script is a smoke check that prints what the PDP serves.
"""

from __future__ import annotations


def main() -> None:
    """Print what the PDP under test serves, and run one decision through it."""
    import httpx

    from cerbos_policy_tests.client import admin_headers, build_client, pdp_url
    from cerbos_policy_tests.config import POLICY_DIR
    from cerbos_policy_tests.fixtures import load_fixtures
    from cerbos_policy_tests.pep import PdpError, PdpUnavailable, authorize

    print(f"PDP: {pdp_url()}")

    health = httpx.get(f"{pdp_url()}/_cerbos/health", timeout=10.0)
    print(f"  health: {health.status_code} {health.json().get('status')}")

    listed = httpx.get(
        f"{pdp_url()}/admin/policies",
        headers=admin_headers(),
        timeout=10.0,
    ).json()
    print(f"  policies: {listed.get('policyIds')}")

    fixtures = load_fixtures(POLICY_DIR)
    print(f"  fixtures: {len(fixtures.principals)} principals, {len(fixtures.resources)} resources")

    try:
        with build_client() as client:
            allowed = authorize(
                client,
                action="read",
                principal=fixtures.principal("alice").to_principal(),
                resource=fixtures.resource("alice_pub").to_resource(),
            )
            print(f"  alice read doc-alice-pub: {'ALLOW' if allowed else 'DENY'}")
    except (PdpError, PdpUnavailable) as exc:
        print(f"  decision failed: {exc}")
        raise SystemExit(1) from exc


__all__ = ["main"]
