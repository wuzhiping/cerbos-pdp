"""The native Cerbos test suites, executed against the running PDP.

Every `*_test.yaml` under `policies/` is written in Cerbos' own format, so
`cerbos compile` runs it unchanged once a binary is available. This module
runs the very same files against the PDP at 10.17.1.201:3592 — the files
are the single source of truth, not copies of them.

Every suite runs, not just the first one. A suite that is discovered but
never executed is worse than no suite at all: the coverage it claims to
provide evaporates silently, and the policy it describes has nothing
checking it.

Each suite runs against the fixtures of its own policy family. The families
keep separate `testdata/` directories precisely so that this can be said
without a second thought.
"""

from __future__ import annotations

import pytest

from cerbos_policy_tests.config import POLICY_DIR
from cerbos_policy_tests.fixtures import load_fixtures
from cerbos_policy_tests.nativesuite import find_suites, load_suite
from cerbos_policy_tests.pep import authorize
from cerbos_policy_tests.reference import EFFECT_ALLOW, EFFECT_DENY, effect

SUITE_PATHS = find_suites(POLICY_DIR)
SUITES = [(path, load_suite(path)) for path in SUITE_PATHS]
FIXTURES = {path.parent: load_fixtures(path.parent) for path in SUITE_PATHS}

CASES = [
    (path, suite, case)
    for path, suite in SUITES
    for case in suite.cases
]


def _case_id(path, suite, case) -> str:
    return f"{suite.kind}-{case.principal}-{case.resource}-{case.action}"


def test_every_suite_is_executed():
    """A suite that no test runs is a coverage claim with nothing behind it."""
    assert SUITE_PATHS, f"no *_test.yaml suite found under {POLICY_DIR}"
    assert len(CASES) == sum(len(suite.cases) for _, suite in SUITES)


@pytest.mark.parametrize(
    ("path", "suite"),
    SUITES,
    ids=[f"{suite.kind}-{path.name}" for path, suite in SUITES],
)
def test_suite_is_loaded(path, suite):
    assert suite.cases, f"{path.name} expanded to no assertions"
    assert suite.name, f"{path.name} declares no suite name"


@pytest.mark.parametrize(
    ("path", "suite"),
    SUITES,
    ids=[f"{suite.kind}-{path.name}" for path, suite in SUITES],
)
def test_suite_declares_strict_evaluation(path, suite):
    """The suite states the strict-evaluation intent.

    The live PDP evaluates without it, so a live run cannot catch a
    condition that errors at runtime and silently evaluates false. The
    declaration is what `cerbos compile --strict-evaluation` will enforce.
    """
    assert suite.options.get("strictEvaluation") is True, (
        f"{path.name} does not declare strictEvaluation"
    )


@pytest.mark.parametrize(
    ("path", "suite", "case"),
    [pytest.param(path, suite, case, id=_case_id(path, suite, case))
     for path, suite, case in CASES],
)
def test_native_suite_assertion(client, path, suite, case):
    """One assertion of a native suite, checked against the live PDP."""
    fixtures = FIXTURES[path.parent]
    principal = fixtures.principal(case.principal)
    resource = fixtures.resource(case.resource)

    allowed = authorize(
        client,
        action=case.action,
        principal=principal.to_principal(),
        resource=resource.to_resource(),
    )

    expected = case.effect == EFFECT_ALLOW
    assert allowed is expected, (
        f"{case.test}: {case.principal} {case.action} on {case.resource} "
        f"expected {case.effect}, got "
        f"{EFFECT_ALLOW if allowed else EFFECT_DENY}"
    )


@pytest.mark.parametrize(
    ("path", "suite", "case"),
    [pytest.param(path, suite, case, id=_case_id(path, suite, case))
     for path, suite, case in CASES],
)
def test_native_suite_agrees_with_the_reference_model(path, suite, case):
    """The hand-written spec and the reference model must not drift apart.

    The suite holds the authoritative expectations; the model is the oracle
    the exhaustive sweep uses. If they disagree, one of them is wrong and
    the disagreement is here rather than inside a policy change.
    """
    fixtures = FIXTURES[path.parent]
    principal = fixtures.principal(case.principal)
    resource = fixtures.resource(case.resource)

    predicted = effect(
        suite.kind,
        principal_id=principal.id,
        roles=principal.roles,
        resource_id=resource.id,
        resource_attr=resource.attr,
        resource_scope=resource.scope,
        resource_kind=resource.kind,
        action=case.action,
    )
    assert predicted == case.effect, (
        f"{case.test}: the reference model says {predicted} but the suite says "
        f"{case.effect}"
    )
