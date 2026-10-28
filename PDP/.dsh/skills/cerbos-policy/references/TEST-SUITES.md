# 测试套件文件（`*_test.yaml`）

声明式测试文件，作为校验的一部分，针对运行中的 PDP 决策 API 执行。若要交互式调试单个条件，见 [TESTING.md](TESTING.md)。

## 文件结构

测试文件必须以 `_test.yaml` 结尾。schema 是严格的——只允许有文档说明的字段（`additionalProperties: false`）。

每个测试文件都必须以测试套件的 language-server 头开始：

```yaml
# yaml-language-server: $schema=https://api.cerbos.dev/latest/cerbos/policy/v1/TestSuite.schema.json
```

```yaml
# yaml-language-server: $schema=https://api.cerbos.dev/latest/cerbos/policy/v1/TestSuite.schema.json
name: "DocumentPolicyTest"
description: "Tests for document resource policy"  # 可选

principals:
  owner_user:
    id: "user1"
    roles:
      - "user"
    attr:
      department: "engineering"
  other_user:
    id: "user2"
    roles:
      - "user"
    attr:
      department: "sales"

resources:
  owned_doc:
    kind: "document"
    id: "doc1"
    attr:
      owner: "user1"
      public: false

# 可选: auxData fixtures -- 只有当策略用到 request.auxData (例如 JWT claims) 时才需要.
# 如果你的策略不引用辅助数据, 整节都可以省略.
# 参见下方的 "AuxData fixtures" 一节了解 jwt / jwts 两种形式.

tests:
  - name: "Owner can edit their document"
    input:
      principals:
        - owner_user
      resources:
        - owned_doc
      actions:
        - edit
        - view
    expected:
      - principal: owner_user
        resource: owned_doc
        actions:
          edit: EFFECT_ALLOW
          view: EFFECT_ALLOW

  - name: "Non-owner cannot edit"
    input:
      principals:
        - other_user
      resources:
        - owned_doc
      actions:
        - edit
    expected:
      - principal: other_user
        resource: owned_doc
        actions:
          edit: EFFECT_DENY
```

## 严格的 schema —— 只允许这些字段

根级字段（仅这些）：

- `name`（必填）、`description`、`options`、`skip`、`skipReason`
- `principals`、`principalGroups`、`resources`、`resourceGroups`、`auxData`
- `tests`（必填）

`tests` 中的每个测试用例（仅这些）：

- `name`（必填）：字符串
- `input`（必填）：对象
- `expected`（必填）：数组
- `description`、`options`、`skip`、`skipReason`：可选

`input` 对象（仅这些）：

- `actions`（必填）：字符串数组
- `principals`：fixture 键的字符串数组
- `resources`：fixture 键的字符串数组
- `principalGroups`、`resourceGroups`：数组（可选）
- `auxData`：指向 fixture 键的 STRING 引用（不是对象）

`expected` 数组元素（仅这些）：

- `actions`（必填）：对象，把动作名映射到 `"EFFECT_ALLOW"` 或 `"EFFECT_DENY"`
- `principal`：字符串（fixture 键）
- `resource`：字符串（fixture 键）
- `principals`、`resources`、`principalGroups`、`resourceGroups`：数组（单数形式的替代）
- `outputs`：数组（可选，用于输出断言）

上面的每个列表都是穷尽的：schema 设置了 `additionalProperties: false`，因此任何不在列表里的字段都会导致校验失败。断言描述的是请求的预期*效果*——策略自己的词汇（条件、角色、规则）在测试文件里没有位置。

## `options` 块

在套件根级和每个测试用例上都有效；测试用例的块会覆盖套件的块。允许的键（仅这些）：

| 键 | 类型 | 用途 |
|---|---|---|
| `now` | RFC3339 时间戳字符串 | 固定 `now()` 的返回值。任何与时间相关的规则都要用它——绝不要依赖墙上时钟 |
| `strictEvaluation` | boolean | 把运行时 CEL 错误当作终止性错误，拒绝受影响的操作（v0.55+） |
| `defaultPolicyVersion` | string | 未设置策略版本的 fixture 所用的策略版本 |
| `defaultScope` | string | 未设置 scope 的 fixture 所用的 scope |
| `lenientScopeSearch` | boolean | 当精确 scope 没有对应策略时，回退到祖先 scope |
| `globals` | object | 绑定到表达式中 `globals.*` 的值 |

```yaml
options:
  now: "2026-01-15T10:00:00Z"
  strictEvaluation: true
  globals:
    tenant_tier: "enterprise"
```

固定 `now` 是测试基于时间的条件的正确做法——见 [TESTING.md](TESTING.md)。

`strictEvaluation` 只作用于测试运行器：HTTP 决策 API 没有严格求值开关（`requestContext` 只携带 `annotations`），所以在 API 上运行时 CEL 错误求值为 false，而不是终止性地拒绝。

## AuxData fixtures

两种互斥的形式。单个 token 用 `jwt`，claims 直接内联；多个具名 token 用 `jwts`，必须带一层 `claims`（v0.55+）。

```yaml
auxData:
  # 单个 JWT -> request.auxData.jwt.dept
  valid_jwt:
    jwt:
      iss: my.domain
      aud: ["x", "y"]
      dept: engineering

  # 具名 JWT -> request.auxData.jwts.primary.claims.dept
  multi_token:
    jwts:
      primary:
        claims:
          iss: my.domain
          dept: engineering
      delegated:
        claims:
          act: service-account
```

在测试中用 `input.auxData: valid_jwt` 引用一个 fixture——一个 STRING 键，绝不是内联对象。

## Output Assertions

当规则带有 `output` 块时，在 `expected[].outputs` 下对它做断言：

```yaml
expected:
  - principal: owner_user
    resource: owned_doc
    actions:
      view: EFFECT_ALLOW
    outputs:
      - action: view
        expected:
          - src: resource.document.vdefault#view-rule
            val:
              key1: value1
```

`expected` 下的每个条目接受 `src`、`val`、`error` 和 `action`。从 v0.54 起，运行时失败的输出表达式会在响应里报告它的 `error`，测试失败信息会显示真正的求值错误——所以出现不匹配时，你能分辨出是表达式出错了，还是仅仅算出了错误的值。`output` 块里表达式为空是编译错误。

## 共享 fixtures

fixtures 有两个来源，一个套件可以用其中之一，也可以两个都用：

- **内联**：套件自己的 `principals`、`resources` 和 `auxData` 映射。自包含的套件把一切都内联定义，不需要 `testdata/` 目录。
- **共享文件**：与测试文件同目录下的 `testdata/principals.yaml`、`testdata/resources.yaml` 和 `testdata/auxdata.yaml`（`.yml` 或 `.json` 也可以）。该目录下的每个 `*_test.yaml` 都共用它们。只用共享 fixtures 的套件要完全省略内联的 `principals` 和 `resources` 键。

每个 `testdata/` 目录下每种文件只有一个，所以要把该目录下各套件需要的内容都合并进去。某个键在两处都存在时，对该套件而言以内联定义为准。需求要求用某一种写法时，就严格照做：不要在一个本该自包含的套件旁边再建 `testdata/` 目录。

在 `input` 中列出、却在 `expected` 中缺席的 principal/资源组合，预期对每个动作都是 DENY；已列出的组合里没写出的动作也默认是 DENY。尽管如此，还是把 DENY 的预期明确写出来，这样意图才读得明白。

### Scoped fixtures

把 `scope` 放在资源 fixture 上（`scope: emea.de`），或者为套件或测试设置 `options.defaultScope`。测试的 `options` 是替换套件的 `options`，而不是与之合并，所以仍然需要的其他套件选项都要重复写出来。

## 独立 fixture 文件格式

独立 fixture 文件必须同时有顶层键和对应的 language-server 头：

- principal fixture：`$schema=https://api.cerbos.dev/latest/cerbos/policy/v1/TestFixture/Principals.schema.json`
- 资源 fixture：`$schema=https://api.cerbos.dev/latest/cerbos/policy/v1/TestFixture/Resources.schema.json`
- auxData fixture：`$schema=https://api.cerbos.dev/latest/cerbos/policy/v1/TestFixture/AuxData.schema.json`

```yaml
# testdata/principals.yaml
# yaml-language-server: $schema=https://api.cerbos.dev/latest/cerbos/policy/v1/TestFixture/Principals.schema.json
principals:
  owner_user:
    id: "user1"
    roles:
      - "user"
    attr:
      department: "engineering"
```

```yaml
# testdata/resources.yaml
# yaml-language-server: $schema=https://api.cerbos.dev/latest/cerbos/policy/v1/TestFixture/Resources.schema.json
resources:
  owned_doc:
    kind: "document"
    id: "doc1"
    attr:
      owner: "user1"
      public: false
```

## Coverage Plan

写测试之前，把计划保存到策略目录**外面**，命名为 `coverage-plan.json`。它是[覆盖审计](#coverage-audit)的输入，所以要按那个脚本的 JSON 格式来写。

先写 `paths`：每条**放行路径**一条记录，也就是一个允许某种资源上动作的规则、角色或派生角色。列出该路径条件里的每一个前提，包括父角色。被多条路径共用的前提——比如两个派生角色里的租户检查——要出现在每条路径中；每个使用它的资源种类都要有自己的路径。

然后为每条计划中的断言写一行，以测试将使用的 fixture 键为索引。每条隔离某个前提的拒绝都要写出它的 `path` 和 `prerequisite`；任何一条路径列出的任何前提缺少这样一行，审计就会失败。

```json
{
  "paths": [
    {"id": "document-owner", "kind": "document", "requires": ["parent-role", "tenant", "ownership"]},
    {"id": "document-reviewer", "kind": "document", "requires": ["parent-role", "tenant", "department"]}
  ],
  "rows": [
    {"id": "document-owner-edit", "principal": "alice_employee", "resource": "document_owned_by_alice",
     "action": "edit", "effect": "EFFECT_ALLOW"},
    {"id": "document-missing-parent-role-edit", "principal": "alice_reviewer_only", "resource": "document_owned_by_alice",
     "action": "edit", "effect": "EFFECT_DENY", "control": "document-owner-edit", "change": "principal.roles",
     "path": "document-owner", "prerequisite": "parent-role"}
  ]
}
```

`principal` 和 `resource` 是 fixture 键。这里的 `alice_reviewer_only` 保留 ID `alice`，只换掉角色。`control` 指向效果相反的那一行，`change` 指向与它不同的那一个字段。

当需求点明了某个限定条件，比如“即使对已归档的项目”或“数量等于上限”，就把它记进该行的 `facts`（例如 `{"resource.attr.archived": true}` 或 `{"resource.scope": "emea"}`；属性不存在时用 `null`）。这样审计检查的是解析后的 fixture，而不是相信它的名字。

`change` 和 `facts` 的字段路径只能是 `principal.id`、`principal.roles`、`principal.attr.<name>`、`principal.scope`、`principal.policyVersion`、`resource.kind`、`resource.attr.<name>`、`resource.scope` 和 `resource.policyVersion`；审计会拒绝其他名字。可选的 `suite`（相对于策略目录的测试文件）或 `test`（测试用例名）用来缩小匹配范围。

每个资源策略都要单独规划行，包括导入了相同派生角色或变量的那些策略。规格用到这些分支时都要覆盖：

- 每条放行路径配一个允许请求，并为无关的角色/动作配一个拒绝。
- 每个独立的授权前提：基础角色、租户、所有权、部门、状态或其他属性条件。
- 精确的阈值以及阈值两侧的值；缺失的可选属性及其显式取值；能把决策从默认值改掉的覆盖值。
- 互相重叠的角色和备选放行路径，按已确认的角色合并语义来测。

**隔离拒绝。** 每条针对某个授权前提的拒绝都要配一个 `control`：同一资源种类、同一动作的一条生效的 ALLOW 行。复制那个允许请求，只改动被测的那一个前提。一个允许用例可以充当多个反向用例的 control。例如，如果编辑要求基础角色、所有权和匹配的租户：

| 用例 | 基础角色 | 所有者等于 principal ID | 租户匹配 | 效果 | `change` |
| --- | --- | --- | --- | --- | --- |
| 允许（control） | 有 | 是 | 是 | ALLOW | — |
| 缺少父角色 | 无；只有无关角色 | 是 | 是 | DENY | `principal.roles` |
| 所有者不同 | 有 | 否 | 是 | DENY | `resource.attr.owner` |
| 租户不同 | 有 | 是 | 否 | DENY | `resource.attr.tenant` 或 `principal.attr.tenant` |

**fixture 键必须唯一；principal ID 不必。** 除非策略会读 `P.id`（或者存在 principal 策略），否则审计会忽略某一行与其 control 之间的 principal ID 差异；不过保留同一个 ID 仍然是“只让被测字段不同”最简单的办法。多个 principal fixture 可以共用一个 `id`。owner 为 `alice` 的“缺少父角色”变体是一个新的键，比如 `alice_reviewer_only`，它的 `id: alice` 但角色不同，这样资源的 `owner` 仍然匹配。给这个变体换一个新 ID 会同时破坏所有权，于是测试就看不出到底是哪个前提导致了拒绝。同理，“限额覆盖”的 principal 保留默认 principal 的 ID，只在覆盖属性上不同。

隔离拒绝时让其他放行路径保持不生效，然后单独测试角色组合。一个同时改了所有者的租户测试无法确定是哪个边界导致了拒绝。同样的原则适用于被封禁的资源、被停用的 principal 或金额上限：满足其他前提，让预期中的那个条件来决定结果。

**默认值和覆盖值必须能翻转决策。** 把可选属性或覆盖值与一条效果相反的 control 配对。对于一个取代默认值 250 的 principal 限额，要测两个限额之间的金额：限额 150 时 200 是 DENY，而默认 principal 得到 ALLOW；限额 500 时 400 是 ALLOW，而默认 principal 得到 DENY。落在两个限额之内的金额什么都证明不了。每个自带默认值的资源都要这样做。

对于派生角色，要测：用无关的基础角色配上匹配的属性；要求的父角色配一个失败的关系；把派生角色名当作 principal 角色提供。每个角色都要先有一个有效的正向用例，再依赖它的反向用例。

**schema 拒绝需要策略本会允许的请求。** 如果请求说明 principals 或 resources 没有属性，就让每个 fixture 的 `attr` 保持为空，也不要为它们添加 schema 拒绝用的 fixture。PDP 配了 `schema.enforcement: reject` 时才会强制 schema，所以只有当同一请求在属性合法时是 ALLOW，schema 拒绝才说明得了问题。用一行 ALLOW 当 control，然后在它的 fixture 里破坏一个属性：删掉一个必填属性、给某个属性一个非法值、加一个未声明的属性，或让某个 principal 属性非法。每个 fixture 只用一个违例，并且破坏放行规则不读取的那个属性。把非法的 principal 与完整合法的资源配对——即使是 `create` 也要这样——这样唯一的违例就落在 principal 身上。如果规则检查 `owner` 或 `status`，那里的缺失或非法值本来就会被策略拒绝，因此证明不了 schema 在起作用；改为在不比较 `amount` 的请求上破坏 `amount`。当一个 fixture 的名字声称了某种属性（比如“archived”）时，要检查它的属性确实带着这个属性。对于 `ignoreWhen`，在一个不完整的资源上，单独为被忽略的动作加一条检查，期望 ALLOW。见 [POLICIES.md](POLICIES.md#schema-enforcement)。

**scope 专属的规则需要符合条件的请求。** 要证明某个 scope 的放行不适用于别处，就复用那个在放行 scope 里被允许的请求，只改资源的 `scope`。要证明某个限制只作用于它自己的 scope，就复用它会拒绝的那个请求（例如一个分析师导出原始数据集），只改 `scope`，期望 ALLOW。一个本来也会被这个限制允许的请求什么都证明不了。例如，一个读取标记为可共享数据集的 `apac` 审计员，在基础 scope 或 `emea` 里变成同一个请求，期望 DENY。每个限制都要在引入它的 scope 里测一遍，并在继承它的每个后代 scope 里测一遍。在每个 scope 里测继承来的基础权限，并测一个带多个角色、其中单个角色会被拒绝的 principal。

在计划里，scope 边界是一对只在 `scope` 上不同的行。如果 `emea` 只允许分析师导出脱敏数据集，就把 `emea` 下原始数据集的那条 DENY 与同一请求的不带 scope 版本配成一对（在只有 `emea` 一个分支的层级里；有其他分支时见下文）：

```json
{"id": "emea-analyst-raw-export", "principal": "analyst", "resource": "emea_raw_dataset", "action": "export",
 "effect": "EFFECT_DENY", "facts": {"resource.scope": "emea", "resource.attr.anonymised": false}},
{"id": "base-analyst-raw-export", "principal": "analyst", "resource": "base_raw_dataset", "action": "export",
 "effect": "EFFECT_ALLOW", "control": "emea-analyst-raw-export", "change": "resource.scope",
 "facts": {"resource.scope": null}}
```

审计要求：每一个被 scoped 资源策略规则点名的角色（`*` 则指任意角色）以及每一个 scoped 角色策略，都要有这样一对行——在引入该规则的 scope 里，以及在每个拥有自己策略的后代 scope 里，因为该规则同样管着那些地方。当层级还有其他顶层分支时，这一对的另一侧必须是其中某个分支里的 scope，而不是不带 scope 的基础 scope，这样同一行才能显示规则不会跨分支泄漏：同时有 `emea` 和 `apac` 策略时，把 `emea` 的导出 DENY 与同一请求在 `apac` 里的那一行配成一对。一行可以同时满足几项要求，比如为 `*` 规则准备的 `apac` 行。一个只是重述父级的 scoped 规则无法产生这样一对；把它列进计划顶层的 `scopeExemptions`，写成 `{"scope": "emea", "role": "analyst", "reason": "..."}`，或者删掉这条冗余规则。

对于显式的 DENY 规则，从一个别的规则会允许的请求开始，然后触发那个拒绝条件。这能证明该拒绝确实压过了一次真实放行。跑一遍严格模式，把那些本来会让拒绝静默失效的条件错误暴露出来（[CEL.md](CEL.md#strict-evaluation-v055)）。与时间相关的用例要固定 `options.now`。

## Coverage Audit

写完或修好 bundle 后，运行自带的审计脚本。它只需要 Python 3 标准库和 PyYAML，并且通过 HTTP 与一台运行中的 PDP 对话——不需要 cerbos 二进制，不需要 cerbosctl，不需要 Docker。

```bash
python3 <skill-dir>/scripts/coverage_audit_api.py --pdp http://<pdp>:3592 \
  --policies policies --plan coverage-plan.json
```

脚本会解析计划里的 fixture 键，针对 PDP 执行计划中的每一行，并套用下面这些规则。覆盖不通过时它以 1 退出；读不了输入时以 2 退出，比如在没装 PyYAML 的机器上碰到带锚点、别名或标签的 fixture YAML。当它以 2 退出，或者 `python3` 不可用时，就自己根据计划、套件和 fixture 文件完成同样的检查，把每一行的结果和每一对 control 的前后值记在计划旁边，并在最终报告里说明可执行的审计没有运行。

审计看不到编译期错误，因为 API 在只读存储上从不编译候选策略。这项检查属于部署步骤：PDP 存储 bundle 时，`POST /admin/policy` 会报告编译错误。

对每一行，审计会做以下事情：

1. 要求有一条已执行且通过的断言，principal、资源、动作和效果都与计划一致。缺失或被跳过的用例算失败；只看通过的总数是不够的。
2. 通过套件的 `testdata/` 文件和内联的套件 fixtures，把 fixture 键解析成真实的 ID、角色和属性。fixture 名字只是标签。
3. 对于带 `control` 的行，要求 control 的效果相反、动作相同，并且解析后的两个请求恰好只在 `change` 字段上不同（忽略 `resource.id`）。它会打印该字段的前后值。
4. 对每条声明路径的每一个前提，要求有一行通过的断言，带上该 `path`、该 `prerequisite`，并且 control 用的是该路径种类的资源。
5. 当 bundle 里有按角色区分的 scoped 规则或 scoped 角色策略时，要求有一行通过的 ALLOW，其 principal 带两个或更多角色，而它的 control 只带这些角色的一个子集（`change: principal.roles`）且结果为 DENY，以此说明角色是合并生效的——除非计划设置了 `roleUnionExemption: {"reason": "..."}`。
6. 对每一个被 scoped 资源策略规则或 scoped 角色策略点名的角色，在该 scope 以及每个拥有自己策略的后代 scope 里，要求有一行通过的断言，带 `change: resource.scope`，其 principal 带该角色，一侧是那个 scope，另一侧是另一个顶层分支里的 scope（没有其他分支时用不带 scope 的基础 scope），除非 `scopeExemptions` 列出了它。

每项需求都需要在每个使用它的资源里各有一行；只测一个使用者，并不能证明共享变量或派生角色的另一个使用者被覆盖。不要为了让审计通过而弱化计划：某一行失败时，去修 fixture 或测试。把计划和审计输出一起保存。反复运行校验和审计，直到两者都以 0 退出。决策结果说明提交的断言成立；审计说明它们覆盖了要求的行为。

## 常见测试失败

| 症状 | 原因 | 修复 |
|---|---|---|
| `additional property not allowed` | 测试或 fixture 里多了字段 | 删掉该字段——schema 是严格的 |
| 期望 ALLOW，实际 DENY | 派生角色没匹配上，或 fixture 缺某个属性 | 在 REPL 里复现（[TESTING.md](TESTING.md)） |
| 期望 ALLOW，实际某个 fixture 的每个动作都是 DENY | fixture 的属性不满足策略的 schema（测试以 reject 模式强制 schema），或者 `create` 与一个受校验的动作共用同一项检查 | 修 fixture，或在不完整的资源上单独测 `create` |
| 编译报错说缺少某个 scope 策略 | 某个 scoped 策略缺了一个祖先（`emea.de` 缺 `emea`，或缺基础策略） | 把链上每个祖先策略都补齐 |
| 期望 DENY，实际 ALLOW | 有重复的无条件规则、通配符动作授权，或者某个 DENY 条件在运行时出错 | 搜索冲突规则；用 `--strict-evaluation` 重跑 |
| 平时通过，在 `--strict-evaluation` 下失败 | 条件在运行时出错并静默求值为 false | 修表达式，或补上缺失的 fixture 属性 |
| 输出断言失败并带一个 `error` 值 | 输出表达式本身出错了，而不是返回了错误的值 | 修输出表达式，而不是期望的 `val` |
| 测试结果 ERRORED：条件基于时间，但没有提供 `now` | 规则走到了 `now()`，而测试没有 `options.now` | 给每个可能走到该规则的测试都设置 `options.now`，包括该 principal 的其他动作的测试 |
| "0 tests executed" | 没有 `*_test.yaml` 文件 | 预期如此——除非你本来就以为会有测试 |
