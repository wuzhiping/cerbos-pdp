"""The enforcement point helper.

This is the code an application would call at the boundary of an operation.
It turns a PDP answer into a decision, and it keeps two things apart that are
easy to conflate:

* a **deny** — the policy says no;
* an **error** — the PDP was unreachable, timed out, or rejected the request.

Collapsing an outage into a deny is what turns a PDP outage into an
authorization bypass, so transport failures raise instead of returning False.
"""

from __future__ import annotations

import httpx

from cerbos.sdk.model import Effect, Principal, Resource, ResourceList

from cerbos_policy_tests.client import build_client


class PdpError(Exception):
    """The PDP could not give an answer: unreachable, timed out, or rejected."""


class PdpUnavailable(PdpError):
    """The PDP could not be reached at all."""


def authorize(client, action: str, principal: Principal, resource: Resource) -> bool:
    """Ask the PDP whether `principal` may perform `action` on `resource`.

    Returns True for EFFECT_ALLOW and False for EFFECT_DENY. Raises PdpError
    for anything that is not a decision.
    """
    resource_list = ResourceList().add(resource, {action})

    try:
        response = client.check_resources(
            principal=principal, resources=resource_list
        )
    except httpx.HTTPError as exc:
        raise PdpUnavailable(
            f"could not reach the PDP: {exc.__class__.__name__}: {exc}"
        ) from exc
    except OSError as exc:
        raise PdpUnavailable(f"could not reach the PDP: {exc}") from exc

    if response.status_msg is not None:
        raise PdpError(
            f"the PDP rejected the request: "
            f"{response.status_msg.message} "
            f"(code {response.status_msg.code})"
        )

    if response.status_code != 200:
        raise PdpError(
            f"the PDP returned status {response.status_code}: {response.status_msg}"
        )

    result = response.get_resource(resource.id)
    if result is None:
        raise PdpError(
            f"the PDP returned no result for resource {resource.id!r}"
        )

    effect = result.actions.get(action)
    if effect is None:
        raise PdpError(
            f"the PDP returned no effect for action {action!r} "
            f"on resource {resource.id!r}"
        )

    return effect == Effect.ALLOW


def authorize_all(
    client, actions, principal: Principal, resource: Resource
) -> dict[str, bool]:
    """Ask about several actions on one resource in a single round trip."""
    resource_list = ResourceList().add(resource, set(actions))

    try:
        response = client.check_resources(
            principal=principal, resources=resource_list
        )
    except httpx.HTTPError as exc:
        raise PdpUnavailable(
            f"could not reach the PDP: {exc.__class__.__name__}: {exc}"
        ) from exc
    except OSError as exc:
        raise PdpUnavailable(f"could not reach the PDP: {exc}") from exc

    if response.status_msg is not None:
        raise PdpError(
            f"the PDP rejected the request: "
            f"{response.status_msg.message} "
            f"(code {response.status_msg.code})"
        )

    result = response.get_resource(resource.id)
    if result is None:
        raise PdpError(
            f"the PDP returned no result for resource {resource.id!r}"
        )

    decisions: dict[str, bool] = {}
    for action in actions:
        effect = result.actions.get(action)
        if effect is None:
            raise PdpError(
                f"the PDP returned no effect for action {action!r} "
                f"on resource {resource.id!r}"
            )
        decisions[action] = effect == Effect.ALLOW
    return decisions


__all__ = [
    "PdpError",
    "PdpUnavailable",
    "authorize",
    "authorize_all",
    "build_client",
]
