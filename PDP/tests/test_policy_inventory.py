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
from cerbos_policy_tests.fdep_rules import kinds, store_names

RESOURCE_KIND = "basicResource"

# The store names a policy by its source file (directory store) or by its
# compiled id (mutable store). This PDP hosts more than one policy, so the
# test asserts that ours is served and that nothing outside the known set is.
EXPECTED_POLICY_IDS = {
    "basicResource.yaml",
    "resource.basicResource.vdefault",
}
# The FDEP families: one policy per provider. The provider is the Cerbos
# kind — `namespace:task_queue:workflow` — and the store keeps it under the
# name with the colons turned into underscores.
FDEP_API_POLICY_IDS = {
    f"resource.{name}.vdefault" for name in store_names()
}

#: The kinds we have ever used. The older ones are here so that a policy
#: left over from an earlier layout is caught rather than ignored.
OUR_KINDS = set(store_names()) | {"fdepApi", "systemone", "twseMops"}
KNOWN_POLICY_IDS = EXPECTED_POLICY_IDS | FDEP_API_POLICY_IDS | {
    "resource.risk_case.vdefault",
}
EXPECTED_ACTIONS = {"*", "create", "delete", "read", "update"}
EXPECTED_ATTRIBUTES = {"isPublished", "ownerId"}

# The policy references its schemas as `cerbos:///principal.json` and
# `cerbos:///basicResource.json`, but the *store* holds them under the path
# relative to the schema root — `principal.json`, `basicResource.json`. The
# PDP strips the prefix before looking one up, so this is what has to match.
DECLARED_SCHEMA_REFS = {"principal.json", "basicResource.json", "fdep.json"}


def _admin_get(path: str) -> dict:
    response = httpx.get(f"{pdp_url()}{path}", headers=admin_headers(), timeout=10.0)
    response.raise_for_status()
    return response.json()


def _inspect() -> dict:
    """The compiled policies, keyed by their store id."""
    return _admin_get("/admin/policies/inspect")["results"]


def _kind_of(policy_id: str) -> str:
    """The kind a store policy id belongs to.

    `resource.pip.JEV.LAYA.vdefault` -> `pip.JEV.LAYA`. The kind is dotted,
    so it cannot be split off with one `.` — it is everything between
    `resource.` and `.vdefault`.
    """
    if not policy_id.startswith("resource."):
        return ""
    return policy_id[len("resource.") : -len(".vdefault")]


def test_only_the_expected_policy_is_served():
    """Every policy of ours is served — and nothing else of ours is.

    This PDP is shared, so other people's policies are legitimately in the
    store. The assertion is therefore about **our** kinds: every policy we
    deploy has to be there and enabled, and no policy of ours may be left
    over from an older layout (a stale policy is never consulted, but it
    makes the inventory a lie).
    """
    listed = set(_admin_get("/admin/policies")["policyIds"])
    ours = {
        policy_id
        for policy_id in listed
        if _kind_of(policy_id) in OUR_KINDS
    }
    assert ours == FDEP_API_POLICY_IDS, sorted(ours ^ FDEP_API_POLICY_IDS)

    assert EXPECTED_POLICY_IDS & listed, listed


def test_policy_exposes_the_expected_actions():
    entry = _inspect()["resource.basicResource.vdefault"]
    assert set(entry["actions"]) == EXPECTED_ACTIONS


def test_policy_exposes_the_expected_attributes():
    entry = _inspect()["resource.basicResource.vdefault"]
    names = {attr["name"] for attr in entry["attributes"]}
    assert names == EXPECTED_ATTRIBUTES


def test_every_provider_policy_is_in_the_store():
    """A provider with no policy is NO_MATCH — every call of it is denied.

    There is no scope any more, so one policy per provider is all there is:
    no chain, no levels to keep complete.
    """
    listed = set(_admin_get("/admin/policies")["policyIds"])
    missing = [
        policy_id
        for policy_id in sorted(FDEP_API_POLICY_IDS)
        if policy_id not in listed
    ]
    assert not missing, missing


def test_the_provider_policies_declare_the_schema_of_their_own():
    """There is no chain, so each policy declares the schema itself.

    The schema validates the attributes, so it is only declared while they
    are in use.
    """
    import yaml

    from cerbos_policy_tests.config import POLICY_DIR
    from cerbos_policy_tests.fdep_rules import attributes_enabled

    for kind in kinds():
        document = yaml.safe_load(
            (POLICY_DIR / f"{kind.replace(':', '.')}.yaml").read_text(encoding="utf-8")
        )
        policy = document["resourcePolicy"]
        assert "scope" not in policy, "there is no scope any more"
        if attributes_enabled():
            assert policy["schemas"]["resourceSchema"]["ref"] == "cerbos:///fdep.json"
        else:
            assert "schemas" not in policy


def test_declared_schema_references_are_resolved_by_the_store():
    """Every schema the policy names must be in the store."""
    present = set(_admin_get("/admin/schemas")["schemaIds"])
    assert DECLARED_SCHEMA_REFS <= present


def test_the_fdep_api_schema_is_stored_under_a_relative_path():
    """The store holds the path relative to the schema root.

    The policy's ref carries the `cerbos:///` prefix and the PDP strips it
    before looking the schema up. A row stored with the prefix lists fine
    and can never be read — and every request is then rejected, because the
    schema fails to load.
    """
    present = set(_admin_get("/admin/schemas")["schemaIds"])
    assert "fdep.json" in present, present
    assert not any(s.startswith("cerbos:///") for s in present), present


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
