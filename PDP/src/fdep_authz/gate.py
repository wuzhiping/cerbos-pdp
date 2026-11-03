"""The FDEP authorization gate.

One call goes in, one verdict comes out. The gate is deliberately a plain
function over plain data — no Temporal, no BPM, no HTTP framework — so it can
be unit tested on its own and dropped into `pipe.py` unchanged.

The verdict carries an HTTP status code, because the difference between 403
and 503 is the difference between "you may not" and "I could not tell":

    403  the PDP said no
    503  the PDP could not answer
    200  the call may proceed

A 503 lets the caller retry. A 403 does not — the caller will believe it
lacks permission and give up, which turns a two-second outage into a
day-long outage of that integration.

**Shadow mode.** With `shadow=True` the gate asks the PDP, records the
answer, and lets everything through. A wrong decision costs nothing, and
real traffic is the only way to find out whether the policy says the right
thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fdep_authz.appid import AppId, InvalidApi, parse_api
from fdep_authz.client import Decision, PdpRejected, PdpUnavailable
from fdep_authz.errors import FdepDenied
from fdep_authz.registry import AppRegistry, InvalidRegistryEntry, UnknownApp
from fdep_authz.token import Principal, Resource, build_principal, build_resource

STATUS_ALLOWED = 200
STATUS_DENIED = 403
STATUS_UNAVAILABLE = 503


@dataclass(frozen=True)
class GateOutcome:
    """What the gate decided about one call."""

    allowed: bool
    status_code: int
    reason: str
    api: str = ""
    kind: str = ""
    path: str = ""
    operation: str = ""
    decision: Decision | None = None
    shadow: bool = False

    @property
    def call_id(self) -> str:
        """The PDP's call id — the key that ties this call to the audit trail."""
        return self.decision.call_id if self.decision else ""

    @property
    def denied_by_policy(self) -> bool:
        """True when the PDP itself said no."""
        return self.decision is not None and not self.decision.allowed

    def to_exception(self) -> FdepDenied:
        """This verdict, as the exception the gate raises.

        A refusal is an error condition, not a result — so it is raised,
        not returned. The exception carries the status code, the reason and
        the PDP's own answer, so nothing is lost on the way out.
        """
        return FdepDenied(
            self.status_code,
            self.reason,
            cerbos_call_id=self.call_id,
            result=dict(self.decision.result) if self.decision else {},
        )


def _outcome(
    status_code: int,
    reason: str,
    app: AppId | None = None,
    kind: str = "",
    *,
    allowed: bool = False,
    decision: Decision | None = None,
    shadow: bool = False,
) -> GateOutcome:
    return GateOutcome(
        allowed=allowed,
        status_code=status_code,
        reason=reason,
        api=str(app) if app else "",
        kind=kind,
        path=app.path if app else "",
        operation=app.operation if app else "",
        decision=decision,
        shadow=shadow,
    )


def authorize_call(
    *,
    api: str,
    do: bool,
    inbound: Mapping[str, Any] | None,
    kind: str,
    registry: AppRegistry,
    client,
    shadow: bool = False,
    default_guest: bool = True,
    run_id: str | None = None,
    annotations: Mapping[str, str] | None = None,
) -> GateOutcome:
    """Decide whether one FDEP call may proceed.

    `kind` is the provider's Cerbos kind — `namespace.task_queue.workflow` —
    and it is built from the org's configuration on the server side, so the
    caller cannot choose it.

    `client` is anything with a `check(...)` method — `CerbosClient` in
    production, a stub in the tests.
    """
    # 1. Which app is being called?
    try:
        app = parse_api(api)
    except InvalidApi as exc:
        return _outcome(STATUS_DENIED, f"the api id is not usable: {exc}")

    # 2. Who is calling?
    token = (inbound or {}).get("_token_", {}) or {}
    principal: Principal = build_principal(token, default_guest=default_guest)
    if not principal.roles:
        # The PDP answers HTTP 400 for an empty role list — a malformed
        # request, not a decision. Refusing here keeps that from ever
        # happening, and the caller is told the truth: there was no role.
        return _outcome(STATUS_DENIED, "the request carries no roles", app, kind)

    # 3. Does this app exist?
    try:
        registry.require(app.registry_key)
    except UnknownApp as exc:
        # The app does not exist, so there is nothing to call and nothing
        # to authorize. That is the caller's mistake.
        return _outcome(STATUS_DENIED, f"the app is not registered: {exc}", app, kind)
    except InvalidRegistryEntry as exc:
        # Our own data is incomplete, so the call cannot be judged. Not the
        # caller's fault, and refusing it would hide the gap.
        return _outcome(
            STATUS_UNAVAILABLE,
            f"the app registry is incomplete: {exc}",
            app,
            kind,
        )

    # The attributes are switched off, so the resource carries none.
    resource: Resource = build_resource(app, kind)

    # 4. Ask the PDP.
    try:
        decision = client.check(
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
            annotations=annotations,
        )
    except (PdpUnavailable, PdpRejected) as exc:
        if shadow:
            return _outcome(
                STATUS_ALLOWED,
                f"shadow mode: the PDP could not answer ({exc})",
                app,
                kind,
                allowed=True,
                shadow=True,
            )
        return _outcome(
            STATUS_UNAVAILABLE, f"the PDP could not answer: {exc}", app, kind
        )

    # 5. The verdict.
    if decision.allowed:
        return _outcome(
            STATUS_ALLOWED,
            f"allowed by {decision.matched_policy or 'the policy'}",
            app,
            kind,
            allowed=True,
            decision=decision,
            shadow=shadow,
        )

    # 6. The PDP said no. Say why, in a way the caller can act on.
    if decision.no_match:
        reason = (
            f"no policy is deployed for the kind {kind!r} — "
            f"the provider has no policy"
        )
    elif decision.rejected_by_schema:
        detail = "; ".join(
            str(error.get("message", error)) for error in decision.validation_errors
        )
        reason = f"the request did not pass schema validation: {detail}"
    else:
        reason = f"denied by {decision.matched_policy or 'the policy'}"

    if shadow:
        return _outcome(
            STATUS_ALLOWED,
            f"shadow mode: {reason}",
            app,
            kind,
            allowed=True,
            decision=decision,
            shadow=True,
        )

    return _outcome(STATUS_DENIED, reason, app, kind, decision=decision)


__all__ = [
    "GateOutcome",
    "STATUS_ALLOWED",
    "STATUS_DENIED",
    "STATUS_UNAVAILABLE",
    "authorize_call",
]
