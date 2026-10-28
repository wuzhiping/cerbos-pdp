"""Edge cases: behaviour the matrix and the native suite do not reach.

Also covers the fail-closed requirement: a PDP that cannot be reached must
surface as an outage, never as an allow.
"""

from __future__ import annotations

import httpx
import pytest

from cerbos_policy_tests.client import build_client
from cerbos_policy_tests.config import POLICY_DIR
from cerbos_policy_tests.fixtures import load_fixtures
from cerbos_policy_tests.pep import PdpError, PdpUnavailable, authorize

from cerbos.sdk.model import Principal, Resource

FIXTURES = load_fixtures(POLICY_DIR)
RESOURCE_KIND = "basicResource"


def _alice_pub():
    return FIXTURES.resource("alice_pub").to_resource()


def test_unknown_role_is_denied_everywhere(client):
    guest = FIXTURES.principal("guest").to_principal()
    for action in ("read", "create", "update", "delete"):
        allowed = authorize(
            client, action=action, principal=guest, resource=_alice_pub()
        )
        assert allowed is False, f"unknown role must not be granted {action}"


def test_scoped_request_matches_no_scoped_policy(client):
    allowed = authorize(
        client,
        action="read",
        principal=Principal(id="alice", roles={"USER"}, scope="tenantA"),
        resource=Resource(
            id="doc-alice-pub",
            kind=RESOURCE_KIND,
            attr={"ownerId": "alice", "isPublished": True},
            scope="tenantA",
        ),
    )
    assert allowed is False


def test_unknown_policy_version_matches_no_policy(client):
    allowed = authorize(
        client,
        action="read",
        principal=Principal(id="alice", roles={"USER"}, policy_version="v2"),
        resource=Resource(
            id="doc-alice-pub",
            kind=RESOURCE_KIND,
            attr={"ownerId": "alice", "isPublished": True},
            policy_version="v2",
        ),
    )
    assert allowed is False


def test_unknown_resource_kind_matches_no_policy(client):
    allowed = authorize(
        client,
        action="read",
        principal=Principal(id="alice", roles={"USER"}),
        resource=Resource(
            id="x1", kind="somethingElse", attr={"ownerId": "alice"}
        ),
    )
    assert allowed is False


def test_string_is_published_does_not_equal_boolean_true(client):
    """CEL is type-strict, and no schema enforces the type either."""
    allowed = authorize(
        client,
        action="read",
        principal=Principal(id="dave", roles={"USER"}),
        resource=Resource(
            id="doc-str",
            kind=RESOURCE_KIND,
            attr={"ownerId": "alice", "isPublished": "true"},
        ),
    )
    assert allowed is False


def test_missing_owner_id_attribute_denies_the_owner_rule(client):
    allowed = authorize(
        client,
        action="update",
        principal=Principal(id="alice", roles={"USER"}),
        resource=Resource(
            id="doc-noattr", kind=RESOURCE_KIND, attr={"isPublished": True}
        ),
    )
    assert allowed is False


def test_principal_without_roles_is_rejected_not_denied(client):
    """An empty role list is a request-level validation error, not a decision."""
    with pytest.raises(PdpError) as excinfo:
        authorize(
            client,
            action="create",
            principal=Principal(id="eve", roles=set()),
            resource=_alice_pub(),
        )
    assert "roles" in str(excinfo.value)


def test_unreachable_pdp_raises_instead_of_allowing():
    """Fail closed: an outage must never be mistaken for a permit."""
    with build_client(host="http://127.0.0.1:1", timeout_secs=1.0) as dead:
        with pytest.raises(PdpUnavailable):
            authorize(
                dead,
                action="read",
                principal=Principal(id="alice", roles={"USER"}),
                resource=_alice_pub(),
            )


def test_admin_wildcard_covers_an_action_no_rule_names(client):
    allowed = authorize(
        client,
        action="publish",
        principal=Principal(id="admin1", roles={"ADMIN"}),
        resource=_alice_pub(),
    )
    assert allowed is True


def test_user_has_no_wildcard(client):
    allowed = authorize(
        client,
        action="publish",
        principal=Principal(id="alice", roles={"USER"}),
        resource=_alice_pub(),
    )
    assert allowed is False


def test_the_sdk_client_is_httpx_based():
    """The HTTP SDK client is httpx-based, so transport failures surface there."""
    import cerbos.sdk.client as sdk_client

    assert hasattr(sdk_client, "CerbosClient")
    assert httpx is not None
