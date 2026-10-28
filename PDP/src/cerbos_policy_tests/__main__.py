"""Run the coverage audit against the live PDP and save the report.

    uv run python -m cerbos_policy_tests            # print
    uv run python -m cerbos_policy_tests --save     # also write coverage-audit.txt

The skill's `coverage_audit.py` needs the JSON reports `cerbos compile`
produces. Without a cerbos binary this runs the same rules against the
running PDP instead, and saves its output next to the coverage plan.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cerbos_policy_tests.client import build_client
from cerbos_policy_tests.config import COVERAGE_PLAN, POLICY_DIR, REPO_ROOT
from cerbos_policy_tests.coverage import audit_live
from cerbos_policy_tests.fixtures import load_fixtures
from cerbos_policy_tests.testplan import load_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cerbos_policy_tests")
    parser.add_argument(
        "--save",
        action="store_true",
        help="write the report next to the coverage plan",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "coverage-audit.txt",
        help="where to write the report",
    )
    args = parser.parse_args(argv)

    plan = load_plan(COVERAGE_PLAN)
    fixtures = load_fixtures(POLICY_DIR)

    with build_client() as client:
        result = audit_live(plan, fixtures, client, POLICY_DIR)

    lines = [
        "Coverage audit against the live PDP",
        f"plan   : {COVERAGE_PLAN}",
        f"policies: {POLICY_DIR}",
        f"rows   : {len(plan.rows)}   paths: {len(plan.paths)}",
        "",
        *result.passes,
        "",
    ]
    if result.errors:
        lines.append("ERRORS")
        lines.extend(result.errors)
    else:
        lines.append("no failures")

    text = "\n".join(lines)
    print(text)

    if args.save:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"\nwritten to {args.out}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
