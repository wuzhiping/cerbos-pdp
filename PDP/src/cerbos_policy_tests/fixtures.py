"""Shared policy fixtures, loaded from the native `testdata/` files.

The fixtures live in `policies/**/testdata/*.yaml` in Cerbos' own format, so
the same files feed `cerbos compile` and this harness. Nothing here restates
a fixture in Python: the YAML is the single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from cerbos.sdk.model import Principal, Resource

DEFAULT_POLICY_VERSION = "default"


@dataclass(frozen=True)
class PrincipalFixture:
    """A principal fixture, resolved from its YAML entry."""

    key: str
    id: str
    roles: tuple[str, ...]
    attr: Mapping[str, Any]
    scope: str
    policy_version: str

    def to_principal(self) -> Principal:
        return Principal(
            id=self.id,
            roles=set(self.roles),
            attr=dict(self.attr),
            policy_version=self.policy_version or DEFAULT_POLICY_VERSION,
            scope=self.scope,
        )


@dataclass(frozen=True)
class ResourceFixture:
    """A resource fixture, resolved from its YAML entry."""

    key: str
    kind: str
    id: str
    attr: Mapping[str, Any]
    scope: str
    policy_version: str

    def to_resource(self) -> Resource:
        return Resource(
            id=self.id,
            kind=self.kind,
            attr=dict(self.attr),
            policy_version=self.policy_version or DEFAULT_POLICY_VERSION,
            scope=self.scope,
        )


@dataclass(frozen=True)
class Fixtures:
    principals: Mapping[str, PrincipalFixture]
    resources: Mapping[str, ResourceFixture]

    def principal(self, key: str) -> PrincipalFixture:
        try:
            return self.principals[key]
        except KeyError:
            raise KeyError(
                f"no principal fixture named {key!r}; known keys: "
                f"{sorted(self.principals)}"
            ) from None

    def resource(self, key: str) -> ResourceFixture:
        try:
            return self.resources[key]
        except KeyError:
            raise KeyError(
                f"no resource fixture named {key!r}; known keys: "
                f"{sorted(self.resources)}"
            ) from None


class AmbiguousTestdataError(FileNotFoundError):
    """More than one `testdata/` directory answers for one policy directory.

    Picking "the first one found" is what makes this worth an error: the
    suite would keep running, against fixtures that belong to a different
    policy family, and every answer it produced would be about the wrong
    policy.
    """

    def __init__(self, policy_dir: Path, candidates: list[Path]) -> None:
        found = ", ".join(str(candidate) for candidate in candidates)
        super().__init__(
            f"{policy_dir} owns more than one testdata/ directory: {found}. "
            f"Point the caller at the policy directory that owns the one it "
            f"means."
        )
        self.policy_dir = policy_dir
        self.candidates = candidates


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _find_testdata(policy_dir: Path) -> Path:
    """Locate the `testdata/` directory that belongs to `policy_dir`.

    A policy directory owns the `testdata/` directory directly inside it.
    The deeper search is a fallback for the single-family layout, and it
    accepts only an unambiguous match.
    """
    direct = policy_dir / "testdata"
    if direct.is_dir():
        return direct

    candidates = sorted(p for p in policy_dir.rglob("testdata") if p.is_dir())
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise FileNotFoundError(f"no testdata/ directory under {policy_dir}")
    raise AmbiguousTestdataError(policy_dir, candidates)


def load_fixtures(policy_dir: Path) -> Fixtures:
    """Load the principal and resource fixtures of one policy family.

    `policy_dir` is the directory that owns the fixtures — the one the
    `*_test.yaml` suite and the policies live in — not the root of the
    policy tree.
    """
    testdata = _find_testdata(policy_dir)

    principals: dict[str, PrincipalFixture] = {}
    resources: dict[str, ResourceFixture] = {}

    principal_file = testdata / "principals.yaml"
    if principal_file.exists():
        for key, entry in (_load_yaml(principal_file).get("principals") or {}).items():
            principals[key] = PrincipalFixture(
                key=key,
                id=entry.get("id", key),
                roles=tuple(entry.get("roles") or ()),
                attr=entry.get("attr") or {},
                scope=entry.get("scope", ""),
                policy_version=entry.get("policyVersion", ""),
            )

    resource_file = testdata / "resources.yaml"
    if resource_file.exists():
        for key, entry in (_load_yaml(resource_file).get("resources") or {}).items():
            resources[key] = ResourceFixture(
                key=key,
                kind=entry.get("kind", ""),
                id=entry.get("id", key),
                attr=entry.get("attr") or {},
                scope=entry.get("scope", ""),
                policy_version=entry.get("policyVersion", ""),
            )

    return Fixtures(principals=principals, resources=resources)
