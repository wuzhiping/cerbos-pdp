"""Load and expand a native Cerbos `*_test.yaml` suite.

The suite file is Cerbos' own format, so `cerbos compile` runs it unchanged
once a binary is available. This module reads the same file and expands it
into individual assertions, which the harness then executes against the
running PDP.

Two rules of the format drive the expansion:

* `input` is a cross product. Every principal listed is checked against every
  resource listed, for every action listed.
* A pair absent from `expected` is expected to be DENY for every action, and
  so is any action of a listed pair that `expected` does not mention.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

EFFECT_ALLOW = "EFFECT_ALLOW"
EFFECT_DENY = "EFFECT_DENY"


@dataclass(frozen=True)
class Case:
    """One assertion: a principal, a resource, an action and an expected effect."""

    test: str
    principal: str
    resource: str
    action: str
    effect: str


@dataclass(frozen=True)
class Suite:
    name: str
    description: str
    path: Path
    options: Mapping[str, Any]
    cases: tuple[Case, ...]

    def by_test(self) -> dict[str, tuple[Case, ...]]:
        grouped: dict[str, list[Case]] = {}
        for case in self.cases:
            grouped.setdefault(case.test, []).append(case)
        return {name: tuple(items) for name, items in grouped.items()}


def _expected_map(test: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, str]]:
    """Resolve the `expected` block into {(principal, resource): {action: effect}}."""
    resolved: dict[tuple[str, str], dict[str, str]] = {}
    for entry in test.get("expected") or []:
        principals = (
            [entry["principal"]] if "principal" in entry else list(entry.get("principals") or [])
        )
        resources = (
            [entry["resource"]] if "resource" in entry else list(entry.get("resources") or [])
        )
        actions = entry.get("actions") or {}
        for principal in principals:
            for resource in resources:
                resolved[(principal, resource)] = dict(actions)
    return resolved


def expand_suite(suite: Mapping[str, Any]) -> tuple[Case, ...]:
    """Expand a parsed suite into individual assertions."""
    cases: list[Case] = []
    for test in suite.get("tests") or []:
        name = test.get("name", "<unnamed>")
        request = test.get("input") or {}
        principals = list(request.get("principals") or [])
        resources = list(request.get("resources") or [])
        actions = list(request.get("actions") or [])
        expected = _expected_map(test)

        for principal in principals:
            for resource in resources:
                pair = expected.get((principal, resource), {})
                for action in actions:
                    cases.append(
                        Case(
                            test=name,
                            principal=principal,
                            resource=resource,
                            action=action,
                            effect=pair.get(action, EFFECT_DENY),
                        )
                    )
    return tuple(cases)


def load_suite(path: Path) -> Suite:
    """Load a native `*_test.yaml` suite from disk."""
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return Suite(
        name=raw.get("name", path.stem),
        description=raw.get("description", ""),
        path=path,
        options=raw.get("options") or {},
        cases=expand_suite(raw),
    )


def find_suites(policy_dir: Path) -> list[Path]:
    """Every native test suite under a policy directory."""
    return sorted(
        p
        for p in policy_dir.rglob("*_test.yaml")
        if "testdata" not in p.parts
    )
