"""What the PDP actually serves: the policy inventory and its schema state.

The store names a policy by its source file on a directory store
(``basicResource.yaml``) and by its compiled id on a mutable one
(``resource.basicResource.vdefault``). Either way it is this policy — so the
test asserts on that, not on a driver-specific id.

The schema tests state what the policy *intends*. The schemas are deployed and
their references resolve, but the PDP's ``schema.enforcement`` defaults to
``none``, so a malformed attribute is evaluated as-is instead of being
rejected. That is recorded as a test rather than a comment.
"""

from __future__ import annotations

import httpx
import pytest

from cerbos_policy_tests.client import admin_headers, pdp_url

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

# The policy references its schemas as `cerbos:///principal.json` and
# `cerbos:///basicResource.json`, but the *store* holds them under the path
# relative to the schema root — `principal.json`, `basicResource.json`. The
# PDP strips the prefix before looking one up, so this is what has to match.
DECLARED_SCHEMA_REFS = {"principal.json", "basicResource.json"}


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


def _check(attr: dict) -> httpx.Response:
    """One check/resources call with the given resource attributes."""
    return httpx.post(
        f"{pdp_url()}/api/check/resources",
        json={
            "requestId": "schema-probe",
            "principal": {
                "id": "alice",
                "roles": ["USER"],
                "policyVersion": "default",
            },
            "resources": [
                {
                    "resource": {
                        "kind": RESOURCE_KIND,
                        "id": "doc-bad",
                        "policyVersion": "default",
                        "attr": attr,
                    },
                    "actions": ["read"],
                }
            ],
        },
        timeout=20.0,
    )


def test_a_well_formed_request_is_allowed_and_reports_no_errors():
    """The control for the test below.

    Every malformed fixture here would be ALLOWED by the policy on its own —
    the ownership branch still matches, or the publication branch does. So the
    only thing that can turn them into a DENY is the schema. This control
    proves the request shape and the fixture are right, so a DENY below is
    attributable to the schema and not to the policy.
    """
    response = _check({"ownerId": "alice", "isPublished": True})
    response.raise_for_status()

    result = response.json()["results"][0]
    assert result["actions"]["read"] == "EFFECT_ALLOW", result
    assert not result.get("validationErrors"), result


@pytest.mark.parametrize(
    "attr",
    [
        {"ownerId": "alice", "isPublished": "true"},        # wrong type
        {"ownerId": "alice"},                               # missing a required one
        {"isPublished": True},                              # missing a required one
        {"ownerId": "alice", "isPublished": True, "x": 1},  # undeclared attribute
    ],
)
def test_malformed_attributes_are_rejected_by_schema_validation(attr):
    """A request that fails schema validation must be denied, and say why.

    Two things the SDK cannot show, so this reads the raw HTTP response:

    * ``reject`` mode *denies* the request, it does not fail it with an error
      status — the response is still 200, with the effect set to DENY.
    * the SDK's response model has no ``validation_errors`` field, so it
      silently drops them. The errors live on the **result entry**, next to
      ``actions`` — not at the top level of the response.
    """
    response = _check(attr)
    assert response.status_code == 200, response.text[:300]

    result = response.json()["results"][0]

    # every action of a request that failed validation is denied
    assert result["actions"]["read"] == "EFFECT_DENY", result

    # and the response says why
    errors = result.get("validationErrors")
    assert errors, result
    assert all({"path", "message"} <= set(e) for e in errors), errors
