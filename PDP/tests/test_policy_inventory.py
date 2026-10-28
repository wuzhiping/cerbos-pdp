"""What the PDP actually serves: the policy inventory and its schema state.

The store names a policy by its source file on a directory store
(``basicResource.yaml``) and by its compiled id on a mutable one
(``resource.basicResource.vdefault``). Either way there is exactly one, and
it is this policy — so the test asserts on that, not on a driver-specific id.

The schema tests state what the policy *intends*. One of them still fails
because the PDP enforces schemas in ``warn`` mode by default: the schemas
resolve, but a malformed attribute is silently denied instead of being
rejected as a validation error. That is recorded as a test rather than a
comment.
"""

from __future__ import annotations

import httpx
import pytest

from cerbos_policy_tests.client import admin_headers, pdp_url
from cerbos_policy_tests.pep import PdpError, authorize

from cerbos.sdk.model import Principal, Resource

RESOURCE_KIND = "basicResource"

# The store names a policy by its source file (directory store) or by its
# compiled id (mutable store). This PDP hosts more than one policy, so the
# test asserts that ours is served and that nothing outside the known set is.
EXPECTED_POLICY_IDS = {
    "basicResource.yaml",
    "resource.basicResource.vdefault",
}
KNOWN_POLICY_IDS = EXPECTED_POLICY_IDS | {
    "resource.risk_case.vdefault",
}
EXPECTED_ACTIONS = {"*", "create", "delete", "read", "update"}
EXPECTED_ATTRIBUTES = {"isPublished", "ownerId"}

DECLARED_SCHEMA_REFS = {"cerbos:///principal.json", "cerbos:///basicResource.json"}


def _admin_get(path: str) -> dict:
    response = httpx.get(f"{pdp_url()}{path}", headers=admin_headers(), timeout=10.0)
    response.raise_for_status()
    return response.json()


def test_only_the_expected_policy_is_served():
    listed = _admin_get("/admin/policies?includeDisabled=true")
    ids = set(listed["policyIds"])
    assert ids & EXPECTED_POLICY_IDS, ids
    assert ids <= KNOWN_POLICY_IDS, ids


def test_policy_exposes_the_expected_actions():
    inspected = _admin_get("/admin/policies/inspect")
    entry = next(iter(inspected["results"].values()))
    assert set(entry["actions"]) == EXPECTED_ACTIONS


def test_policy_exposes_the_expected_attributes():
    inspected = _admin_get("/admin/policies/inspect")
    entry = next(iter(inspected["results"].values()))
    names = {attr["name"] for attr in entry["attributes"]}
    assert names == EXPECTED_ATTRIBUTES


def test_declared_schema_references_are_resolved_by_the_store():
    """Every schema the policy names must be in the store."""
    present = set(_admin_get("/admin/schemas")["schemaIds"])
    assert DECLARED_SCHEMA_REFS <= present


@pytest.mark.xfail(
    strict=True,
    reason=(
        "the PDP enforces schemas in 'warn' mode by default (schema.enforcement), "
        "so a malformed attribute is silently denied instead of being rejected "
        "as a validation error"
    ),
)
@pytest.mark.parametrize(
    "attr",
    [
        {"ownerId": "alice", "isPublished": "true"},
        {"ownerId": "alice"},
        {"isPublished": True},
    ],
)
def test_malformed_attributes_are_rejected_by_schema_validation(client, attr):
    with pytest.raises(PdpError):
        authorize(
            client,
            action="read",
            principal=Principal(id="alice", roles={"USER"}),
            resource=Resource(id="doc-bad", kind=RESOURCE_KIND, attr=attr),
        )
