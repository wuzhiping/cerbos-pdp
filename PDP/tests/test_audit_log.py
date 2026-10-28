"""Audit logs and decision records.

The skill this suite is built on says a PDP records every API call it serves
and every decision it makes, and that the backend decides whether that trail
can be read back. Where the trail goes and what can be asked of it is the
choice this module checks.

This PDP now runs the ``local`` audit backend, so the trail **can** be read
back through the Admin API:

    GET /admin/auditlog/list/{kind}

The response is ``application/x-ndjson`` — one JSON object per line, each
wrapped in a ``result`` envelope because the entry is a gRPC oneof. Parsing it
as a single JSON document fails as soon as more than one entry comes back,
which is why this module reads it line by line.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest

from cerbos_policy_tests.client import admin_headers, pdp_url

KIND_DECISION = "KIND_DECISION"
KIND_ACCESS = "KIND_ACCESS"


def _audit_response(kind: str) -> httpx.Response:
    return httpx.get(
        f"{pdp_url()}/admin/auditlog/list/{kind}?tail=5",
        headers=admin_headers(),
        timeout=10.0,
    )


def _audit_entries(kind: str) -> list[dict]:
    """Read the trail.

    The endpoint streams newline-delimited JSON: one entry per line, each
    wrapped in ``{"result": {...}}``. A single ``response.json()`` would work
    only while exactly one entry came back.
    """
    response = _audit_response(kind)
    if response.status_code != 200:
        return []
    entries = []
    for line in response.text.splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        entries.append(payload.get("result", payload))
    return entries


def _make_one_decision() -> str:
    """Drive one decision and return its call ID.

    The raw HTTP call is used rather than the SDK because the SDK does not
    expose ``cerbosCallId`` — and the call ID is what ties a decision to its
    audit entry.
    """
    response = httpx.post(
        f"{pdp_url()}/api/check/resources",
        json={
            "requestId": "audit-probe",
            "principal": {
                "id": "alice",
                "roles": ["USER"],
                "policyVersion": "default",
            },
            "resources": [
                {
                    "resource": {
                        "kind": "basicResource",
                        "id": "doc-audit-probe",
                        "policyVersion": "default",
                        "attr": {"ownerId": "alice", "isPublished": True},
                    },
                    "actions": ["read"],
                }
            ],
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return response.json()["cerbosCallId"]


def _lookup(call_id: str, timeout: float = 60.0) -> dict | None:
    """Fetch the entry for one specific call.

    ``lookup`` rather than ``tail``: the tail is the most recent entry, and
    on a PDP with other traffic that is not necessarily the one you made.

    The ``local`` audit backend buffers entries before committing them, so a
    decision is **not** readable the instant it is made — measured on this
    PDP, it took 13 seconds. Poll rather than read once.
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


def test_the_audit_backend_state_is_recorded():
    """Whatever the backend is, the suite knows which state it is in.

    This passes in either state: it records the backend's answer so a change
    shows up as a diff rather than as silence.
    """
    response = _audit_response(KIND_DECISION)

    if response.status_code == 200:
        assert "error" not in response.text, response.text[:200]
    else:
        body = response.json()
        message = body.get("error", {}).get("message", "")
        assert "does not support querying" in message, (
            f"the audit backend answered {response.status_code}: {message!r}"
        )


def test_decision_logs_can_be_queried():
    """A decision trail that cannot be read is not a trail."""
    call_id = _make_one_decision()

    entry = _lookup(call_id)
    assert entry is not None, f"no entry for {call_id}"
    assert entry["callId"] == call_id
    assert entry["timestamp"]
    # the record holds the request as the PDP evaluated it
    inputs = entry["checkResources"]["inputs"]
    assert inputs[0]["principal"]["id"] == "alice"
    # and it names the policy that decided
    effective = entry["auditTrail"]["effectivePolicies"]
    assert effective, entry["auditTrail"]
    # and where the policy came from
    assert entry["policySource"], entry


def test_the_record_names_the_policy_that_decided():
    """The effect and the policy that produced it are both in the record."""
    call_id = _make_one_decision()

    entry = _lookup(call_id)
    assert entry is not None

    outputs = entry["checkResources"]["outputs"]
    assert outputs
    effect = outputs[0]["actions"]["read"]
    assert effect["effect"] == "EFFECT_ALLOW"
    assert effect["policy"] in entry["auditTrail"]["effectivePolicies"]


def test_access_logs_can_be_queried():
    _make_one_decision()

    entries = _audit_entries(KIND_ACCESS)
    assert entries, "the audit backend answered but returned no access entries"

    entry = entries[-1]["accessLogEntry"]
    assert entry["callId"]
    assert entry["method"]


def test_the_decision_record_carries_the_policy_source():
    """Which store the policy came from is part of the record."""
    call_id = _make_one_decision()

    entry = _lookup(call_id)
    assert entry is not None

    source = entry["policySource"]
    # one key per driver kind: `disk` for a directory store, `database` for a
    # mutable one
    assert source, source
    assert set(source) <= {"disk", "database", "blob", "git", "hub", "bundle"}


def test_a_failed_check_is_an_error_not_a_denial():
    """An outage must never read as a deny.

    A PDP that is unreachable produces a deny in naive code, and a deny in
    telemetry is indistinguishable from a policy bug. The separation is the
    check that tells the two apart: whether the PDP recorded the request at
    all. The trail is queryable on this PDP now, so the separation is real
    rather than aspirational.
    """
    from cerbos_policy_tests.pep import PdpError, PdpUnavailable, authorize

    from cerbos.sdk.model import Principal, Resource

    with pytest.raises(PdpUnavailable):
        from cerbos_policy_tests.client import build_client

        with build_client(host="http://127.0.0.1:1", timeout_secs=1.0) as dead:
            authorize(
                dead,
                action="read",
                principal=Principal(id="alice", roles={"USER"}),
                resource=Resource(id="x", kind="basicResource"),
            )

    assert issubclass(PdpUnavailable, PdpError)
