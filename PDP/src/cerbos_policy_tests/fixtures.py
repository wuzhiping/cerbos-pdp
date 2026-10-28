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


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _find_testdata(policy_dir: Path) -> Path | None:
    """Locate the shared `testdata/` directory under a policy directory."""
    for candidate in sorted(policy_dir.rglob("testdata")):
        if candidate.is_dir():
            return candidate
    return None


def load_fixtures(policy_dir: Path) -> Fixtures:
    """Load the shared principal and resource fixtures under `policy_dir`."""
    testdata = _find_testdata(policy_dir)
    if testdata is None:
        raise FileNotFoundError(f"no testdata/ directory under {policy_dir}")

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
