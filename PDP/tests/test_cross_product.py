"""The exhaustive sweep: every principal, every resource, every action.

The native suite is rule-focused — each case isolates one rule, so a failure
names the rule that broke. This sweep is the opposite: it pairs everything
with everything, so a combination the rule-focused suite never named is
still checked.

The oracle is the reference model in `cerbos_policy_tests.rules`, written
from the policy text rather than from the PDP. `test_native_suite.py` checks
that the model and the hand-written spec agree, so the two cannot drift.
"""

from __future__ import annotations

import pytest

from cerbos_policy_tests.config import POLICY_DIR
from cerbos_policy_tests.fixtures import load_fixtures
from cerbos_policy_tests.pep import authorize
from cerbos_policy_tests.rules import EFFECT_ALLOW, effect as reference_effect

FIXTURES = load_fixtures(POLICY_DIR)

ACTIONS = ("read", "create", "update", "delete")

CASES = [
    (principal_key, resource_key, action)
    for principal_key in FIXTURES.principals
    for resource_key in FIXTURES.resources
    for action in ACTIONS
]


def test_the_sweep_covers_every_combination():
    assert len(CASES) == (
        len(FIXTURES.principals) * len(FIXTURES.resources) * len(ACTIONS)
    )
    assert len(CASES) == len(set(CASES))


@pytest.mark.parametrize(
    ("principal_key", "resource_key", "action"),
    CASES,
    ids=[f"{p}-{r}-{a}" for p, r, a in CASES],
)
def test_the_pdp_agrees_with_the_reference_model(
    client, principal_key, resource_key, action
):
    principal = FIXTURES.principal(principal_key)
    resource = FIXTURES.resource(resource_key)

    allowed = authorize(
        client,
        action=action,
        principal=principal.to_principal(),
        resource=resource.to_resource(),
    )

    predicted = reference_effect(
        principal.id,
        set(principal.roles),
        resource.attr,
        action,
        principal.attr,
    )

    assert allowed is (predicted == EFFECT_ALLOW), (
        f"{principal_key} {action} on {resource_key}: the PDP said "
        f"{'ALLOW' if allowed else 'DENY'}, the reference model says {predicted}"
    )
