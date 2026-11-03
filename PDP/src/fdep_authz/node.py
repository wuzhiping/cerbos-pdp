"""The FDEP dispatch node, with the authorization gate in front of it.

This is the PocketFlow `Node` that FDEP's flow uses. It follows the
reference implementation's shape — `prep` collects, `exec` acts, `post`
publishes — with one thing added: **the gate runs before the work starts.**

The order is the whole point. A refusal has to happen before Temporal is
asked to run anything, because once a workflow is running, stopping it is
much harder than not starting it.

    shared ──► prep ──► exec ──────────────► post ──► shared["output"]
                  │       │
                  │       ├─► gate ──► PDP ──► DENY ──► 抛 FdepDenied,什么都没启动
                  │       │            └─► unreachable ──► 503,什么都没启动
                  │       └─► dispatch ──► Temporal
                  │
                  └─ api, do, inbound, workflowId, org, run_id

The `dispatch` callable is injected: FDEP passes the function that runs
the Temporal workflow, and the tests pass a stub. The node itself knows
nothing about Temporal, which is what makes it testable.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from pocketflow import Node

from fdep_authz.client import DEFAULT_PDP_URL, CerbosClient
from fdep_authz.errors import FdepDenied
from fdep_authz.gate import (
    STATUS_ALLOWED,
    GateOutcome,
    authorize_call,
)
from fdep_authz.registry import AppRegistry


def provider_kind(org: Mapping[str, Any]) -> str:
    """The Cerbos kind of a provider: `namespace.task_queue.workflow`.

    This is the provider's identity in the request, and it is built from the
    org's configuration **on the server side** — so the caller cannot
    choose which provider they are judged under.

    **Dotted, so every spelling of the provider is the same string:** the
    policy file, the policy's `resource:`, the request's `kind`, and the
    store's id (`resource.pip.JEV.LAYA.vdefault`). A colon-separated kind
    is rewritten by the store, and the kind and its id would disagree.
    """
    return ".".join(
        str(org[segment]) for segment in ("namespace", "task_queue", "workflow")
    )


class AuthzDispatchNode(Node):
    """Authorize, then dispatch.

    `dispatch(request_data, workflow_id, namespace, task_queue, workflow)`
    is what actually starts the work. It is only called after the PDP has
    allowed the call.
    """

    def __init__(
        self,
        dispatch: Callable[..., Any],
        *,
        registry: AppRegistry,
        pdp_url: str = DEFAULT_PDP_URL,
        client: CerbosClient | None = None,
        shadow: bool = False,
        timeout_secs: float = 10.0,
    ) -> None:
        super().__init__()
        self.dispatch = dispatch
        self.registry = registry
        self.pdp_url = pdp_url
        self.client = client
        self.shadow = shadow
        self.timeout_secs = timeout_secs

    # ── the flow contract ───────────────────────────────────────────────────
    def prep(self, shared: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "api": shared["api"],
            "do": shared.get("do", True),
            "inbound": shared.get("inbound", None),
            "workflowId": shared["workflowId"],
            "org": shared.get("org", None),
            "run_id": (shared.get("token", {}) or {}).get("run_id", None),
        }

    def exec(self, prep_res: Mapping[str, Any]) -> Any:
        api = prep_res["api"]
        do = prep_res["do"]
        inbound = prep_res["inbound"]
        workflow_id = prep_res["workflowId"]
        org = prep_res["org"]
        run_id = prep_res["run_id"]

        # Check before reading. The reference implementation reads
        # `org["namespace"]` before it checks that `org` is there, so a
        # missing org is a TypeError instead of the message that says what
        # is wrong.
        if not inbound:
            raise ValueError("缺少 inbound 参数")
        if not org:
            raise ValueError("org 为 None")

        namespace = org["namespace"]
        task_queue = org["task_queue"]
        workflow = org["workflow"]

        request_data = {
            "start_to_close_timeout": 600,
            # The `C4.` prefix is FDEP's own routing requirement. It is not
            # part of what the caller asked for, so it does not go into the
            # authorization request — the app id is what is authorized.
            "api": "C4." + api,
            "do": do,
            "inbound": inbound,
        }

        kind = provider_kind(org)

        outcome = self._authorize(
            api=api,
            do=do,
            inbound=inbound,
            kind=kind,
            run_id=run_id,
        )

        if not outcome.allowed:
            # A refusal is an error condition, not a result. Returning the
            # PDP's answer as if it were the workflow's output would make a
            # denied call indistinguishable from a workflow that ran and
            # produced nothing — and the caller would treat it as success.
            #
            # The exception carries the status code (403 / 503), the reason
            # and the PDP's own answer, so the layer above can still tell
            # "not permitted" from "could not tell", and can still find the
            # decision in the PDP's audit trail.
            raise outcome.to_exception()

        return self.dispatch(
            request_data, workflow_id, namespace, task_queue, workflow
        )

    def exec_fallback(self, prep_res: Mapping[str, Any], exc: Exception) -> Any:
        """A denial stays a denial.

        PocketFlow calls this when `exec` raises. Re-raising is the point:
        turning the refusal back into a return value would undo exactly
        what the raise was for. The flow's own error handling turns the
        exception into the response — `FdepDenied.to_payload()` has
        everything it needs.
        """
        raise exc

    def post(
        self,
        shared: dict[str, Any],
        prep_res: Mapping[str, Any],
        exec_res: Any,
    ) -> None:
        shared["output"] = {"data": exec_res}

    # ── the gate ────────────────────────────────────────────────────────────
    def _authorize(
        self,
        *,
        api: str,
        do: bool,
        inbound: Mapping[str, Any] | None,
        kind: str,
        run_id: str | None,
    ) -> GateOutcome:
        client = self.client or CerbosClient(
            self.pdp_url, timeout_secs=self.timeout_secs
        )
        return authorize_call(
            api=api,
            do=do,
            inbound=inbound,
            kind=kind,
            registry=self.registry,
            client=client,
            shadow=self.shadow,
            run_id=run_id,
            annotations={"app_id": api, "kind": kind},
        )


__all__ = ["AuthzDispatchNode", "STATUS_ALLOWED", "provider_kind"]
