"""Cerbos Hello World — four steps, every one of them an HTTP API call.

    uv run python quickstart/quickstart.py --pdp http://10.17.1.201:3592

No `cerbos` CLI, no `cerbosctl`, no Docker. Each step names the skill it comes
from and the API call it makes:

    step 0  probe the PDP            cerbos-pep-integration   GET /_cerbos/health
    step 1  define a policy           cerbos-policy            (write the YAML)
    step 2  deploy it                 cerbos-policy            POST /admin/policy
    step 3  ask for ALLOW and DENY    cerbos-pep-integration   POST /api/check/resources
    step 4  read the audit trail      cerbos-audit-insights    GET /admin/auditlog/list/{kind}

Two steps depend on how the PDP is configured rather than on the method:

    step 2 needs a **mutable** store. A PDP reading policies from a directory
           answers `501 Configured store is not mutable`, and the operator
           owns deployment.
    step 4 needs a **queryable** audit backend. The `local` backend answers;
           `file` and `kafka` write but do not answer queries.

The script reports either answer plainly and carries on, so a run against a
differently configured PDP still shows what that PDP can do.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import sys
from urllib.parse import urlsplit

import httpx
import yaml
from cerbos.sdk.client import CerbosClient
from cerbos.sdk.model import Principal, Resource, ResourceList

ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_PDP = os.environ.get("CERBOS_PDP_URL", "http://10.17.1.201:3592")
DEFAULT_POLICY_DIR = ROOT / "policies"


def use_utf8_output() -> None:
    """Make stdout and stderr UTF-8, whatever the console locale says.

    On a Chinese Windows the preferred encoding is cp936 (GBK), so Python
    writes this script's Chinese output as GBK bytes and a UTF-8 terminal
    renders every character as garbage. Forcing UTF-8 here fixes it without
    the caller having to set PYTHONIOENCODING.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


# --------------------------------------------------------------------------- #
# plumbing
# --------------------------------------------------------------------------- #
def bypass_proxy(url: str) -> None:
    """Keep the PDP request off any proxy.

    On Windows `urllib.request.getproxies()` and httpx both pick up the proxy
    declared in the registry, and a PDP on the operator's own network usually
    cannot be reached through it. The PDP host joins NO_PROXY; the proxy stays
    in place for everything else.
    """
    host = urlsplit(url).hostname
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


class Step:
    """One step of the walkthrough and what came of it."""

    def __init__(self, number: int, title: str, skill: str, call: str) -> None:
        self.number = number
        self.title = title
        self.skill = skill
        self.call = call
        self.detail: list[str] = []
        self.ok = True
        self.skipped: str | None = None
        self.deferred: str | None = None

    def note(self, line: str) -> None:
        self.detail.append(line)

    def fail(self, line: str, skipped: str | None = None) -> None:
        self.ok = False
        self.skipped = skipped
        self.detail.append(line)

    def defer(self, line: str, why: str) -> None:
        """Not performed, and not a failure either — it was a deliberate choice."""
        self.deferred = why
        self.detail.append(line)

    def render(self) -> str:
        head = f"-- step {self.number}: {self.title}"
        meta = f"   skill : {self.skill}\n   call  : {self.call}"
        body = "\n".join(f"   {line}" for line in self.detail)
        return f"{head}\n{meta}\n{body}"


# --------------------------------------------------------------------------- #
# step 0 — probe the PDP
# --------------------------------------------------------------------------- #
def step_probe(pdp: str) -> Step:
    step = Step(0, "探活", "cerbos-pep-integration", "GET /_cerbos/health")
    with httpx.Client(timeout=10.0) as client:
        health = client.get(f"{pdp}/_cerbos/health")
        step.note(f"GET /_cerbos/health -> {health.status_code} {health.text.strip()}")

        info = client.get(f"{pdp}/api/server_info")
        if info.status_code == 200:
            payload = info.json()
            step.note(
                f"GET /api/server_info -> {payload.get('version')} "
                f"(commit {str(payload.get('commit'))[:12]})"
            )
        else:
            step.note(f"GET /api/server_info -> {info.status_code}")

        spec = client.get(f"{pdp}/schema/swagger.json")
        if spec.status_code == 200:
            paths = len(spec.json().get("paths", {}))
            step.note(f"GET /schema/swagger.json -> {paths} 条已文档化的路径")
        else:
            step.note(f"GET /schema/swagger.json -> {spec.status_code}")

        unauth = client.get(f"{pdp}/admin/policies")
        if unauth.status_code == 401:
            step.note("GET /admin/policies 不带凭据 -> 401,admin API 是受保护的")
        else:
            step.note(f"GET /admin/policies 不带凭据 -> {unauth.status_code}")
    return step


# --------------------------------------------------------------------------- #
# step 1 — define the policy
# --------------------------------------------------------------------------- #
def step_define(policy_dir: pathlib.Path) -> tuple[Step, dict | None, dict | None]:
    step = Step(
        1,
        "定义一个最简的策略",
        "cerbos-policy",
        "写 policies/hello.yaml 和 policies/_schemas/hello.json",
    )
    policy_file = policy_dir / "hello.yaml"
    schema_file = policy_dir / "_schemas" / "hello.json"

    if not policy_file.exists():
        step.fail(f"{policy_file} 不存在")
        return step, None, None

    policy = yaml.safe_load(policy_file.read_text(encoding="utf-8"))
    rules = policy.get("resourcePolicy", {}).get("rules", [])
    for rule in rules:
        step.note(
            f"规则 {rule.get('name')}: actions={rule.get('actions')} "
            f"roles={rule.get('roles')} effect={rule.get('effect')}"
        )

    schema = None
    if schema_file.exists():
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
        step.note(f"schema {schema_file.name}: properties={list(schema.get('properties', {}))}")
    else:
        step.fail(f"{schema_file} 不存在")

    # Write the request bodies the later steps send, so every call in this
    # walkthrough is copy-pasteable and nothing is hidden in the script.
    if policy is not None:
        (ROOT / "deploy-policy.json").write_text(
            json.dumps({"policies": [policy]}, indent=2), encoding="utf-8"
        )
        step.note(f"wrote {ROOT / 'deploy-policy.json'}")
    if schema is not None:
        (ROOT / "deploy-schema.json").write_text(
            json.dumps(
                {
                    "schemas": [
                        {
                            "id": "cerbos:///hello.json",
                            "definition": base64.b64encode(
                                json.dumps(schema).encode()
                            ).decode(),
                        }
                    ]
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        step.note(f"wrote {ROOT / 'deploy-schema.json'}")

    return step, policy, schema


# --------------------------------------------------------------------------- #
# step 2 — deploy
# --------------------------------------------------------------------------- #
def step_deploy(
    pdp: str, user: str, password: str, policy: dict, schema: dict | None, deploy: bool
) -> Step:
    step = Step(2, "部署", "cerbos-policy", "POST /admin/schema, POST /admin/policy")
    auth = (user, password)

    with httpx.Client(timeout=20.0) as client:
        if not deploy:
            # Read-only by default: writing to a PDP is a side effect on a
            # shared server, and it is not something a demo should do behind
            # the reader's back.
            listed = client.get(f"{pdp}/admin/policies", auth=auth)
            served = listed.json().get("policyIds") if listed.status_code == 200 else []
            step.note(
                f"GET /admin/policies -> {served}"
                f"   (只读探测,没有写入)"
            )
            probe = client.post(f"{pdp}/admin/policy", json={"policies": []}, auth=auth)
            if probe.status_code == 501:
                step.note(
                    f"POST /admin/policy (空数组探测) -> 501 "
                    f"{probe.json().get('message')}"
                )
                step.defer(
                    "这台 PDP 的 store 是只读的,部署归运维",
                    "store 不可变,部署通道是往策略目录提交文件",
                )
            else:
                step.note(
                    f"POST /admin/policy (空数组探测) -> {probe.status_code},"
                    f"store 可变 —— 加 --deploy 就会把 hello 策略推上去"
                )
                step.defer(
                    "没有写入。加 --deploy 会把 hello 策略推到这台 PDP 上",
                    "写入共享服务器要显式要求",
                )
            return step

        if schema is not None:
            body = {
                "schemas": [
                    {
                        "id": "cerbos:///hello.json",
                        "definition": base64.b64encode(
                            json.dumps(schema).encode()
                        ).decode(),
                    }
                ]
            }
            response = client.post(
                f"{pdp}/admin/schema", json=body, auth=auth
            )
            if response.status_code < 300:
                step.note(f"POST /admin/schema -> {response.status_code}")
            else:
                message = response.json().get("message", response.text)
                step.fail(
                    f"POST /admin/schema -> {response.status_code} {message}",
                    skipped="这台 PDP 不接受写入 schema",
                )

        body = {"policies": [policy]}
        response = client.post(f"{pdp}/admin/policy", json=body, auth=auth)
        if response.status_code < 300:
            step.note(f"POST /admin/policy -> {response.status_code},策略已存下")
        else:
            payload = response.json()
            message = payload.get("message", response.text)
            if "not mutable" in message:
                step.fail(
                    f"POST /admin/policy -> {response.status_code} {message}",
                    skipped=(
                        "这台 PDP 从目录读策略,部署归运维;"
                        "同样的调用在一台 store 可变的 PDP 上会成功"
                    ),
                )
            else:
                step.fail(f"POST /admin/policy -> {response.status_code} {message}")

        listed = client.get(f"{pdp}/admin/policies", auth=auth)
        if listed.status_code == 200:
            step.note(f"GET /admin/policies -> {listed.json().get('policyIds')}")
    return step


# --------------------------------------------------------------------------- #
# step 3 — ALLOW and DENY
# --------------------------------------------------------------------------- #
def step_check(
    pdp: str,
    kind: str,
    allow_role: str,
    deny_role: str,
    owner: str,
    other: str,
    attr: dict,
    deployed: bool,
) -> Step:
    step = Step(
        3,
        "问一次 ALLOW 和 DENY",
        "cerbos-pep-integration",
        "POST /api/check/resources",
    )

    if not deployed:
        step.note(
            f"note: 第 2 步的策略这台 PDP 并不在提供,所以 "
            f"'{allow_role}' 那一例在这里拿不到允许。下面同样两个调用"
            f"仍然完整地走了一遍决策 API。"
        )

    with CerbosClient(pdp, timeout_secs=10.0, tls_verify=False) as client:
        for label, principal_id, role in (
            ("ALLOW", owner, allow_role),
            ("DENY", other, deny_role),
        ):
            resource = Resource(
                id=f"greeting-{principal_id}",
                kind=kind,
                attr=dict(attr),
            )
            principal = Principal(id=principal_id, roles={role})
            body = {
                "requestId": f"quickstart-{label.lower()}",
                "includeMeta": True,
                "principal": {
                    "id": principal.id,
                    "roles": sorted(principal.roles),
                    "policyVersion": principal.policy_version,
                },
                "resources": [
                    {
                        "resource": {
                            "kind": resource.kind,
                            "id": resource.id,
                            "policyVersion": resource.policy_version,
                            "attr": dict(resource.attr),
                        },
                        "actions": ["read"],
                    }
                ],
            }
            (ROOT / f"check-{label.lower()}.json").write_text(
                json.dumps(body, indent=2), encoding="utf-8"
            )
            try:
                response = client.check_resources(
                    principal=principal,
                    resources=ResourceList().add(resource, {"read"}),
                )
            except Exception as error:  # noqa: BLE001
                step.fail(f"{label}: {error.__class__.__name__}: {error}")
                continue

            if response.status_msg is not None:
                step.fail(
                    f"{label}: PDP 拒绝了这个请求:{response.status_msg.message}"
                )
                continue

            result = response.get_resource(resource.id)
            if result is None:
                step.fail(f"{label}: PDP 没有返回结果")
                continue

            effect = result.actions.get("read")
            step.note(
                f"{label}: {principal_id} ({role}) read {kind} -> "
                f"{effect.value if effect is not None else 'no effect'}"
            )
    return step


# --------------------------------------------------------------------------- #
# step 4 — the audit trail
# --------------------------------------------------------------------------- #
def step_audit(pdp: str, user: str, password: str) -> Step:
    step = Step(
        4,
        "把审计轨迹读回来",
        "cerbos-audit-insights",
        "GET /admin/auditlog/list/KIND_DECISION",
    )
    with httpx.Client(timeout=20.0) as client:
        response = client.get(
            f"{pdp}/admin/auditlog/list/KIND_DECISION?tail=5", auth=(user, password)
        )
        if response.status_code == 200:
            # The endpoint answers application/x-ndjson: one entry per line,
            # each wrapped in a "result" envelope. A single response.json()
            # only works while exactly one entry comes back.
            entries = []
            for line in response.text.splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                entries.append(payload.get("result", payload))

            step.note(
                f"GET /admin/auditlog/list/KIND_DECISION -> 200 "
                f"({response.headers.get('content-type')}, {len(entries)} 条)"
            )
            if not entries:
                step.note("  还没有任何记录")
            for result in entries[-3:]:
                entry = result.get("decisionLogEntry") or {}
                step.note(f"  callId {entry.get('callId')} at {entry.get('timestamp')}")
                for output in (entry.get("checkResources") or {}).get("outputs") or []:
                    step.note(
                        f"    {output.get('resourceId')} "
                        f"{json.dumps(output.get('actions'), ensure_ascii=False)}"
                    )
                trail = entry.get("auditTrail") or {}
                step.note(f"    生效的策略:{list((trail.get('effectivePolicies') or {}))}")
        else:
            payload = response.json()
            message = (payload.get("error") or payload).get("message", response.text)
            if "does not support querying" in message:
                step.fail(
                    f"GET /admin/auditlog/list/KIND_DECISION -> {response.status_code} {message}",
                    skipped=(
                        "这台 PDP 把审计轨迹写进一个读不回来的后端;"
                        "同样的调用在 local 后端上是能回答的"
                    ),
                )
            else:
                step.fail(
                    f"GET /admin/auditlog/list/KIND_DECISION -> {response.status_code} {message}"
                )
    return step


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    use_utf8_output()
    parser = argparse.ArgumentParser(prog="quickstart.py")
    parser.add_argument("--pdp", default=DEFAULT_PDP, help="base URL of the PDP")
    parser.add_argument("--policy-dir", type=pathlib.Path, default=DEFAULT_POLICY_DIR)
    parser.add_argument("--user", default=os.environ.get("CERBOS_ADMIN_USER", "cerbos"))
    parser.add_argument("--password", default=os.environ.get("CERBOS_ADMIN_PASSWORD", "cerbosAdmin"))
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="真的把 hello 策略推到 PDP 上。默认只读探测 —— 往共享服务器写东西要显式要求",
    )
    parser.add_argument(
        "--demo-kind", default="hello", help="resource kind for the ALLOW/DENY demo"
    )
    parser.add_argument("--demo-allow-role", default="user")
    parser.add_argument("--demo-deny-role", default="guest")
    parser.add_argument("--demo-owner", default="alice")
    parser.add_argument("--demo-other", default="bob")
    parser.add_argument(
        "--demo-attr",
        default='{"name": "world"}',
        help="resource attributes for the ALLOW/DENY demo, as JSON",
    )
    args = parser.parse_args(argv)

    try:
        demo_attr = json.loads(args.demo_attr)
    except json.JSONDecodeError as error:
        print(f"--demo-attr is not valid JSON: {error}", file=sys.stderr)
        return 2

    bypass_proxy(args.pdp)

    print(f"Cerbos Hello World - {args.pdp}")
    print("每一步都是一次 HTTP API 调用;不用 cerbos CLI、不用 cerbosctl、不用 Docker")
    print()

    steps = [step_probe(args.pdp)]

    define, policy, schema = step_define(args.policy_dir)
    steps.append(define)

    deployed = False
    if policy is not None:
        deploy = step_deploy(
            args.pdp, args.user, args.password, policy, schema, args.deploy
        )
        deployed = deploy.ok and deploy.deferred is None
        steps.append(deploy)
        steps.append(
            step_check(
                args.pdp,
                args.demo_kind,
                args.demo_allow_role,
                args.demo_deny_role,
                args.demo_owner,
                args.demo_other,
                demo_attr,
                deployed,
            )
        )
    else:
        steps.append(
            step_deploy(args.pdp, args.user, args.password, {}, None, args.deploy)
        )

    steps.append(step_audit(args.pdp, args.user, args.password))

    for step in steps:
        print(step.render())
        print()

    failed = [s for s in steps if not s.ok]
    deferred = [s for s in steps if s.deferred]
    done = len(steps) - len(failed) - len(deferred)
    print(f"这台 PDP 上,{len(steps)} 个步骤:完成 {done},未执行 {len(deferred)},失败 {len(failed)}")
    for step in deferred:
        print(f"  第 {step.number} 步({step.title}):{step.deferred}")
    for step in failed:
        print(f"  第 {step.number} 步({step.title}):{step.skipped or '失败'}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
