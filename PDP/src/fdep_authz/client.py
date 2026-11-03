"""The PDP client of the FDEP authorization gate.

**Standard library only.** The gate runs inside FDEP, and FDEP should not
have to grow a dependency to ask a policy engine a question. `urllib` is
enough for one POST.

Why it does not use `cerbos-sdk`: the gate has to tell three things apart,
and the SDK's response model carries only one of them.

* **denied** vs **not found.** `matchedPolicy` is `NO_MATCH` when the store
  holds no policy for the scope the request carries. That is a different
  failure from "the policy says no" — it means the scope chain has a gap —
  and the design requires the two to be distinguishable. `matchedPolicy`
  arrives only when the request sets `includeMeta`.
* **the call id.** `cerbosCallId` is what ties a decision to the PDP's
  audit trail and to FDEP's own log line. It is at the top level of the
  response and the SDK does not expose it.

**Do not cache the answer.** An authorization decision reflects the roles
the caller holds right now; a stale answer is a way around the gate.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

DEFAULT_PDP_URL = "http://10.17.1.201:3592"

EFFECT_ALLOW = "EFFECT_ALLOW"
EFFECT_DENY = "EFFECT_DENY"

#: What the PDP reports when it holds no policy for the scope of the
#: request. The base policy is not a fallback for a missing scope.
NO_MATCH = "NO_MATCH"

DEFAULT_TIMEOUT_SECS = 10.0
DEFAULT_RETRIES = 1
DEFAULT_BACKOFF_SECS = 0.1


class PdpError(RuntimeError):
    """The PDP could not give an answer.

    A `RuntimeError`, so a caller that only knows the reference
    implementation's `except RuntimeError` still catches it.
    """


class PdpUnavailable(PdpError):
    """The PDP could not be reached at all: refused, timed out, cut off.

    Not a decision. The caller must answer 503, not 403 — "could not tell"
    and "not allowed" are different, and only one of them is worth
    retrying.
    """


class PdpRejected(PdpError):
    """The PDP answered, but not with a decision.

    A 400 (a malformed request), an unexpected status, or a body that does
    not carry the answer. Also not a decision: answer 503.
    """


@dataclass(frozen=True)
class Decision:
    """What the PDP said about one call."""

    effect: str
    call_id: str = ""
    matched_policy: str = ""
    matched_scope: str = ""
    validation_errors: tuple[Mapping[str, Any], ...] = field(default=())
    result: Mapping[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.effect == EFFECT_ALLOW

    @property
    def no_match(self) -> bool:
        """True when the store holds no policy for this scope.

        A different failure from a denial: the policy for this provider was
        never deployed, so nothing was actually judged.
        """
        return self.matched_policy == NO_MATCH

    @property
    def rejected_by_schema(self) -> bool:
        """True when the request did not pass schema validation."""
        return bool(self.validation_errors)


class CerbosClient:
    """A small HTTP client for the PDP's check/resources API."""

    def __init__(
        self,
        base_url: str = DEFAULT_PDP_URL,
        *,
        timeout_secs: float = DEFAULT_TIMEOUT_SECS,
        retries: int = DEFAULT_RETRIES,
        backoff_secs: float = DEFAULT_BACKOFF_SECS,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_secs = timeout_secs
        self.retries = max(0, retries)
        self.backoff_secs = backoff_secs
        self._opener = opener

    @property
    def opener(self) -> urllib.request.OpenerDirector:
        if self._opener is None:
            # An empty ProxyHandler: no proxy at all.
            #
            # `urllib` reads the proxy from the Windows registry
            # (`HKCU\...\Internet Settings\ProxyServer`) whether or not the
            # environment says anything, and an internal host cannot be
            # reached through it — the request stalls until it times out.
            # An explicit empty handler disables the proxy for this client
            # only.
            self._opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({})
            )
        return self._opener

    # ── lifecycle ───────────────────────────────────────────────────────────
    def __enter__(self) -> "CerbosClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        if self._opener is not None:
            self._opener.close()
            self._opener = None

    # ── the decision ────────────────────────────────────────────────────────
    def check(
        self,
        *,
        principal: Mapping[str, Any],
        resource: Mapping[str, Any],
        action: str,
        request_id: str | None = None,
        annotations: Mapping[str, str] | None = None,
    ) -> Decision:
        """Ask the PDP whether the call is allowed.

        Raises PdpUnavailable when the PDP could not be reached and
        PdpRejected when it answered with anything other than a decision.
        Neither is a denial.
        """
        body: dict[str, Any] = {
            "requestId": request_id or "",
            # The match metadata is what tells "the policy says no" from
            # "there is no policy for this scope".
            "includeMeta": True,
            "principal": dict(principal),
            "resources": [{"resource": dict(resource), "actions": [action]}],
        }
        if annotations:
            # Annotations correlate a decision with the call that caused it.
            # They do not participate in the evaluation, so a caller cannot
            # influence the outcome through them.
            body["requestContext"] = {"annotations": dict(annotations)}

        payload = self._post(body)

        call_id = str(payload.get("cerbosCallId") or "")
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            raise PdpRejected("the PDP returned no result for the request")

        entry = results[0]
        if not isinstance(entry, dict):
            raise PdpRejected("the PDP returned a result that is not an object")

        actions = entry.get("actions")
        if not isinstance(actions, dict) or action not in actions:
            raise PdpRejected(f"the PDP returned no effect for action {action!r}")

        effect = str(actions[action])
        if effect not in (EFFECT_ALLOW, EFFECT_DENY):
            raise PdpRejected(f"the PDP returned an unknown effect: {effect!r}")

        meta = (entry.get("meta") or {}).get("actions") or {}
        matched = meta.get(action) or {}

        errors = entry.get("validationErrors") or []
        return Decision(
            effect=effect,
            call_id=call_id,
            matched_policy=str(matched.get("matchedPolicy") or ""),
            matched_scope=str(matched.get("matchedScope") or ""),
            validation_errors=tuple(errors),
            result=entry,
        )

    # ── transport ───────────────────────────────────────────────────────────
    def _post(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        url = f"{self.base_url}/api/check/resources"
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        attempts = self.retries + 1
        last: PdpUnavailable | None = None

        for attempt in range(attempts):
            try:
                with self.opener.open(request, timeout=self.timeout_secs) as response:
                    raw = response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")
                raise PdpRejected(
                    f"the PDP returned HTTP {exc.code}: {detail[:300]}"
                ) from exc
            except (urllib.error.URLError, socket.timeout, OSError) as exc:
                reason = getattr(exc, "reason", exc)
                last = PdpUnavailable(f"could not reach the PDP: {reason}")
            else:
                try:
                    payload = json.loads(raw)
                except ValueError as exc:
                    raise PdpRejected(
                        f"the PDP returned a body that is not JSON: {exc}"
                    ) from exc
                if not isinstance(payload, dict):
                    raise PdpRejected("the PDP returned a body that is not an object")
                return payload

            if attempt < attempts - 1 and self.backoff_secs > 0:
                time.sleep(self.backoff_secs * (attempt + 1))

        assert last is not None
        raise last


__all__ = [
    "CerbosClient",
    "Decision",
    "DEFAULT_BACKOFF_SECS",
    "DEFAULT_PDP_URL",
    "DEFAULT_RETRIES",
    "DEFAULT_TIMEOUT_SECS",
    "EFFECT_ALLOW",
    "EFFECT_DENY",
    "NO_MATCH",
    "PdpError",
    "PdpRejected",
    "PdpUnavailable",
]
