"""Filter a list by permission, the way a list endpoint should.

The skill is explicit that filtering a list item by item is the common wrong
turn: pagination breaks, counts and aggregates stop working, the 50-resource
batch ceiling is hit, and the cost grows with the length of the list.
`planResources` inverts the order — the PDP returns the condition a resource
must satisfy, and the database filters.

This module turns that condition into SQL through the `cerbos-sqlalchemy`
adapter, so the whole chain is exercised: PDP plan -> condition tree -> WHERE
clause -> rows.
"""

from __future__ import annotations

from typing import Any, Mapping

from cerbos.sdk.model import PlanResourcesResponse, Principal, ResourceDesc

from cerbos_policy_tests.client import build_client


def plan_for(
    client,
    principal: Principal,
    action: str,
    kind: str,
    policy_version: str = "default",
) -> PlanResourcesResponse:
    """Ask the PDP which resources of `kind` this principal may act on."""
    return client.plan_resources(
        actions=action,
        principal=principal,
        resource=ResourceDesc(kind=kind, policy_version=policy_version),
    )


def sql_select(
    plan: PlanResourcesResponse,
    table: Any,
    attr_map: Mapping[str, Any],
    table_mapping: Any = None,
    operator_override_fns: Any = None,
):
    """Turn a query plan into a SQLAlchemy SELECT.

    `attr_map` maps the attribute paths the policy reads onto columns:
    `request.resource.attr.ownerId` -> the resource table's owner column.
    """
    from cerbos_sqlalchemy import get_query

    return get_query(
        plan,
        table,
        dict(attr_map),
        table_mapping,
        operator_override_fns,
    )


def readable_ids(select, session) -> list[str]:
    """Run a SELECT and return the resource ids it matches, in order."""
    rows = session.execute(select).all()
    ids: list[str] = []
    for row in rows:
        value = row[0]
        # An ORM select yields the entity; a column select yields the value.
        ids.append(value.id if hasattr(value, "id") else value)
    return ids


__all__ = [
    "build_client",
    "plan_for",
    "readable_ids",
    "sql_select",
]
