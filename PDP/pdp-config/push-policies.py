"""把策略目录推送到 PDP 的 Admin API —— 存储驱动换成 sqlite3 之后的迁移步骤。

    python3 pdp-config/push-policies.py --pdp http://10.17.1.201:3592 \
        --policies config/policies

为什么要它:换成 `sqlite3` 之后,策略住在数据库里,磁盘目录里的文件**不会**
自动进数据库。切驱动之后不推送策略,PDP 的策略集是空的,每个决策都会变成
DENY——从"全部允许"变成"全部拒绝",而且没有任何报错。

顺序很重要:
    1. 先推 schema(`POST /admin/schema`)
    2. 再推 policy(`POST /admin/policy`)
    3. 最后用 `GET /admin/policies` 核对清单

schema 的 id 是**相对于 `_schemas/` 的路径**,不带 `cerbos:///` 前缀:
`_schemas/principal.json` -> `principal.json`,`_schemas/resources/foo.json` ->
`resources/foo.json`。

    这个前缀是个坑,踩过一次。**store 里存的是相对路径**,策略里
    `schemas.principalSchema.ref` 写的是带前缀的 `cerbos:///principal.json`。
    PDP 编译 schema 时会把 ref 的前缀去掉、再拿相对路径去 store 里找。
    如果把 `cerbos:///principal.json` 当 id 推上去,`GET /admin/schemas` 会
    照原样把它列出来(看着像成功了),但编译时永远找不到,每一个请求都会
    带着 `Failed to load ... schema` 变成拒绝。而且**这种行读不回来**——
    `GET /admin/schema?id=...` 各种前缀组合都返回 500。

    在 `schema.enforcement: none`(默认)下这件事完全看不出来,因为 PDP
    根本不编译 schema。改成 `reject` 之后,每一个请求都直接失败。

只依赖标准库 + PyYAML。认证用 HTTP Basic,默认 cerbos / cerbosAdmin。
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


def use_utf8_output() -> None:
    """让 stdout/stderr 变成 UTF-8,不管控制台 locale 说什么。

    中文 Windows 的首选编码是 cp936(GBK),Python 会把中文输出写成 GBK 字节,
    UTF-8 终端读出来全是乱码。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def bypass_proxy(url: str) -> None:
    """把 PDP 主机排除在代理之外。

    Windows 上 `urllib.request.getproxies()` 和 httpx 都会读注册表里的代理,
    而内网 PDP 通常走不通那个代理。PDP 主机加入 NO_PROXY,别的照旧走代理。
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


def collect_schemas(policies_dir: pathlib.Path) -> list[dict]:
    """`_schemas/` 下的每个 .json 变成一条 schema 记录。"""
    schemas_dir = policies_dir / "_schemas"
    if not schemas_dir.is_dir():
        return []

    records = []
    for path in sorted(schemas_dir.rglob("*.json")):
        relative = path.relative_to(schemas_dir).as_posix()
        definition = base64.b64encode(path.read_bytes()).decode()
        # The id is the path relative to _schemas/ -- no `cerbos:///` prefix.
        # The store holds relative paths; the policy's ref carries the prefix,
        # and the PDP strips it before looking the schema up. Pushing the
        # prefixed form stores a row nothing can ever read.
        records.append({"id": relative, "definition": definition})
    return records


POLICY_KINDS = ("resourcePolicy", "rolePolicy", "principalPolicy", "derivedRoles")


def collect_policies(policies_dir: pathlib.Path) -> list[dict]:
    """策略目录里的每个 .yaml 变成一条 policy 记录。

    跳过的:
      * `*_test.yaml` —— 测试套件,不是策略
      * `testdata/` 下的文件 —— fixture,不是策略
      * 顶层键不像策略的 YAML —— 按内容判断,不靠文件名
    """
    policies = []
    for path in sorted(policies_dir.rglob("*.yaml")):
        if path.name.endswith("_test.yaml"):
            continue
        if "_schemas" in path.parts:
            continue
        if "testdata" in path.parts:
            continue
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        # 按内容判断:策略一定带 apiVersion,外加一种策略类型。
        if "apiVersion" not in document:
            continue
        if not any(kind in document for kind in POLICY_KINDS):
            continue
        policies.append(document)
    return policies


def main(argv: list[str] | None = None) -> int:
    use_utf8_output()

    parser = argparse.ArgumentParser(prog="push-policies.py")
    parser.add_argument("--pdp", default=os.environ.get("CERBOS_PDP_URL", "http://10.17.1.201:3592"))
    parser.add_argument(
        "--policies",
        type=pathlib.Path,
        default=pathlib.Path("config/policies"),
        help="策略目录,里面应有 _schemas/ 和各个 *.yaml",
    )
    parser.add_argument("--user", default=os.environ.get("CERBOS_ADMIN_USER", "cerbos"))
    parser.add_argument("--password", default=os.environ.get("CERBOS_ADMIN_PASSWORD", "cerbosAdmin"))
    parser.add_argument("--dry-run", action="store_true", help="只列出会推什么,不真的发")
    parser.add_argument(
        "--no-schemas",
        action="store_true",
        help="只推策略,不推 schema。属性校验由 schema 决定,单独推可以先恢复服务再开校验",
    )
    args = parser.parse_args(argv)

    bypass_proxy(args.pdp)

    if not args.policies.is_dir():
        print(f"策略目录不存在:{args.policies}", file=sys.stderr)
        return 2

    schemas = collect_schemas(args.policies)
    policies = collect_policies(args.policies)
    if args.no_schemas:
        schemas = []

    print(f"策略目录:{args.policies}")
    print(f"  schema : {len(schemas)} 条")
    for record in schemas:
        print(f"           {record['id']}")
    print(f"  policy : {len(policies)} 条")
    for document in policies:
        kind = next((k for k in POLICY_KINDS if k in document), "?")
        body = document.get(kind, {})
        name = (
            body.get("resource")
            or body.get("role")
            or ",".join(body.get("roles", []))
            or "?"
        )
        print(f"           {kind:<16} {name}")

    if not policies:
        print("\n没有找到任何策略。迁移前先确认目录里确实有 *.yaml。", file=sys.stderr)
        return 2

    if args.dry_run:
        print("\n--dry-run,什么都没发。")
        return 0

    auth = (args.user, args.password)
    with httpx.Client(timeout=30.0) as client:
        if schemas:
            response = client.post(
                f"{args.pdp}/admin/schema", json={"schemas": schemas}, auth=auth
            )
            if response.status_code >= 300:
                print(f"\nPOST /admin/schema -> {response.status_code} {response.text}", file=sys.stderr)
                return 1
            print(f"\nPOST /admin/schema -> {response.status_code}")

        response = client.post(
            f"{args.pdp}/admin/policy", json={"policies": policies}, auth=auth
        )
        if response.status_code >= 300:
            print(f"\nPOST /admin/policy -> {response.status_code} {response.text}", file=sys.stderr)
            return 1
        print(f"POST /admin/policy -> {response.status_code}")

        listed = client.get(f"{args.pdp}/admin/policies", auth=auth)
        if listed.status_code == 200:
            print(f"GET  /admin/policies -> {listed.json().get('policyIds')}")
        served = client.get(f"{args.pdp}/admin/schemas", auth=auth)
        if served.status_code == 200:
            print(f"GET  /admin/schemas  -> {served.json().get('schemaIds')}")

    print("\n推送完成。用 POST /api/check/resources 发一个请求,确认策略真的生效了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
