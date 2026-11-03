"""The one call FDEP makes: `cerbos_valid`.

This is the drop-in for the reference implementation's `cerbosValid`. Same
argument order, same return shape — the result entry the PDP sent, so
`(result.get("actions") or {}).get(action, "EFFECT_DENY")` keeps working.

Two things are added:

* `cerbosCallId` is folded into the returned dict, so FDEP can write it
  into its own log line and the two audit trails can be reconciled.
* the failures are typed. A PDP that cannot be reached raises
  `PdpUnavailable`; a PDP that answered with something that is not a
  decision raises `PdpRejected`. Both are `RuntimeError`, so a caller that
  only knows the reference implementation's `except RuntimeError` still
  catches them — but a caller that wants to answer 503 instead of 403 can
  now tell the two apart.
"""

from __future__ import annotations

from typing import Any, Mapping

from fdep_authz.appid import parse_api
from fdep_authz.client import (
    DEFAULT_PDP_URL,
    DEFAULT_TIMEOUT_SECS,
    CerbosClient,
    Decision,
    PdpError,
)
from fdep_authz.registry import AppRegistry
from fdep_authz.token import build_principal, build_resource

#: What the reference implementation uses when there is no app registry
#: yet: every app is low risk. It is a placeholder — the registry is the
#: real source, and `fdep_authz.registry` says why a missing entry is not
#: the same thing as a missing risk level.
DEFAULT_RISK_LEVEL = "low"


def default_registry() -> AppRegistry:
    """A registry that treats every app as low risk.

    Only for the window between "the gate is switched on" and "the app
    registry is wired up". It is a placeholder, and a dangerous one: a
    high-risk app would come out as low risk. Wire the real registry in.
    """
    return AppRegistry.from_mapping({}, default_risk_level=DEFAULT_RISK_LEVEL)


def cerbos_valid(
    run_id: str | None,
    do: bool,
    inbound: Mapping[str, Any] | None,
    api: str,
    kind: str,
    *,
    registry: AppRegistry | None = None,
    pdp_url: str = DEFAULT_PDP_URL,
    timeout_secs: float = DEFAULT_TIMEOUT_SECS,
    client: CerbosClient | None = None,
) -> dict[str, Any]:
    """Ask the PDP whether one FDEP call may proceed.

    `run_id` becomes the PDP's request id, so the decision can be found
    again in the PDP's audit trail. `kind` is the provider's Cerbos kind —
    `namespace.task_queue.workflow` — built from the org's configuration on
    the server side.

    Returns the PDP's result entry, plus `cerbosCallId`.
    """
    token = (inbound or {}).get("_token_", {}) or {}
    app = parse_api(api)

    principal = build_principal(token)
    resource = build_resource(app, kind)

    own_client = client is None
    active = client or CerbosClient(pdp_url, timeout_secs=timeout_secs)
    try:
        decision = active.check(
            principal={
                "id": principal.id,
                "roles": list(principal.roles),
                "policyVersion": "default",
                "attr": dict(principal.attr),
            },
            resource={
                "kind": resource.kind,
                "id": resource.id,
                "policyVersion": "default",
            },
            action=app.action,
            request_id=run_id,
        )
    finally:
        if own_client:
            active.opener.close()

    return result_with_call_id(decision)


def result_with_call_id(decision: Decision) -> dict[str, Any]:
    """The result entry the PDP sent, plus the call id."""
    result = dict(decision.result)
    result["cerbosCallId"] = decision.call_id
    return result


__all__ = [
    "DEFAULT_RISK_LEVEL",
    "PdpError",
    "cerbos_valid",
    "default_registry",
    "result_with_call_id",
]
