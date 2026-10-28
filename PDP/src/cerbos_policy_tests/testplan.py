"""The coverage plan: grant paths, planned assertions and their isolation.

This module reads `coverage-plan.json` in the format the `cerbos-policy`
skill's `coverage_audit.py` expects, and provides the flattening and
difference helpers that audit uses, so the same rules can be applied against
a running PDP instead of a compile report.

The plan records, for every rule that grants something, the prerequisites it
depends on, and for every prerequisite an isolated denial: a request that
differs from a granting request in exactly one field.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from cerbos_policy_tests.fixtures import PrincipalFixture, ResourceFixture

ABSENT = "<absent>"
EFFECTS = {"EFFECT_ALLOW", "EFFECT_DENY"}

FIELD = re.compile(
    r"(principal\.(id|roles|scope|policyVersion|attr\..+)"
    r"|resource\.(id|kind|scope|policyVersion|attr\..+))"
)


@dataclass(frozen=True)
class Path:
    """A grant path: a rule or role that allows actions on one resource kind."""

    id: str
    kind: str
    requires: tuple[str, ...]


@dataclass(frozen=True)
class Row:
    """One planned assertion, optionally isolated against a control."""

    id: str
    principal: str
    resource: str
    action: str
    effect: str
    control: str | None = None
    change: str | None = None
    path: str | None = None
    prerequisite: str | None = None
    facts: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.facts is None:
            object.__setattr__(self, "facts", {})


@dataclass(frozen=True)
class Plan:
    paths: tuple[Path, ...]
    rows: tuple[Row, ...]

    def by_id(self) -> dict[str, Row]:
        return {row.id: row for row in self.rows}


def load_plan(path: Path) -> Plan:
    """Load a coverage plan and check the shape the audit expects."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: the coverage plan must be a JSON object")

    paths = tuple(
        Path(
            id=item.get("id", ""),
            kind=item.get("kind", ""),
            requires=tuple(item.get("requires") or ()),
        )
        for item in (raw.get("paths") or [])
    )

    rows: list[Row] = []
    seen: set[str] = set()
    for item in raw.get("rows") or []:
        missing = {"id", "principal", "resource", "action", "effect"} - set(item)
        if missing:
            raise ValueError(f"{path}: row {item!r} is missing {sorted(missing)}")
        if item["effect"] not in EFFECTS:
            raise ValueError(
                f"{path}: row {item['id']}: effect must be EFFECT_ALLOW or EFFECT_DENY"
            )
        if item["id"] in seen:
            raise ValueError(f"{path}: duplicate row id {item['id']}")
        seen.add(item["id"])

        change = item.get("change")
        for field in [*(item.get("facts") or {}), *([change] if change else [])]:
            if not FIELD.fullmatch(field):
                raise ValueError(f"{path}: row {item['id']}: unknown field path {field!r}")

        rows.append(
            Row(
                id=item["id"],
                principal=item["principal"],
                resource=item["resource"],
                action=item["action"],
                effect=item["effect"],
                control=item.get("control"),
                change=change,
                path=item.get("path"),
                prerequisite=item.get("prerequisite"),
                facts=item.get("facts") or {},
            )
        )

    return Plan(paths=paths, rows=tuple(rows))


def flatten(
    principal: PrincipalFixture, resource: ResourceFixture
) -> dict[str, Any]:
    """Flatten a resolved request into the field paths the audit compares.

    Mirrors `flatten()` in the skill's `coverage_audit.py` exactly, including
    the sentinel for an absent field.
    """
    fields: dict[str, Any] = {
        "principal.id": principal.id,
        "principal.roles": sorted(principal.roles),
        "resource.kind": resource.kind,
    }
    for side, value in (("principal", principal), ("resource", resource)):
        for key in ("scope", "policy_version"):
            fields[f"{side}.{key}"] = getattr(value, key) or ABSENT
        for key, attr in (value.attr or {}).items():
            fields[f"{side}.attr.{key}"] = attr
    return fields


def differences(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, tuple]:
    """Fields whose values differ between two flattened requests."""
    keys = set(left) | set(right)
    return {
        key: (left.get(key, ABSENT), right.get(key, ABSENT))
        for key in sorted(keys)
        if left.get(key, ABSENT) != right.get(key, ABSENT)
    }
