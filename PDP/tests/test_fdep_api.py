"""The FDEP authorization gate — the FDEP side of the design.

The native suites in `policies/` say what the policies should do. This
module checks the other half: that the gate FDEP will call turns an app
id, a `_token_` and a payload into that policy's decision — and that it
answers 403 and 503 for the two different failures.

The three rules that are easiest to get wrong have a test each:

* the `do` flag is inverted once upstream, so `do == False` is "execute";
* the kind is the provider's identity and it is built on the server side;
* "no" and "could not tell" are different answers.

The live tests run against the PDP this repository deploys to, so they check
the whole chain: app id -> principal and resource -> PDP -> verdict.
"""

from __future__ import annotations

import json
import time
from typing import Any, Mapping

import httpx
import pytest

from cerbos_policy_tests.client import admin_headers, pdp_url
from fdep_authz import (
    AppRegistry,
    AuthzDispatchNode,
    CerbosClient,
    Decision,
    FdepDenied,
    InvalidApi,
    PdpUnavailable,
    STATUS_ALLOWED,
    STATUS_DENIED,
    STATUS_UNAVAILABLE,
    authorize_call,
    cerbos_valid,
    parse_api,
    provider_kind,
)

# ── the fixtures the gate is exercised with ─────────────────────────────────

#: The provider's Cerbos kind: namespace.task_queue.workflow.
KIND = "pip.JEV.LAYA"

#: The app id that reaches the gate — the org prefix is already stripped.
API = "systemone.LAYA.Choice"

REGISTRY = AppRegistry.from_mapping(
    {
        "systemone.LAYA": {"riskLevel": "low"},
        "twseMops": {"riskLevel": "medium"},
    }
)

ORG = {"namespace": "pip", "task_queue": "JEV", "workflow": "LAYA"}

GUEST_INBOUND: Mapping[str, Any] = {
    "_token_": {
        "sk": "encrypted-timestamp",
        "from": "203.0.113.9, 10.17.1.94",
        "user_id": "guests",
        "roles": [],
        "email": "guests@feg.cn",
        "now": "2026-11-02T08:00:00Z",
    }
}

ADMIN_INBOUND: Mapping[str, Any] = {
    "_token_": {
        "sk": "encrypted-timestamp",
        "from": "10.17.1.94",
        "user_id": "admin1",
        "roles": ["FDEP_ADMIN"],
        "email": "admin@feg.cn",
        "now": "2026-11-02T08:00:00Z",
    }
}


class StubClient:
    """A PDP that answers with whatever the test tells it to."""

    def __init__(self, decision: Decision | None = None, error: Exception | None = None):
        self.decision = decision
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def check(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.decision is not None
        return self.decision


def _decision(effect="EFFECT_ALLOW", **kwargs) -> Decision:
    return Decision(effect=effect, **kwargs)


def _call(client, *, api=API, do=True, inbound=None, kind=KIND, **kwargs):
    return authorize_call(
        api=api,
        do=do,
        inbound=ADMIN_INBOUND if inbound is None else inbound,
        kind=kind,
        registry=REGISTRY,
        client=client,
        **kwargs,
    )


# ── the app id ──────────────────────────────────────────────────────────────


def test_the_api_id_splits_into_path_and_operation():
    """The last segment is the operation; everything before it is the C4 path.

    The C4 path is a folder path, so it may have several segments —
    `systemone.LAYA` is the folder `systemone/LAYA`.
    """
    app = parse_api(API)
    assert app.path == "systemone.LAYA"
    assert app.operation == "Choice"
    assert app.action == "Choice"
    assert app.registry_key == "systemone.LAYA"


def test_a_path_with_one_segment_works_too():
    app = parse_api("twseMops.todayMaterial")
    assert app.path == "twseMops"
    assert app.operation == "todayMaterial"
    assert app.action == "todayMaterial"


def test_the_org_prefix_is_tolerated_and_kept():
    app = parse_api("@jev.systemone.LAYA.Choice")
    assert app.org == "jev"
    assert app.path == "systemone.LAYA"
    assert app.operation == "Choice"


@pytest.mark.parametrize(
    "api", ["", "   ", "systemone", "@jev", "@jev.systemone", ".Choice"]
)
def test_an_unusable_api_id_is_refused(api):
    with pytest.raises(InvalidApi):
        parse_api(api)


# ── the kind ────────────────────────────────────────────────────────────────


def test_the_kind_is_the_providers_path():
    """Built from the org's configuration, so the caller cannot choose it."""
    assert provider_kind(ORG) == KIND
    assert provider_kind(
        {"namespace": "pip", "task_queue": "FDEP", "workflow": "SOP"}
    ) == "pip.FDEP.SOP"


def test_the_resource_carries_the_kind_the_path_and_the_action():
    client = StubClient(_decision())
    _call(client)
    resource = client.calls[0]["resource"]
    assert resource["kind"] == KIND
    assert resource["id"] == "systemone.LAYA"
    assert "scope" not in resource, "there is no scope any more"
    assert client.calls[0]["action"] == "Choice"
    assert "scope" not in client.calls[0]["principal"]


# ── the `do` flag ───────────────────────────────────────────────────────────


def test_do_false_means_execute():
    """The flag is inverted once upstream, so `False` means "run the flow"."""
    from fdep_authz import access_mode

    assert access_mode(False) == "execute"
    assert access_mode(True) == "read"


def test_the_access_mode_follows_the_inverted_flag():
    """The flag still says what it means — but it is not sent.

    The attributes are switched off, so the resource carries none. The
    inversion is still worth pinning: it is the easiest thing in this
    flow to get wrong, and it comes back with the attributes.
    """
    from fdep_authz import access_mode

    assert access_mode(False) == "execute"
    assert access_mode(True) == "read"

    client = StubClient(_decision())
    _call(client, do=False)
    assert "attr" not in client.calls[0]["resource"], (
        "the attributes are switched off, so the resource carries none"
    )


# ── the attributes ──────────────────────────────────────────────────────────


def test_the_client_ip_is_the_last_hop_of_the_chain():
    """The chain is client-controllable at the front, so only the last hop counts."""
    client = StubClient(_decision())
    _call(client, inbound=GUEST_INBOUND)
    assert client.calls[0]["principal"]["attr"]["clientIp"] == "10.17.1.94"


def test_the_risk_level_is_not_sent_while_the_attributes_are_off():
    """The registry is still the list of apps — but its risk level is not
    read, so it is not sent."""
    client = StubClient(_decision())
    _call(client)
    assert "attr" not in client.calls[0]["resource"]


def test_an_app_that_is_not_registered_is_refused():
    """The registry is the list of apps FDEP serves."""
    registry = AppRegistry.from_mapping({})
    outcome = authorize_call(
        api=API,
        do=True,
        inbound=ADMIN_INBOUND,
        kind=KIND,
        registry=registry,
        client=StubClient(_decision()),
    )
    assert outcome.status_code == STATUS_DENIED
    assert "not registered" in outcome.reason


# ── the roles ───────────────────────────────────────────────────────────────


def test_a_call_with_no_roles_is_judged_as_a_guest():
    client = StubClient(_decision())
    _call(client, inbound=GUEST_INBOUND)
    assert client.calls[0]["principal"]["roles"] == ["FDEP_GUEST"]


def test_a_call_with_no_roles_is_refused_when_guest_defaulting_is_off():
    """An empty role list is not a decision the PDP can give."""
    client = StubClient(_decision())
    outcome = _call(client, inbound=GUEST_INBOUND, default_guest=False)
    assert outcome.allowed is False
    assert outcome.status_code == STATUS_DENIED
    assert client.calls == [], "the PDP must not be asked about a request with no roles"


# ── the two failures that look alike ────────────────────────────────────────


def test_denied_is_403_and_unreachable_is_503():
    """"No" and "could not tell" are different answers.

    A 503 lets the caller retry. A 403 does not — the caller will believe
    it lacks permission and give up.
    """
    denied = _call(
        StubClient(
            _decision("EFFECT_DENY", matched_policy="resource.pip.JEV.LAYA.vdefault")
        )
    )
    assert denied.allowed is False
    assert denied.status_code == STATUS_DENIED

    unreachable = _call(StubClient(error=PdpUnavailable("connection refused")))
    assert unreachable.allowed is False
    assert unreachable.status_code == STATUS_UNAVAILABLE


def test_an_unusable_risk_level_does_not_matter_while_the_attributes_are_off():
    """Nothing reads the risk level yet, so a broken one changes nothing.

    The registry is the list of apps, and the risk level belongs to it —
    but with the attributes switched off the risk level is not consulted,
    so it cannot make the call unjudgeable.
    """
    broken = AppRegistry.from_mapping({"systemone.LAYA": {"riskLevel": "spicy"}})
    outcome = authorize_call(
        api=API,
        do=True,
        inbound=ADMIN_INBOUND,
        kind=KIND,
        registry=broken,
        client=StubClient(_decision()),
    )
    assert outcome.status_code == STATUS_ALLOWED


def test_an_unregistered_app_is_403():
    """The app does not exist, so there is nothing to call."""
    outcome = _call(StubClient(_decision()), api="nosuchfamily.Choice")
    assert outcome.status_code == STATUS_DENIED


def test_a_provider_with_no_policy_says_so():
    """NO_MATCH is not "not permitted" — it is "nothing was judged"."""
    outcome = _call(
        StubClient(_decision("EFFECT_DENY", matched_policy="NO_MATCH")),
        kind="pip.nosuch.org",
    )
    assert outcome.status_code == STATUS_DENIED
    assert "no policy" in outcome.reason


def test_a_schema_rejection_says_so():
    outcome = _call(
        StubClient(
            _decision(
                "EFFECT_DENY",
                matched_policy="resource.pip.JEV.LAYA.vdefault",
                validation_errors=({"path": "/accessMode", "message": "bad"},),
            )
        )
    )
    assert outcome.status_code == STATUS_DENIED
    assert "schema" in outcome.reason


# ── shadow mode ─────────────────────────────────────────────────────────────


def test_shadow_mode_lets_a_denied_call_through():
    """A wrong decision costs nothing, and real traffic is the only way to
    find out whether the policy says the right thing."""
    client = StubClient(_decision("EFFECT_DENY", matched_policy="NO_MATCH"))
    outcome = _call(client, shadow=True)
    assert outcome.allowed is True
    assert outcome.status_code == STATUS_ALLOWED
    assert outcome.shadow is True
    assert outcome.denied_by_policy is True, "the shadow report must keep the verdict"


def test_shadow_mode_lets_a_call_through_when_the_pdp_is_down():
    outcome = _call(StubClient(error=PdpUnavailable("connection refused")), shadow=True)
    assert outcome.allowed is True
    assert outcome.status_code == STATUS_ALLOWED


# ── the drop-in for the reference implementation ────────────────────────────


def test_cerbos_valid_returns_the_result_entry_the_reference_reads():
    """`cerbos_valid` is the reference implementation's `cerbosValid`.

    The reference reads `(result.get("actions") or {}).get(action, "EFFECT_DENY")`,
    so the returned dict has to carry `actions` — and it has to carry the
    call id as well, which is what ties the decision to FDEP's own log line.
    """
    captured = {}

    class Recorder:
        def check(self, **kwargs):
            captured.update(kwargs)
            return _decision(
                "EFFECT_ALLOW",
                call_id="call-123",
                matched_policy="resource.pip.JEV.LAYA.vdefault",
                result={"actions": {"Choice": "EFFECT_ALLOW"}},
            )

    result = cerbos_valid(
        "run-1", True, GUEST_INBOUND, API, KIND, client=Recorder()
    )

    assert result["actions"]["Choice"] == "EFFECT_ALLOW"
    assert result["cerbosCallId"] == "call-123"
    assert captured["action"] == "Choice"
    assert captured["request_id"] == "run-1"
    assert captured["resource"]["kind"] == KIND
    assert "scope" not in captured["resource"]


# ── the PocketFlow node ─────────────────────────────────────────────────────


def _node(client, **kwargs):
    calls = []

    def dispatch(request_data, workflow_id, namespace, task_queue, workflow):
        calls.append((request_data, workflow_id, namespace, task_queue, workflow))
        return {"workflow": "started"}

    node = AuthzDispatchNode(dispatch, registry=REGISTRY, client=client, **kwargs)
    shared = {
        "api": API,
        "do": True,
        "inbound": GUEST_INBOUND,
        "workflowId": "workflow-1",
        "org": ORG,
        "token": {"run_id": "run-1"},
    }
    return node, shared, calls


def test_the_node_starts_the_work_when_the_pdp_allows():
    node, shared, calls = _node(StubClient(_decision()))
    node.run(shared)
    assert len(calls) == 1
    assert calls[0][1] == "workflow-1"
    assert calls[0][2] == "pip"
    assert shared["output"]["data"] == {"workflow": "started"}


def test_the_node_raises_when_the_pdp_denies():
    """The gate runs before the work does — that is the whole point.

    And a denial is raised, not returned: a caller that only checks "did
    it error?" must not read a denied call as a successful one.
    """
    node, shared, calls = _node(StubClient(_decision("EFFECT_DENY")))
    with pytest.raises(FdepDenied) as excinfo:
        node.run(shared)
    assert calls == [], "the workflow must not start on a denied call"
    assert excinfo.value.status_code == STATUS_DENIED


def test_the_node_raises_when_the_pdp_cannot_be_reached():
    node, shared, calls = _node(StubClient(error=PdpUnavailable("refused")))
    with pytest.raises(FdepDenied) as excinfo:
        node.run(shared)
    assert calls == []
    assert excinfo.value.status_code == STATUS_UNAVAILABLE


def test_the_refusal_carries_the_pdp_result_and_the_call_id():
    """Nothing is lost on the way out."""
    node, shared, _ = _node(
        StubClient(
            _decision(
                "EFFECT_DENY",
                call_id="call-42",
                matched_policy="NO_MATCH",
                result={"actions": {"Choice": "EFFECT_DENY"}},
            )
        )
    )
    with pytest.raises(FdepDenied) as excinfo:
        node.run(shared)

    payload = excinfo.value.to_payload()
    # the reference's caller reads `data["actions"]` — it has to still work
    assert payload["actions"]["Choice"] == "EFFECT_DENY"
    assert payload["status"] == STATUS_DENIED
    assert payload["cerbosCallId"] == "call-42"
    assert "no policy" in payload["reason"]


def test_a_refusal_does_not_publish_an_output():
    """The flow has no result to publish — the refusal is the error."""
    node, shared, calls = _node(StubClient(_decision("EFFECT_DENY")))
    with pytest.raises(FdepDenied):
        node.run(shared)
    assert "output" not in shared
    assert calls == []


def test_the_node_adds_the_c4_prefix_only_to_the_workflow_request():
    """`C4.` is FDEP's routing requirement, not part of what was authorized."""
    node, shared, calls = _node(StubClient(_decision()))
    node.run(shared)
    assert calls[0][0]["api"] == "C4." + API


def test_the_node_refuses_a_request_with_no_inbound():
    node, shared, calls = _node(StubClient(_decision()))
    shared["inbound"] = None
    with pytest.raises(ValueError):
        node.run(shared)
    assert calls == []


def test_the_node_refuses_a_request_with_no_org():
    """The reference reads `org["namespace"]` before it checks that `org`
    is there, so a missing org is a TypeError instead of the message that
    says what is wrong."""
    node, shared, calls = _node(StubClient(_decision()))
    shared["org"] = None
    with pytest.raises(ValueError):
        node.run(shared)
    assert calls == []


# ── the whole chain, against the live PDP ───────────────────────────────────


@pytest.fixture(scope="module")
def live_client():
    with CerbosClient(pdp_url()) as client:
        yield client


def test_the_gate_lets_the_administrator_through(live_client):
    """The app id, the kind and the action all have to line up.

    The kind is the jev provider, the id is the systemone.LAYA family and
    the action is `Choice.py` — so the provider's own policy decides, and
    the administrator's rule grants it.
    """
    outcome = _call(live_client, inbound=ADMIN_INBOUND)
    assert outcome.allowed is True, outcome.reason
    assert outcome.status_code == STATUS_ALLOWED
    assert outcome.decision is not None
    assert outcome.decision.matched_policy == "resource.pip.JEV.LAYA.vdefault"


def test_the_gate_lets_the_guest_through(live_client):
    """The guest's grant names three things, and the request has all three.

    The principal's id is `guests` — the platform's own — the resource's id
    is `systemone.LAYA`, and the action is `Choice.py`. The roles are
    ignored, so the platform's `roles: ["guests"]` cannot stop it.
    """
    outcome = _call(live_client, inbound=GUEST_INBOUND)
    assert outcome.allowed is True, outcome.reason
    assert outcome.status_code == STATUS_ALLOWED
    assert outcome.decision is not None
    assert outcome.decision.matched_policy == "resource.pip.JEV.LAYA.vdefault"


def test_the_gate_refuses_somebody_else(live_client):
    """A principal no grant names gets nothing.

    The default denial, and the policy says so: it was consulted and it
    declined.
    """
    outcome = _call(
        live_client,
        inbound={"_token_": {"user_id": "someone-else", "roles": []}},
        kind="pip.FDEP.SOP",
    )
    assert outcome.allowed is False
    assert outcome.status_code == STATUS_DENIED
    assert outcome.denied_by_policy is True
    assert outcome.decision is not None
    assert outcome.decision.matched_policy == "resource.pip.FDEP.SOP.vdefault"


def test_the_gate_reports_a_provider_with_no_policy(live_client):
    """The store holds no policy for this kind, so nothing was judged."""
    outcome = _call(live_client, kind="pip.nosuch.org")
    assert outcome.allowed is False
    assert outcome.status_code == STATUS_DENIED
    assert outcome.decision is not None
    assert outcome.decision.no_match is True
    assert "no policy" in outcome.reason


def test_the_gate_lets_the_administrator_through_any_operation(live_client):
    """The general rules live in the provider's own policy."""
    outcome = _call(live_client, api="systemone.LAYA.Score", do=False)
    assert outcome.allowed is True, outcome.reason
    assert outcome.decision is not None
    assert outcome.decision.matched_policy == "resource.pip.JEV.LAYA.vdefault"


def test_the_gate_answers_503_when_the_pdp_is_unreachable():
    """An outage must not read as a permit, and must not read as a denial."""
    with CerbosClient("http://127.0.0.1:1", timeout_secs=1.0, retries=0) as dead:
        outcome = authorize_call(
            api=API,
            do=True,
            inbound=ADMIN_INBOUND,
            kind=KIND,
            registry=REGISTRY,
            client=dead,
        )
    assert outcome.allowed is False
    assert outcome.status_code == STATUS_UNAVAILABLE


def test_the_decision_carries_the_call_id_that_links_the_two_audit_trails(live_client):
    """The PDP's call id is what ties the decision to FDEP's own log line."""
    outcome = authorize_call(
        api=API,
        do=True,
        inbound=GUEST_INBOUND,
        kind=KIND,
        registry=REGISTRY,
        client=live_client,
        run_id="fdep-gate-probe",
        annotations={"trace_id": "trace-fdep-gate-probe", "app_id": API},
    )
    assert outcome.decision is not None
    call_id = outcome.call_id
    assert call_id, "the PDP answered without a call id"

    entry = _lookup_decision(call_id)
    assert entry is not None, f"the audit trail has no entry for {call_id}"
    assert entry["callId"] == call_id

    # the annotations travelled with the request and did not change the verdict
    context = entry.get("requestContext") or {}
    annotations = context.get("annotations") or {}
    assert annotations.get("app_id") == API


def _lookup_decision(call_id: str, timeout: float = 45.0) -> dict | None:
    """Fetch one decision entry, polling.

    The `local` audit backend buffers before it commits, so a decision is
    not readable the instant it is made — measured on this PDP, 13 seconds.
    Reading once and concluding "not there" gives the wrong answer.
    """
    deadline = time.monotonic() + timeout
    while True:
        response = httpx.get(
            f"{pdp_url()}/admin/auditlog/list/KIND_DECISION?lookup={call_id}",
            headers=admin_headers(),
            timeout=10.0,
        )
        if response.status_code == 200:
            for line in response.text.splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                entry = payload.get("result", payload).get("decisionLogEntry")
                if entry is not None:
                    return entry
        if time.monotonic() >= deadline:
            return None
        time.sleep(1.0)
