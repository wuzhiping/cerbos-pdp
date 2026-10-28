# 通过 API 测试 Cerbos 策略

两个层次的测试，都通过 HTTP 针对运行中的 PDP 进行：

1. **`*_test.yaml` 测试套件**——声明式回归测试，针对 PDP 的决策 API 执行。所有结论都应沉淀在这里。
2. **决策记录**——某一次请求的审计轨迹条目，它展示的是 PDP *实际求值时*所看到的输入。意外的拒绝要靠它来解释。

经验法则：一旦条件的行为出乎意料，立刻去看决策记录，并按它展示的内容来修改策略。

没有 REPL，也没有本地编译器。PDP 就是求值器。

---

## 可用的工具

| 用途 | 调用 |
|---|---|
| 求值单个请求 | `POST /api/check/resources` |
| 查看是哪个策略做出了决策 | 同一次调用加上 `includeMeta: true`，然后读 `meta.actions.<action>.matchedPolicy` |
| 查看 PDP 编译出了什么 | `GET /admin/policies/inspect` |
| 查看所提供的策略 | `GET /admin/policy?id=<policyId>` |
| 查看 PDP 求值时看到的输入 | `GET /admin/auditlog/list/KIND_DECISION?lookup=<callId>` |

决策类端点不需要凭据；管理类端点使用 HTTP Basic。

---

## 复现一个 fixture

把 `testdata/*.yaml` 中的 principal 和 resource 复制到一个请求里：

```bash
curl -s -X POST -H 'Content-Type: application/json' --data-binary @request.json \
  http://<pdp>:3592/api/check/resources
```

```json
{
  "requestId": "debug",
  "includeMeta": true,
  "principal": { "id": "alice", "roles": ["user"], "policyVersion": "default" },
  "resources": [
    { "resource": { "kind": "document", "id": "d1", "policyVersion": "default",
                    "attr": { "owner": "alice" } },
      "actions": ["read"] }
  ]
}
```

响应会给出效果，以及产生该效果的策略：

```json
{
  "results": [{
    "resource": { "id": "d1", "kind": "document" },
    "actions": { "read": "EFFECT_DENY" },
    "meta": { "actions": { "read": { "matchedPolicy": "resource.document.vdefault" } } }
  }]
}
```

`matchedPolicy` 能区分两种在效果上看不出差别的失败：

* **策略匹配上了，但条件为 false**——规则存在，只是条件不成立；
* **完全没有策略匹配**——资源 kind、scope 或 version 与 PDP 所提供的任何策略都不匹配。

属于第二种情况时，`GET /admin/policies/inspect` 能显示 PDP 实际持有的内容：

```bash
curl -s -u "cerbos:cerbosAdmin" http://<pdp>:3592/admin/policies/inspect
```

---

## 决策记录

这是可用的最精确的调试工具，因为它记录的是 **PDP 实际求值时的那个请求**——PEP 真正发出去的内容，而不是你以为它发出去的内容。

每个响应都带有 `cerbosCallId`。在应用中把它记下来，然后：

```bash
curl -s -u "cerbos:cerbosAdmin" \
  'http://<pdp>:3592/admin/auditlog/list/KIND_DECISION?lookup=<callId>'
```

该条目包含 `checkResources.inputs`（求值时的 principal、resource 及其属性）和 `checkResources.outputs`（每个 action 的效果，以及放行它的那条策略）。把记录下来的属性和你本想发送的属性做对比：调用方根本没发某个属性，是意外拒绝最常见的单一原因。

响应的 `Content-Type` 是 `application/x-ndjson`——一行一条记录，每行外面套着一层 `result`，所以要逐行解析，别用一次性的 `response.json()`（超过一条记录就会抛错）。

审计轨迹只能通过 `GET /admin/auditlog/list/{kind}` 读取，而且需要 `local` 审计后端：`file` 和 `kafka` 后端只写入，不支持查询。如果该端点返回 `501 Audit log backend does not support querying`，说明这个 PDP 上的审计轨迹无法读取——参见 `cerbos-audit-insights`。

---

## 调试步骤

由外向内排查。当某个测试产生了意料之外的 DENY 时：

1. 把 fixture **复现**为发往 `POST /api/check/resources` 的一个请求。
2. **读取 `matchedPolicy`。** 没有策略匹配说明是 kind、scope 或 version 的问题，而不是条件的问题。
3. **检查 PDP 收到的属性**——即决策记录里 `checkResources.inputs` 中的 `principal` 和 `resource`，或者你自己发出去的 `attr`。确认条件触及的每个字段都存在，且类型符合预期。
4. **分别检查条件的各个分支。** 对于 `all.of` 条件，每次只改动一个分支、其余分支保持满足，各发一个请求，以定位是哪一个分支失败。
5. 用 `GET /admin/policies/inspect` **确认规则确实接上了**，它会显示编译后的 action、属性和实际生效的派生角色。

---

## 常见失败模式

### 派生角色悄悄地不匹配

症状：规则期望某个派生角色（如 `owner`），而请求被拒绝了。

查看编译后的视图：

```bash
curl -s -u "cerbos:cerbosAdmin" http://<pdp>:3592/admin/policies/inspect
```

该条目会列出 PDP 计算出的 `effectiveDerivedRoles`。如果某个角色缺失，说明它的 `parentRoles` 中不包含 principal 持有的任何角色。把 `parentRoles` 与 principal 的角色逐一对照。

### `has(P.attr.x)` 意外返回 false

`has()` 对完整路径很严格。如果 `P.attr.context` 本身不存在，`has(P.attr.context.case_id)` 就是 false。先构造父级——先发一个 `context` 存在但 `case_id` 不存在的请求，再发一个两者都存在的请求。

如果某个派生角色依赖 `P.attr.context.*`，测试用的 principal fixture 必须填上这个 context 字段，否则该派生角色会悄悄地永不生效。

### 基于时间的条件

`now()` 返回的是 Cerbos 运行时时钟。复现一个失败的时间条件时，要在测试套件里固定时钟，绝不要依赖系统挂钟：

```yaml
options:
  now: "2026-01-15T10:00:00Z"
```

注意 HTTP API 没有对应的开关——`requestContext` 只携带 annotations——因此依赖时间的用例只能在测试套件里固定，无法在实时请求中固定。

### `R.attr` 引用错误

在缺少 `attr.owner` 字段的 resource 上使用 `R.attr.owner` 会产生运行时错误。HTTP API 上没有严格求值开关，采用非严格求值，该错误被吞掉，条件被当作 false——规则悄悄不匹配，而在 DENY 规则上这意味着该动作被放行。

只用 API 时的防线是让这种情况不可能发生：每个 fixture 都带上其条件读取的每一个属性，并且测试套件断言响应中不含 `validationErrors`。在策略本身里保护可选属性，例如 `has(request.resource.attr.ownerId) && request.resource.attr.ownerId == request.principal.id`。

### `match.all` 与 `match.all.of` 的区别

`match.all` 后面直接跟列表是无效的，必须写成 `match.all.of: [...]`。`any` 和 `none` 同理。PDP 会在策略部署时把它报告为编译错误，在决策记录里报告为策略级错误。

---

## 测试套件与决策记录的分工

| 决策记录用于 | `*_test.yaml` 测试套件用于 |
|---|---|
| 排查某个条件为什么不匹配 | 永久的回归覆盖 |
| 查看 PDP 实际收到的属性 | ALLOW 和 DENY 断言 |
| 确认是哪个策略做出了决策 | 在 CI 中强制执行策略约定 |
| 一次性的“这个属性到底有没有传进来”检查 | 团队可见的行为文档 |

不要止步于决策记录。每个已确认的行为都要写进测试文件。

---

## 运行完整测试套件

把每个 `*_test.yaml` 中的每条断言都针对 PDP 跑一遍，然后审计覆盖率计划：

```bash
python3 <skill-dir>/scripts/coverage_audit_api.py --pdp http://<pdp>:3592 \
  --policies policies --plan coverage-plan.json
```

审计会执行计划中的每一行，逐字段比对 control 对，并检查每条授权路径的每个前置条件是否都有孤立的拒绝用例。

如果没有任何 `*_test.yaml` 文件，“0 assertions”是预期结果，不是错误。只有当你本应有测试运行时才需要排查。

---

## 测试失败时

1. 阅读失败信息：它会指出失败的测试用例、principal、resource 和 action。
2. 把确切的 principal 和 resource 复现成一个请求。
3. 读取 `matchedPolicy` 以及决策记录中的 `inputs`。
4. 修策略或修 fixture——改错的那一个。
5. 只做这一处修改，然后重跑测试套件。
