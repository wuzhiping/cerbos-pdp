"""The coverage audit, executed against a running PDP.

The `cerbos-policy` skill ships `coverage_audit.py`, which checks a coverage
plan against the JSON reports `cerbos compile` produces. That needs the cerbos
binary, which this machine does not have.

This module applies the same rules to a live PDP instead: each planned row is
executed as a real request, and the isolation of every denial is checked by
comparing the resolved requests. The checks are the ones the skill's audit
performs:

1. every planned row must hold at the PDP;
2. the plan's `facts` must match the resolved fixture, not its name;
3. a row with a `control` must have the opposite effect and the same action,
   and the two requests must differ at exactly the field named by `change`;
4. every prerequisite of every declared grant path must have an isolated
   denial row with a passing control on a resource of that path's kind.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cerbos_policy_tests.fixtures import Fixtures
from cerbos_policy_tests.pep import authorize
from cerbos_policy_tests.rules import EFFECT_ALLOW
from cerbos_policy_tests.testplan import (
    ABSENT,
    Plan,
    Row,
    differences,
    flatten,
)

EFFECT_DENY = "EFFECT_DENY"


@dataclass
class AuditResult:
    passes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def principal_id_matters(policy_dir: Path) -> bool:
    """True when any policy reads the principal ID.

    Mirrors the skill's audit: a principal ID difference between a row and
    its control cannot explain a decision unless a policy reads it.
    """
    pattern = re.compile(r"\bP\.id\b|\bprincipal\.id\b|principalPolicy")
    for path in policy_dir.rglob("*"):
        if path.suffix not in {".yaml", ".yml", ".json"}:
            continue
        if "testdata" in path.parts or path.name.endswith(
            ("_test.yaml", "_test.yml", "_test.json")
        ):
            continue
        if pattern.search(path.read_text(errors="replace")):
            return True
    return False


def _resolve(row: Row, fixtures: Fixtures):
    return fixtures.principal(row.principal), fixtures.resource(row.resource)


def audit_live(plan: Plan, fixtures: Fixtures, client, policy_dir: Path) -> AuditResult:
    """Run the coverage audit against a live PDP."""
    result = AuditResult()
    by_id = plan.by_id()
    requests: dict[str, dict[str, Any]] = {}
    passed: set[str] = set()

    # 1. Every planned row must hold at the PDP.
    for row in plan.rows:
        principal, resource = _resolve(row, fixtures)
        try:
            allowed = authorize(
                client,
                action=row.action,
                principal=principal.to_principal(),
                resource=resource.to_resource(),
            )
        except Exception as exc:  # noqa: BLE001 - a failure must not abort the audit
            result.errors.append(f"FAIL {row.id}: {exc.__class__.__name__}: {exc}")
            continue

        actual = EFFECT_ALLOW if allowed else EFFECT_DENY
        if actual != row.effect:
            result.errors.append(
                f"FAIL {row.id}: {row.principal} {row.action} on {row.resource} "
                f"expected {row.effect}, got {actual}"
            )
            continue
        requests[row.id] = flatten(principal, resource)
        passed.add(row.id)

    # 2. The plan's facts must match the resolved fixture.
    for row in plan.rows:
        if row.id not in requests:
            continue
        request = requests[row.id]
        wrong = {
            path: request.get(path, ABSENT)
            for path, value in row.facts.items()
            if request.get(path, ABSENT) != (ABSENT if value is None else value)
        }
        if wrong:
            detail = ", ".join(
                f"{k}={v!r} (planned {row.facts[k]!r})" for k, v in wrong.items()
            )
            result.errors.append(
                f"FAIL {row.id}: fixture facts differ from the plan: {detail}"
            )

    # 3. Control pairs: opposite effect, same action, exactly one field differs.
    id_matters = principal_id_matters(policy_dir)
    for row in plan.rows:
        if row.id not in requests:
            continue

        if row.control is None:
            if row.change is not None:
                result.errors.append(f"FAIL {row.id}: `change` needs a `control`")
            else:
                result.passes.append(
                    f"PASS {row.id}: {requests[row.id]['resource.kind']} "
                    f"{row.action} {row.principal} / {row.resource} -> {row.effect}"
                )
            continue

        control = by_id.get(row.control)
        if control is None or row.control not in requests:
            result.errors.append(
                f"FAIL {row.id}: control {row.control!r} is not a passing row"
            )
            continue

        problems = []
        if control.effect == row.effect:
            problems.append(f"control {row.control} has the same effect")
        if control.action != row.action:
            problems.append(f"control {row.control} uses action {control.action}")

        diff = differences(requests[row.control], requests[row.id])
        diff.pop("resource.id", None)
        if not id_matters and row.change != "principal.id":
            diff.pop("principal.id", None)
        if set(diff) != {row.change}:
            detail = (
                ", ".join(f"{k}: {a!r} -> {b!r}" for k, (a, b) in diff.items())
                or "nothing"
            )
            problems.append(f"expected only {row.change} to differ, found {detail}")

        if problems:
            result.errors.append(f"FAIL {row.id}: " + "; ".join(problems))
        else:
            before, after = diff[row.change]
            result.passes.append(
                f"PASS {row.id}: vs {row.control}: {row.change} {before!r} -> {after!r}"
            )

    # 4. Every prerequisite of every grant path needs an isolated denial.
    for path in plan.paths:
        for prerequisite in path.requires:
            isolated = [
                row.id
                for row in plan.rows
                if row.path == path.id
                and row.prerequisite == prerequisite
                and row.control
                and row.id in passed
                and requests[row.id]["resource.kind"] == path.kind
            ]
            label = f"path {path.id} ({path.kind}) prerequisite {prerequisite}"
            if isolated:
                result.passes.append(f"PASS {label}: {', '.join(isolated)}")
            else:
                result.errors.append(
                    f"FAIL {label}: no passing isolated row with a control"
                )

    return result
