"""The coverage plan, audited against the live PDP.

The plan declares every grant path in the policy and, for each prerequisite
of each path, an isolated denial: a request that differs from a granting
request in exactly one field. This module checks that the PDP really behaves
that way, using the same rules the skill's `coverage_audit.py` applies to a
compile report.
"""

from __future__ import annotations

import pytest

from cerbos_policy_tests.config import POLICY_DIR
from cerbos_policy_tests.coverage import audit_live, principal_id_matters


def test_plan_is_well_formed(plan):
    assert plan.rows, "the coverage plan has no rows"
    assert plan.paths, "the coverage plan declares no paths"


def test_every_row_has_a_unique_id(plan):
    ids = [row.id for row in plan.rows]
    assert len(ids) == len(set(ids))


def test_every_path_prerequisite_has_an_isolated_denial(plan):
    """A grant path with no isolated denial for one of its prerequisites
    proves nothing about that prerequisite."""
    for path in plan.paths:
        for prerequisite in path.requires:
            rows = [
                row
                for row in plan.rows
                if row.path == path.id and row.prerequisite == prerequisite
            ]
            assert rows, (
                f"path {path.id} prerequisite {prerequisite} has no row"
            )
            for row in rows:
                assert row.control, (
                    f"path {path.id} prerequisite {prerequisite}: "
                    f"row {row.id} has no control"
                )
                assert row.change, (
                    f"path {path.id} prerequisite {prerequisite}: "
                    f"row {row.id} names no changed field"
                )


def test_the_policy_reads_the_principal_id():
    """The policy compares ownerId against the principal ID, so a difference
    in that field can explain a decision and must not be ignored."""
    assert principal_id_matters(POLICY_DIR) is True


def test_coverage_audit_passes_against_the_live_pdp(client, plan, fixtures):
    result = audit_live(plan, fixtures, client, POLICY_DIR)
    assert result.ok, "\n".join(f"  {error}" for error in result.errors)
    assert result.passes, "the audit produced no passes at all"


def test_coverage_audit_covers_every_row(client, plan, fixtures):
    """Every planned row must be exercised, not merely mentioned."""
    result = audit_live(plan, fixtures, client, POLICY_DIR)
    covered = {
        row.id
        for row in plan.rows
        if any(pass_line.startswith(f"PASS {row.id}") for pass_line in result.passes)
    }
    missing = {row.id for row in plan.rows} - covered
    assert not missing, f"rows not exercised by a passing assertion: {sorted(missing)}"


@pytest.mark.parametrize(
    "prerequisite",
    ["admin-role", "user-role", "published", "owner"],
)
def test_each_prerequisite_is_isolated_somewhere(plan, prerequisite):
    rows = [
        row
        for row in plan.rows
        if row.prerequisite == prerequisite and row.control and row.change
    ]
    assert rows, f"no isolated denial for the {prerequisite!r} prerequisite"
