#!/usr/bin/env python3
"""Audit a Cerbos coverage plan against the decisions a running PDP made.

This is the API-only counterpart of `coverage_audit.py`, which checks a plan
against the JSON reports `cerbos compile` produces. It needs no cerbos binary,
no cerbosctl and no Docker: it resolves the plan's fixture keys, executes
every planned row against a live PDP over HTTP, and applies the same rules.

    python3 coverage_audit_api.py --pdp http://localhost:3592 \
        --policies policies --plan coverage-plan.json

Environment:
    CERBOS_ADMIN_USER       optional, for a PDP whose check endpoints need auth
    CERBOS_ADMIN_PASSWORD   optional

Exit codes:
    0  the audit passed
    1  the audit found failures
    2  an input could not be read (missing PyYAML, malformed plan, unknown fixture)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ABSENT = "<absent>"
EFFECTS = {"EFFECT_ALLOW", "EFFECT_DENY"}
FIELD = re.compile(
    r"(principal\.(id|roles|scope|policyVersion|attr\..+)"
    r"|resource\.(id|kind|scope|policyVersion|attr\..+))"
)

try:
    import yaml
except ImportError:  # pragma: no cover
    print(
        "PyYAML is required to read the policy fixtures and test suites.\n"
        "Install it with: pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(2)


class Unreadable(Exception):
    """An input could not be read."""


def bypass_proxy_for(base_url: str) -> None:
    """Keep the PDP request off any proxy.

    On Windows, `urllib.request.getproxies()` returns the proxy declared in
    the registry, and a PDP on the operator's own network usually cannot be
    reached through it. The PDP host is added to NO_PROXY, which leaves the
    proxy in place for everything else.
    """
    host = urllib.parse.urlsplit(base_url).hostname
    if not host:
        return
    entries = {
        value.strip()
        for name in ("NO_PROXY", "no_proxy")
        for value in os.environ.get(name, "").split(",")
        if value.strip()
    }
    if host not in entries:
        entries.add(host)
        os.environ["NO_PROXY"] = ",".join(sorted(entries))
        os.environ["no_proxy"] = os.environ["NO_PROXY"]


# --------------------------------------------------------------------------- #
# Policy fixtures and native test suites
# --------------------------------------------------------------------------- #
def load_yaml(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as error:
        raise Unreadable(f"{path}: {error}") from error


def find_testdata(policy_dir: Path) -> Path:
    for candidate in sorted(policy_dir.rglob("testdata")):
        if candidate.is_dir():
            return candidate
    raise Unreadable(f"no testdata/ directory under {policy_dir}")


def load_fixtures(policy_dir: Path) -> tuple[dict, dict]:
    """Shared principal and resource fixtures, as the audit compares them."""
    testdata = find_testdata(policy_dir)
    principals: dict = {}
    resources: dict = {}
    for name, target in (("principals", principals), ("resources", resources)):
        for extension in ("yaml", "yml", "json"):
            path = testdata / f"{name}.{extension}"
            if path.exists():
                target.update(load_yaml(path).get(name) or {})
    return principals, resources


def expand_suite(suite: dict) -> list[tuple[str, str, str, str]]:
    """Expand a native suite into (test, principal key, resource key, action, effect)."""
    assertions: list[tuple[str, str, str, str]] = []
    for test in suite.get("tests") or []:
        name = test.get("name", "<unnamed>")
        request = test.get("input") or {}
        expected: dict[tuple[str, str], dict[str, str]] = {}
        for entry in test.get("expected") or []:
            principals = (
                [entry["principal"]]
                if "principal" in entry
                else list(entry.get("principals") or [])
            )
            resources = (
                [entry["resource"]]
                if "resource" in entry
                else list(entry.get("resources") or [])
            )
            for principal in principals:
                for resource in resources:
                    expected[(principal, resource)] = dict(entry.get("actions") or {})

        for principal in request.get("principals") or []:
            for resource in request.get("resources") or []:
                pair = expected.get((principal, resource), {})
                for action in request.get("actions") or []:
                    assertions.append(
                        (name, principal, resource, action, pair.get(action, "EFFECT_DENY"))
                    )
    return assertions


def load_suite_assertions(policy_dir: Path) -> list[tuple[str, str, str, str, str]]:
    """Every assertion in every native suite under the policy directory."""
    assertions: list[tuple[str, str, str, str, str]] = []
    for path in sorted(policy_dir.rglob("*_test.yaml")):
        if "testdata" in path.parts:
            continue
        suite = load_yaml(path)
        assertions.extend(expand_suite(suite))
    return assertions


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #
def load_plan(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Unreadable(f"{path}: the coverage plan must be JSON ({error})") from error
    if not isinstance(raw, dict):
        raise Unreadable(f"{path}: the coverage plan must be a JSON object")

    rows = raw.get("rows") or []
    if not rows:
        raise Unreadable(f"{path}: the plan has no rows")

    seen: set[str] = set()
    for row in rows:
        missing = {"id", "principal", "resource", "action", "effect"} - set(row)
        if missing:
            raise Unreadable(f"{path}: row {row!r} is missing {sorted(missing)}")
        if row["effect"] not in EFFECTS:
            raise Unreadable(
                f"{path}: row {row['id']}: effect must be EFFECT_ALLOW or EFFECT_DENY"
            )
        if row["id"] in seen:
            raise Unreadable(f"{path}: duplicate row id {row['id']}")
        seen.add(row["id"])
        change = [row["change"]] if isinstance(row.get("change"), str) else []
        for field in [*(row.get("facts") or {}), *change]:
            if not FIELD.fullmatch(field):
                raise Unreadable(f"{path}: row {row['id']}: unknown field path {field!r}")
    return raw


def flatten(principal: dict, resource: dict) -> dict:
    """Flatten a resolved request into the field paths the audit compares."""
    fields = {
        "principal.id": principal.get("id"),
        "principal.roles": sorted(principal.get("roles") or []),
        "resource.kind": resource.get("kind"),
    }
    for side, value in (("principal", principal), ("resource", resource)):
        for key in ("scope", "policyVersion"):
            fields[f"{side}.{key}"] = value.get(key, ABSENT)
        for key, attr in (value.get("attr") or {}).items():
            fields[f"{side}.attr.{key}"] = attr
    return fields


def differences(left: dict, right: dict) -> dict:
    keys = set(left) | set(right)
    return {
        key: (left.get(key, ABSENT), right.get(key, ABSENT))
        for key in sorted(keys)
        if left.get(key, ABSENT) != right.get(key, ABSENT)
    }


def principal_id_matters(policy_dir: Path) -> bool:
    """True when any policy reads the principal ID."""
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


# --------------------------------------------------------------------------- #
# The PDP
# --------------------------------------------------------------------------- #
class Pdp:
    def __init__(self, base_url: str, user: str = "", password: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = ""
        if user:
            token = base64.b64encode(f"{user}:{password}".encode()).decode()
            self.auth = f"Basic {token}"
        bypass_proxy_for(self.base_url)

    def _post(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if self.auth:
            request.add_header("Authorization", self.auth)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")
            raise Unreadable(f"{path}: HTTP {error.code}: {body}") from error
        except urllib.error.URLError as error:
            raise Unreadable(f"{path}: could not reach the PDP: {error.reason}") from error

    def effect(self, principal: dict, resource: dict, action: str) -> str:
        """The effect the PDP grants for one request."""
        payload = {
            "requestId": "coverage-audit",
            "principal": {
                "id": principal.get("id"),
                "roles": principal.get("roles") or [],
            },
            "resources": [
                {
                    "resource": {
                        "kind": resource.get("kind"),
                        "id": resource.get("id"),
                        "attr": resource.get("attr") or {},
                    },
                    "actions": [action],
                }
            ],
        }
        if principal.get("policyVersion"):
            payload["principal"]["policyVersion"] = principal["policyVersion"]
        if resource.get("policyVersion"):
            payload["resources"][0]["resource"]["policyVersion"] = resource["policyVersion"]
        if principal.get("scope"):
            payload["principal"]["scope"] = principal["scope"]
        if resource.get("scope"):
            payload["resources"][0]["resource"]["scope"] = resource["scope"]

        response = self._post("/api/check/resources", payload)
        results = response.get("results") or []
        if not results:
            message = response.get("message") or response.get("error") or response
            raise Unreadable(f"the PDP returned no result: {message}")
        actions = results[0].get("actions") or {}
        if action not in actions:
            raise Unreadable(f"the PDP returned no effect for action {action!r}")
        return actions[action]


# --------------------------------------------------------------------------- #
# The audit
# --------------------------------------------------------------------------- #
def audit(args) -> tuple[list[str], list[str]]:
    policy_dir = Path(args.policies)
    plan = load_plan(Path(args.plan))
    principals, resources = load_fixtures(policy_dir)
    suite_assertions = load_suite_assertions(policy_dir)
    suite_pairs = {(p, r, a, e) for _, p, r, a, e in suite_assertions}

    pdp = Pdp(args.pdp, args.admin_user, args.admin_password)
    id_matters = principal_id_matters(policy_dir)

    passes: list[str] = []
    errors: list[str] = []
    by_id = {row["id"]: row for row in plan["rows"]}
    requests: dict[str, dict] = {}
    passed: set[str] = set()

    for row in plan["rows"]:
        principal = principals.get(row["principal"])
        resource = resources.get(row["resource"])
        if principal is None:
            errors.append(f"FAIL {row['id']}: no principal fixture named {row['principal']!r}")
            continue
        if resource is None:
            errors.append(f"FAIL {row['id']}: no resource fixture named {row['resource']!r}")
            continue

        # The row must correspond to an assertion the suite actually makes.
        if (row["principal"], row["resource"], row["action"], row["effect"]) not in suite_pairs:
            errors.append(
                f"FAIL {row['id']}: no test-suite assertion for "
                f"{row['principal']} / {row['resource']} / {row['action']} -> {row['effect']}"
            )
            continue

        try:
            actual = pdp.effect(principal, resource, row["action"])
        except Unreadable as error:
            errors.append(f"FAIL {row['id']}: {error}")
            continue

        if actual != row["effect"]:
            errors.append(
                f"FAIL {row['id']}: {row['principal']} {row['action']} on {row['resource']} "
                f"expected {row['effect']}, got {actual}"
            )
            continue

        requests[row["id"]] = flatten(principal, resource)
        passed.add(row["id"])

    for row in plan["rows"]:
        if row["id"] not in requests:
            continue
        request = requests[row["id"]]

        wrong = {
            path: request.get(path, ABSENT)
            for path, value in (row.get("facts") or {}).items()
            if request.get(path, ABSENT) != (ABSENT if value is None else value)
        }
        if wrong:
            detail = ", ".join(f"{k}={v!r} (planned {row['facts'][k]!r})" for k, v in wrong.items())
            errors.append(f"FAIL {row['id']}: fixture facts differ from the plan: {detail}")
            continue

        line = (
            f"{row['id']}: {request['resource.kind']} {row['action']} "
            f"{row['principal']} / {row['resource']} -> {row['effect']}"
        )

        control_id = row.get("control")
        if control_id is None:
            if "change" in row:
                errors.append(f"FAIL {line}; `change` needs a `control`")
            else:
                passes.append(f"PASS {line}")
            continue

        control = by_id.get(control_id)
        if control is None or control_id not in requests:
            errors.append(f"FAIL {line}; control {control_id!r} is not a passing row")
            continue

        problems = []
        if control["effect"] == row["effect"]:
            problems.append(f"control {control_id} has the same effect")
        if control["action"] != row["action"]:
            problems.append(f"control {control_id} uses action {control['action']}")

        diff = differences(requests[control_id], request)
        diff.pop("resource.id", None)
        if not id_matters and row.get("change") != "principal.id":
            diff.pop("principal.id", None)
        if set(diff) != {row.get("change")}:
            detail = (
                ", ".join(f"{k}: {a!r} -> {b!r}" for k, (a, b) in diff.items()) or "nothing"
            )
            problems.append(f"expected only {row.get('change')} to differ, found {detail}")

        if problems:
            errors.append(f"FAIL {line}; " + "; ".join(problems))
        else:
            before, after = diff[row["change"]]
            passes.append(f"PASS {line}; vs {control_id}: {row['change']} {before!r} -> {after!r}")

    for path in plan.get("paths") or []:
        for prerequisite in path.get("requires") or []:
            isolated = [
                row["id"]
                for row in plan["rows"]
                if row.get("path") == path.get("id")
                and row.get("prerequisite") == prerequisite
                and row.get("control")
                and row["id"] in passed
                and requests[row["id"]]["resource.kind"] == path.get("kind")
            ]
            label = f"path {path.get('id')} ({path.get('kind')}) prerequisite {prerequisite}"
            if isolated:
                passes.append(f"PASS {label}: {', '.join(isolated)}")
            else:
                errors.append(
                    f"FAIL {label}: no passing isolated row with a control; add a DENY row "
                    "with this `path` and `prerequisite`, a passing ALLOW `control`, and the "
                    "one differing field as `change`"
                )

    return passes, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coverage_audit_api.py")
    parser.add_argument("--pdp", required=True, help="base URL of the PDP, e.g. http://localhost:3592")
    parser.add_argument("--policies", required=True, help="the policy directory")
    parser.add_argument("--plan", required=True, help="the coverage plan")
    parser.add_argument("--admin-user", default=os.environ.get("CERBOS_ADMIN_USER", ""))
    parser.add_argument("--admin-password", default=os.environ.get("CERBOS_ADMIN_PASSWORD", ""))
    parser.add_argument("--out", default="", help="write the report to this file as well")
    args = parser.parse_args(argv)

    try:
        passes, errors = audit(args)
    except Unreadable as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    for line in errors:
        print(line)
    for line in passes:
        print(line)

    summary = f"\n{len(passes)} passed, {len(errors)} failed"
    print(summary)

    if args.out:
        Path(args.out).write_text(
            "\n".join(errors + passes) + summary + "\n", encoding="utf-8"
        )

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
