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


def effect(
    principal_id: str,
    roles: frozenset[str] | set[str],
    resource_attr: Mapping[str, Any],
    action: str,
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
    """
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
