"""The native Cerbos test suite, executed against the running PDP.

`policies/resource_policies/basicResource_test.yaml` is written in Cerbos'
own format, so `cerbos compile` runs it unchanged once a binary is
available. This module runs the very same file against the PDP at
10.17.1.201:3592 — the file is the single source of truth, not a copy of it.
"""

from __future__ import annotations

import pytest

from cerbos_policy_tests.config import POLICY_DIR
from cerbos_policy_tests.fixtures import load_fixtures
from cerbos_policy_tests.nativesuite import find_suites, load_suite
from cerbos_policy_tests.pep import authorize
from cerbos_policy_tests.rules import EFFECT_ALLOW, effect as reference_effect

EFFECT_DENY = "EFFECT_DENY"

SUITE_PATH = find_suites(POLICY_DIR)[0]
SUITE = load_suite(SUITE_PATH)
FIXTURES = load_fixtures(POLICY_DIR)


def _case_id(case) -> str:
    return f"{case.principal}-{case.resource}-{case.action}"


def test_suite_is_loaded():
    assert SUITE.cases, "the native suite expanded to no assertions"
    assert SUITE.name == "BasicResourceTest"
    assert SUITE_PATH.name == "basicResource_test.yaml"


def test_suite_declares_strict_evaluation():
    """The suite states the strict-evaluation intent.

    The live PDP evaluates without it, so a live run cannot catch a
    condition that errors at runtime and silently evaluates false. The
    declaration is what `cerbos compile --strict-evaluation` will enforce.
    """
    assert SUITE.options.get("strictEvaluation") is True


@pytest.mark.parametrize(
    "case",
    [pytest.param(case, id=_case_id(case)) for case in SUITE.cases],
)
def test_native_suite_assertion(client, case):
    """One assertion of the native suite, checked against the live PDP."""
    principal = FIXTURES.principal(case.principal)
    resource = FIXTURES.resource(case.resource)

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
    "case",
    [pytest.param(case, id=_case_id(case)) for case in SUITE.cases],
)
def test_native_suite_agrees_with_the_reference_model(case):
    """The hand-written spec and the reference model must not drift apart.

    The suite holds the authoritative expectations; the model is the oracle
    the exhaustive sweep uses. If they disagree, one of them is wrong and
    the disagreement is here rather than inside a policy change.
    """
    principal = FIXTURES.principal(case.principal)
    resource = FIXTURES.resource(case.resource)

    predicted = reference_effect(
        principal.id,
        set(principal.roles),
        resource.attr,
        case.action,
    )
    assert predicted == case.effect, (
        f"{case.test}: the reference model says {predicted} but the suite says "
        f"{case.effect}"
    )
