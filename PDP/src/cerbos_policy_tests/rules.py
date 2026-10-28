"""A reference implementation of basicResource's rules.

This is written from the policy text, not from the PDP, so it is an oracle
the PDP can be checked against: if the PDP and this model ever disagree, one
of them is wrong.

It is not the authoritative expectation. That is the native `*_test.yaml`
suite, whose expectations are written by hand. This model exists so the
exhaustive cross-product sweep can cover every principal, resource and action
without a hand-written table of a hundred and forty rows.
"""

from __future__ import annotations

from typing import Any, Mapping

EFFECT_ALLOW = "EFFECT_ALLOW"
EFFECT_DENY = "EFFECT_DENY"

# The schemas the policy declares, and the `ignoreWhen` that exempts one
# action from resource validation. With `schema.enforcement: reject` on the
# PDP, a request that fails validation is denied for every action it covers —
# so the oracle has to know about the schemas, or it will predict ALLOW where
# the PDP says DENY.
RESOURCE_SCHEMA = {
    "ownerId": str,
    "isPublished": bool,
}
RESOURCE_REQUIRED = ("ownerId", "isPublished")
PRINCIPAL_SCHEMA = {
    "department": str,
    "tenant": str,
}
# resourceSchema.ignoreWhen in the policy: a record being created has no
# owner and no publication state yet.
RESOURCE_VALIDATION_IGNORED_ACTIONS = frozenset({"create"})


def _matches_type(value: Any, expected: type) -> bool:
    if expected is bool:
        # isinstance(1, bool) is False, but True/False must be exact: the
        # schema says boolean, not "something truthy".
        return isinstance(value, bool)
    return isinstance(value, expected)


def _satisfies(attributes: Mapping[str, Any], schema: Mapping[str, type],
               required: tuple[str, ...]) -> bool:
    """Would these attributes pass the schema?

    Mirrors the JSON Schema the PDP compiles: required properties present,
    each property's type right, and no undeclared properties.
    """
    for name in required:
        if name not in attributes:
            return False
    for name, value in attributes.items():
        if name not in schema:
            return False
        if not _matches_type(value, schema[name]):
            return False
    return True


def resource_is_valid(resource_attr: Mapping[str, Any], action: str) -> bool:
    """Would this resource pass schema validation for this action?"""
    if action in RESOURCE_VALIDATION_IGNORED_ACTIONS:
        return True
    return _satisfies(resource_attr, RESOURCE_SCHEMA, RESOURCE_REQUIRED)


def effect(
    principal_id: str,
    roles: frozenset[str] | set[str],
    resource_attr: Mapping[str, Any],
    action: str,
    principal_attr: Mapping[str, Any] | None = None,
) -> str:
    """The effect the policy grants for one request.

    Mirrors the four rules of basicResource:

        R1  actions=[*]              roles=[ADMIN]  ALLOW
        R2  actions=[create]         roles=[USER]   ALLOW
        R3  actions=[read]           roles=[USER]   ALLOW if isPublished==true
                                                        OR ownerId==principal.id
        R4  actions=[update,delete]  roles=[USER]   ALLOW if ownerId==principal.id

    Deny by default. Within a role a matching deny would beat a matching
    allow, and an allow from any role grants the action — the policy has no
    deny rules, so the roles simply combine.

    CEL is type-strict, and so is this: `isPublished` must be the boolean
    true, not the string "true" and not 1.

    And before any rule is consulted, the request has to pass schema
    validation. The PDP rejects the whole check when it does not, so the
    oracle denies it too — for every action the schema covers.
    """
    if principal_attr is not None and not _satisfies(
        principal_attr, PRINCIPAL_SCHEMA, ()
    ):
        return EFFECT_DENY

    if not resource_is_valid(resource_attr, action):
        return EFFECT_DENY

    if "ADMIN" in roles:
        return EFFECT_ALLOW

    if "USER" in roles:
        if action == "create":
            return EFFECT_ALLOW
        if action == "read":
            if resource_attr.get("isPublished") is True:
                return EFFECT_ALLOW
            if resource_attr.get("ownerId") == principal_id:
                return EFFECT_ALLOW
        if action in ("update", "delete"):
            if resource_attr.get("ownerId") == principal_id:
                return EFFECT_ALLOW

    return EFFECT_DENY
