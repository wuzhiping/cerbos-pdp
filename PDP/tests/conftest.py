"""Shared fixtures for the Cerbos policy test suite.

The suite talks to a real Cerbos PDP over the network; it never writes to it.
"""

from __future__ import annotations

import pytest

from cerbos_policy_tests.client import build_client
from cerbos_policy_tests.config import COVERAGE_PLAN, POLICY_DIR
from cerbos_policy_tests.fixtures import load_fixtures
from cerbos_policy_tests.nativesuite import find_suites, load_suite
from cerbos_policy_tests.testplan import load_plan


@pytest.fixture(scope="session")
def client():
    """A session-scoped Cerbos client pointing at the PDP under test."""
    with build_client() as c:
        yield c


@pytest.fixture(scope="session")
def fixtures():
    """Principal and resource fixtures loaded from `policies/**/testdata/`."""
    return load_fixtures(POLICY_DIR)


@pytest.fixture(scope="session")
def suite():
    """The native `*_test.yaml` suite, expanded into assertions."""
    suites = find_suites(POLICY_DIR)
    assert suites, f"no *_test.yaml suite found under {POLICY_DIR}"
    return load_suite(suites[0])


@pytest.fixture(scope="session")
def plan():
    """The coverage plan."""
    return load_plan(COVERAGE_PLAN)
