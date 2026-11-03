"""The FDEP authorization gate.

FDEP is a single entry point that dispatches to each app's business flow by
app id. Without a gate, holding any app id is holding every app id. This
package is the gate: it turns a call into a Cerbos decision, and a Cerbos
decision into an HTTP status.

    from fdep_authz import AppRegistry, CerbosClient, authorize_call

    registry = AppRegistry.from_mapping({"systemone.LAYA": {"riskLevel": "low"}})
    with CerbosClient("http://10.17.1.201:3592") as client:
        outcome = authorize_call(
            api="systemone.LAYA.Choice",
            do=True,
            inbound=inbound,
            kind="pip.JEV.LAYA",
            registry=registry,
            client=client,
        )
    if not outcome.allowed:
        raise FdepDenied(outcome.status_code, outcome.reason)

The three rules that are easiest to get wrong, and where they are pinned
down:

* the `do` flag is inverted once upstream — `do == False` means "execute"
  (`token.access_mode`);
* the kind is the provider's identity and it is built on the server side —
  the caller cannot choose which provider they are judged under
  (`node.provider_kind`);
* "no" and "cannot tell" are different answers — 403 and 503
  (`gate.GateOutcome`).

A refusal is **raised**, not returned (`errors.FdepDenied`): it is an error
condition, not a result, and a caller that only checks "did it error?" must
not read a denied call as a successful one.

**Where the identity comes from** is not this package's business. The
identity layer fills `_token_.user_id` / `.roles` / `.email`; the gate only
reads them. What the gate does insist on is that the role names the
identity layer emits are the same names the policies use — the PDP judges
by role and nothing else, so a mismatch denies everything.
"""

from __future__ import annotations

from fdep_authz.appid import AppId, InvalidApi, parse_api
from fdep_authz.cerbos import cerbos_valid, default_registry
from fdep_authz.client import (
    DEFAULT_PDP_URL,
    EFFECT_ALLOW,
    EFFECT_DENY,
    NO_MATCH,
    CerbosClient,
    Decision,
    PdpError,
    PdpRejected,
    PdpUnavailable,
)
from fdep_authz.errors import FdepDenied
from fdep_authz.gate import (
    STATUS_ALLOWED,
    STATUS_DENIED,
    STATUS_UNAVAILABLE,
    GateOutcome,
    authorize_call,
)
from fdep_authz.node import AuthzDispatchNode, provider_kind
from fdep_authz.registry import (
    AppRegistry,
    InvalidRegistryEntry,
    UnknownApp,
)
from fdep_authz.token import (
    GUEST_ROLE,
    Principal,
    Resource,
    access_mode,
    build_principal,
    build_resource,
    client_ip,
    effective_roles,
)

__all__ = [
    "AppId",
    "AppRegistry",
    "AuthzDispatchNode",
    "CerbosClient",
    "Decision",
    "DEFAULT_PDP_URL",
    "EFFECT_ALLOW",
    "EFFECT_DENY",
    "FdepDenied",
    "GUEST_ROLE",
    "GateOutcome",
    "InvalidApi",
    "InvalidRegistryEntry",
    "NO_MATCH",
    "PdpError",
    "PdpRejected",
    "PdpUnavailable",
    "Principal",
    "Resource",
    "STATUS_ALLOWED",
    "STATUS_DENIED",
    "STATUS_UNAVAILABLE",
    "UnknownApp",
    "access_mode",
    "authorize_call",
    "build_principal",
    "build_resource",
    "cerbos_valid",
    "client_ip",
    "default_registry",
    "effective_roles",
    "parse_api",
    "provider_kind",
]
