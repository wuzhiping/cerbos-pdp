"""Turning FDEP's `_token_` and the call payload into a Cerbos request.

The `_token_` is filled in by the server; whatever the client sends is
discarded. That is what makes the principal trustworthy — and it is why the
identity layer has to put the real user id and roles in it.

    _token_ = {
      sk:      "<encrypted timestamp>",   pipe.py checks: valid for 5 minutes
      from:    "<source IP>",             an XFF chain, client-controllable
      user_id: "guests",                  <- to be filled with the real value
      roles:   [],                        <- to be filled with the real value
      email:   "guests@feg.cn",           <- to be filled with the real value
      now:     "<server time>",
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from fdep_authz.appid import AppId
from fdep_authz.registry import AppRegistry

#: The role an unauthenticated caller is judged under.
GUEST_ROLE = "FDEP_GUEST"


@dataclass(frozen=True)
class Principal:
    """The Cerbos principal of one call."""

    id: str
    roles: tuple[str, ...]
    attr: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Resource:
    """The Cerbos resource of one call.

    There is no scope: the provider is the kind, the app family inside it
    is the id, and the operation is the action.

    **There are no attributes** — the attributes are switched off, so
    nothing reads them.
    """

    kind: str
    id: str


def access_mode(do: bool) -> str:
    """What the call does with the app, from the `do` flag.

    **The flag is inverted once upstream.** The BPM layer sends
    `"do": !i.payload.do`, so what pipe.py sees is the opposite of what the
    caller asked for:

        the caller sent   the flag pipe.py sees   meaning
        do: false         true                    look at a file
        do: true          false                   run the business flow

    So `do == False` means "execute". Writing this the other way round
    inverts the whole authorization — a read grant becomes an execute grant
    and back.
    """
    return "read" if do else "execute"


def client_ip(from_header: str) -> str:
    """The last hop of the XFF chain.

    The chain is client-controllable at the front — a client can prepend
    anything it likes — so only the last entry is worth recording.

    This is for the record. It does not gate anything: deciding which
    addresses are trusted is a network-layer question, and a policy that
    gated on a client-supplied header would be gating on nothing.
    """
    parts = [part.strip() for part in (from_header or "").split(",") if part.strip()]
    return parts[-1] if parts else ""


def effective_roles(
    token: Mapping[str, Any], *, default_guest: bool = True
) -> tuple[str, ...]:
    """The roles the request is judged under.

    An empty role list is not a valid Cerbos principal: the PDP answers HTTP
    400, which is a malformed request rather than a decision. So the roles
    never go out empty — an unverified caller becomes a guest, and the guest
    rule decides what a guest may do.

    With `default_guest=False` the empty list is kept, and the caller is
    expected to refuse the call instead of guessing a role for it.
    """
    roles = tuple(str(role) for role in (token.get("roles") or ()))
    if roles:
        return roles
    return (GUEST_ROLE,) if default_guest else ()


def build_principal(
    token: Mapping[str, Any],
    *,
    default_guest: bool = True,
) -> Principal:
    """Build the principal of one call.

    The attributes are the caller's — IP, email and request time. They are
    for the record and for the audit trail; no condition reads them, and
    the policy declares no principal schema. Keeping them off the resource
    matters: a resource's attributes are facts about the resource, and
    putting the caller's IP there would make "the same app, called from a
    different address" a different resource.
    """
    return Principal(
        id=str(token.get("user_id") or GUEST_ROLE),
        roles=effective_roles(token, default_guest=default_guest),
        attr={
            "clientIp": client_ip(str(token.get("from") or "")),
            "email": str(token.get("email") or ""),
            "requestTime": str(token.get("now") or ""),
        },
    )


def build_resource(app: AppId, kind: str) -> Resource:
    """Build the resource of one call.

    The `id` is the C4 path — the app family — and the `kind` is the
    provider. The policy is filed under the kind, and the families inside it
    are told apart by the id.

    **There are no attributes.** `accessMode` and `riskLevel` are switched
    off for now: nothing reads `R.attr`, so carrying the attributes would
    be carrying facts nobody looks at. `access_mode` still says what the
    `do` flag means — the inversion upstream is the easiest thing in this
    whole flow to get wrong — and it comes back with the attributes.
    """
    return Resource(kind=kind, id=app.path)


def build_resource(app: AppId, kind: str) -> Resource:
    """Build the resource of one call.

    The `id` is the C4 path — the app family — and the `kind` is the
    provider. The policy is filed under the kind, and the families inside it
    are told apart by the id.

    **There are no attributes.** `accessMode` and `riskLevel` are switched
    off for now: nothing reads `R.attr`, so carrying the attributes would
    be carrying facts nobody looks at. `access_mode` still says what the
    `do` flag means — the inversion upstream is the easiest thing in this
    whole flow to get wrong — and it comes back with the attributes.
    """
    return Resource(kind=kind, id=app.path)


__all__ = [
    "GUEST_ROLE",
    "Principal",
    "Resource",
    "access_mode",
    "build_principal",
    "build_resource",
    "client_ip",
    "effective_roles",
]
