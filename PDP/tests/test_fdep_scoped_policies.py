"""The policies: one per provider.

There is **no scope**. The provider is the Cerbos kind —
`namespace:task_queue:workflow` — the app family inside it is the id (the
C4 path), and the operation is the action.

So the policy tree is flat: one file per provider, and the app families
inside it are told apart by `R.id`.

    policies/
    ├── _schemas/fdep.json
    ├── pip_JEV_LAYA.yaml        the jev provider — kind pip.JEV.LAYA
    ├── pip_JEV_LAYA_test.yaml
    ├── pip_FDEP_SOP.yaml        the fdep provider — kind pip.FDEP.SOP
    ├── pip_FDEP_SOP_test.yaml
    └── testdata/                the FDEP fixtures, shared by the two suites
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import httpx
import pytest
import yaml

from cerbos_policy_tests.client import admin_headers, pdp_url
from cerbos_policy_tests.config import GENERAL_RULES, ORGS_REGISTRY, POLICY_DIR
from cerbos_policy_tests.fdep_rules import (
    attributes_enabled,
    families,
    kinds,
    store_names,
)

GENERATOR = pathlib.Path(__file__).resolve().parents[1] / "pdp-config" / "gen-scoped-policies.py"


def _load_generator():
    """Import the generator script — it is a script, not a package."""
    spec = importlib.util.spec_from_file_location("gen_scoped_policies", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GEN = _load_generator()


def _orgs() -> list[dict]:
    document = yaml.safe_load(ORGS_REGISTRY.read_text(encoding="utf-8")) or {}
    return document.get("orgs") or []


def _general() -> list[dict]:
    document = yaml.safe_load(GENERAL_RULES.read_text(encoding="utf-8")) or {}
    return document.get("rules") or []


def _policy_files() -> list[pathlib.Path]:
    """The policy files — the native suites and the fixtures are not among them."""
    return sorted(
        path
        for path in POLICY_DIR.glob("*.yaml")
        if not path.name.endswith("_test.yaml")
    )


def test_the_registry_lists_at_least_one_org():
    assert _orgs(), f"{ORGS_REGISTRY} lists no orgs"


def test_there_is_one_policy_per_provider():
    for kind in kinds():
        target = POLICY_DIR / f"{GEN.file_name(kind)}.yaml"
        assert target.exists(), f"{target} is missing"


def test_the_generated_files_are_up_to_date():
    """The committed files are what the generator produces.

    A hand-edited policy is one that the next run overwrites — and, worse,
    one that nobody can explain.

    The expected body is built **in memory**: writing it out and comparing
    afterwards would compare the file with itself, and the test would
    overwrite the committed policy on the way — including the attributes
    switch, which the generator takes from the registry and the test does
    not.
    """
    orgs = _orgs()
    general = _general()
    attributes = GEN.load_flag(ORGS_REGISTRY, "attributes", default=True)

    switched_off: list[str] = []

    def usable(rules: list[dict]) -> list[dict]:
        if attributes:
            return rules
        kept = []
        for rule in rules:
            if GEN.reads_an_attribute(rule):
                switched_off.append(str(rule.get("name")))
                continue
            kept.append(rule)
        return kept

    for org in orgs:
        kind = str(org.get("kind") or "")
        rules = [GEN.compile_rule(rule) for rule in usable(list(general))]
        for app in org.get("apps") or []:
            for grant in app.get("grants") or []:
                rules.extend(
                    usable(
                        [
                            GEN.compile_rule(
                                GEN.for_family(grant, str(app.get("path") or ""))
                            )
                        ]
                    )
                )

        expected = GEN.policy_body(
            kind, str(org.get("name") or "org"), rules,
            "the general rules, plus each app family's own",
            schema=attributes,
        )
        target = POLICY_DIR / f"{GEN.file_name(kind)}.yaml"
        assert target.read_text(encoding="utf-8") == expected, (
            f"{target.name} is not what the generator produces — "
            f"run pdp-config/gen-scoped-policies.py"
        )


def test_the_policy_carries_the_general_rules():
    """Every general rule that is switched on is in the policy.

    A rule that reads `R.attr` is switched off **entirely** while the
    attributes are off — so the policy carries fewer rules, not wider
    ones.
    """
    for kind in kinds():
        document = yaml.safe_load(
            (POLICY_DIR / f"{GEN.file_name(kind)}.yaml").read_text(encoding="utf-8")
        )
        names = {rule["name"] for rule in document["resourcePolicy"]["rules"]}
        expected = {
            rule["name"]
            for rule in _general()
            if attributes_enabled() or not GEN.reads_an_attribute(rule)
        }
        assert names >= expected, (kind, names, expected)


def test_a_family_rule_is_narrowed_to_that_family():
    """The id is what tells the families apart, so the rule has to name it.

    The generator adds the `R.id == "<c4 path>"` test itself — the author of
    a rule only says what is true *of that family*.

    The guest's rule reads `R.attr`, so while the attributes are off it is
    switched off and there is nothing to look at. The narrowing is checked
    against the registry instead, where the rule still is.
    """
    document = yaml.safe_load(
        (POLICY_DIR / f"{GEN.file_name('pip.JEV.LAYA')}.yaml").read_text(
            encoding="utf-8"
        )
    )
    rules = document["resourcePolicy"]["rules"]
    guest = next((rule for rule in rules if rule["name"] == "guests-may-read"), None)

    if guest is None:
        assert not attributes_enabled(), (
            "the guest's rule reads R.attr, so it is only switched off while "
            "the attributes are off"
        )
        registry = yaml.safe_load(ORGS_REGISTRY.read_text(encoding="utf-8")) or {}
        for org in registry.get("orgs") or []:
            for app in org.get("apps") or []:
                for rule in app.get("rules") or []:
                    if rule["name"] == "guests-may-read":
                        narrowed = GEN.for_family(rule, str(app.get("path") or ""))
                        expr = narrowed["condition"]["match"]["expr"]
                        assert 'R.id == "systemone.LAYA"' in expr, expr
        return

    expr = guest["condition"]["match"]["expr"]
    assert 'R.id == "systemone.LAYA"' in expr, expr


def test_a_family_grants_only_what_the_registry_lists():
    """The fdep family's own grant, and the general rules — nothing else.

    The grant is role-based (`USERS`), the general rules are role-based
    too, so the two are judged the same way.
    """
    document = yaml.safe_load(
        (POLICY_DIR / f"{GEN.file_name('pip.FDEP.SOP')}.yaml").read_text(
            encoding="utf-8"
        )
    )
    rules = document["resourcePolicy"]["rules"]
    names = {rule["name"] for rule in rules}
    expected = {
        rule["name"]
        for rule in _general()
        if attributes_enabled() or not GEN.reads_an_attribute(rule)
    }
    expected.add("users-may-use-twseMops")
    assert names == expected, names

    users = next(rule for rule in rules if rule["name"] == "users-may-use-twseMops")
    assert users["roles"] == ["USERS"]
    assert users["actions"] == ["todayMaterial", "materialDetail"]
    assert users["condition"]["match"]["expr"] == 'R.id == "twseMops"' 


def test_every_policy_declares_the_schema():
    """The schema validates the attributes — so it is only there while they
    are in use."""
    for kind in kinds():
        document = yaml.safe_load(
            (POLICY_DIR / f"{GEN.file_name(kind)}.yaml").read_text(encoding="utf-8")
        )
        policy = document["resourcePolicy"]
        assert policy["resource"] == kind
        assert policy["version"] == "default"
        assert "scope" not in policy, "there is no scope any more"
        if attributes_enabled():
            assert policy["schemas"]["resourceSchema"]["ref"] == "cerbos:///fdep.json"
        else:
            assert "schemas" not in policy


def test_every_rule_names_its_roles():
    """A rule without `roles` invalidates the whole policy.

    The whole request then falls to the default denial, while the policy
    still looks deployed in the admin API.
    """
    for path in _policy_files():
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for rule in document["resourcePolicy"]["rules"]:
            assert rule.get("roles"), f"{path.name}: rule {rule.get('name')!r} has no roles"


def test_no_policy_carries_a_catch_all_denial():
    """A catch-all DENY adds nothing — the default denial is already there —
    and a DENY rule without roles would take the whole policy down."""
    for path in _policy_files():
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for rule in document["resourcePolicy"]["rules"]:
            assert rule["effect"] != "EFFECT_DENY", (
                f"{path.name}: rule {rule.get('name')!r} is a catch-all denial"
            )


def test_the_roles_the_identity_layer_must_emit():
    """The PDP judges by role and nothing else.

    The identity layer fills `_token_.roles` — that is where the real
    user id and roles will come from. The names it emits have to be the
    names the policies use: a mismatch denies every call, and the policy
    looks perfectly healthy while it does.

    This test is the contract, written down where the identity layer will
    find it.
    """
    # The contract is the **whole** set of names, not the ones that happen
    # to be switched on: the identity layer has to emit the right ones
    # whichever rules are live.
    #
    # Two kinds of name now:
    #
    # * **the roles** — the general rules are role-based
    # * **the principal's ids** — the app grants are id-based
    roles: set[str] = set()
    for rule in _general():
        roles.update(rule.get("roles") or ())
    ids: set[str] = set()
    registry = yaml.safe_load(ORGS_REGISTRY.read_text(encoding="utf-8")) or {}
    for org in registry.get("orgs") or []:
        for app in org.get("apps") or []:
            for grant in app.get("grants") or []:
                if grant.get("principal"):
                    ids.add(str(grant["principal"]))
    assert roles == {
        "FDEP_ADMIN",
        "FDEP_DEVELOPER",
        "FDEP_AUDITOR",
    }, roles
    # The app grants are open — they name the app and the operations, not
    # a person. The ids are empty until a grant names one.
    assert ids == set(), ids


def test_the_attributes_switch_is_in_the_registry():
    """The switch lives in one place — the registry the generator reads.

    It has to be a *setting*, not a deletion: the rules stay in the
    registry and in `general-rules.yaml` with their conditions intact, so
    flipping it brings them all back.
    """
    document = yaml.safe_load(ORGS_REGISTRY.read_text(encoding="utf-8")) or {}
    assert "attributes" in document, (
        "the registry must say whether the attributes are in use"
    )
    assert isinstance(document["attributes"], bool)


def test_no_policy_reads_an_attribute_while_the_attributes_are_off():
    """The switch has to hold in the deployed policies.

    A rule that reads `R.attr` would be a rule the generator dropped, and
    the deployment would then differ from the registry — the deployment
    would be judging by an attribute the registry says is switched off.
    """
    if attributes_enabled():
        return
    for path in _policy_files():
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for rule in document["resourcePolicy"]["rules"]:
            expr = ((rule.get("condition") or {}).get("match") or {}).get("expr", "")
            assert "R.attr" not in expr, (
                f"{path.name}: the rule {rule.get('name')!r} reads R.attr, but the "
                f"attributes are switched off"
            )


def test_no_policy_declares_a_schema_while_the_attributes_are_off():
    """The schema validates the attributes — so it goes with them.

    A schema that pins `accessMode` and `riskLevel` is itself a function
    of `R.attr`: a request with a bad value is rejected before any rule
    is consulted.
    """
    if attributes_enabled():
        return
    for path in _policy_files():
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "schemas" not in document["resourcePolicy"], path.name


def test_the_switched_off_rules_are_still_in_the_registry():
    """They are switched off, not deleted.

    The point of the switch is that the rules come back when the app
    registry is wired up — so they have to still be there.
    """
    if attributes_enabled():
        return
    document = yaml.safe_load(GENERAL_RULES.read_text(encoding="utf-8")) or {}
    names = {rule["name"] for rule in document.get("rules") or []}
    assert "developer-may-execute-non-high-risk" in names
    assert "auditor-may-only-read-low-risk" in names


def test_the_model_and_the_registry_agree_on_the_families():
    """The reference model derives its families from the same file."""
    expected = {
        (kind, path)
        for kind in kinds()
        for path, _ in families(kind)
    }
    assert expected == {
        ("pip.JEV.LAYA", "systemone.LAYA"),
        ("pip.FDEP.SOP", "twseMops"),
    }


@pytest.mark.parametrize("kind", sorted(kinds()))
def test_the_store_holds_the_policy_for_every_provider(kind):
    """A provider with no policy is NO_MATCH — every call of it is denied."""
    response = httpx.get(
        f"{pdp_url()}/admin/policies", headers=admin_headers(), timeout=10.0
    )
    response.raise_for_status()
    served = set(response.json()["policyIds"])
    assert f"resource.{kind}.vdefault" in served, sorted(served)


def test_the_store_keeps_the_dotted_kind():
    """A dotted kind is kept as it is.

    A colon-separated kind is rewritten by the store — `pip:JEV:LAYA` is
    kept as `resource.pip_JEV_LAYA.vdefault` — so the kind and its id
    would disagree. With dots every spelling of the provider is the same
    string: the file name, the policy's `resource:`, the request's `kind`
    and the store's id.
    """
    assert "pip.JEV.LAYA" in store_names()
    assert "pip.FDEP.SOP" in store_names()
