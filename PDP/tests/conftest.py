"""Shared fixtures for the Cerbos policy test suite.

The suite talks to a real Cerbos PDP over the network; it never writes to it.
"""

from __future__ import annotations

import pytest

from cerbos_policy_tests.client import build_client
from cerbos_policy_tests.config import (
    BASIC_RESOURCE_POLICY_DIR,
    COVERAGE_PLAN,
    POLICY_DIR,
)
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
    """The basicResource family's principal and resource fixtures.

    The coverage plan and the exhaustive sweep describe basicResource, so
    this fixture is that family's set. Each policy family owns its own
    `testdata/`; a family that shares one with another would have its
    expectations silently answered with the wrong fixtures.
    """
    return load_fixtures(BASIC_RESOURCE_POLICY_DIR)


@pytest.fixture(scope="session")
def suites():
    """Every native `*_test.yaml` suite under the policy directory."""
    found = find_suites(POLICY_DIR)
    assert found, f"no *_test.yaml suite found under {POLICY_DIR}"
    return [(path, load_suite(path)) for path in found]


@pytest.fixture(scope="session")
def suite():
    """The first native suite, for the tests that are about one of them."""
    found = find_suites(POLICY_DIR)
    assert found, f"no *_test.yaml suite found under {POLICY_DIR}"
    return load_suite(found[0])


@pytest.fixture(scope="session")
def plan():
    """The coverage plan."""
    return load_plan(COVERAGE_PLAN)
