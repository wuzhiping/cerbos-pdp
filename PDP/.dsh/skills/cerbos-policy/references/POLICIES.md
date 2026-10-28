# Cerbos 策略类型

每个 Cerbos 策略都是 YAML，开头带 `apiVersion: api.cerbos.dev/v1`，并且顶层只有一个策略对象。

## 必需的 YAML 语言服务器头部

每个策略文件都必须以 Cerbos 策略的 schema 注释开头，这样支持 LSP 的编辑器才能提供校验和自动补全：

```yaml
# yaml-language-server: $schema=https://api.cerbos.dev/latest/cerbos/policy/v1/Policy.schema.json
```

这适用于所有策略文件：资源策略、派生角色、导出变量、角色策略和 principal 策略。测试套件和 fixture 用的是另一套 schema——见 [TEST-SUITES.md](TEST-SUITES.md)。

## 资源策略（最常见）

```yaml
# yaml-language-server: $schema=https://api.cerbos.dev/latest/cerbos/policy/v1/Policy.schema.json
apiVersion: api.cerbos.dev/v1
resourcePolicy:
  version: "default"
  resource: "document"
  schemas:
    principalSchema:
      ref: "cerbos:///principal.json"
    resourceSchema:
      ref: "cerbos:///resources/document.json"
  importDerivedRoles:
    - document_roles
  rules:
    - actions: ["view"]
      effect: EFFECT_ALLOW
      derivedRoles: ["owner"]
```

### 跨角色的拒绝优先级

规则顺序无关紧要。principal 的每个角色各自单独求值，对某个角色而言，匹配的 DENY 压过匹配的 ALLOW，而任意一个角色给出的 ALLOW 都会授予这个动作。所以：

- 带 `roles: [contractor]` 的 DENY 挡不住既是员工又是 contractor 的人拿到员工的 ALLOW。
- 要否决所有持有某个角色的人（不管他还持有什么别的角色）的某个动作，就用 `roles: ["*"]`，并把角色写进条件：`"contractor" in P.roles && ...`。
- 要让某些东西压过这个否决（例如 admin，或者有序来源里的靠前分支，比如 Rego 的 `else` 链或防火墙列表），就在 DENY 的条件里把它排除掉：`... && !("admin" in P.roles)`。单独的 ALLOW 规则永远压不过匹配的 DENY。

要测重叠情况：让一个 principal 同时持有被否决的角色和应当胜出的角色。

### 动作通配符

`actions` 或 `allowActions` 里的动作是一个 glob。`*` 匹配除 `:` 以外的任意字符序列，所以冒号是分段分隔符，而不是必须出现的部分：

| 模式 | 匹配 | 不匹配 |
|---|---|---|
| `*` | 任意动作 | — |
| `delete_*` | `delete_ticket` | — |
| `view:*` | `view:public` | `view:public:draft`、`view` |
| `b*` | `bx` | `b:x` |

再多匹配一段就再加一个 `:*`（`view:*:*`）。动作集合不大时，一个名字写一条；通配符会把后来新增的动作悄悄带进来。

始终要写 `schemas` 字段：

- `principalSchema.ref`：`cerbos:///principal.json`
- `resourceSchema.ref`：`cerbos:///resources/{resource_name}.json`（必须与资源名一致）

这些 JSON schema 校验的是 `P.attr` 和 `R.attr`。把属性定义放在 schema 根上。例如，`P.attr: {tenant: "northwind"}` 由 `{"type": "object", "properties": {"tenant": {"type": "string"}}, "required": ["tenant"]}` 校验。请求信封字段（`id`、`roles`、`kind`、`attr`）属于 API 请求，不在属性 schema 里。见[属性 schema](https://docs.cerbos.dev/cerbos/latest/policies/schemas.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-schemas-html)。

### Schema enforcement

Schema 使用 JSON Schema draft 2020-12。强制执行是 PDP 的配置，不是策略内容，三个取值：`none`（**默认**，完全不校验）、`warn`（校验但只记警告）、`reject`（校验不过就拒绝这次检查里的**所有**动作）。

`reject` 模式下，响应是 **200**，动作被置为 DENY，`validationErrors` 出现在 **`results[]` 那一层**（和 `actions`、`meta` 并列），不是响应的顶层。**SDK 会把它丢掉**——Python SDK 的响应模型里没有 `validation_errors` 字段——所以要看到这些错误得读原始 HTTP 响应。

默认的 `none` 意味着属性不合 schema 也照样求值，响应里不会有 `validationErrors`。那也意味着 PDP 根本不编译 schema——策略引用了一个不存在的 schema 也没有任何症状，直到开启 `reject` 才会全面崩塌。部署 schema 的 id 要用**相对路径**，详见 [API-VALIDATION.md](API-VALIDATION.md)。所以「属性无效的 fixture 即使有规则授予也会被拒绝」这句话只在 PDP 配了 `reject` 时成立：只走 API 的流程里，强制级别取决于 PDP 的配置，不取决于测试运行器。fixture 仍然必须满足它声明的 schema，否则测的就不是策略想表达的东西。

- 当需求禁止未声明的属性时，设置 `"additionalProperties": false`；JSON Schema 默认允许它们。
- 整数用 `"type": "integer"`；`number` 接受 `2.5`。
- `resourceSchema.ignoreWhen.actions` 会跳过资源校验，通常用于 `create`，因为新记录的属性还不完整。它只在这次检查里的**每一个**动作都被列出时才生效：只检查 `create` 的不完整资源可以被放行，但同一资源上 `create` 加 `view` 就会被校验并拒绝。除非 `principalSchema` 自己有 `ignoreWhen`，否则 principal 的属性总是会被校验。
- 在 scope 链里，该资源的每份策略都必须声明相同的 schema。

## 规则输出

规则的 `output` 块会在 CheckResources 响应里返回值，比如审计事件或拒绝原因。资源策略、principal 策略和角色策略的规则都支持它。见[输出](https://docs.cerbos.dev/cerbos/latest/policies/outputs.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-outputs-html)。

```yaml
    - name: publish-reviewed-articles
      actions: [publish]
      roles: [editor]
      effect: EFFECT_ALLOW
      condition:
        match:
          expr: R.attr.review_status == "approved"
      output:
        when:
          # 规则匹配了角色和动作, 且条件为真.
          ruleActivated: '{"event": "article_published", "article": R.id, "editor": P.id}'
          # 规则匹配了角色和动作, 但条件为假.
          conditionNotMet: '{"reason": "not_reviewed", "review_status": R.attr.review_status}'
```

- 每个输出按动作上报，形式为 `{src, action, val}`，其中 `src` 是 `resource.<kind>.v<version>#<rule name>`。每个带输出的规则都要给一个稳定的 `name`，因为消费方和测试是靠 `src` 匹配的。
- 要解释某条规则为什么没有放行，就把解释写进那条规则的 `conditionNotMet`。不要另加一条 DENY 规则：它会改变策略的决策逻辑，并发出不同的 `src`。属于其他角色或动作的规则不会发出任何内容。
- DENY 规则同样支持输出；拒绝生效时 `ruleActivated` 会被触发。
- 重叠的规则可能各自都发出输出，所以响应里可能同时出现某条 ALLOW 规则的 `ruleActivated` 输出和决定该动作的 DENY。消费方必须读 effect，不能从输出反推决策。列在决定性 DENY 规则之后的规则是否仍然发出输出取决于规则顺序，所以不要依赖这一点。
- 运行时失败的输出表达式会产出一个 `error` 条目而不是 `val`；用 `has()` 守卫可选属性。
- 输出表达式接受任意 CEL 值：字符串、数字、map、list，以及条件表达式，比如 `R.attr.word_count > 5000 ? "long" : "short"`。

测试套件里的 `outputs` 断言（见 [TEST-SUITES.md](TEST-SUITES.md#output-assertions)）是子集检查：列出的输出必须匹配，没列出的输出会被忽略。需求指定的每个输出都要断言。每个分支都要覆盖：触发、条件不满足，以及表达式里任何边界值的两侧。

## 派生角色

```yaml
# yaml-language-server: $schema=https://api.cerbos.dev/latest/cerbos/policy/v1/Policy.schema.json
apiVersion: api.cerbos.dev/v1
derivedRoles:
  name: "document_roles"
  definitions:
    - name: owner
      parentRoles: ["user"]
      condition:
        match:
          expr: R.attr.owner == P.id
```

用 `resourcePolicy.importDerivedRoles` 导入这组定义，再用规则的 `derivedRoles` 字段选中其中一个定义，就像上面那份资源策略那样。规则的 `roles` 字段匹配调用方给出的基础角色。这些基础角色要留在 principal fixture 里；Cerbos 根据 `parentRoles` 和条件算出派生角色。见[派生角色](https://docs.cerbos.dev/cerbos/latest/policies/derived_roles.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-derived-roles-html)。

## 导出变量

```yaml
# yaml-language-server: $schema=https://api.cerbos.dev/latest/cerbos/policy/v1/Policy.schema.json
apiVersion: api.cerbos.dev/v1
exportVariables:
  name: "common_vars"
  definitions:
    is_owner: R.attr.owner == P.id
```

### Variable dependency design

只在一处使用的条件就内联写。同一份策略内部复用的表达式放进 `variables.local`。只有当条件确实跨策略复用时才导出，并且按聚焦的业务关注点和相容的属性要求来组织导出，而不是把所有辅助函数都堆进 `common_vars.yaml`。

`variables.import` 指的是一个导出的**集合**，不是单个变量；看到任何一个 `V.*` 引用，并不代表每个 import 都有必要。对每份策略：

1. 从它的条件和输出入手，包括它用到的派生角色的条件与输出。把变量引用（`V.*` 或 `variables.*`）解析到相应策略上下文里的本地定义或导出定义。
2. 沿着这些定义里的引用做传递追踪。保留每个必需的定义和 import；删掉没有可达消费方的 import 和没被使用的本地定义。
3. 检查每个保留下来的导出集合的完整内容。如果某份策略只需要一个大集合里的一个辅助函数，就按关注点拆开这个集合，并更新受影响的消费方。其他策略还需要的共享定义要保留。
4. 检查这些表达式所需的资源属性和 principal 属性确实存在于消费方策略的输入契约中。只为已确认的关系规则所适用的资源导入与关系相关的辅助函数。

导入的集合并不是免费的抽象：源码文件简洁并不保证编译产物就小。即使编译能过，也要让依赖保持最小化。import 与本地变量的语法见[Cerbos 变量文档](https://docs.cerbos.dev/cerbos/latest/policies/variables.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-variables-html)。

## Principal 策略（按用户的例外）

principal 策略会为某一个 principal ID 覆盖资源策略，比如破窗账号（break-glass）或临时承包商。把它放在 `principal_policies/<principal-id>.yaml`。

```yaml
# yaml-language-server: $schema=https://api.cerbos.dev/latest/cerbos/policy/v1/Policy.schema.json
apiVersion: api.cerbos.dev/v1
principalPolicy:
  principal: sre-breakglass       # 与 P.id 完全匹配
  version: default
  rules:
    - resource: database
      actions:
        # 破窗账号只在已批准的事件处置窗口内读取生产数据.
        - name: breakglass-reads-during-incident
          action: read
          effect: EFFECT_ALLOW
          condition:
            match:
              expr: now() < timestamp(P.attr.incident_window_ends)
        # 无论 IdP 授予了哪些角色, 破窗访问都不允许丢弃数据.
        - name: breakglass-never-drops
          action: drop
          effect: EFFECT_DENY
```

匹配上的 principal 策略 DENY 会覆盖资源策略的 ALLOW。条件为假的 principal 策略 ALLOW 不决定任何事，所以资源策略依然生效：超出窗口、但同时持有某个团队角色的破窗账号，仍然保有该角色的访问权限。两边都要测，并用一个长得像的 principal ID 说明这个例外是按用户生效的。见[principal 策略](https://docs.cerbos.dev/cerbos/latest/policies/principal_policies.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-principal-policies-html)。

## 角色策略（以 IdP 角色为中心）

角色策略从 IdP 角色的视角定义权限。和资源/principal 策略不同，它采用允许列表模型——任何没有被明确列出的资源-动作组合都会被拒绝。

```yaml
# yaml-language-server: $schema=https://api.cerbos.dev/latest/cerbos/policy/v1/Policy.schema.json
apiVersion: api.cerbos.dev/v1
rolePolicy:
  role: "emea_admin"
  scope: "emea"           # 可选: 与资源的 scope 匹配
  parentRoles:            # 可选: 继承并收窄权限
    - "admin"
  rules:
    - resource: "document"
      allowActions:
        - "view"
        - "edit"
        - "delete"
    - resource: "dataset"
      allowActions:
        - "view"
        - "view:*"        # 通配符
      condition:
        match:
          expr: R.attr.department == P.attr.department
```

关键特性：

- **允许列表模型**：没有 `EFFECT_ALLOW`/`EFFECT_DENY`——`allowActions` 就是允许动作的完整清单
- **隐式拒绝**：任何不在 `allowActions` 里的动作都被拒绝
- **父角色继承**：子角色只能收窄父角色的权限（严格子集）
- **通配符**：`resource` 和 `allowActions` 都支持通配符（`view:*`）；`*` 如何处理 `:` 见上面的*动作通配符*
- **条件**：每条规则项可以带可选的 CEL 表达式
- **`allowActions` 不能为空**：`allowActions: []` 是校验错误
- **不会超出资源策略授权**：被允许的动作还需要资源策略链为该角色（或其 `parentRoles`）给出授权。自定义角色如果没有能对应到资源策略角色的 `parentRoles`，就什么也拿不到。资源策略始终是必需的，但不需要 scoped 资源策略；策略链会回落到基础策略。
- **父角色递归解析**：父角色在同一 scope 下有自己的角色策略时，那份策略的限制同样适用。如果某个 scope 收窄了 `analyst`，基于 `analyst` 的自定义角色会继承这份收窄。
- **收窄一个 IdP 角色**：以已有角色命名的角色策略（`role: analyst`，没有 `parentRoles`）只在该 scope 内收窄这个角色；在 scope 之外，这个角色保留它的资源策略权限。
- **条件失败即拒绝**：匹配的规则若条件为假，就拒绝该动作，即使策略里另一条规则无条件列出了它。每个动作只放在一条规则里。
- **严格子集是在求值时检查的，不是编译时**：列出父角色没有的动作能编译通过，但会被拒绝。
- **Scope**：带 scope 的角色策略适用于对具有该 scope 的资源的请求；principal 的 scope 不会决定选用它。未带 scope 的角色策略只适用于未带 scope 的请求。

## Scoped 资源策略（策略层级）

带 `scope: "emea.de"` 的资源策略适用于其资源（或 principal，对 principal 策略而言）具有该 scope 的请求。Cerbos 按从具体到宽泛的顺序求值这条链：`emea.de`、`emea`，然后是未带 scope 的基础策略。链上的每个祖先都必须存在，包括基础策略，否则编译失败。在没有 `lenientScopeSearch`（引擎配置）的情况下，请求一个自己没有策略的 scope 会被拒绝。import（派生角色、变量）不会被继承：每个 scoped 策略自己 import 它的规则用到的东西。见[scoped 策略](https://docs.cerbos.dev/cerbos/latest/policies/scoped_policies.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-scoped-policies-html)。

`scopePermissions` 决定 scoped 策略相对父策略可以做什么，同一 scope 里的所有策略必须一致：

| 设置 | 规则匹配、条件为真 | 规则匹配、条件为假 | 没有规则匹配 | 何时使用 |
|---|---|---|---|---|
| `SCOPE_PERMISSIONS_OVERRIDE_PARENT`（默认） | 它的 effect 是最终结果 | 继续往上找父策略 | 继续往上找父策略 | 该 scope 可以独立于父策略授予或撤销权限 |
| `SCOPE_PERMISSIONS_REQUIRE_PARENTAL_CONSENT_FOR_ALLOWS` | ALLOW 仍然需要父策略的 ALLOW；DENY 是最终结果 | 隐式 DENY | 继续往上找父策略 | 该 scope 只能收窄父策略允许的内容 |

把需求映射到设置上，不要只看今天的决策结果。“只能限制”“不能超出父策略授予”“只做收窄”这类要求，需要在该 scope 以及每个必须保持这一保证的后代 scope 上使用 `REQUIRE_PARENTAL_CONSENT_FOR_ALLOWS`。一个 override 模式的策略如果复述父策略的授权再加几条 DENY 规则，今天可能给出相同的决策，但以后往里加的任何 ALLOW 规则都可能超出父策略。

在 consent 模式下，把限制表达成针对受影响角色和动作的条件式 ALLOW。条件失败时，结果就是隐式 DENY。不受影响的权限不要写进这份策略，让它们落到父策略；不要复述父策略的授权。角色是分别求值再合并结果的，所以一个 principal 只要还有一个不受限制的角色，就仍然保有该角色的访问权限。一条 `roles: ["*"]` 且 `actions: ["*"]`、由条件把关的 ALLOW 规则，会在整个 scope 上加一条要求（比如要求使用受管设备），同时不会授予父策略拒绝的任何东西。

```yaml
resourcePolicy:
  resource: dataset
  version: default
  scope: emea
  scopePermissions: SCOPE_PERMISSIONS_REQUIRE_PARENTAL_CONSENT_FOR_ALLOWS
  rules:
    # 只有 EMEA 的分析师可以导出脱敏数据集; 其他基础权限原样透传.
    - name: analysts-export-anonymised
      actions: [export]
      roles: [analyst]
      effect: EFFECT_ALLOW
      condition:
        match:
          expr: R.attr.anonymised == true
```

把 scoped 策略放在与 scope 对应的目录里（`resource_policies/emea/de/dataset.yaml`）。资源 fixture 带上 `scope`；见 [TEST-SUITES.md](TEST-SUITES.md#scoped-fixtures)。

## Scoped 角色策略（`parentRoles` + `scope`）

Scoped 角色策略让租户可以创建收窄基础角色权限的自定义角色。

**继承行为：**

- 子策略中**列出**的资源会被收窄到子策略的 `allowActions`（必须是父策略的严格子集）
- 子策略中**没有列出**的资源一律被拒绝——允许列表是穷尽的
- 想给某个资源任何访问权限，它必须在子策略的规则里被明确列出

**派生角色不需要自定义角色名：**

- 如果基础派生角色列出 `parentRoles: ["admin", "operator", "developer", "viewer"]`，那么带 `parentRoles: ["operator"]` 的自定义角色会自动沿父链解析出来
- 绝不要把自定义角色名加进派生角色的 `parentRoles` 列表

**Scope 写在资源 fixture 上，不是 principal：**

- 角色策略声明 `scope: "emea"`
- 测试资源 fixture 必须带 `scope: "emea"`，scoped 角色策略才会参与求值
- 测试 principal fixture **不要**有 `scope` 字段——只要在 `roles` 里写上自定义角色名就行

```yaml
# role_policies/emea/release_manager.yaml
apiVersion: api.cerbos.dev/v1
rolePolicy:
  role: "release_manager"
  scope: "emea"
  parentRoles:
    - "operator"
  rules:
    - resource: "flow"
      allowActions:
        - "read"
        - "deploy"
    - resource: "secret"
      allowActions:
        - "read"
    # connector 未列出 → 拒绝 (允许列表是穷尽的)
```

```yaml
# testdata/principals.yaml — principal 上没有 scope
emea_release_manager:
  id: "user_emea_rm"
  roles:
    - "release_manager"
  attr:
    org_id: "org1"
```

```yaml
# testdata/resources.yaml — scope 写在资源上
emea_staging_flow:
  kind: "flow"
  id: "flow1"
  scope: "emea"
  attr:
    org_id: "org1"
    project_id: "proj1"
    environment: "staging"
```

**scoped 角色规则上的条件：**

scoped 角色策略里的单条规则可以带 CEL 条件。对同一资源用分开的规则项，就只对特定动作施加条件。

```yaml
rules:
  - resource: "flow"
    allowActions:
      - "read"
  - resource: "flow"
    allowActions:
      - "create"
      - "update"
    condition:
      match:
        expr: R.attr.environment == "staging"
```

**文件组织：** 按租户把 scoped 角色策略分到子目录：`role_policies/emea/`、`role_policies/apac/`。

## 策略设计模式

选择最贴合需求的模式。

### 动作主导（推荐默认）

以动作为中心，列出每个动作由哪些角色执行。适合：

- 角色之间有层级化的权限
- 需要看清哪些动作属于“高风险”
- 角色多，动作种类少

### 角色主导

以角色为中心，指定它们允许的动作。适合：

- 角色界限清晰，重叠很少
- 角色少，动作多
- 角色分工明确

### 属性主导（ABAC）

用动态属性代替静态角色。适合：

- 多租户系统
- 上下文相关的访问（时间、地点、状态）
- 不改策略也能灵活调整规则

### 角色策略（以 IdP 角色为中心）

当权限需要从 IdP 角色的视角来定义时，使用角色策略。适合：

- 与 IdP 管理的角色集成
- 简单的允许列表语义（列出允许的，其余一律拒绝）
- 带继承和收窄的层级角色
- 想避免写显式 DENY 规则时
