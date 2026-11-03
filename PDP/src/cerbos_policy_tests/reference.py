"""The reference model of a policy family, chosen by resource kind.

Every policy family has a model written from its own policy text — an
oracle the PDP can be checked against. This module is the one place that
knows which model belongs to which kind, so the tests do not have to.

A family without a model is an error, not a skip: a suite whose
expectations are never compared against anything would run, and pass,
without checking the policy it describes.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from cerbos_policy_tests import fdep_rules, rules

EFFECT_ALLOW = rules.EFFECT_ALLOW
EFFECT_DENY = rules.EFFECT_DENY


def effect(
    kind: str,
    *,
    principal_id: str,
    roles: Iterable[str],
    resource_id: str,
    resource_attr: Mapping[str, Any],
    resource_scope: str = "",
    resource_kind: str = "",
    action: str = "",
    principal_attr: Mapping[str, Any] | None = None,
) -> str:
    """What the reference model says about one request.

    `kind` is the family the suite belongs to; `resource_kind` is the kind
    the request actually carries — for the FDEP families that is the
    provider, so it is what the policy is filed under.
    """
    role_set = set(roles)

    if kind == "basicResource":
        return rules.effect(
            principal_id, role_set, resource_attr, action, principal_attr
        )

    try:
        policy_kind = fdep_rules.resolve(kind)
    except KeyError:
        raise KeyError(f"no reference model for resource kind {kind!r}") from None

    return fdep_rules.effect(
        resource_kind or policy_kind,
        resource_id,
        role_set,
        resource_attr,
        action,
        principal_id=principal_id,
    )


__all__ = ["EFFECT_ALLOW", "EFFECT_DENY", "effect"]
