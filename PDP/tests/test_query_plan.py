"""Filtering a list by permission.

The skill is explicit that filtering a list item by item is the common wrong
turn: pagination breaks, counts and aggregates stop working, the 50-resource
batch ceiling is hit, and the cost grows with the length of the list.
`planResources` inverts the order — the PDP returns the condition a resource
must satisfy and the database filters.

This module exercises the whole chain: PDP plan -> condition tree -> WHERE
clause -> the rows the database returns.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Boolean, Column, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from cerbos_policy_tests.fixtures import load_fixtures
from cerbos_policy_tests.config import POLICY_DIR
from cerbos_policy_tests.pep import authorize
from cerbos_policy_tests.queryplan import plan_for, readable_ids, sql_select

from cerbos.sdk.model import PlanResourcesFilterKind, Principal

Base = declarative_base()


class BasicResourceRow(Base):
    """The table the plan is translated into."""

    __tablename__ = "basic_resource"

    id = Column(String, primary_key=True)
    owner_id = Column(String, nullable=False)
    is_published = Column(Boolean, nullable=True)


ATTR_MAP = {
    "request.resource.attr.ownerId": BasicResourceRow.owner_id,
    "request.resource.attr.isPublished": BasicResourceRow.is_published,
}

FIXTURES = load_fixtures(POLICY_DIR)


@pytest.fixture(scope="module")
def session():
    """A database holding exactly the rows the fixtures describe."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        for key, fixture in FIXTURES.resources.items():
            db.add(
                BasicResourceRow(
                    id=fixture.id,
                    owner_id=fixture.attr.get("ownerId", ""),
                    is_published=fixture.attr.get("isPublished"),
                )
            )
        db.commit()
        yield db


def test_plan_kind_for_an_unrestricted_principal(client):
    plan = plan_for(
        client,
        Principal(id="admin1", roles={"ADMIN"}),
        action="read",
        kind="basicResource",
    )
    assert plan.filter.kind == PlanResourcesFilterKind.ALWAYS_ALLOWED


def test_plan_kind_for_an_unknown_role(client):
    plan = plan_for(
        client,
        Principal(id="guest", roles={"GUEST"}),
        action="read",
        kind="basicResource",
    )
    assert plan.filter.kind == PlanResourcesFilterKind.ALWAYS_DENIED


def test_plan_is_conditional_for_a_regular_user(client):
    plan = plan_for(
        client,
        Principal(id="alice", roles={"USER"}),
        action="read",
        kind="basicResource",
    )
    assert plan.filter.kind == PlanResourcesFilterKind.CONDITIONAL


def test_the_plan_bakes_in_the_principal_id(client):
    """The condition is resolved for this principal, not left symbolic."""
    plan = plan_for(
        client,
        Principal(id="dave", roles={"USER"}),
        action="update",
        kind="basicResource",
    )
    rendered = str(plan.filter.to_dict())
    assert "dave" in rendered
    assert "alice" not in rendered


@pytest.mark.parametrize(
    ("principal_id", "roles", "action", "expected_ids"),
    [
        (
            "alice",
            {"USER"},
            "read",
            ["doc-alice-pub", "doc-alice-unpub", "doc-bob-pub"],
        ),
        (
            "dave",
            {"USER"},
            "read",
            ["doc-alice-pub", "doc-bob-pub"],
        ),
        (
            "alice",
            {"USER"},
            "update",
            ["doc-alice-pub", "doc-alice-unpub"],
        ),
        (
            "bob",
            {"USER"},
            "delete",
            ["doc-bob-pub", "doc-bob-unpub"],
        ),
    ],
)
def test_query_plan_selects_the_right_rows(
    client, session, principal_id, roles, action, expected_ids
):
    plan = plan_for(
        client,
        Principal(id=principal_id, roles=roles),
        action=action,
        kind="basicResource",
    )
    select = sql_select(plan, BasicResourceRow, ATTR_MAP)
    assert sorted(readable_ids(select, session)) == sorted(expected_ids)


def test_an_unrestricted_principal_sees_every_row(client, session):
    plan = plan_for(
        client,
        Principal(id="admin1", roles={"ADMIN"}),
        action="read",
        kind="basicResource",
    )
    select = sql_select(plan, BasicResourceRow, ATTR_MAP)
    assert len(readable_ids(select, session)) == len(FIXTURES.resources)


def test_an_unknown_role_sees_no_rows(client, session):
    plan = plan_for(
        client,
        Principal(id="guest", roles={"GUEST"}),
        action="read",
        kind="basicResource",
    )
    select = sql_select(plan, BasicResourceRow, ATTR_MAP)
    assert readable_ids(select, session) == []


@pytest.mark.parametrize("action", ["read", "update", "delete", "create"])
def test_the_query_plan_agrees_with_the_point_check(client, session, action):
    """The plan and a per-resource check must select the same rows.

    They are two paths to the same answer. If they drift, a list endpoint
    would show rows that a direct check would refuse, or hide rows the
    caller may act on.
    """
    principal = Principal(id="alice", roles={"USER"})
    plan = plan_for(client, principal, action=action, kind="basicResource")
    select = sql_select(plan, BasicResourceRow, ATTR_MAP)
    planned = set(readable_ids(select, session))

    checked = set()
    for key, fixture in FIXTURES.resources.items():
        allowed = authorize(
            client,
            action=action,
            principal=principal,
            resource=fixture.to_resource(),
        )
        if allowed:
            checked.add(fixture.id)

    assert planned == checked, (
        f"the query plan and the point check disagree for {action}: "
        f"plan={sorted(planned)} check={sorted(checked)}"
    )
