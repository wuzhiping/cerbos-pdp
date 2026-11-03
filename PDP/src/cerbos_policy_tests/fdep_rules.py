"""A reference implementation of the FDEP rules.

Written from the policy text, not from the PDP, so it is an oracle the PDP
can be checked against: if the PDP and this model ever disagree, one of
them is wrong.

It is not the authoritative expectation. That is the native `*_test.yaml`
suite, whose expectations are written by hand. This model exists so the
exhaustive sweep can cover every principal, app and action without a
hand-written table of hundreds of rows.

**The shape of one call.** There is no scope. The provider is the kind, the
app family inside it is the id, and the operation is the action:

    kind   = namespace.task_queue.workflow      pip.JEV.LAYA
    id     = the C4 path                       systemone.LAYA
    action = the plugin file                   Choice.py
    attr   = { accessMode, riskLevel }

So there is one policy per provider, and the app families inside it are
told apart by the resource id — the generator puts `R.id == "<c4 path>"`
into each family rule, and this model applies the same test.

**Where the rules come from.** The same sources the generator reads:

    pdp-config/general-rules.yaml   the same for every provider
    pdp-config/orgs.yaml → orgs[]   that provider's own rules

The model knows how to evaluate the rules by name. A rule it does not know
is an error, not a guess — the oracle has to be able to say "I don't know
this one" rather than quietly skip it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable, Mapping

import yaml

from cerbos_policy_tests.config import GENERAL_RULES, ORGS_REGISTRY

EFFECT_ALLOW = "EFFECT_ALLOW"
EFFECT_DENY = "EFFECT_DENY"

# The schema every FDEP resource is validated against. With
# `schema.enforcement: reject` on the PDP, a request that fails validation
# is denied for every action it covers — so the oracle has to know about
# the schema, or it would predict ALLOW where the PDP says DENY.
RESOURCE_SCHEMA = {
    "accessMode": str,
    "riskLevel": str,
}
RESOURCE_REQUIRED = ("accessMode", "riskLevel")
ACCESS_MODES = ("read", "execute")
RISK_LEVELS = ("low", "medium", "high")


@lru_cache(maxsize=1)
def _registry() -> dict:
    document = yaml.safe_load(ORGS_REGISTRY.read_text(encoding="utf-8")) or {}
    return {"orgs": document.get("orgs") or []}


@lru_cache(maxsize=1)
def _general() -> list[dict]:
    document = yaml.safe_load(GENERAL_RULES.read_text(encoding="utf-8")) or {}
    return document.get("rules") or []


@lru_cache(maxsize=1)
def attributes_enabled() -> bool:
    """Whether the policy may read `R.attr`.

    The switch lives in the org registry, and the generator reads the same
    file — so the model and the deployment cannot disagree about which
    rules are live.
    """
    document = yaml.safe_load(ORGS_REGISTRY.read_text(encoding="utf-8")) or {}
    value = document.get("attributes")
    return True if value is None else bool(value)


def reads_an_attribute(rule: dict) -> bool:
    """Whether a rule's condition reads `R.attr`."""
    condition = rule.get("condition") or {}
    expr = (condition.get("match") or {}).get("expr", "")
    return "R.attr" in expr


@lru_cache(maxsize=1)
def kinds() -> tuple[str, ...]:
    """Every provider kind the store is expected to hold."""
    return tuple(sorted(str(org.get("kind") or "") for org in _registry()["orgs"]))


@lru_cache(maxsize=1)
def store_names() -> tuple[str, ...]:
    """The kinds under the names the store keeps them.

    A dotted kind is kept as it is — `resource.pip.JEV.LAYA.vdefault` — so
    this is the kinds themselves. A **colon-separated** kind is rewritten
    (`pip:JEV:LAYA` -> `resource.pip_JEV_LAYA.vdefault`), which is why the
    kind is dotted.
    """
    return tuple(sorted(kinds()))


@lru_cache(maxsize=1)
def file_names() -> tuple[str, ...]:
    """The kinds under the names the policy files carry — the kinds again."""
    return tuple(sorted(kinds()))


def resolve(name: str) -> str:
    """The policy kind a suite's file name stands for.

    A suite is named after the policy it tests, and the file name is the
    kind — so this is usually the identity, but a colon-separated spelling
    is accepted too.
    """
    for kind in kinds():
        if name in (kind, kind.replace(":", "_"), kind.replace(":", ".")):
            return kind
    raise KeyError(name)


@lru_cache(maxsize=1)
def families(kind: str) -> tuple[tuple[str, tuple[dict, ...]], ...]:
    """The app families a provider serves, with their own grants.

    The C4 path is the family's id, and it is what separates the families
    inside one policy.

    A grant is three things: the principal's id, the family, and the
    operations.
    """
    for org in _registry()["orgs"]:
        if str(org.get("kind") or "") != kind:
            continue
        found = []
        for app in org.get("apps") or []:
            found.append((str(app.get("path") or ""), tuple(app.get("grants") or [])))
        return tuple(found)
    return ()


@lru_cache(maxsize=1)
def general_rules() -> tuple[dict, ...]:
    return tuple(_general())


# ── how a rule is evaluated ─────────────────────────────────────────────────
#
# Each rule is evaluated by name. A rule the model does not know raises —
# an oracle that quietly skipped a rule would agree with the PDP for the
# wrong reason.

def _admin(
    principal_id: str, resource_id: str, roles: frozenset[str], attr: Mapping[str, Any]
) -> bool:
    return "FDEP_ADMIN" in roles


def _developer(
    principal_id: str, resource_id: str, roles: frozenset[str], attr: Mapping[str, Any]
) -> bool:
    return (
        "FDEP_DEVELOPER" in roles
        and attr.get("accessMode") == "execute"
        and attr.get("riskLevel") != "high"
    )


def _auditor(
    principal_id: str, resource_id: str, roles: frozenset[str], attr: Mapping[str, Any]
) -> bool:
    return (
        "FDEP_AUDITOR" in roles
        and attr.get("accessMode") == "read"
        and attr.get("riskLevel") == "low"
    )


KNOWN_RULES: dict[
    str, Callable[[str, str, frozenset[str], Mapping[str, Any]], bool]
] = {
    "admin-may-call-anything": _admin,
    "developer-may-execute-non-high-risk": _developer,
    "auditor-may-only-read-low-risk": _auditor,
}


def _matches_action(pattern: str, action: str) -> bool:
    """Whether a rule's action pattern covers an action.

    Cerbos matches the action name against a glob in which `*` stands for
    any characters — so `*.py` covers `Choice.py`, and `*` covers
    everything.
    """
    if pattern == "*":
        return True
    if "*" not in pattern:
        return pattern == action
    import re

    expression = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.fullmatch(expression, action) is not None


def _grants(
    rules: tuple[dict, ...],
    principal_id: str,
    resource_id: str,
    roles: frozenset[str],
    attr: Mapping[str, Any],
    action: str,
    *,
    known: dict[str, Callable[[str, str, frozenset[str], Mapping[str, Any]], bool]]
    | None = None,
) -> bool:
    """Does any of these rules grant the action?

    `known` is the table of rules the model can evaluate by name — the
    general rules. A rule that is not in it is an error, because an oracle
    that quietly skipped a rule would agree with the PDP for the wrong
    reason.

    A **grant** (the app families' own) is judged by the registry alone:
    it names a principal, or roles, or nothing at all.
    """
    for rule in rules:
        name = rule.get("name")
        if rule.get("effect") != "EFFECT_ALLOW":
            continue
        if not attributes_enabled() and reads_an_attribute(rule):
            # The rule is switched off **entirely**: the condition is what
            # made it narrow, so stripping only the condition would widen
            # the grant.
            continue
        patterns = [str(p) for p in (rule.get("actions") or ["*"])]
        if not any(_matches_action(p, action) for p in patterns):
            continue

        # A grant that names a principal is judged by the principal's id.
        # A grant that names roles is judged by the roles. A grant that
        # names neither is **open** — whoever asks, gets it.
        principal = rule.get("principal")
        rule_roles = set(rule.get("roles") or ())
        if principal:
            if str(principal) != principal_id:
                continue
        elif rule_roles and "*" not in rule_roles:
            if not (rule_roles & roles):
                continue

        if known is not None:
            evaluate = known.get(name)
            if evaluate is None:
                raise KeyError(
                    f"the reference model does not know how to evaluate the rule "
                    f"{name!r} — add it to "
                    f"cerbos_policy_tests.fdep_rules.KNOWN_RULES"
                )
            if not evaluate(principal_id, resource_id, roles, attr):
                continue
        return True
    return False


def _matches_type(value: Any, expected: type) -> bool:
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


def resource_is_valid(resource_attr: Mapping[str, Any]) -> bool:
    """Would this resource pass schema validation?

    The schema pins the two attributes to enumerations, so a value outside
    one of them is rejected — that is stricter than a type check, and it is
    what makes a typo fail loudly instead of silently denying every rule.

    **While the attributes are switched off there is no schema**, so there
    is nothing to validate: whatever the resource carries is ignored.
    """
    if not attributes_enabled():
        return True
    if not _satisfies(resource_attr, RESOURCE_SCHEMA, RESOURCE_REQUIRED):
        return False
    if resource_attr["accessMode"] not in ACCESS_MODES:
        return False
    if resource_attr["riskLevel"] not in RISK_LEVELS:
        return False
    return True


def effect(
    kind: str,
    resource_id: str,
    roles: frozenset[str] | set[str],
    resource_attr: Mapping[str, Any],
    action: str = "",
    principal_id: str = "",
) -> str:
    """The effect the policy grants for one request.

    The order of the checks is the order of the PDP's:

    1. schema validation — a request that fails it is denied for every
       action it covers, before any rule is consulted;
    2. the kind — a provider with no policy is NO_MATCH, and nothing else
       is consulted;
    3. the general rules, which every provider's policy carries;
    4. the app family's own grants, which apply to that family only.

    A grant is judged on **three things**: the principal's id, the
    resource's id (the C4 path) and the action (the plugin file).

    While the attributes are switched off, a rule that reads `R.attr` is
    not applied at all — the same way the generator leaves it out of the
    policy.
    """
    role_set = frozenset(roles)

    if not resource_is_valid(resource_attr):
        return EFFECT_DENY

    if kind not in kinds():
        # NO_MATCH: the store holds no policy for this provider.
        return EFFECT_DENY

    if _grants(
        general_rules(),
        principal_id,
        resource_id,
        role_set,
        resource_attr,
        action,
        known=KNOWN_RULES,
    ):
        return EFFECT_ALLOW

    for path, rules in families(kind):
        if path != resource_id:
            continue
        if _grants(
            rules, principal_id, resource_id, role_set, resource_attr, action
        ):
            return EFFECT_ALLOW

    return EFFECT_DENY


__all__ = [
    "EFFECT_ALLOW",
    "EFFECT_DENY",
    "KNOWN_RULES",
    "attributes_enabled",
    "effect",
    "families",
    "file_names",
    "general_rules",
    "kinds",
    "resolve",
    "resource_is_valid",
    "store_names",
]
