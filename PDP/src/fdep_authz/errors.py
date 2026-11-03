"""The exception the gate raises when a call must not proceed.

A refusal is an **error condition**, not a result. Returning the PDP's
answer as if it were a workflow's output would make the two
indistinguishable: a caller that only checks "did it error?" would treat a
denied call as a successful one that happened to produce nothing.

So the gate raises. The exception carries everything the layer above needs
to answer the caller properly:

* `status_code` — 403 when the PDP said no, 503 when it could not answer.
  The two must not look the same: a 403 tells the caller "retrying won't
  help", a 503 tells it "retrying might".
* `cerbos_call_id` — the key that ties this refusal to the PDP's audit
  trail.
* `result` — the PDP's own answer, so nothing is lost.
"""

from __future__ import annotations

from typing import Any, Mapping

STATUS_DENIED = 403
STATUS_UNAVAILABLE = 503


class FdepDenied(Exception):
    """The call must not proceed.

    `status_code` is 403 when the PDP said no, and 503 when it could not
    answer. Both refuse the call; only one of them tells the caller that
    retrying might work.
    """

    def __init__(
        self,
        status_code: int,
        reason: str,
        *,
        cerbos_call_id: str = "",
        result: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{status_code}: {reason}")
        self.status_code = status_code
        self.reason = reason
        self.cerbos_call_id = cerbos_call_id
        self.result: dict[str, Any] = dict(result or {})

    def to_payload(self) -> dict[str, Any]:
        """What the layer above needs, in one dict.

        The PDP's own result is kept, so a caller that already knows how to
        read it keeps working. `status` and `reason` are added: 403 means
        "not permitted", 503 means "could not tell", and the two must not
        look the same.
        """
        payload = dict(self.result)
        payload["status"] = self.status_code
        payload["reason"] = self.reason
        if self.cerbos_call_id:
            payload["cerbosCallId"] = self.cerbos_call_id
        return payload


__all__ = ["FdepDenied", "STATUS_DENIED", "STATUS_UNAVAILABLE"]
