# Policies.md · Cerbos 策略文档阅读笔记

> 目的:逐页阅读 Cerbos 官方文档,记录**对它的理解**。
>
> **约定**
> - 一次一个 URL。只解读当前这一页的内容。
> - **不自行阅读子链接**——除非明确指示,只处理给定的 URL。
> - **不发挥**:只记录页面说了什么、以及它意味着什么。不加自己的设计判断。
> - 页面版本:Cerbos PDP **0.57.0**(与本机 PDP 一致)。

---

## 1. 索引页 · Cerbos policies

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/

### 页面说了什么

Cerbos 有**六种**策略:

| # | 种类 | 页面给的说明 |
|---|---|---|
| 1 | **Derived roles** | 传统 RBAC 角色通常是很宽的分组,没有上下文感知。派生角色是用上下文数据来增强那些宽泛角色,以便在运行时提供更细粒度的控制。例:持有宽泛 `manager` 角色的人,可以通过考虑地理位置(或其他因子)被增强为 `manager_of_scranton_branch`,让这个派生角色的持有者在属于 Scranton 分支的资源上拥有额外权限。 |
| 2 | **Resource policies** | 定义可以对某个 resource 执行的 action。resource 是应用特定的概念,适用于任何需要访问控制的东西。例如在 HR 应用里,resource 可以粗到整个员工记录,也可以细到记录里的单个字段。 |
| 3 | **Principal policies** | 为特定用户定义覆盖(overrides)。 |
| 4 | **Role policies** | 定义针对某个特定角色的规则。规则被定义为一份适用于特定 resource 的允许 action 列表。 |
| 5 | **Exported variables** | 定义变量,供其他策略的条件表达式复用。 |
| 6 | **Exported constants** | 定义常量,供其他策略的条件表达式复用。 |

**策略依据请求里传给 Cerbos PDP 的 metadata 来求值。**

页面末尾提到:可以访问运行中的 Cerbos 实例(`http://localhost:3592/`)查看最新文档和示例请求;OpenAPI(Swagger)schema 从 `/schema/swagger.json` 获取。

### 我的理解

**1. 六种策略分两类:「定义规则」和「提供素材」。**

- 前四种(resource / principal / role / derived roles)是**规则本身**
- 后两种(exported variables / constants)不是规则,是**给规则用的素材**

这个区分重要,因为后两者不能单独授权任何东西——它们只是被其他策略的
`condition` 表达式引用。

**2. 六种策略对应不同的「主体 × 客体」组合。**

| 策略 | 谁决定 | 管什么 |
|---|---|---|
| Resource policies | 按 **resource 类型** | 谁能对这个 resource 做哪些 action |
| Role policies | 按 **role** | 这个角色能做哪些 action |
| Principal policies | 按 **具体用户** | 对这个用户的覆盖 |
| Derived roles | 按 **角色 + 上下文** | 从宽角色推导出更细的角色 |

**3. resource policies 是主力,另外三种是它的补充。**

页面用「HR 应用里的 resource 可以粗到整个员工记录,细到单个字段」来说明
resource 的粒度是**由应用决定的**,Cerbos 不预设粒度。这解释了为什么
resource 是 `(kind, id, attr)` 三元组——kind 就是粒度的标识。

**4. Derived roles 解决的是 RBAC 的经典问题:角色太宽。**

`manager` → `manager_of_scranton_branch`:同一个基础角色,加上上下文
(地理位置等)后派生出更细的角色,让派生角色的持有者在特定分支的资源上有
额外权限。

**这意味着 Cerbos 的角色不只是一个字符串标签**——它可以由上下文推导出来。
本项目里 `FDEP_ADMIN` 之类的固定角色属于「宽角色」这一档。

**5. 「策略依据请求里的 metadata 求值」是理解整套机制的枢纽。**

策略本身不含任何数据。所有输入——谁在请求、请求什么资源、带了什么属性、
什么时间、来自哪个 IP——都从请求的 metadata 来。这意味着:

- 策略是**纯函数**:输入 → 决定,同样的输入永远同样的输出
- 任何需要「上下文」的规则,都必须有人把上下文放进请求
- `attr` 不是可有可无的装饰,而是**策略唯一的数据来源**

**6. `/schema/swagger.json` 正是本项目已经在用的东西。**

页面上说 OpenAPI schema 从这里取——本项目 `openapi-spec.json` 就是它
(95,524 bytes,16 条路径,122 个定义)。所以文档页面的「示例请求」可以直接
和实际 API 对上。

### 与本项目的关系(仅记录对应关系,不作设计判断)

| 文档概念 | 本项目对应物 |
|---|---|
| resource policy | `policies/resource_policies/basicResource.yaml` |
| resource 的「粒度由应用决定」 | kind `basicResource` / `fdepApi` |
| 策略依据请求 metadata 求值 | `POST /api/check/resources` 的 body |
| metadata 里的属性 | `principal.attr` / `resource.attr` |
| `/schema/swagger.json` | `openapi-spec.json` |

---

---

## 2. How Cerbos evaluates requests · 求值流程

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/evaluation

页面开头说:理解 Cerbos 如何求值授权请求,有助于写正确的策略和诊断意外的结果。

### 页面说了什么

#### 默认拒绝

> Cerbos is deny-by-default. If no policy exists for the resource kind and version in the request, or if no rule within a matching policy grants access, the result is `EFFECT_DENY`. There is no concept of "no opinion" — the absence of an explicit allow is a deny.

请求的 resource kind 和 version 找不到 policy,或者匹配到的 policy 里没有任何规则授予访问,结果都是 `EFFECT_DENY`。**不存在「没有意见」这种状态** —— 缺少明确的允许就是拒绝。

#### 策略查找

按请求里的 resource `kind` 和 `version` 找 resource policy。

如果提供了 `scope`,先找**最具体的 scoped policy**,然后沿 scope 层级往上走。例如 scope 为 `a.b.c` 时,按这个顺序检查:

1. scope `a.b.c`
2. scope `a.b`
3. scope `a`
4. 无 scope

#### 规则匹配

对请求里的每个 action,求值匹配到的 policy 里的所有规则。一条规则在以下**全部**成立时才算匹配:

1. 规则的 `actions` 匹配请求的 action。支持通配符,且**遵守 `:` 分隔符**(例如 `view:*` 匹配 `view:public`,但不匹配 `view`)。
2. 规则的 `roles` 或 `derivedRoles` 至少包含 principal 的一个静态角色或已激活的派生角色。
3. 如果规则有 condition,condition 求值为 `true`。

#### 冲突解决

> This is the most important part of the evaluation model.

| 规则 |
|---|
| **对单个角色和单个 action,如果 ALLOW 和 DENY 规则都匹配,结果是 DENY。拒绝永远优先。** |

但如果 principal 有**多个角色**,并且其中至少一个角色对该 action 求值出 `EFFECT_ALLOW`(且该角色没有 `EFFECT_DENY`),整体结果是 `EFFECT_ALLOW`。这避免了「admin 用户因为同时持有权限较低的角色而被锁在外面」的情况。

**例一:多角色**

principal 的角色是 `["admin", "user"]`:

```yaml
rules:
  - actions: ["delete"]
    effect: EFFECT_ALLOW
    roles: ["admin"]
```

- 规则:ALLOW `admin` 执行 `delete` —— 匹配。
- 没有任何规则允许 `user` 执行 `delete`。
- 结果:**EFFECT_ALLOW** —— 因为 `admin` 角色有一个 allow。

**例二:拒绝优先于允许**

principal 的角色是 `["manager"]`:

```yaml
rules:
  - actions: ["approve"]
    effect: EFFECT_ALLOW
    roles: ["manager"]
    condition:
      match:
        expr: R.attr.status == "PENDING"

  - actions: ["approve"]
    effect: EFFECT_DENY
    roles: ["manager"]
    condition:
      match:
        expr: R.attr.amount > 10000
```

若 resource 的 `status: "PENDING"` 且 `amount: 15000`,两条规则对 `manager` 角色都匹配。结果是 **EFFECT_DENY**,因为同一角色下拒绝优先于允许。

#### 派生角色

派生角色在 resource policy 规则**之前**求值。principal 根据 derived roles policy 里的条件被赋予派生角色,这些派生角色随后可以在 resource policy 规则里被引用。

**derived roles policy 必须通过 `importDerivedRoles` 导入 resource policy 才生效。**

#### Principal policies

Principal policies 在 resource policies **之前**求值。当一个 principal policy 匹配上请求的 principal 时,Cerbos 先对它请求的 action 求值。**对每个 principal policy 给出明确 `EFFECT_ALLOW` 或 `EFFECT_DENY` 的 action,那个决定就是最终结果 —— 该 action 不再查 resource policy。**

principal policy 未决定的 action(没有匹配规则,或有匹配规则但 condition 不成立)才落到 resource policy 求值。

#### Role policies

Role policies 作为 resource policy 之上的**附加约束**。它们不直接产生 `EFFECT_ALLOW` 或 `EFFECT_DENY` —— 相反,`allowActions` 列表充当该角色在每个 resource 上被允许的 action 的**允许清单**。不在清单里的 action,对该角色就是隐含的 `EFFECT_DENY`。

**一个 action 要被允许,必须同时被 role policy 和匹配的 resource policy 允许。** role policy 可以**收窄** resource policy 授予的访问,但不能授予 resource policy 本来就不允许的访问 —— **这就是为什么 resource policy 总是必需的**。

如果 role policy 声明了 `parentRoles`,它会递归继承并收窄那些角色的权限。

#### 求值顺序总结

1. 如果 principal policy 匹配上请求的 principal,先求值它。对 principal policy 给出明确 `EFFECT_ALLOW` 或 `EFFECT_DENY` 的每个 action,那就是最终结果,不再做进一步求值。
2. 对 principal policy 未决定的 action,查找 resource kind 和 version 对应的 resource policy(考虑 scope)。
3. 求值 derived roles,确定哪些适用于该 principal。
4. 求值 resource policy 里所有匹配的规则。如果有 role policy 适用于该 principal 的角色,它们的 `allowActions` 列表会进一步限制那些角色被允许的 action。
5. 应用冲突解决:**同一角色下拒绝优先于允许;跨角色则任一角色的允许胜出**。
6. 任何没有明确 `EFFECT_ALLOW` 的 action 都是 `EFFECT_DENY`。

### 我的理解

**1. 「没有意见」这个状态不存在 —— 这是整个模型的基石。**

页面把它放在第一位并特别强调。它的后果是:**不能靠「没写规则」来实现拒绝之外的任何语义**。
每一条走到最后的 action,都必然落在一个明确的决定上(EFFECT_ALLOW 或 EFFECT_DENY)。

这解释了为什么本项目 PDP 在「策略集为空」时把每个请求都变成 DENY —— 那不是故障,
是模型本身在「没有策略」时的正常输出。**故障和「全部拒绝」在响应里长得一样**,
这正是 FDEP 侧必须区分 403 和 503 的原因(见 `FDEP-AUTHZ-DESIGN.md` §7.3)。

**2. 冲突解决有两个层级,方向相反。**

| 范围 | 规则 |
|---|---|
| **同一角色内** | DENY 优先 |
| **跨角色** | 任一角色的 ALLOW 胜出 |

第二层的设计意图页面写得很直白:避免 admin 因为同时持有低权限角色而被锁在外面。
也就是说,**Cerbos 的多角色是「取权限并集」,不是「取最严」**。

**3. 规则匹配的第三个条件(condition)决定了 condition 是「过滤器」而不是「决定者」。**

规则匹配的三个条件是「并且」关系。所以 condition 只能**收窄**一条已经靠
actions+roles 匹配上的规则,不能单独构成一条允许。

**4. Principal policy 有「最终决定权」。**

它先于 resource policy 求值,而且一旦对某个 action 给出明确结论,resource policy
就不再被查。这和 role policy 的性质完全不同:

| 策略 | 性质 |
|---|---|
| Principal policy | **最终决定**,对特定 action 一票定案 |
| Role policy | **附加约束**,只能收窄,不能授予 |

**5. Role policy 是允许清单,不是决策器。**

`allowActions` 是「白名单」语义 —— 不在清单里的 action 自动是 DENY。
而且它**必须和 resource policy 同时允许**才行,所以 resource policy 永远不可省。

**6. 求值顺序是分层短路,不是把所有 policy 一起算。**

```
principal policy  ──(明确决定就结束)──►  结束
      │ 未决定
      ▼
resource policy 查找(含 scope 从具体往一般)
      ▼
derived roles 求值
      ▼
resource policy 规则求值
      ▼
role policy 收窄(allowActions)
      ▼
冲突解决(同角色 deny 优先;跨角色 allow 胜出)
      ▼
未明确允许的 → DENY
```

**7. Scope 查找是「从具体往一般」的层级链。**

scope `a.b.c` 会依次试 `a.b.c` → `a.b` → `a` → 无 scope。
这意味着**同一个 kind+version 可以有多个 policy,按 scope 细分**,
越具体的优先。

### 与本项目的对应关系(仅记录对应关系)

| 页面概念 | 本项目对应物 |
|---|---|
| default deny | PDP 策略集为空时全部 DENY(实测过) |
| policy lookup by kind + version | `resource.fdepApi.vdefault` / `resource.basicResource.vdefault` |
| scope 层级查找 | 之前实测 scope 未命中,`matchedPolicy=NO_MATCH` —— 这页说明查找顺序,细节在 scoped policies 页 |
| 规则匹配三条件 | `roles` 省略的规则不匹配(实测);`actions` 支持 `:` 分隔的通配符 |
| 冲突解决 | 同角色 deny 优先、跨角色 allow 胜出(实测过 catch-all DENY 掩蔽 ALLOW 的现象) |
| principal policy 最终决定权 | 本项目未使用 |
| role policy 附加约束 | 本项目未使用 |
| derived roles 需 `importDerivedRoles` | 本项目未使用 |

---

---

## 3. Policy authoring · 编写策略

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/authoring_tips

### 页面说了什么

#### 使用策略的提示

- 策略可以是 YAML 或 JSON。**接受的文件扩展名是 `.yml`、`.yaml` 或 `.json`,其他扩展名一律被忽略。**
- Cerbos 文件的 JSON schema 地址:
  - Policy — `https://api.cerbos.dev/v0.57.0/cerbos/policy/v1/Policy.schema.json`
  - Test suite — `.../TestSuite.schema.json`
  - Principal test fixtures — `.../TestFixture/Principals.schema.json`
  - Resources test fixtures — `.../TestFixture/Resources.schema.json`
  - Auxiliary data test fixtures — `.../TestFixture/AuxData.schema.json`
  - 同一组地址把 `v0.57.0` 换成 `latest` 也可以取到。

#### 策略结构

- **所有策略类型共用的策略头部**:
  - `apiVersion`:**必填**,必须是 `api.cerbos.dev/v1`。
  - `description`:可选,策略的描述。
  - `disabled`:可选,设为 `true` 让 Cerbos 引擎忽略这个策略文件。
  - `metadata.sourceFile`:可选,设置策略数据的来源,供审计用。
  - `metadata.annotations`:可选,字符串键值对,自由格式,供审计用。
- **resource 名称、action、principal 名称都可以是分层的**。用 `:` 作为分隔符。例如:`app:component:resource`。
- **某些字段允许通配符匹配**。通配符遵守层级分隔符 `:`。
- Scoped policies(可选)适用于多租户这类场景,可以在某些租户上覆盖特定规则。

#### 编辑策略

最快的熟悉方式是使用 [online playground](https://play.cerbos.dev),它提供 IDE 式的体验:交互式编辑器、示例、代码片段、测试用例等。

**编辑器配置** —— 支持 LSP 的编辑器可以用 YAML language server,在策略文件开头加这一行就能得到上下文感知的代码建议和校验消息:

```yaml
# yaml-language-server: $schema=https://api.cerbos.dev/latest/cerbos/policy/v1/Policy.schema.json
```

测试文件同理,把 URL 换成 `TestSuite.schema.json`;fixtures 换成 `TestFixture/Resources.schema.json`、`TestFixture/Principals.schema.json`、`TestFixture/AuxData.schema.json`。

YAML language server 也支持按目录设置。示例(把 schema 应用到 `/cerbos` 目录):

```yaml
yaml.schemas: {
    "https://api.cerbos.dev/latest/cerbos/policy/v1/Policy.schema.json": "/cerbos/*",
    "https://api.cerbos.dev/latest/cerbos/policy/v1/TestSuite.schema.json": "/cerbos/**/*_test.yaml",
    "https://api.cerbos.dev/latest/cerbos/policy/v1/TestFixture/Resources.schema.json": "/cerbos/**/testdata/resources.yaml",
    "https://api.cerbos.dev/latest/cerbos/policy/v1/TestFixture/Principals.schema.json": "/cerbos/**/testdata/principals.yaml",
    "https://api.cerbos.dev/latest/cerbos/policy/v1/TestFixture/AuxData.schema.json": "/cerbos/**/testdata/auxdata.yaml"
}
```

JSON 文件用顶层 `$schema` 属性指定 schema。

页面随后给出三种编辑器的具体配置:Neovim(nvim-lspconfig + mason-lspconfig)、JetBrains IDEs(Preferences → Languages & Frameworks → Schemas and DTDs → JSON Schema Mappings)、Visual Studio Code(装 `redhat.vscode-yaml` 扩展后编辑 `Yaml: Schemas`)。

### 我的理解

**1. 「其他扩展名一律被忽略」这条有实际后果。**

策略文件被静默忽略,不报错。这意味着:文件命名错了(比如 `basicResource.yml.txt`),
策略就不生效,而 PDP 不会告诉你。本项目之前踩过类似的坑——部署后必须查
`GET /admin/policies` 确认策略在不在清单里。

**2. 策略头部有两个专门为审计准备的字段。**

`metadata.sourceFile` 和 `metadata.annotations` 的用途页面写明是 "for auditing purposes"。
这和请求侧的 `requestContext.annotations`(我们用来放 trace id)是同一个思路:
**审计信息要能进到策略本身和请求本身两个地方**。

**3. `disabled: true` 让引擎忽略整个策略文件 —— 这是「停用」不是「删除」。**

这解释了本项目之前实测到的现象:`DELETE /admin/policy` 停用后,策略仍出现在
`?includeDisabled=true` 清单里。**Cerbos 有「停用」这个一等概念,不只是删除。**
所以「停用」和「删除」是两件事,页面把 `disabled` 放在头部字段里,是正式支持的。

**4. 名称可以分层,分隔符是 `:`。**

resource 名称、action、principal 名称三者都支持 `app:component:resource` 这种层级。
**而通配符也遵守同一个分隔符** —— 这和上一页说的「`view:*` 匹配 `view:public`
但不匹配 `view`」是同一套规则:分层与通配共享 `:` 这个边界。

所以 `:` 同时承担两个角色:既是层级的路径分隔符,也是通配符的作用域边界。
这解释了为什么 `view:*` 不匹配 `view` —— `view` 是没有子层的那一层。

**5. 页面把 editor 配置写得很细,说明「写策略」的第一道关是编辑器。**

五种 schema URL(Policy / TestSuite / 三种 fixture)加上按目录的映射规则,
本质上是在说:**策略文件应该由 schema 校验,而不是由眼睛校验**。

### 与本项目的对应关系(仅记录对应关系)

| 页面概念 | 本项目对应物 |
|---|---|
| 接受的扩展名 `.yml` / `.yaml` / `.json`,其他忽略 | `policies/**/*.yaml`;`push-policies.py` 也按 `*.yaml` 收集 |
| `apiVersion` 必填 | 本项目所有 policy 都有 `apiVersion: api.cerbos.dev/v1` |
| `disabled: true` 忽略策略文件 | 与实测到的「`DELETE /admin/policy` 是停用」一致 |
| `metadata.sourceFile` / `metadata.annotations` | 审计用途;本项目未使用 |
| `:` 分层 + 通配符遵守同一分隔符 | 解释了 `view:*` 不匹配 `view` |
| yaml-language-server 那行注释 | 本项目每个 policy 开头都有(`# yaml-language-server: $schema=...`) |

---

---

## 4. Derived roles · 派生角色

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/derived_roles

### 页面说了什么

#### 定义

> Derived roles are computed at request evaluation time from the principal's base roles and request attributes. They augment static IdP-assigned roles with context-dependent designations.

派生角色在**请求求值时**从 principal 的基础角色和请求属性算出来。它们用上下文相关的称谓来增强 IdP 分配的静态角色。

传统 RBAC 角色通常是很宽的分组、没有上下文感知。它们是**静态的,由 Identity Provider(IDP) 提供,不是 Cerbos 提供的**。Cerbos 提供派生角色作为用上下文数据增强那些宽泛角色的方式,以便在运行时提供更细粒度的控制。例:持有宽泛 `manager` 角色的人,可以通过考虑地理位置(或另一个因子)被增强为 `manager_of_scranton_branch`,让这个派生角色的持有者在属于 Scranton 分支的资源上拥有额外权限。

> **注意**:派生角色在运行时由「把 API 请求里的 principal `roles`」与「派生角色定义里的 `parentRoles`」匹配来确定。**不要把派生角色的名字当作请求里的 `roles`** —— Cerbos 期望那个字段只包含「普通」角色。

#### 结构

```yaml
---
apiVersion: "api.cerbos.dev/v1"
description: |-
  Common dynamic roles used within the Apatr app
derivedRoles:
  name: apatr_common_roles (1)
  constants:
    import: (2)
      - apatr_common_constants
    local: (3)
      corporate_network_ip_range: 10.20.0.0/16
  variables:
    import: (4)
      - apatr_common_variables
    local: (5)
      flagged_resource: request.resource.attr.flagged
  definitions:
    - name: owner (6)
      parentRoles: ["user"] (7)
      condition: (8)
        match:
          expr: request.resource.attr.owner == request.principal.id

    - name: abuse_moderator
      parentRoles: ["moderator"]
      condition:
        match:
          expr: variables.flagged_resource

    - name: corporate_user
      parentRoles: ["user"]
      condition:
        match:
          expr: request.principal.attr.ip_address.inIPAddrRange(constants.corporate_network_ip_range)
```

| 标注 | 含义 |
|---|---|
| (1) | 导入这组派生角色时要用的名字 |
| (2) | 要导入的常量定义(可选) |
| (3) | 本地常量定义(可选) |
| (4) | 要导入的变量定义(可选) |
| (5) | 本地变量定义(可选) |
| (6) | 这个派生角色的描述性名字 |
| (7) | 这个派生角色适用于哪些静态角色(来自 IdP)。**特殊值 `*` 可以匹配任何角色** |
| (8) | (可选)一组表达式,求值为 true 时该角色被激活 |

#### 理解派生角色

页面用 DC 宇宙的例子解释:亿万富翁花花公子 Bruce Wayne 穿上蝙蝠装就成为 Batman。成为 Batman 给他额外特权。在 Cerbos 术语里,Batman 是 `derived role`,Bruce Wayne 是 `parentRole`。激活 Batman 派生角色的 condition 是:「Bruce Wayne 正穿着蝙蝠装」。

Cerbos 永远只跟 Bruce Wayne 打交道(在这个场景里他是唯一真实的人)。但 Cerbos 足够聪明,在他穿着戏服时把他当成 Batman。

```yaml
---
apiVersion: "api.cerbos.dev/v1"
derivedRoles:
  name: gotham_city
  definitions:
    - name: batman
      parentRoles: ["bruce_wayne"]
      condition:
        match:
          expr: P.attr.isWearingBatCostume
```

#### 排查:派生角色没有生效

如果派生角色没起作用,按这个清单走:

1. **派生角色策略已被导入 resource policy。** resource policy 必须包含一个与派生角色策略 `name` 字段匹配的 `importDerivedRoles` 条目。

   ```yaml
   resourcePolicy:
     resource: "document"
     version: "default"
     importDerivedRoles:
       - my_derived_roles  # 必须与派生角色策略里的 `name` 一致
     rules:
       - actions: ["edit"]
         effect: EFFECT_ALLOW
         derivedRoles:
           - owner
   ```

2. **principal 的静态角色匹配 `parentRoles`。** API 请求里带的角色必须至少包含派生角色 `parentRoles` 字段里列出的一个。**这些是大小写敏感的。**

3. **condition 求值为 true。** 如果派生角色有 condition,验证请求里的属性名和类型与表达式期望的一致。用 [Cerbos REPL](https://docs.cerbos.dev/cerbos/latest/cli/cerbos#repl) 交互式测试表达式。

4. **resource policy 有规则引用这个派生角色。** 规则必须在 `derivedRoles` 列表里包含该派生角色名字,才能授予或拒绝访问。

#### 怎么看哪些派生角色被激活了

在 `CheckResources` 请求里加 `"includeMeta": true`。响应的 `meta` 块包含 `effectiveDerivedRoles` 列表,显示每个 resource 上为该 principal 激活了哪些派生角色。

#### 派生角色不会自动授予访问

> Defining a derived role only creates a named condition. You must still write a rule in a resource policy that references the derived role in its `derivedRoles` list for it to have any effect on authorization decisions.

定义派生角色**只是创建了一个有名字的条件**。仍然必须在 resource policy 里写一条规则、在它的 `derivedRoles` 列表里引用这个派生角色,它才会对授权决定产生影响。

#### 派生角色与通配符

特殊值 `*` 可以在 `parentRoles` 里匹配任何静态角色。这对纯粹基于 resource 属性的派生角色(例如所有权)很有用,与 principal 的静态角色无关。

```yaml
definitions:
  - name: owner
    parentRoles: ["*"]
    condition:
      match:
        expr: R.attr.owner == P.id
```

### 我的理解

**1. 派生角色是「运行时算出来的角色名」,不是「另一套权限系统」。**

页面那句 "Defining a derived role only creates a named condition" 是整页最关键的一句。
派生角色本身**不授予任何权限** —— 它只是一个**带名字的条件**。
真正授权的还是 resource policy 里的规则,只不过规则的 `roles` 可以换成 `derivedRoles`。

这个区分很重要:派生角色是**语法糖**,把「条件 + 角色」打包成可复用的名字。

**2. `parentRoles` 是闸门,`condition` 是判据,两者是「与」的关系。**

派生角色激活 = 请求的静态角色命中 `parentRoles` **且** condition 求值为 true。
`parentRoles` 里的 `*` 表示「不管你是什么静态角色都算数」—— 于是可以做出纯粹基于
resource 属性的派生角色(页面给的 `owner` 例子就是)。

**3. 三道「必须做对」的门,缺一不可。** 页面给的排查清单其实就是三道门:

| 门 | 缺了会怎样 |
|---|---|
| `importDerivedRoles` 导入 | 派生角色策略存在,但 resource policy 看不到它 |
| `parentRoles` 命中 | 静态角色对不上 |
| condition 为 true | 条件不成立 |
| (外加)resource policy 有规则引用 | 定义了但没人用 |

**第 4 条是「不报错但完全无效」的那一类** —— 派生角色算出来了、`effectiveDerivedRoles`
里也有,但因为没有规则引用它,访问权限一点没变。

**4. 页面特别强调「不要把派生角色名当请求里的 roles」。**

这是因为派生角色是**运行时算出来的**,不是 IdP 发的。请求里的 `roles` 只能是静态角色。
如果调用方把 `batman` 放进请求的 roles,Cerbos 不会当成派生角色处理。

**5. `includeMeta: true` 是观测派生角色的唯一途径。**

`meta.effectiveDerivedRoles` 告诉你「为这个 principal 在这个 resource 上激活了哪些」。
本项目用过 `includeMeta` 拿 `matchedPolicy`,同一块 meta 里还有这个列表。

**6. 派生角色可以引入常量与变量。**

`constants.import` / `constants.local` / `variables.import` / `variables.local`。
例子里的 `corporate_user` 用了 `inIPAddrRange()` 做 IP 段判断——**这是 Cerbos 自带的
IP 范围判断能力**,不需要在策略里手写 CIDR 匹配。

### 与本项目的对应关系(仅记录对应关系)

| 页面概念 | 本项目对应物 |
|---|---|
| 派生角色 `name` + `importDerivedRoles` | 本项目未使用派生角色 |
| `parentRoles` + `condition` | 与「roles 省略的规则不匹配」(实测)是两套机制:`parentRoles` 是匹配静态角色,`roles` 是直接匹配 |
| `includeMeta` → `effectiveDerivedRoles` | 本项目用 `includeMeta` 取 `matchedPolicy`;`effectiveDerivedRoles` 同一块 meta |
| `inIPAddrRange()` | 本项目 IP 白名单目前没做(§4.5 决定放网络层) |
| 大小写敏感的 `parentRoles` | 与实测的「角色精确匹配、大小写敏感」一致 |

---

---

## 5. Resource policies · 资源策略

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/resource_policies

### 页面说了什么

> A resource policy contains all rules governing access to a single resource kind. Rules are evaluated per action and can reference roles, derived roles, and conditions.

一个 resource policy 包含治理**单一 resource kind** 访问的所有规则。规则按 action 求值,可以引用 roles、derived roles 和 conditions。

冲突解决协议(与 evaluation 页一致):

- 对单一角色和某个 action,若部分规则求值为 `EFFECT_ALLOW`、另一些为 `EFFECT_DENY`,整体是 **`EFFECT_DENY`**。
- 若 principal 有多个角色,且其中至少一个角色对该 action 求值为 `EFFECT_ALLOW`,整体是 **`EFFECT_ALLOW`**。这避免了 admin 用户因为恰好还挂着一个权限较低的角色而把自己锁死。

#### 结构

```yaml
---
apiVersion: api.cerbos.dev/v1
resourcePolicy:
  resource: "album:object" (1)
  version: "default" (2)
  scope: "acme.corp" (3)
  scopePermissions: SCOPE_PERMISSIONS_REQUIRE_PARENTAL_CONSENT_FOR_ALLOWS (4)
  importDerivedRoles:
    - apatr_common_roles (5)
  constants:
    import: (6)
      - apatr_common_constants
    local: (7)
      corporate_network_ip_range: 10.20.0.0/16
  variables:
    import: (8)
      - apatr_common_variables
    local: (9)
      is_corporate_network: |-
        request.principal.attr.ip_address.inIPAddrRange(constants.corporate_network_ip_range)
  rules:
    - actions: ['*'] (10)
      effect: EFFECT_ALLOW
      derivedRoles:
        - owner (11)

    - actions: ['view']
      effect: EFFECT_ALLOW
      roles:
        - user (12)
      condition:
        match:
          expr: request.resource.attr.public == true
      output: (13)
        when:
          ruleActivated: |-
            "view_allowed:%s".format([request.principal.id])
          conditionNotMet: |-
            "view_not_allowed:%s".format([request.principal.id])

    - name: moderator_rule (14)
      actions: ['view', 'delete']
      effect: EFFECT_ALLOW
      condition:
        match:
          expr: variables.is_corporate_network
      derivedRoles:
        - abuse_moderator
  schemas: (15)
    principalSchema:
      ref: cerbos:///principal.json (16)
    resourceSchema:
      ref: cerbos:///album/object.json (17)
```

| 标注 | 含义 |
|---|---|
| (1) | 这份策略适用的 resource kind |
| (2) | 策略的版本。**策略由 resource 名和版本这一对唯一标识**。同一个 resource 可以有多个版本(如生产 vs 预发布)。版本值 `default` 是特殊的:请求里没指定版本时的默认兜底 |
| (3) | 这份策略的可选 [scope](https://docs.cerbos.dev/cerbos/latest/policies/scoped_policies) |
| (4) | 这份策略的可选 [scope permission](https://docs.cerbos.dev/cerbos/latest/policies/scope_permissions),默认是 `SCOPE_PERMISSIONS_OVERRIDE_PARENT` |
| (5) | 导入一组 [derived roles](https://docs.cerbos.dev/cerbos/latest/policies/derived_roles)(可选) |
| (6) | 要导入的常量定义(可选) |
| (7) | 本地常量定义(可选) |
| (8) | 要导入的变量定义(可选) |
| (9) | 本地变量定义(可选) |
| (10) | action 可以包含通配符。通配符遵守 `:` 分隔符。例如 `a:*:d` 匹配 `a:x:d` 但不匹配 `a:x` |
| (11) | 这条规则适用于一个派生角色 |
| (12) | 规则也可以直接引用静态角色。特殊值 `*` 可以在求值这条规则时**忽略角色** |
| (13) | action 规则的可选 output。可以定义可选表达式,根据规则是**激活**还是**因条件不满足而未激活**来求值 |
| (14) | 规则的可选名字 |
| (15) | 可选部分,定义适用于这个 resource kind 的 schemas |
| (16) | 可选 schema,用于校验 principal 属性 |
| (17) | 可选 schema,用于校验 resource 属性 |

#### 两条硬性约束

> **Each policy must be defined in its own file. You cannot define multiple policies in a single YAML or JSON file.**

每份策略必须定义在**自己的文件**里。不能在同一个 YAML 或 JSON 文件里定义多份策略。

(页面指向 policy repository layout 那一节看怎么组织文件。)

### 我的理解

**1. 策略的身份是 `(resource, version)` 这一对。**

标注 (2) 说得很明确。而且 `default` 是特殊的兜底版本——**请求里不指定版本时用它**。
这解释了本项目实测到的 policy id 形式:`resource.basicResource.vdefault`,
即 `resource.<kind>.<version>` 的结构。

**2. 一个 kind 只能有一份策略(同一版本下)。**

「一份 resource policy 包含治理单一 resource kind 的所有规则」+「每份策略必须在
自己的文件里」+「策略由 resource 名和版本唯一标识」—— 三句合起来:
**同一个 (kind, version) 只能有一份策略文件。**

所以要按 kind 拆分权限,得用不同的 kind(本项目的 `basicResource` / `fdepApi`),
或者用 scope(标注 3)、或用不同版本。

**3. 通配符的边界规则在这一页给了第二个例子。**

`a:*:d` 匹配 `a:x:d` 但不匹配 `a:x`。和 evaluation 页的 `view:*` 一致:
**通配符匹配的是「至少一层」,不是「零层或更多」**。`*` 填的是恰好一层。

**4. `roles: ["*"]` 在规则里的含义是「忽略角色」。**

标注 (12) 说得很直接:「特殊值 `*` 可以在求值这条规则时 disregard roles」。
这和 `parentRoles: ["*"]`(derived roles 页)是**两个不同位置的 `*`**:
- `parentRoles: ["*"]` = 任何静态角色都触发这个派生角色
- `roles: ["*"]` = 这条规则不看 principal 有什么角色

后者意味着**这条规则对所有人生效**——这正是之前实测的「省略 `roles` 会让整个
policy 失效」的**正确写法**。

**5. `output` 有两个分支:`ruleActivated` 和 `conditionNotMet`。**

标注 (13) 说的是「根据规则是激活还是因条件失败而未激活」。这意味着 output 不只
在放行时产生,**拒绝时也能产生**——所以它可以用来记录「为什么没放行」。

**6. `scopePermissions` 的默认值是 `SCOPE_PERMISSIONS_OVERRIDE_PARENT`。**

这是 scope 相关的第一个具体值;之前 scope 一直没匹配上,这一页提示了
「scope 层级查找」之外还有「scope 权限」这一层。具体语义在 scope_permissions 页。

**7. `schemas` 是 resource policy 的可选部分,两个 ref 分开。**

`principalSchema` 校验 principal 属性,`resourceSchema` 校验 resource 属性。
这和本项目实测到的「每个 policy 可以引用自己的 principal schema」一致——
**schema 是按 policy 声明的**,所以同一份 principal 属性,不同 policy 可以有
不同的词汇表。

### 与本项目的对应关系(仅记录对应关系)

| 页面概念 | 本项目对应物 |
|---|---|
| `(resource, version)` 唯一标识 | `resource.basicResource.vdefault` / `resource.fdepApi.vdefault` |
| 版本 `default` 是请求不指定版本时的兜底 | 请求里不带 `policyVersion` 时命中它 |
| 一个 kind 一份策略文件 | `policies/resource_policies/basicResource.yaml` 一个文件一个 kind |
| `actions` 通配符遵守 `:` 边界 | 实测 `view:*` 不匹配 `view`;`a:*:d` 不匹配 `a:x` |
| `roles: ["*"]` = 忽略角色 | 这就是「catch-all DENY」的正确写法(实测省略 `roles` 会让整个 policy 失效) |
| `schemas` 两个 ref 分开 | 实测:每个 policy 可引用自己的 principal schema,互不影响 |
| `scopePermissions` 默认 `SCOPE_PERMISSIONS_OVERRIDE_PARENT` | 与 scope 一起读,细节在 scope_permissions 页 |

---

---

## 6. Principal policies · 主体策略

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/principal_policies

### 页面说了什么

> Principal policies define overrides for a specific user.

主体策略为**特定用户**定义覆盖。

#### 结构

```yaml
---
apiVersion: "api.cerbos.dev/v1"
principalPolicy:
  principal: daffy_duck (1)
  version: "dev" (2)
  scope: "acme.corp" (3)
  scopePermissions: SCOPE_PERMISSIONS_REQUIRE_PARENTAL_CONSENT_FOR_ALLOWS (4)
  constants:
    import: (5)
      - apatr_common_constants
    local: (6)
      test_department_id: 12345
  variables:
    import: (7)
      - apatr_common_variables
    local: (8)
      is_dev_record: |-
        request.resource.attr.dev_record == true || request.resource.attr.department_id == constants.test_department_id
  rules:
    - resource: leave_request (9)
      actions:
        - name: dev_record_wildcard (10)
          action: "*" (11)
          condition: (12)
            match:
              expr: variables.is_dev_record
          effect: EFFECT_ALLOW
          output: (13)
            when:
              ruleActivated: |-
                "wildcard_override:%s".format([request.principal.id])
              conditionNotMet: |-
                "wildcard_condition_not_met:%s".format([request.principal.id])

    - resource: employee_profile
      actions:
        - name: view_employee_profile
          action: "*"
          condition:
            match:
              all:
                of:
                  - expr: variables.is_dev_record
                  - expr: request.resource.attr.public == true
          effect: EFFECT_ALLOW

    - resource: salary_record
      actions:
        - action: "*"
          effect: EFFECT_DENY
```

| 标注 | 含义 |
|---|---|
| (1) | 这份策略适用的 principal |
| (2) | 策略的版本。**策略由 principal 名和版本这一对唯一标识**。同一个 principal 可以有多个版本(如生产 vs 预发布)。版本值 `default` 是特殊的:请求里没指定版本时的默认兜底 |
| (3) | 这份策略的可选 scope |
| (4) | 这份策略的可选 scope permission,默认是 `SCOPE_PERMISSIONS_OVERRIDE_PARENT` |
| (5) | 要导入的常量定义(可选) |
| (6) | 本地常量定义(可选) |
| (7) | 要导入的变量定义(可选) |
| (8) | 本地变量定义(可选) |
| (9) | 这个覆盖适用的 resource。**这里支持通配符** |
| (10) | 规则的可选名字 |
| (11) | 可以在该 resource 上执行的 action。**这里也支持通配符** |
| (12) | 匹配这条规则所需的可选条件 |
| (13) | action 规则的可选 output。根据规则是**激活**还是**因条件失败而未激活**分别求值 |

### 我的理解

**1. Principal policy 的粒度是「一个人 × 一个版本」。**

和 resource policy 的 `(kind, version)` 完全平行 —— 标注 (2) 用的是同一句话:
「策略由 X 名和版本这一对唯一标识」。所以主体策略的 id 形式应该是
`principal.<name>.v<version>`。

**2. 规则的结构和 resource policy 不同:多了 `resource` 维度。**

| | resource policy | principal policy |
|---|---|---|
| 规则按什么分组 | 按 action | 按 **resource**,再按 action |
| action 怎么写 | `actions: [...]`(列表) | `actions:` 下面是 `{name, action, condition, effect, output}` 的**对象列表** |

resource policy 里一条规则可以管多个 action;principal policy 里每条规则只管一个
action,但可以写 `action: "*"` 覆盖该 resource 的全部 action。

**3. 通配符出现在两个位置,粒度不同。**

- `resource: leave_request` 这一层支持通配符 → 「这个覆盖适用于哪些 resource」
- `action: "*"` → 「该 resource 上的哪些 action」

而 `leave_request` 的 action 实际是 `view:leave` 这样的层级名,`*` 填的是恰好一层
(和前两页的规则一致)。

**4. `condition` 可以用 `all` / `of` 组织多个表达式。**

第二个规则用了:

```yaml
condition:
  match:
    all:
      of:
        - expr: variables.is_dev_record
        - expr: request.resource.attr.public == true
```

这是 CEL 的标准写法 —— 多个子表达式用 `all.of`(全部成立)或 `any.of`(任一成立)组合。

**5. 主体策略是「覆盖」,而且能覆盖成 DENY。**

第三个规则直接 `effect: EFFECT_DENY` 作用在 `salary_record` 的全部 action 上。
结合 evaluation 页的求值顺序:principal policy 先求值,**对给出明确结论的 action
就是最终结果,resource policy 不再被查**。

所以主体策略能**单方面否决** resource policy 会给的允许。

**6. `scopePermissions` 和 `constants` / `variables` 的语义与 resource policy 一致。**

连 `scopePermissions` 的默认值都是同一个 `SCOPE_PERMISSIONS_OVERRIDE_PARENT`。
说明这两种 policy 的头部字段是共用的一套结构。

### 与本项目的对应关系(仅记录对应关系)

| 页面概念 | 本项目对应物 |
|---|---|
| `(principal, version)` 唯一标识 | 本项目未使用 principal policy |
| 规则按 resource + action 分组 | 与 resource policy 的「规则按 action」结构不同 |
| `condition.match.all.of` | 本项目目前只用单表达式;`all.of` 是组合多个条件的标准写法 |
| principal policy 可单方面 DENY | evaluation 页的「principal policy 有最终决定权」 |
| `scopePermissions` 默认值 | 与 resource policy 同一个默认值 |

---

---

## 7. Role policies · 角色策略

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/role_policies

### 页面说了什么

> Role policies define the set of actions a role is permitted to perform on each resource. The allowable actions list is exhaustive: any action not listed is denied for that role.

角色策略定义一个角色在每个 resource 上被允许执行的动作集合。**允许动作列表是穷尽的**:任何没列出的动作,对该角色都被拒绝。

> Role policies are ABAC policies in which you specify a number of resources, each with a set of allowable actions that the role can carry out on the resource. Optionally, a condition can also be specified for each set of allowable actions. In the simple case, they allow you to author permissions from the view of an IdP role, rather than for a given resource.

角色策略是 ABAC 策略:指定若干 resource,每个配上一组该角色可以在其上执行的动作。可选地为每组动作指定条件。简单情况下,它让你**从 IdP 角色的视角**而不是从某个 resource 的视角来编写权限。

> Role policies are not standalone. They apply as an additive constraint on top of resource policies, so an action is only allowed if it is permitted by both the role policy and a matching resource policy. A role policy cannot grant access that the resource policy does not already allow, which means a resource policy is always required.

角色策略**不是独立生效的**。它们作为 resource policy 之上的**附加约束**,所以一个动作只有**同时**被角色策略和匹配的 resource policy 允许才被允许。角色策略无法授予 resource policy 本来不允许的访问 —— **这意味着 resource policy 总是必需的**。

> Unlike resource and principal policies, role policies do not define explicit `ALLOW` or `DENY` effects. Instead, the allowable actions act as an exhaustive list of actions allowed on each resource. Any resource and action pair not defined in this list is immediately denied for that role.

与 resource policy 和 principal policy 不同,角色策略**不定义显式的 `ALLOW` 或 `DENY` 效果**。取而代之,允许动作充当每个 resource 上允许动作的穷尽列表。任何没在这个列表里定义的 resource 与 action 组合,**立即**对该角色拒绝。

> The name of a role policy is effectively a custom role within the context of Cerbos. A role policy (custom role) can optionally define `parentRoles`, inheriting and narrowing their permissions by default. **The policy can only define rules that are a strict subset of the parent role's permissions and cannot introduce any extra rules beyond what the parent roles allow.** They can immediately DENY an action but if they ALLOW an action, a parent policy higher up the scope chain must also ALLOW the same action.

角色策略的名字在 Cerbos 语境下实际上就是一个**自定义角色**。角色策略(自定义角色)可选地定义 `parentRoles`,默认继承并收窄它们的权限。**这份策略只能定义父角色权限的严格子集,不能引入超出父角色允许范围的任何额外规则。** 它们可以立即 DENY 某个动作;但如果它们 ALLOW 某个动作,scope 链上更高层的父策略也必须 ALLOW 同一个动作。

> A parent role can be either an arbitrary IdP role or the name of another role policy within the system. Parent role resolution is recursive—if a custom role inherits from another custom role that also has parent roles, it inherits and narrows their permissions as well.

父角色可以是任意 IdP 角色,也可以是系统内另一份角色策略的名字。**父角色解析是递归的** —— 如果一个自定义角色继承自另一个也有 parent roles 的自定义角色,它会一并继承并收窄那些权限。

#### 结构

```yaml
---
apiVersion: api.cerbos.dev/v1
rolePolicy:
  role: "acme_admin" (1)
  version: "default" (2)
  scope: "acme.hr.uk" (3)
  parentRoles: (4)
    - admin
  constants:
    import: (5)
      - apatr_common_constants
    local: (6)
      corporate_network_ip_range: 10.20.0.0/16
  variables:
    import: (7)
      - apatr_common_variables
    local: (8)
      is_corporate_network: |-
        P.attr.ip_address.inIPAddrRange(constants.corporate_network_ip_range)
  rules:
    - resource: leave_request (9)
      allowActions: (10)
        - view:* (11)
        - deny

    - resource: salary_record
      name: salary_record_owner (12)
      allowActions:
        - edit
      condition: (13)
        match:
          expr: R.attr.owner == P.id && variables.is_corporate_network
      output: (14)
        when:
          ruleActivated: |-
            "salary_record_edited:%s".format([P.id])
          conditionNotMet: |-
            "salary_record_edit_blocked:%s".format([P.id])

    - resource: "*" (15)
      allowActions: ["create"]
```

| 标注 | 含义 |
|---|---|
| (1) | 这份策略适用的 role |
| (2) | 策略的版本。**策略由 role 名和版本这一对唯一标识**。同一个 role 可以有多个版本。版本值 `default` 是特殊的:请求里没指定版本时的默认兜底 |
| (3) | 这份策略的可选 principal scope |
| (4) | 这个自定义角色继承的父角色列表 |
| (5) | 要导入的常量定义(可选) |
| (6) | 本地常量定义(可选) |
| (7) | 要导入的变量定义(可选) |
| (8) | 本地变量定义(可选) |
| (9) | 下面这条规则适用的 resource |
| (10) | 该角色可以在给定 resource 上执行的动作列表 |
| (11) | 支持通配符动作 |
| (12) | 规则的可选名字 |
| (13) | 动作被允许所需满足的条件 |
| (14) | action 规则的可选 output |
| (15) | **也支持通配符 resource** |

### 我的理解

**1. 角色策略是「白名单」语义,不是「决策」语义。**

这是它和另外两种策略最根本的区别:

| 策略 | 规则怎么写 | 没命中时 |
|---|---|---|
| Resource policy | `effect: EFFECT_ALLOW` / `EFFECT_DENY` | 默认拒绝 |
| Principal policy | `effect: EFFECT_ALLOW` / `EFFECT_DENY` | 落到 resource policy |
| **Role policy** | **`allowActions: [...]`** | **该 resource+action 立即被拒** |

所以角色策略里**没有 `effect` 字段**。它不产出决定,只产出**允许清单**。

**2. 「穷尽」这个性质意味着角色策略会主动收窄。**

页面反复强调 "exhaustive"、"immediately denied"、"additive constraint"。
所以哪怕 resource policy 允许了 `view`,只要角色策略没把 `view` 列进
`allowActions`,该角色照样被拒。

**这两条合起来就是 evaluation 页那句话的完整含义:**
「一个 action 要被允许,必须同时被 role policy 和 resource policy 允许」。

**3. `parentRoles` 只能收窄,不能扩张。**

页面给了一个很精确的说法:**「只能定义父角色权限的严格子集」**,以及
「可以立即 DENY 某个动作;但如果 ALLOW 某个动作,scope 链上更高层的父策略
也必须 ALLOW 同一个动作」。

也就是说,自定义角色之间的继承是**单调收窄**的:
- 继承来的权限,子角色可以再删(加 condition、加 DENY)
- 但不能加父角色没有的

**4. 父角色可以是自己。**

「父角色可以是任意 IdP 角色,也可以是系统内另一份角色策略的名字」,而且解析是递归的。
所以角色策略能构成**一棵自定义角色的树**,根是 IdP 角色。

**5. 通配符出现在两个维度。**

| 位置 | 例子 | 含义 |
|---|---|---|
| `resource` | `"*"` | 这个规则适用于所有 resource |
| `allowActions` | `view:*` | 该 resource 上的这一类动作 |

而 `view:*` 是「恰好一层」——和前几页的规则一致。

**6. 角色策略天然是 ABAC。**

页面说得很直接:「角色策略是 ABAC 策略」。因为每组 `allowActions` 可以带 condition
(`R.attr.owner == P.id && variables.is_corporate_network`),
所以同一条规则能按属性细分。

### 与本项目的对应关系(仅记录对应关系)

| 页面概念 | 本项目对应物 |
|---|---|
| `(role, version)` 唯一标识 | 本项目未使用 role policy |
| `allowActions` 白名单,穷尽 | 与 resource policy 的 `effect` 是两套语义 |
| 角色策略永远需要 resource policy 配合 | 本项目只有 resource policy,不需要这层 |
| `parentRoles` 只能收窄 | 与 derived roles 的 `parentRoles` 是**不同**的机制:那个匹配静态角色,这个继承并收窄另一份角色策略的权限 |
| `resource: "*"` + `allowActions` | 与本项目 §5.2.2 讨论的批量授权是不同层次:那是 resource policy 内的 condition,这是 role policy 的规则粒度 |

---

---

## 8. Scoped policies · 作用域策略

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/scoped_policies

### 页面说了什么

#### 三条前置说明

> Scoped Policies are optional and are only evaluated if a "scope" is passed in the request, and there are matching "scope" attributes defined in the policies.

作用域策略是可选的,**只有在请求里传了 scope、且策略里有匹配的 scope 属性时才会被求值**。

> Empty scope can also be represented by setting the "scope" to value "." in the request.

空 scope 也可以用请求里的 `scope` 设为 `"."` 来表示。

> Resource and principal policies can define "scopePermissions", which affects how rules are applied across scopes.

Resource policy 和 principal policy 可以定义 `scopePermissions`,它影响规则如何跨 scope 应用。

#### 用途

> Scoped policies offer a way to model hierarchical relationships that regularly occur in many situations. Typically, the requirement is to have a base set of policies that can then be overridden for specific cases.

作用域策略提供一种方式,建模很多场景里经常出现的层级关系。典型需求是:有一套**基础策略**,然后针对特定情况**覆盖**它。

页面举了两个例子:多租户 SaaS 有一套标准访问规则,再按不同租户定制;大型组织想做区域或部门级的定制。

#### 结构

```yaml
apiVersion: api.cerbos.dev/v1
resourcePolicy:
  version: "default"
  scope: "acme.corp" (1)
  scopePermissions: SCOPE_PERMISSIONS_OVERRIDE_PARENT (2)
  resource: "album:object"
  rules:
    - actions: ['*']
      effect: EFFECT_ALLOW
      roles: ["admin"]
```

| 标注 | 含义 |
|---|---|
| (1) | Scope 定义 |
| (2) | Scope permissions 设置 |

> The value of `scope` is a dot-separated string where each dotted segment defines an ancestor.

`scope` 的值是**点号分隔**的字符串,每个点分段定义一层祖先。

求值时,Cerbos 引擎**从最具体的 scoped policy 开始,沿层级往上走**。以 scope `a.b.c` 为例,引擎最多处理四份策略得出最终决定:

- scope `a.b.c`
- scope `a.b`
- scope `a`
- scope `""`(无 scope)

**resource 和 principal 各自可以有自己的 scope。** 请求示例:

```json
{
  "requestId": "test01",
  "actions": ["view", "comment"],
  "resource": {
    "kind": "album:object",
    "policyVersion": "default",
    "scope": "customer.abc", (1)
    "instances": {
      "XX125": {
        "attr": { "owner": "alicia", "public": false, "tags": ["x", "y"] }
      }
    }
  },
  "principal": {
    "id": "alicia",
    "policyVersion": "default",
    "scope": "customer", (2)
    "roles": ["user"],
    "attr": { "geography": "GB" }
  }
}
```

| 标注 | 含义 |
|---|---|
| (1) | 可选的 resource scope |
| (2) | 可选的 principal scope |

#### 使用要点

- **没有任何 scope 定义的策略永远是基础策略。** 如果请求没指定任何 scope,就用它。
- **同一个 scope 内,scope permissions 必须一致。** 如果检测到同一 scope 内的策略有冲突的 `scopePermissions` 设置,**构建时会报错**。
- **scope 遍历行为取决于 `scopePermissions`**:
  - `SCOPE_PERMISSIONS_OVERRIDE_PARENT`:第一个返回决定的策略对每个 action 获胜。
  - `SCOPE_PERMISSIONS_REQUIRE_PARENTAL_CONSENT_FOR_ALLOWS`:叶子节点只能**收窄**访问,且必须符合父级权限。
- **策略链里不能有缺口。** 例如定义了 scope `a.b.c`,那么 scope `a.b`、`a` 和无 scope 的策略也应当存在于策略仓库里。
- **整条链上的 Schemas 必须相同。** 用于校验请求的 schema 取自**基础策略**(无 scope 的那个);链上其他策略里定义的 schema 会被忽略。
- **首个匹配获胜(用 `SCOPE_PERMISSIONS_OVERRIDE_PARENT` 时)**:作用域策略从最具体到最不具体求值。**第一个为某个 action 产生决定(ALLOW/DENY)的策略就是赢家。** 剩下的策略不能覆盖该 action 的决定。
- **父级约束生效(用 `SCOPE_PERMISSIONS_REQUIRE_PARENTAL_CONSENT_FOR_ALLOWS` 时)**:最具体的策略只能**进一步收窄**权限,不能授予新的。
- **派生角色和变量需要显式导入**:变量和派生角色的导入**在策略之间不继承**。需要它们的每个策略都要显式导入派生角色、重新定义变量。
- **除非开启 [lenient scope search](https://docs.cerbos.dev/cerbos/latest/configuration/engine#lenient_scopes)**,否则 store 里必须存在一个与 API 请求里请求的 scope **完全匹配**的策略文件。

### 实测补充(2026-10-30,对着线上 PDP 0.57.0)

官方文档说「从最具体的 scoped policy 开始,沿 scope 层级往上走」。**实测下来,
这条链的行为比文档描述的更严格**,有三条必须知道:

**① 存进 store 的 id 格式是 `<kind>.v<version>/<scope>`。**

```
resource.fdepApi.vdefault            ← 无 scope 的基础 policy
resource.fdepApi.vdefault/jev        ← scope: jev 的 policy
```

**② 请求的 scope 必须有对应的 policy,否则 `NO_MATCH` —— 基础 policy 不是兜底。**

| 请求 | 结果 |
|---|---|
| scope=`jev`(有这份 policy) | 按 jev 的规则判 |
| scope=`other`(**没有**这份 policy) | **`NO_MATCH`**,所有 action 被拒 |
| scope=`jev.child`(jev 有,jev.child 没有) | **`NO_MATCH`**,所有 action 被拒 |

**注意第二行:基础 policy 的规则完全没被咨询。** 这和「往上走」的直觉相反 ——
链是「必须有」,不是「可选的兜底」。

**③ scope 存在时,基础 policy 仍然会被咨询,但更具体的 scope 优先。**

同一个角色在基础 policy 里 ALLOW、在 scoped policy 里 DENY → **scoped 赢**(DENY)。

### 我的理解

**1. Scope 是「同名策略的多实例」,不是「资源的层级」。**

这是最关键的一点。`scope: acme.corp` 的策略和 `scope: acme` 的策略,**resource kind 和 version 都一样**,区别只在 scope 字符串。所以:

**同一个 (kind, version) 可以有多个策略实例**,用 scope 区分。
而前几页说过「一份 resource policy 包含治理单一 resource kind 的所有规则」——
这两句合起来:同一 kind+version 下,scope 是唯一的区分维度。

**2. scope 层级用 `.` 分隔,和 action 层级用 `:` 分隔是两套独立的分隔符。**

页面明确写 scope 是 "dot-separated",而 action / resource 名是 `:` 分隔。
两者不共用边界 —— 这和「通配符遵守 `:` 分隔符」是不同的事。

**3. 两条「必须一致」和「不能有缺口」的约束,是构建期检查。**

- 同一 scope 内 `scopePermissions` 冲突 → **构建时报错**
- 链上有缺口(scope `a.b.c` 存在但 `a.b` 不存在)→ 不构成错误,但**行为会退化**

第二条我理解为:查找是从最具体往上的,缺一层只是少一个候选,不会崩。但配合下面这条就危险了。

**4. 「store 里必须有完全匹配的 scope 策略」这条,解释了之前实测到的现象。**

页面最后一条:除非开 lenient scope search,**必须存在一个与请求 scope 完全匹配的策略文件**。

本项目之前实测:推了 `scope: systemone` 的策略,store 里存成
`resource.fdepApi.vdefault/systemone`,请求带 `scope: systemone` 却
`matchedPolicy=NO_MATCH`。**按这一页,原因很可能是「链上有缺口」**——
`systemone` 存在,但 `systemone` 的父级(无 scope 的基础策略)也必须存在。
我那次测试里,推 scoped 策略前先硬删掉了同 kind 的无 scope 策略,
所以基础策略缺失,查找链断了。

这正好对应「There must be no gaps in the policy chain」。

**5. 两种 scopePermissions 是两种完全不同的组合语义。**

| | `OVERRIDE_PARENT`(默认) | `REQUIRE_PARENTAL_CONSENT_FOR_ALLOWS` |
|---|---|---|
| 谁赢 | 最具体的策略说了算 | 最具体的只能收窄 |
| 叶子能否授予父级没有的 | **能** | **不能** |
| 层次 | 类似「覆盖」 | 类似「交集」 |

第二种更安全,适合「全局基线 + 局部收紧」的场景。

**6. 变量和派生角色在 scope 链上不继承。**

页面专门加粗了 "Explicit imports for derived roles and variables"。
这条很容易踩:以为在基础策略里 import 了变量,scoped 策略里就能用 —— 不能,
每个策略都要自己 import、自己定义变量。

**7. schema 取自基础策略,链上其他策略的 schema 被忽略。**

这条和「整条链上的 Schemas 必须相同」是配套的。因为校验请求时只认基础策略的
schema,所以如果链上其他策略声明了不同的 schema,它们不会生效 —— 静默失效。

### 与本项目的对应关系(仅记录对应关系)

| 页面概念 | 本项目对应物 |
|---|---|
| scope 是同名策略的多实例,靠 scope 区分 | 本项目未使用 scope;每个 kind 只有一份无 scope 的策略 |
| 「store 里必须有完全匹配的 scope 策略」+「链上不能有缺口」 | **可能解释之前实测的 scope 未命中**:推 scoped 策略时基础策略被硬删,查找链断裂 → `matchedPolicy=NO_MATCH` |
| scope 用 `.` 分隔,action 用 `:` 分隔 | 两套独立分隔符 |
| `SCOPE_PERMISSIONS_OVERRIDE_PARENT` 是默认值 | 与 resource / principal / role policy 页标注的默认值一致 |
| scope 链上 schema 取自基础策略 | 与「每个 policy 可引用自己的 principal schema」是**不同层面**:后者是不同 kind 之间,前者是同 kind 的 scope 链之间 |
| 变量 / 派生角色在 scope 链上不继承 | 本项目未使用变量 / 派生角色 |

---

---

## 9. Scope Permissions · 作用域权限

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/scope_permissions

### 页面说了什么

> `scopePermissions` is a setting applied to resource and principal policies that impacts how rules are evaluated within a scope hierarchy. It defines whether policies in a given scope can **override** parent scope rules or whether they can only **restrict** the permissions granted by parent scopes.

`scopePermissions` 是应用在 resource policy 和 principal policy 上的设置,影响规则在 scope 层级里如何求值。它决定某个 scope 里的策略**可以覆盖**父 scope 的规则,还是**只能收窄**父 scope 授予的权限。

> All resource or principal policies within the same scope **must** use the same `scopePermissions` setting. If conflicting settings are detected within a shared scope, a build-time error will occur.

同一 scope 内的所有 resource / principal policy **必须**用同一个 `scopePermissions` 设置。检测到同一 scope 内有冲突设置时,**构建时会报错**。

两个可选值:`SCOPE_PERMISSIONS_OVERRIDE_PARENT`、`SCOPE_PERMISSIONS_REQUIRE_PARENTAL_CONSENT_FOR_ALLOWS`。

> By default, resource and principal policies use `SCOPE_PERMISSIONS_OVERRIDE_PARENT` unless explicitly set otherwise.

默认是 `SCOPE_PERMISSIONS_OVERRIDE_PARENT`。

#### SCOPE_PERMISSIONS_OVERRIDE_PARENT

> This is the default evaluation strategy for scoped policies. Cerbos starts evaluating policies from the bottom of the scope chain and moves up. The first policy to produce a decision for a given action is the winner. Any policies further up the chain cannot influence that decision.

这是作用域策略的默认求值策略。Cerbos **从 scope 链的底部开始求值,往上走**。**第一个为某个 action 产生决定的策略就是赢家。** 链上更上层的策略无法影响那个决定。

- 如果输入匹配到某条规则**且其 condition 成立**,就应用指定的效果(不需要检查父级)。
- 如果规则匹配了**但 condition 不成立**,或者规则没匹配上,求值继续往上走。

#### SCOPE_PERMISSIONS_REQUIRE_PARENTAL_CONSENT_FOR_ALLOWS

> When a policy is configured with `scopePermissions: SCOPE_PERMISSIONS_REQUIRE_PARENTAL_CONSENT_FOR_ALLOWS`, it **inherits and restricts** the permissions of parent scopes. Policies at this level must define rules within the maximum set of permissions allowed by parent policies—they cannot introduce new permissions that exceed what a parent scope already permits.

这个设置下,策略**继承并收窄**父 scope 的权限。这一层的策略必须在父策略允许的最大权限集合内定义规则 —— **不能引入超出父 scope 已允许的新权限**。

> In this mode, an `ALLOW` rule that matches an action doesn't immediately generate an `ALLOW` decision. A parent policy higher up in the scope chain must also `ALLOW` that same action in order to produce a definitive decision. However, if a rule is matched but its condition is not met, the request is implicitly denied.

在这个模式下,一条匹配上的 `ALLOW` 规则**不会立即产生 `ALLOW` 决定**。必须链上更高层的父策略也 `ALLOW` 同一个 action,才能产生确定决定。**但如果规则匹配了而 condition 不成立,请求被隐式拒绝。**

- 如果输入没匹配上,求值继续往上走。
- 如果规则匹配了但 condition 不成立,**发出隐式 DENY**。
- 如果规则匹配且 condition 成立,求值继续到父策略,验证该 action 在更高层也被允许。

### 实测补充(2026-10-30)

把「基础 policy ALLOW 某个角色 / scoped policy DENY 同一个角色」推上去,请求带 scope:

| 请求 | 结果 | 说明 |
|---|---|---|
| scope=`jev`,该角色 | **DENY** | scoped 的 DENY 赢过基础的 ALLOW |
| scope=`jev`,只有基础有规则的角色 | 按基础判 | scoped 没有匹配规则时会继续往下走 |
| scope=`other`(无 scoped policy) | **NO_MATCH** | 连基础 policy 都不被咨询 |

### 我的理解

**1. 两种模式的差别,核心在「一条 ALLOW 规则能独立成立吗」。**

| | `OVERRIDE_PARENT` | `REQUIRE_PARENTAL_CONSENT_FOR_ALLOWS` |
|---|---|---|
| 一条匹配的 ALLOW 规则 | **立即决定**,不看父级 | **不能单独成立**,父级也要 ALLOW |
| condition 不成立 | **继续往上走** | **立即隐式 DENY** |
| 语义 | 覆盖(override) | 交集(require consent) |
| 叶子能否授予父级没有的 | 能 | 不能 |

**第二个差别比第一个更容易踩。** `OVERRIDE_PARENT` 下 condition 不成立是「这一层不管,看父级」;
`REQUIRE_PARENTAL_CONSENT` 下 condition 不成立是「**就地拒绝**」。

**2. `REQUIRE_PARENTAL_CONSENT` 的 condition 不成立会「就地终止」,这是它更安全的地方。**

页面写得很明确:「if a rule is matched but its condition is not met, an implicit DENY is issued」。

所以在这个模式下,「这一层说了不」就是最终的不,不用看父级 —— 层级收窄是**单调**的:
父级给允许,子级可以用 condition 把它收掉,而且收掉之后不会因为父级允许而复活。

而 `OVERRIDE_PARENT` 下,condition 不成立会往上走,父级可能又允许了 —— 收窄不彻底。

**3. 「first policy to produce a decision wins」是逐 action 的。**

页面反复强调 "for a given action"。所以同一个请求里,不同的 action 可能由**不同层级**的策略决定:

- action X:叶子策略匹配且 condition 成立 → 叶子说了算
- action Y:叶子策略没匹配 → 往上走,由父级决定

**4. 默认值是 `OVERRIDE_PARENT`,但它是「更宽松」的那个。**

页面特意说明默认值。如果一个组织想「全局基线 + 局部只能收紧」,必须**显式**在每个 scope 的策略里写 `REQUIRE_PARENTAL_CONSENT_FOR_ALLOWS` —— 而且同一 scope 内必须全部一致,否则构建报错。

**5. 这两种模式不能混用,是因为混用时「谁赢」无法确定。**

同 scope 内冲突 → 构建时报错。所以这不是「运行时的歧义」,是「部署时就拦住」。

### 与本项目的对应关系(仅记录对应关系)

| 页面概念 | 本项目对应物 |
|---|---|
| `scopePermissions` 只作用于 resource / principal policy | 本项目未使用 scope,所以未使用这个设置 |
| 默认 `OVERRIDE_PARENT` | 与 resource / principal / role policy 页标注的默认值一致 |
| condition 不成立:一边往上走、一边就地 DENY | 这两种差别是 scope 模式的核心;本项目暂不涉及 |
| 同 scope 内冲突 → 构建报错 | 与本项目实测到的「policy 推送返回 200 但 `matchedPolicy=NO_MATCH`」是不同层面的问题(那个是查找链缺基础策略) |

---

---

## 10. Conditions · 条件表达式

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/conditions

> 页面较长,末尾的 Strings / Timestamps 两节从渲染版被截断,已从同一页的源文件
> (`docs/modules/policies/pages/conditions.adoc`)补齐,内容一致。

### 页面说了什么

#### 定义

> Conditions are CEL expressions evaluated at request time against principal, resource, and request attributes. A rule with a condition applies only when the expression evaluates to true.

条件是 CEL 表达式,在请求时针对 principal、resource 和请求属性求值。带 condition 的规则**只在表达式求值为 true 时才适用**。

**每个条件表达式必须求值为布尔值。** 一个 condition 块可以包含单个表达式,或用
`all` / `any` / `none` 组合的多个表达式。**这些逻辑运算符可以嵌套。**

```yaml
condition:
  match:
    all:
      of:
        - expr: request.resource.attr.status == "PENDING_APPROVAL"
        - expr: >
            "GB" in request.resource.attr.geographies
```

#### 顶层标识符

| 标识符 | 内容 |
|---|---|
| `request` | check / plan 请求里提供的数据(principal、resource、辅助数据) |
| `runtime` | 求值策略时算出的额外数据 |
| `variables` | 策略 `variables` 段声明的变量 |
| `constants` | 策略 `constants` 段声明的常量 |
| `globals` | 策略引擎配置里声明的全局变量 |

**单字母别名**(用来写紧凑的表达式):

| 别名 | 全名 |
|---|---|
| `P` | `request.principal` |
| `R` | `request.resource` |
| `V` | `variables` |
| `C` | `constants` |
| `G` | `globals` |

**`request` 对象**:

```yaml
request:
  principal:
    id: alice          # (2) principal 的 ID
    roles:             # (3) 身份管理系统分配的静态角色
      - employee
    attr:              # (4) 关于 principal 的自由格式上下文数据
      geography: GB

  resource:
    kind: leave_request  # (6) resource kind
    id: XX125            # (7) resource 实例的 ID
    attr:                # (8) 关于 resource 实例的自由格式上下文数据
      owner: alice

  auxData:              # (9) 辅助数据源
    jwt:                # (10) JWT claims。与 jwts 互斥
      iss: acme.corp
    jwts:               # (11) 具名 JWT claims。Cerbos 0.55.0 起。与 jwt 互斥
      token_a:
        claims:
          iss: acme.corp
          sub: foo
      token_b:
        claims:
          iss: acme.corp
          sub: bar
```

**`runtime` 对象**:

```yaml
runtime:
  effectiveDerivedRoles:   # (1) Cerbos 求值时赋给 principal 的派生角色
    - owner
    - gb_employee
```

(1) 只在 **resource policy** 的表达式里有值,且只包含**至少被一条策略规则引用过**的派生角色。

#### 表达式与块

**单个布尔表达式**:

```yaml
condition:
  match:
    expr: P.id.matches("^dev_.*")
```

**`all`**:全部表达式都为 true(逻辑与)。
**`any`**:只要有一个为 true(逻辑或)。
**`none`**:没有一个为 true(逻辑非)。

**嵌套**:

```yaml
condition:
  match:
    all:
      of:
        - expr: R.attr.status == "DRAFT"
        - any:
            of:
              - expr: R.attr.dev == true
              - expr: R.attr.id.matches("^[98][0-9]+")
        - none:
            of:
              - expr: R.attr.qa == true
              - expr: R.attr.canary == true
```

等价于:

```yaml
condition:
  match:
    expr: >
      (R.attr.status == "DRAFT" &&
        (R.attr.dev == true || R.attr.id.matches("^[98][0-9]+")) &&
        !(R.attr.qa == true || R.attr.canary == true))
```

#### 引号

单引号和双引号在 YAML 里有特殊含义。为避免表达式含引号时解析出错,
用 YAML 块标量语法,或把表达式包在括号里:

```yaml
expr: >
  "GB" in R.attr.geographies
```
```yaml
expr: ("GB" in R.attr.geographies)
```

#### ⚠️ 运行时错误的后果

> A CEL **runtime error** while evaluating a condition (for example comparing incompatible types such as `R.attr.amount > 1000` when `amount` is a string, or referencing a missing attribute) causes the condition to be treated as not satisfied. For `ALLOW` rules this fails closed: the rule simply does not match. For `DENY` rules it currently fails **open**: the deny is skipped, so a matching `ALLOW` can still grant the request.
>
> From Cerbos v0.55 a `DENY` rule whose condition raises a runtime error will fail closed (the deny is applied). Cerbos v0.54 logs every runtime error raised during evaluation and includes the errors in audit log entries so you can find and fix affected policies before upgrading. The `engine.celErrorLogLevel` setting controls the level of the log messages.

求值条件时发生 CEL **运行时错误**(例如比较不兼容的类型,如 `amount` 是字符串时写
`R.attr.amount > 1000`;或引用了不存在的属性),会让该条件被当作**未满足**。

- 对 `ALLOW` 规则:这是**失败即拒绝**——规则 Simply 不匹配。
- 对 `DENY` 规则:**Cerbos v0.55 之前是失败即放行**——deny 被跳过,一条匹配的
  `ALLOW` 仍可能放行请求。

**从 Cerbos v0.55 起**,condition 抛运行时错误的 `DENY` 规则改为**失败即拒绝**
(deny 生效)。Cerbos v0.54 会记录求值期间的每个运行时错误,并把错误放进审计日志条目,
方便在升级前找到并修好受影响的策略。`engine.celErrorLogLevel` 设置控制日志级别。

#### 辅助数据

配置了辅助数据源后,用 `request.auxData` 访问。

```yaml
"cerbie" in request.auxData.jwt.aud && request.auxData.jwt.iss == "cerbos"
```

具名 JWT claims(Cerbos 0.55.0 起):

```yaml
"cerbie" in request.auxData.jwts.token_a.claims.aud && request.auxData.jwts.token_b.claims.iss == "cerbos"
```

多个 JWT 时的语法是 `request.auxData.jwts.TOKEN_NAME.claims.CLAIM_NAME`,
注意 token 名和 claim 名之间的 `claims` 是必需字段。

#### 运算符

CEL 内置函数和运算符很多,完整列表在 cel-spec 的 langdef.md。常用:

| 运算符 | 含义 |
|---|---|
| `!` | 逻辑非 |
| `&&` / `\|\|` | 逻辑与 / 逻辑或 |
| `==` / `!=` | 相等 / 不等 |
| `<` `<=` `>` `>=` | 比较 |
| `+` `-` `*` `/` `%` | 算术 / 字符串拼接 |
| `in` | 在列表或 map 中的成员判断 |
| `? :` | 三元条件 |

#### Durations

时长值必须用以下单位之一指定。**更大的单位(天、周、年)不支持**,因为夏令时切换等因素
使它们的含义有歧义。

| 后缀 | 单位 |
|---|---|
| `ns` | 纳秒 |
| `us` | 微秒 |
| `ms` | 毫秒 |
| `s` | 秒 |
| `m` | 分 |
| `h` | 小时 |

| 函数 | 说明 | 示例 |
|---|---|---|
| `duration` | 把带单位的字符串转成 duration | `duration(R.attr.cooldownPeriod).getSeconds() == 3750` |
| `getHours` / `getMinutes` / `getSeconds` / `getMilliseconds` | 取 duration 的对应部分 | `duration(R.attr.cooldownPeriod).getHours() == 1` |
| `timeSince` | 从给定时间戳到**服务器当前时间**的间隔。**Cerbos 对 CEL 的扩展** | `timestamp(R.attr.lastAccessed).timeSince() > duration("1h")` |

#### Hierarchies(层级)

**层级函数是 Cerbos 对 CEL 的扩展。**

| 函数 | 说明 | 示例 |
|---|---|---|
| `hierarchy` | 把点号字符串或字符串列表转成层级 | `hierarchy("a.b.c") == hierarchy(["a","b","c"])` |
| `hierarchy` | 把用指定分隔符的字符串转成层级 | `hierarchy("a:b:c", ":").size() == 3` |
| `ancestorOf` | 第一个层级是否是第二个的公共前缀 | `hierarchy("a.b").ancestorOf(hierarchy("a.b.c.d")) == true` |
| `commonAncestors` | 公共祖先层级 | `hierarchy(R.attr.scope).commonAncestors(hierarchy(P.attr.scope)) == hierarchy("foo.bar")` |
| `descendentOf` | `ancestorOf` 的镜像 | `hierarchy("a.b.c.d").descendentOf(hierarchy("a.b")) == true` |
| `immediateChildOf` | 是否为一级子节点 | `hierarchy("a.b.c").immediateChildOf(hierarchy("a.b")) == true` |
| `immediateParentOf` | `immediateChildOf` 的镜像 | `hierarchy("a.b").immediateParentOf(hierarchy("a.b.c")) == true` |
| `overlaps` | 一个层级是否是另一个的前缀 | `hierarchy("a.b.c").overlaps(hierarchy("a.b.c.d.e")) == true` |
| `siblingOf` | 是否有同一个父节点 | `hierarchy("a.b.c").siblingOf(hierarchy("a.b.d")) == true` |
| `size` | 层级的层数 | `hierarchy("a.b.c").size() == 3` |
| `[]` | 取某一层 | `hierarchy("a.b.c.d")[1] == "b"` |

#### IP addresses

**`inIPAddrRange` 是 Cerbos 对 CEL 的扩展函数。**

| 函数 | 说明 | 示例 |
|---|---|---|
| `inIPAddrRange` | IP 是否在 CIDR 定义的范围内 | `P.attr.ipv4Address.inIPAddrRange("192.168.0.0/24")` |
| `cidr(<cidr>).containsCIDR` | 该 CIDR 是否包含给定 CIDR。v0.55.0 起 | `cidr("192.168.0.0/8").containsCIDR(cidr("192.168.1.0/24")) == true` |
| `cidr(<cidr>).containsIP` | 该 CIDR 是否包含给定 IP。v0.55.0 起 | `cidr("2001:db8::/48").containsIP(P.attr.ipv6Address) == true` |
| `cidr(<cidr>).isMask` / `.masked` / `.prefixLength` | 判断是否为掩码 / 取掩码 / 取前缀长度。v0.55.0 起 | `cidr("192.168.1.0/24").prefixLength() == 24` |
| `ip(<ip>).family` | IP 族。v0.55.0 起 | `ip(P.attr.ipv4Address) == 4` |
| `ip(<ip>).isGlobalUnicast` / `.isLoopback` / `.isLinkLocalUnicast` / `.isLinkLocalMulticast` / `.isUnspecified` | 各类 IP 性质判断。v0.55.0 起 | `ip(P.attr.ipv4Address).isLoopback() == false` |
| `ip.isCanonical` | IPv6 字符串是否符合 RFC 5952。v0.55.0 起 | `ip.isCanonical(P.attr.ipv6Address) == false` |
| `isCIDR` / `isIP` | 判断字符串是不是 CIDR / IP。v0.55.0 起 | `isIP(P.attr.ipv4Address) == true` |

#### Lists, maps, and sets

| 运算符/函数 | 说明 | 示例 |
|---|---|---|
| `+` | 拼接列表 | `P.attr.teams + ["design", "engineering"]` |
| `[]` | 取列表或 map 的元素 | `P.attr.teams[0] == "design" && P.attr.clients["acme"]["active"] == true` |
| `all` | 列表里所有元素都满足谓词 | `P.attr.teams.all(t, size(t) > 3)` |
| `distinct` | 去重 | `[1, 2, 2, 3, 3, 3].distinct() == [1, 2, 3]` |
| `except` | 集合差 | `P.attr.teams.except(["design", "engineering"]) == [...]` |
| `exists` | 至少存在一个满足谓词的元素 | `P.attr.teams.exists(t, t.startsWith("comm"))` |
| `exists_one` | 恰好一个满足谓词的元素 | `P.attr.teams.exists_one(t, t.startsWith("comm")) == false` |
| `filter` | 按谓词过滤列表 | `size(P.attr.teams.filter(t, t.matches("^comm"))) == 2` |
| `flatten` | 展平列表,可指定层数 | `[1,[2,[3,[4]]]].flatten(2) == [1, 2, 3, [4]]` |
| `hasIntersection` | 是否有共同元素 | `hasIntersection(["design", "engineering"], P.attr.teams)` |
| `in` | 元素是否在列表或 map 中 | `("design" in P.attr.teams) && ("acme" in P.attr.clients)` |
| `intersect` | 集合交集 | `intersect(["design", "engineering"], P.attr.teams) == ["design"]` |
| `isSubset` | 是否为子集 | `["design", "engineering"].isSubset(P.attr.teams) == false` |
| `lists.range` | 0 到 n-1 的整数列表 | `lists.range(5) == [0, 1, 2, 3, 4]` |
| `map` | 逐元素变换 | `"DESIGN" in P.attr.teams.map(t, t.upperAscii())` |
| `reverse` | 反转列表 | `[5, 3, 1, 2].reverse() == [2, 1, 3, 5]` |
| `size` | 列表或 map 的元素个数 | `size(P.attr.teams) == 4` |
| `slice` | 按下标取子列表 | `[1,2,3,4].slice(1, 3) == [2, 3]` |
| `sort` / `sortBy` | 排序 / 按表达式结果排序 | `[{...}].sortBy(e, e.score).map(e, e.name) == [...]` |
| `transformList` | 把 map 或 list 转成 list,可过滤 | `[1, 2, 3].transformList(i, v, i > 0, 2 * v) == [4, 6]` |
| `transformMap` | 把 map 或 list 转成 map | `[1, 2, 3].transformMap(i, v, i > 0, 2 * v) == {1: 4, 2: 6}` |
| `transformMapEntry` | 转成 map,值必须是 map 字面量 | `{'greeting': 'hello'}.transformMapEntry(k, v, {v: k}) == {'hello': 'greeting'}` |
| `sets.contains` / `sets.equivalent` / `sets.intersects` | 集合关系判断。**v0.55.0 起**;旧版本用 `hasIntersection` | `sets.contains(P.attr.teams, ["design"]) == true` |

#### Math

`math.abs` / `math.ceil` / `math.floor` / `math.greatest` / `math.least` /
`math.round`(平局远离零)/ `math.sign` / `math.trunc` / `math.isFinite` /
`math.isInf` / `math.isNaN` / `math.bitAnd` / `math.bitOr` / `math.bitXor` /
`math.bitNot` / `math.bitShiftLeft` / `math.bitShiftRight`。

#### Paths

**路径函数是 Cerbos 对 CEL 的扩展。**

`basePath` / `dirPath` / `extPath` / `joinPath` / `pathHasPrefix` /
`pathMatch` / `pathMatchAnyOf` / `relPath` / `volumeName`。

#### SPIFFE

**SPIFFE 函数是 Cerbos 对 CEL 的扩展。**

`spiffeID.isMemberOf` / `spiffeID.path` / `spiffeID.trustDomain` /
`spiffeMatchAny` / `spiffeMatchExact` / `spiffeMatchOneOf` /
`spiffeMatchTrustDomain` / `spiffeTrustDomain.id` / `spiffeTrustDomain.name`。

#### Strings

| 函数 | 说明 | 示例 |
|---|---|---|
| `base64.encode` / `base64.decode` | base64 编解码 | `base64.encode(bytes("hello")) == "aGVsbG8="` |
| `charAt` | 取指定位置的字符 | `R.attr.department.charAt(1) == 'a'` |
| `contains` | 是否含子串 | `R.attr.department.contains("arket")` |
| `endsWith` | 是否以某后缀结尾 | `R.attr.department.endsWith("ing")` |
| `format` | 格式化字符串 | `"department_%s_%d".format(["marketing", 1])` |
| `indexOf` / `lastIndexOf` | 首次 / 末次出现的下标 | `R.attr.department.indexOf('a') == 1` |
| `json.encode` | 编码成 JSON。v0.55.0 起 | `json.encode(R.attr) == '{"id":"125",...}'` |
| `lowerAscii` / `upperAscii` | ASCII 大小写转换 | `"MARKETING".lowerAscii() == R.attr.department` |
| `matches` | 是否匹配 **RE2** 正则 | `R.attr.department.matches("^[mM].*g$")` |
| `regex.extractAll` | 提取所有正则匹配。v0.55.0 起 | `regex.extractAll("a bb a cc", "a") == ["a", "a"]` |
| `regex.replace` | 正则替换,可限次数。v0.55.0 起 | `regex.replace("banana", "a", "i") == "binini"` |
| `replace` | 子串替换,可限次数(0 不换,-1 全换) | `"engineering".replace("e", "a", 1) == "angineering"` |
| `size` | 字符串长度 | `size(R.attr.department) == 9` |
| `split` | 按分隔符切分,可限次数 | `"a,b,c,d".split(",")[1] == "b"` |
| `startsWith` | 是否以某前缀开头 | `R.attr.department.startsWith("mark")` |
| `substring` | 取子串 | `R.attr.department.substring(4, 6) == "et"` |
| `trim` | 去掉首尾空白 | `"  marketing  ".trim() == "marketing"` |

#### Timestamps

> **IMPORTANT**: All timestamp getters (getHours, getMinutes, getDayOfWeek, and similar) take a time zone parameter. If omitted, the 'UTC' time zone is used by default.

**所有时间戳 getter(getHours、getMinutes、getDayOfWeek 等)都接受时区参数。省略则默认用 UTC。**

| 函数 | 说明 | 示例 |
|---|---|---|
| `timestamp` | 把 RFC3339 格式字符串转成 timestamp | `timestamp(R.attr.lastAccessed).getFullYear() == 2021` |
| `getDate` | 月中的第几天 | `timestamp(R.attr.lastAccessed).getDate() == 20` |
| `getDayOfMonth` / `getDayOfWeek` / `getDayOfYear` / `getMonth` | **返回从 0 开始的值**(周日是 0,一月是 0) | `timestamp(R.attr.lastAccessed).getDayOfWeek() == 2` |
| `getFullYear` | 年 | `timestamp(R.attr.lastAccessed).getFullYear() == 2021` |
| `getHours` / `getMinutes` / `getSeconds` / `getMilliseconds` | 时/分/秒/毫秒,**可带时区参数** | `timestamp(R.attr.lastAccessed).getHours("-05:00") == 10` |
| `now` | **服务器当前时间**。Cerbos 对 CEL 的扩展 | `now() > timestamp(R.attr.lastAccessed)` |
| `timeSince` | 从给定时间戳到服务器当前时间的间隔。Cerbos 对 CEL 的扩展 | `timestamp(R.attr.lastAccessed).timeSince() > duration("1h")` |

**例:断言最后访问与最后更新之间超过 36 小时**:

```yaml
timestamp(R.attr.lastUpdateTime) - timestamp(R.attr.lastAccessed) > duration("36h")
```

**例:给时间戳加一个 duration**:

```yaml
timestamp(R.attr.lastUpdateTime) + duration("24h") == timestamp("2021-05-02T13:34:12.024Z")
```

### 我的理解

**1. 运行时错误在 v0.55 前后对 DENY 规则的语义相反。**

| | ALLOW 规则 | DENY 规则 |
|---|---|---|
| v0.54 及之前 | 失败即拒绝(不匹配) | **失败即放行**(deny 被跳过) |
| v0.55 起 | 失败即拒绝 | **失败即拒绝**(deny 生效) |

本机 PDP 是 **0.57.0**,所以 DENY 规则是失败即拒绝。

**这一条对「用 DENY 兜底」的做法很关键。** 在旧版本上,一条条件写错的 DENY 规则
**不会拦住任何人** —— 它只是不生效,一条匹配的 ALLOW 照常放行。这是最隐蔽的
「以为有保护其实没有」。

**2. `has()` 守卫在这个模型里没有必要,但 `!= null` 之类的写法要小心。**

页面把「引用不存在的属性」列为运行时错误的例子。而 Cerbos 没有暴露 `has()`
这种检查(map 字段缺失是运行时错误,不是 false)。所以**属性缺失的处理只有两条路**:

- 用 schema 保证属性一定存在(§ schemas 页)
- 条件写成不引用可能缺失的属性

这和之前实测到的「`P.attr.userTier` 不存在 → 条件报错 → ALLOW 规则不匹配」是同一件事。

**3. `now()` 和 `timeSince()` 是 Cerbos 扩展,不是 CEL 标准。**

两者都以**服务器当前时间**为基准。这对本项目有意义:`now()` 让「工作时间之外禁止
执行」这类规则不需要调用方传时间 —— 调用方传的时间是不可信的。

**4. 时间戳 getter 的「从 0 开始」很容易踩。**

`getMonth()` 一月返回 **0**;`getDayOfWeek()` 周日返回 **0**;`getDayOfMonth()`
和 `getDayOfYear()` 也是从 0 开始。而 `getDate()`(月中的第几天)返回的是实际日期。

同一族函数里 `getDate` 用 1-based、`getDayOfMonth` 用 0-based,这个不一致值得记。

**5. 时区参数默认 UTC,而且省略时区会静默按 UTC 算。**

`getHours("-05:00")` 这种写法存在,说明可以显式指定。但不写就是 UTC ——
对一个在台湾(UTC+8)部署的系统,「上午 9 点前禁止执行」这类规则必须显式写时区,
否则差 8 小时。

**6. `matches` 用的是 RE2,不是 PCRE。**

RE2 没有反向引用、没有环视。这限制了正则的写法,但换来了没有灾难性回溯。

**7. 层级函数和路径函数是两套。**

`hierarchy("a.b.c")` 处理**用点号分隔的层级**,有 `ancestorOf` / `siblingOf` /
`immediateParentOf` 这些关系判断;`pathMatch` / `relPath` 处理**文件系统路径**。

而 scope 用的是点号分隔(`a.b.c`),所以 `hierarchy()` 正好可以用来判断 scope 关系 ——
这比上一章说的「scope 链」更细:scope 是策略查找的层级,而 `hierarchy()` 是数据层面的层级判断。

**8. `runtime.effectiveDerivedRoles` 只在 resource policy 里可用。**

而且只包含**至少被一条规则引用过**的派生角色。所以想用它来判断「某个派生角色
是否激活」,得先在某条规则里引用它。

### 与本项目的对应关系(仅记录对应关系)

| 页面概念 | 本项目对应物 |
|---|---|
| `P` / `R` 别名 | 本项目策略用的正是 `P.attr.*` / `R.attr.*` |
| `request.principal.attr` / `request.resource.attr` | 本项目 `clientIp`/`email`/`requestTime` 放 principal;`c4Path`/`provider`/`app` 放 resource |
| 运行时错误 → 条件不满足 | 实测过:`P.attr.userTier` 缺失 → ALLOW 规则不匹配 → DENY |
| DENY 规则 v0.55 起失败即拒绝 | 本机 PDP 0.57.0,适用 |
| `now()` / `timeSince()` | 本项目 §4.4 设计的 `requestTime` 用的是 `_token_.now`;`now()` 是 PDP 服务器时间,两者来源不同 |
| `inIPAddrRange` | 本项目 IP 白名单目前放在网络层(§4.5);若改用 policy,这个函数是现成的 |
| `hierarchy()` | 与 scope 的点号层级同名不同义:前者是数据层判断,后者是策略查找路径 |
| `getMonth()` / `getDayOfWeek()` 从 0 开始 | 若用时间窗口规则,注意与 `getDate()` 的 1-based 不一致 |
| 时间戳 getter 默认 UTC | 本项目部署在 UTC+8,任何时间窗口规则都该显式写时区 |

---

---

## 11. Variables and constants · 变量与常量

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/variables

### 页面说了什么

#### Variables

> You can use variables to reduce duplication in policy condition expressions. Variables may either be defined locally within a policy, or in a standalone `exportVariables` policy file that can be imported by other policies.

变量用来减少条件表达式里的重复。变量可以**在策略内本地定义**,也可以放在独立的
`exportVariables` 策略文件里供其他策略导入。

**本地变量**:

```yaml
---
apiVersion: api.cerbos.dev/v1
resourcePolicy:
  variables:
    local: (1)
      flagged_resource: request.resource.attr.flagged
      label: '"latest"' # 赋一个字符串字面量
      teams: '["red", "blue"]' # 赋一个数组字面量
      lookup: '{"red": 9001, "blue": 0}' # 赋一个 map 字面量
  # ...
```

| 标注 | 含义 |
|---|---|
| (1) | 从变量名到表达式的映射 |

**本地变量只能在定义它的策略里访问。** 特别是,**为派生角色定义的本地变量不能在导入该派生角色的 resource policy 里使用**。

**导出变量**:

```yaml
---
apiVersion: api.cerbos.dev/v1
description: Common variables used within the Apatr app
exportVariables:
  name: apatr_common_variables (1)
  definitions: (2)
    flagged_resource: request.resource.attr.flagged
    label: '"latest"'
    teams: '["red", "blue"]'
    lookup: '{"red": 9001, "blue": 0}'
```

| 标注 | 含义 |
|---|---|
| (1) | 导入这组变量时要用的名字 |
| (2) | 从变量名到表达式的映射 |

其他策略按名字导入:

```yaml
---
apiVersion: api.cerbos.dev/v1
resourcePolicy:
  variables:
    import: (1)
      - apatr_common_variables
  # ...
```

**在条件里使用**:

```yaml
---
condition:
  match:
    expr: variables.flagged_resource
```

通过 `variables`(别名 `V`)这个特殊变量引用。

> Local and imported variable definitions are merged, and each variable is evaluated before any rule condition. If a variable is defined in more than one location, the policy will fail to compile.

**本地定义和导入的定义会被合并**,并且**每个变量在所有规则条件之前求值**。
**同一个变量在多处定义,策略会编译失败。**

**顶层的 `variables` 字段已废弃**:早期版本在策略文件顶层定义本地变量,现在改用策略体
内的 `variables.local`。为向后兼容,那个废弃的顶层字段在 derived roles、resource
和 principal policy 里仍会与 `variables.local` 合并。

#### Constants

> Variables are expressions that are evaluated at runtime. That makes them slightly awkward to use with literal values, because you have to quote the value to make it a valid CEL expression.

变量是**运行时求值的表达式**。这让它们在表达字面值时有点别扭,因为必须把值加引号
才能成为合法的 CEL 表达式。

**常量是变量用字面值时的替代方案** —— 允许用标准 YAML 或 JSON 语法书写值。

**本地常量**:

```yaml
---
apiVersion: api.cerbos.dev/v1
resourcePolicy:
  constants:
    local: (1)
      label: latest
      teams:
        - red
        - blue
      lookup:
        red: 9001
        blue: 0
  # ...
```

| 标注 | 含义 |
|---|---|
| (1) | 从常量名到值的映射 |

**本地常量同样只能在定义它的策略里访问**,**为派生角色定义的本地常量不能在导入该
派生角色的 resource policy 里使用**。

**导出常量**:

```yaml
---
apiVersion: api.cerbos.dev/v1
description: Common constants used within the Apatr app
exportConstants:
  name: apatr_common_constants (1)
  definitions: (2)
    label: latest
    teams:
      - red
      - blue
    lookup:
      red: 9001
      blue: 0
```

导入方式与变量相同:`constants.import: [name]`。

**在条件里使用**:

```yaml
---
condition:
  match:
    expr: constants.lookup[request.principal.attr.team] > 9000
```

通过 `constants`(别名 `C`)引用。

> Local and imported constant definitions are merged. If a constant is defined in more than one location, the policy will fail to compile.

本地定义和导入的定义会被合并。**同一个常量在多处定义,策略会编译失败。**

### 我的理解

**1. 变量和常量的区别只有一个:值是不是字面量。**

| | 值的形态 | 写法 |
|---|---|---|
| 变量 | **表达式**,运行时求值 | `'"latest"'`、`'["red","blue"]'` —— 要加引号成为 CEL 字面量 |
| 常量 | **字面量**,直接是值 | `latest`、`[red, blue]` —— 标准 YAML |

页面说得很直白:变量用字面值时「有点别扭」。所以**能用常量就别用变量** ——
常量的写法是普通 YAML,不需要理解 CEL 字面量语法。

**2. 变量在所有规则条件之前求值 —— 所以它是「预处理」,不是「按需计算」。**

「each variable is evaluated before any rule condition」。这有两个后果:

- 一个没被任何规则用到的变量,**也会被求值**。如果它引用的属性不存在,求值会出错。
- 变量不能依赖规则的求值结果(它没有依赖关系)。

**3. 「多处定义 = 编译失败」是硬冲突,不是覆盖。**

变量和常量都是:本地 + 导入合并后,**同名即编译失败**。这比「后者覆盖前者」安全 ——
覆盖会静默产生「我以为导入的那份生效了」的错觉。

**4. 本地变量不能跨策略边界。**

页面两处都特别强调:**为派生角色定义的本地变量/常量,不能在导入该派生角色的
resource policy 里使用**。

结合上一章 scope 链那条「变量和派生角色的导入在策略之间不继承」,可以看到一个
一致的图景:**导入是单向的、显式的**。derived roles policy 导入了什么,
resource policy 就得自己再导入一次。

**5. 变量名冲突会在编译期暴露,这是好事。**

上一章说 scope 链上变量不继承时,担心的是「以为继承其实没有」导致静默失效。
这里给出的是另一半:真要同名,**编译就失败**,不会静默。

**6. `exportVariables` / `exportConstants` 是独立的策略类型。**

它们有自己的 `apiVersion`、自己的文件,靠 `name` 被 import。和 derived roles 的
`exportDerivedRoles` 是同一个模式:**命名的一组定义,被别的策略按名字导入**。

### 与本项目的对应关系(仅记录对应关系)

| 页面概念 | 本项目对应物 |
|---|---|
| `variables.local` / `constants.local` | 本项目策略目前没有用变量 / 常量 |
| 变量在规则条件之前求值 | 与条件里的运行时错误同理:属性缺失 → 求值出错 → 条件不满足 |
| 同名定义 → 编译失败 | 本项目 `push-policies.py` 推送返回 200 即编译通过;这条能在推送阶段拦住变量名冲突 |
| 本地变量不跨策略 | 与 scope 链上不继承是同一方向:导入是单向、显式的 |
| `exportVariables` / `exportConstants` 独立策略文件 | 与 `exportDerivedRoles` 同一模式;本项目未使用 |
| 常量 vs 变量 | 本项目若要用「批量授权」,`constants` 放 app 清单可能比 `variables` 更省事 |

---

---

## 12. Outputs · 输出表达式

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/outputs

### 页面说了什么

> You can define an optional expression to be evaluated when a policy rule is fully activated (`action`, `roles` and `derivedRoles` match and `condition` is satisfied) or partially activated (`condition` is not satisfied). The collected outputs from all the rules are included in the Cerbos API response.

可以定义一个可选表达式,在规则**完全激活**(`action`、`roles` 和 `derivedRoles` 都匹配、且 `condition` 满足)或**部分激活**(`condition` 不满足)时求值。**所有规则收集到的 outputs 会一并放进 Cerbos API 响应。**

Outputs 支持 resource policy、principal policy 和 role policy 的规则。下面用 resource policy 举例,三种策略的 `output` 字段形状相同。

**用途**:如果你想在应用里根据触发的规则采取特定动作。页面的例子:策略里有一条规则在工作时间之外拒绝访问,它可以输出一条说明限制原因的消息,应用再把它显示给用户,让人知道**为什么**被拒。

```yaml
---
apiVersion: api.cerbos.dev/v1
resourcePolicy:
  version: "default"
  resource: "system_access"
  rules:
    - name: working-hours-only
      actions: ['*']
      effect: EFFECT_DENY
      roles: ['*']
      condition:
        match:
          expr: now().getHours() > 18 || now().getHours() < 8
      output:
        when:
          ruleActivated: |-
            {"principal": P.id, "resource": R.id, "timestamp": now(), "message": "System can only be accessed between 0800 and 1800"}
          conditionNotMet: |-
            {"principal": P.id, "resource": R.id, "timestamp": now(), "message": "System can be accessed at this time"}
```

**工作时间之外的请求**,响应形如:

```json
{
  "requestId": "xx-010023-23459",
  "results": [
    {
      "resource": { "id": "bastion_002", "kind": "system_access" },
      "actions": { "login": "EFFECT_DENY" },
      "meta": {
        "actions": {
          "login": { "matchedPolicy": "resource.system_access.vdefault" }
        }
      },
      "outputs": [
        {
          "src": "resource.system_access.vdefault#working-hours-only",
          "val": {
            "message": "System can only be accessed between 0800 and 1800",
            "principal": "john",
            "resource": "bastion_002",
            "timestamp": "2023-06-02T21:53:58.319506543+01:00"
          }
        }
      ]
    }
  ]
}
```

**工作时间之内的请求**,响应形如:

```json
{
  "requestId": "xx-010023-23459",
  "results": [
    {
      "resource": { "id": "bastion_002", "kind": "system_access" },
      "actions": { "login": "EFFECT_ALLOW" },
      "meta": {
        "actions": {
          "login": { "matchedPolicy": "resource.system_access.vdefault" }
        }
      },
      "outputs": [
        {
          "src": "resource.system_access.vdefault#working-hours-only",
          "val": {
            "message": "System can be accessed at this time",
            "principal": "john",
            "resource": "bastion_002",
            "timestamp": "2023-06-02T21:53:58.319506543+01:00"
          }
        }
      ]
    }
  ]
}
```

> Depending on the evaluation result of the expression(s) under the `condition.match`, the result of the expression `output.when.ruleActivated` or `output.when.conditionNotMet` will be rendered in the output.

取决于 `condition.match` 下表达式的求值结果,`output.when.ruleActivated` 或
`output.when.conditionNotMet` 里的表达式结果会被渲染进 output。

**输出表达式可以是任何合法的 CEL 表达式。** 可以返回简单值(字符串、数字、布尔),
也可以返回复杂值(map 和 list)。

> Excessive use of output expressions could affect policy evaluation performance. If you use them for debugging purposes, remember to remove them before going to production.

**过多使用 output 表达式会影响策略求值性能。** 如果用于调试,记得在进生产前移除。

### 我的理解

**1. outputs 是「规则级」的,不是「action 级」的。**

`src` 字段的格式是 `resource.system_access.vdefault#working-hours-only` ——
**策略 id + 规则名**。而 `val` 在**结果条目**里,不在 `actions` 里面。

所以一次请求里,每个 resource 有一个 `outputs` 数组,里面可能有**多条**(每条触发的规则一条)。

**2. 两个分支对应规则的两个状态,而不是「允许/拒绝」。**

| 分支 | 何时求值 | 例子里的含义 |
|---|---|---|
| `ruleActivated` | 规则**完全**激活(action/roles/derivedRoles 匹配 **且** condition 满足) | 「工作时间之外」→ 拒绝原因 |
| `conditionNotMet` | 规则**部分**激活(condition 不满足) | 「现在可以访问」 |

注意例子里的规则 `effect: EFFECT_DENY`、condition 是「不在工作时间」——
所以「工作时间之外」→ condition 满足 → `ruleActivated` → 输出拒绝原因;
「工作时间之内」→ condition 不满足 → `conditionNotMet` → 输出「可以访问」。

**这两个分支都出现在同一个请求的输出里是可能的** —— 不同规则各有各的分支。

**3. outputs 的用途是「让拒绝可解释」。**

页面的定位很清楚:应用把 output 里的 `message` 显示给用户,让人知道**具体为什么**
被拒。**决策本身是 EFFECT_ALLOW / EFFECT_DENY,outputs 是补充说明**,不影响决策。

这和本项目之前遇到的「拒绝和故障分不清」是同一类问题的另一面 ——
DENY 是「不允许」,但用户还想知道「不允许的原因」。

**4. `now()` 在 output 里出现两次会得到不同的时间戳。**

例子里 `timestamp: now()` 写在两个分支里。页面没提这一点,但既然 output 是独立求值的
表达式,两次调用 `now()` 是两次求值 —— 理论上可能差几微秒。不影响用途,但要知道
**output 不是求值结果的快照,是独立计算的**。

**5. 性能提示是「移除调试用的 output」。**

页面明说 output 会影响求值性能,调试完要移除。所以 output 是**生产环境也有价值的东西**
(解释拒绝原因),但不是「随便加一堆」。

### 与本项目的对应关系(仅记录对应关系)

| 页面概念 | 本项目对应物 |
|---|---|
| outputs 在结果条目的 `outputs` 数组,不在 `actions` 里 | 本项目实测的决策记录里 `checkResources.outputs` 就是这个位置 |
| `src` = 策略 id + 规则名 | 本项目 policy 里的 `name: everyone-else-is-denied` 之类规则名会成为 `src` 的一部分 |
| `ruleActivated` / `conditionNotMet` 两个分支 | 本项目若要让「为什么被拒」可解释,这是现成的机制 |
| `now()` | 与上一章的条件页一致:`now()` 是 PDP 服务器时间 |
| 调试用的 output 要移除 | 本项目的影子模式(设计文档 §9 阶段 2)正需要这种输出 |

---

---

## 13. Schemas · 属性校验模式

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/schemas

### 页面说了什么

> Cerbos policies rely on context data about the principal and the resource(s) that are submitted through the `attr` fields of the API request. While the free-form nature of these fields gives you maximum flexibility to author policies that work on data of any shape or form, they can become difficult to reason about and make it harder to enforce system-wide standards and conventions.

Cerbos 策略依赖通过 API 请求的 `attr` 字段提交的 principal 和 resource 上下文数据。
这些字段的自由形式带来了最大的灵活性(策略可以基于任意形状的数据编写),
但它们会变得**难以推理**,也让**全系统标准和约定的强制**变得更难。

> Using the JSON Schema support built into Cerbos, you can define schemas for all your principal and resource attributes on a per-resource basis by specifying them in the resource policy. The Cerbos PDP will validate the incoming requests and either log warnings or completely reject them based on the schema enforcement configuration in effect.

用 Cerbos 内建的 JSON Schema 支持,可以在 resource policy 里**按 resource 逐个声明**
principal 和 resource 的所有属性 schema。Cerbos PDP 会校验进来的请求,
按生效的 schema enforcement 配置,**要么记警告,要么完全拒绝**。

#### 定义 schema

> Cerbos schemas are standard JSON Schemas (draft 2020-12).

Cerbos schema 是标准 JSON Schema(draft 2020-12)。

> If you are using any of `disk`, `git` or `blob` storage drivers the schemas are expected to be in a special directory named `_schemas` located at the root of the storage directory or bucket. Use the Admin API to add or update schemas if you are using one of the database drivers.

用 `disk`、`git` 或 `blob` 存储驱动时,schema 放在存储目录或桶根下的**特殊目录 `_schemas`** 里。
用数据库驱动时,用 **Admin API** 增删改 schema。

> To avoid repetition, you can define common schema fragments inline using `$defs` or refer to other schemas using `$ref`. When using `$ref` to refer to another schema stored in Cerbos storage, make sure to use an absolute URL with `cerbos` as the scheme. For example, use `cerbos:///common/address.json` to refer to a schema file stored in `_schemas/common/address.json` (if using one of the disk-based stores). This ensures that policies remain portable between different environments.

为避免重复,可以用 `$defs` 内联定义公共片段,或用 `$ref` 引用其他 schema。
**引用存储在 Cerbos 里的 schema 时,必须用 `cerbos` 作为 scheme 的绝对 URL**,
例如 `cerbos:///common/address.json` 指向 `_schemas/common/address.json`。
**这确保策略在不同环境之间保持可移植。**

`customer.json` —— 一个引用另一个 schema 的 schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "first_name": { "type": "string" },
    "last_name": { "type": "string" },
    "shipping_address": { "$ref": "cerbos:///address.json" },
    "billing_address": { "$ref": "cerbos:///address.json" }
  },
  "required": ["first_name", "last_name", "shipping_address", "billing_address"]
}
```

`address.json` —— 被 customer.json 引用的 schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "street_address": { "type": "string" },
    "city": { "type": "string" },
    "state": { "type": "string" }
  },
  "required": ["street_address", "city", "state"]
}
```

#### 用 schema 校验请求

先让 resource policy 指向应该用于校验该 resource kind 请求的 schema:

```yaml
---
apiVersion: api.cerbos.dev/v1
resourcePolicy:
  importDerivedRoles:
    - apatr_common_roles
  resource: "album:object"
  rules:
    - actions: ['create']
      effect: EFFECT_ALLOW
      derivedRoles:
        - owner

    - actions: ['view']
      effect: EFFECT_ALLOW
      roles:
        - user
      condition:
        match:
          expr: request.resource.attr.public == true

  schemas: (1)
    principalSchema: (2)
      ref: cerbos:///principal.json
    resourceSchema: (3)
      ref: cerbos:///album/object.json
      ignoreWhen: (4)
        actions: ['create', 'delete:*']
```

| 标注 | 含义 |
|---|---|
| (1) | Schema 定义块。**可选**。不想要这个 resource 类型的 schema 校验就省掉 |
| (2) | 校验 principal 属性的 schema。可选 |
| (3) | 校验 resource 属性的 schema。可选 |
| (4) | Ignore 块。可选。定义**哪些 action 忽略 schema 校验**。对 `CREATE` 这类特殊情况有用 —— 你的 resource 那时可能还没有全部必填属性 |

最后,**配置 Cerbos PDP 的 schema enforcement 级别**为 `warn` 或 `reject` 并重启它。
此后 PDP 会校验所有「匹配到的 resource policy 里指定了 schemas」的请求。

> If enforcement level is `reject` and the request is invalid according to the schema, the effect for all actions will be set to `EFFECT_DENY`. If enforcement level is `warn`, then Cerbos will still evaluate the policies and return the effects determined by the policy.

**enforcement 是 `reject` 且请求不符合 schema 时,所有 action 的效果都会被置为 `EFFECT_DENY`。**
是 `warn` 时,Cerbos **仍然会求值策略**,并返回策略决定的效果。

**CheckResourceSet 响应里带校验错误的例子**:

```json
{
  "requestId": "test",
  "resourceInstances": {
    "XX125": {
      "actions": {
        "approve": "EFFECT_DENY",
        "create": "EFFECT_DENY",
        "defer": "EFFECT_ALLOW",
        "view:public": "EFFECT_ALLOW"
      },
      "validationErrors": [
        {
          "path": "/department",
          "message": "value must be one of "marketing", "engineering"",
          "source": "SOURCE_PRINCIPAL"
        },
        {
          "path": "/department",
          "message": "value must be one of "marketing", "engineering"",
          "source": "SOURCE_RESOURCE"
        }
      ]
    }
  }
}
```

### 我的理解

**1. schema 解决的是「attr 是自由格式」带来的两个问题。**

页面说得很直接:自由形式给灵活性,但让数据**难以推理**、让**全系统标准强制**变难。
所以 schema 是「给 attr 立规矩」,不是「限制 attr 的形状」。

**2. `ignoreWhen` 是「schema 校验的例外清单」,按 action 粒度。**

例子是 `actions: ['create', 'delete:*']`。注意 `delete:*` —— **通配符在这里可用**,和 action 通配符是同一套规则。

用途页面写得很具体:`CREATE` 时 resource 可能还没有全部必填属性。

**3. `reject` 和 `warn` 的差别是「策略还求不求值」。**

| enforcement | 请求不合法时 |
|---|---|
| `reject` | **所有 action 置为 DENY**,策略不求值 |
| `warn` | **策略照常求值**,返回策略决定的效果(另有警告) |

**这个差别比「拒绝 vs 记录」更大** —— `reject` 是**先拒绝,不问策略**;`warn` 是**照常决策,只顺带警告**。

**4. `validationErrors` 分 principal 和 resource 两个来源。**

`source` 字段取 `SOURCE_PRINCIPAL` / `SOURCE_RESOURCE`。同一个 `/department` 路径可以同时出现在两个来源里(例子就是)。

**5. `$ref` 用 `cerbos:///...` 绝对 URL,是为了跨环境可移植。**

页面给的理由是 "This ensures that policies remain portable between different environments"。
如果用相对路径或文件路径,同一份 schema 在不同环境下就要改。

**6. schema 的存放位置取决于存储驱动。**

| 驱动 | schema 放哪 |
|---|---|
| `disk` / `git` / `blob` | 存储根目录下的 `_schemas/` 目录 |
| 数据库驱动(sqlite3 / postgres / mysql) | **Admin API** |

**这就是本项目之前踩坑的根源**:本项目用的是 sqlite3(数据库驱动),所以 schema 必须走
Admin API 推,不能放进 `_schemas/` 目录 —— 而 store 里存的键是**相对路径**
(`principal.json`),不是策略 `ref` 里带的 `cerbos:///principal.json`。

### 与本项目的对应关系(仅记录对应关系)

| 页面概念 | 本项目对应物 |
|---|---|
| 数据库驱动 → schema 走 Admin API | 本项目用 sqlite3,`push-policies.py` 用 `POST /admin/schema` 推 |
| `disk` 驱动 → `_schemas/` 目录 | 不适用(本项目是 sqlite3);但仓库 `pdp-config/config/policies/_schemas/` 里那份是给 disk 模式准备的 |
| `$ref` 用 `cerbos:///...` 绝对 URL | 本项目策略里正是 `ref: cerbos:///principal.json` |
| store 里存相对路径 | **实测确认**:推 `principal.json` 才能用;推 `cerbos:///principal.json` 会「看着像成功了」但每请求被拒且读不回来 |
| `reject` → 所有 action 置 DENY | 实测一致:畸形属性 → `EFFECT_DENY` + `validationErrors` |
| `warn` → 策略照常求值 | 本项目没开;开了就能验证「策略本身是否正确」而不管 schema |
| `ignoreWhen.actions` | 本项目 `basicResource.yaml` 里就有 `ignoreWhen: actions: [create]` |
| `validationErrors[].source` | 实测到的 `source: SOURCE_PRINCIPAL` 与页面一致 |

---

---

## 14. Validating and testing policies · 校验与测试

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/compile

### 页面说了什么

#### 校验策略

> You can use the Cerbos compiler to make sure that your policies are valid before pushing them to a production Cerbos instance. We recommend setting up a git hook or a CI step to run the Cerbos compiler before you push any policy changes to production.

用 Cerbos 编译器可以在推到生产实例之前确认策略是有效的。**页面建议设置 git hook 或 CI 步骤**,在推任何策略改动到生产之前跑一遍编译器。

```sh
docker run -i -t -v /path/to/policy/dir:/policies ghcr.io/cerbos/cerbos:0.57.0 compile /policies
```

#### 测试策略

> You can write optional tests for policies and run them as part of the compilation stage to make sure that the policies do exactly what you expect.

可以给策略写可选的测试,作为**编译阶段的一部分**运行,确认策略做的正是你期望的。

> A test file must have `_test` suffix in the name and one of the following file extensions: `yaml`, `yml`, or `json`.

**测试文件名必须带 `_test` 后缀**,扩展名是 `yaml`、`yml` 或 `json` 之一。

测试套件定义:

```yaml
---
name: AlbumObjectTestSuite (1)
description: Tests for verifying the album:object resource policy (2)
options:
  now: "2022-08-02T15:00:00Z" (3)
  defaultPolicyVersion: staging (4)
  defaultScope: "" (5)
  lenientScopeSearch: true (6)
  strictEvaluation: true (7)
  globals: (8)
    my_global_var: foo

principals: (9)
  alicia:
    id: aliciaID
    roles:
      - user

  bradley:
    id: bradleyID
    roles:
      - user

principalGroups: (10)
  everyone:
    principals:
      - alicia
      - bradley

resources: (11)
  alicia_album:
    id: XX125
    kind: album:object
    policyVersion: default
    attr:
      owner: aliciaID
      public: false
      flagged: false

  bradley_album:
    id: XX250
    kind: album:object
    policyVersion: staging
    attr:
      owner: bradleyID
      public: false
      flagged: false

resourceGroups: (12)
  all_albums:
    resources:
      - alicia_album
      - bradley_album

auxData: (13)
  validJWT:
    jwt:
      iss: my.domain
      aud: ["x", "y"]
      myField: value

tests: (14)
  - name: Accessing an album (15)
    options: (16)
      now: "2022-08-03T15:00:00Z" (17)
      defaultPolicyVersion: production (18)
      defaultScope: "" (19)
      lenientScopeSearch: false (20)
      strictEvaluation: true (21)
      globals: (22)
        my_global_var: bar

    input: (23)
      principals: (24)
        - alicia
        - bradley
      resources: (25)
        - alicia_album
        - bradley_album
      actions: (26)
        - view
        - delete
      auxData: validJWT (27)

    expected: (28)
      - principal: alicia (29)
        resource: alicia_album (30)
        actions: (31)
          view: EFFECT_ALLOW
          delete: EFFECT_ALLOW
        outputs: (32)
          - action: view (33)
            expected: (34)
              - src: resource.album.vdefault#view-rule
                val:
                  key1: value1
                  key2: ["value2", "value3"]
              - src: resource.album.vdefault#token-lifetime
                val: 1h

      - principal: bradley
        resource: bradley_album
        actions:
          view: EFFECT_ALLOW
          delete: EFFECT_ALLOW

  - name: Using groups
    input:
      principalGroups: (35)
        - everyone
      resourceGroups: (36)
        - all_albums
      actions:
        - download

    expected:
      - principalGroups: (37)
          - everyone
        resourceGroups: (38)
          - all_albums
        actions:
          download: EFFECT_DENY
```

| 标注 | 含义 |
|---|---|
| (1) | 测试套件的名字 |
| (2) | 测试套件的描述 |
| (3) | 可选的 RFC3339 时间戳,用作 `now` 函数的返回值。**除非在测试里单独覆盖,否则适用于套件里所有测试** |
| (4) | 可选:为这个测试套件设置默认策略版本 |
| (5) | 可选:默认 scope |
| (6) | 可选:lenient scope search |
| (7) | 可选:为这个测试套件启用严格求值 |
| (8) | 可选:为这个测试套件设置 globals |
| (9) | principal fixtures 映射。键是一个字符串,用来引用对应的 principal |
| (10) | principal groups 映射 |
| (11) | resource fixtures 映射 |
| (12) | resource groups 映射 |
| (13) | (可选)辅助数据 fixtures 映射,用于求值某些请求 |
| (14) | 这个套件里的测试列表 |
| (15) | 测试的名字 |
| (16) | 可选:只作用于这个测试的选项。**测试专属选项不与套件级选项合并**,未指定的值回到默认 |
| (17) | 可选的 RFC3339 时间戳,用作 `now` 函数的返回值 |
| (18) | 可选:默认策略版本 |
| (19) | 可选:默认 scope |
| (20) | 可选:lenient scope search |
| (21) | 可选:严格求值 |
| (22) | 可选:globals |
| (23) | 传给策略引擎的输入 |
| (24) | 要测试的 principal fixture 键列表 |
| (25) | 要测试的 resource fixture 键列表 |
| (26) | 要测试的 action 列表 |
| (27) | 要测试的辅助数据 fixture 键(可选) |
| (28) | 每个 principal 与 resource 期望的结果列表。**`input` 里指定了、但 `expected` 里没列出的 principal+resource 组合,所有 action 都期望 `EFFECT_DENY`** |
| (29) | 被测 principal 的键。想给多个 principal 指定相同期望,用 `principals` 代替 `principal` |
| (30) | 被测 resource 的键。想给多个 resource 指定相同期望,用 `resources` 代替 `resource` |
| (31) | 每个 principal+resource 组合下每个 action 的期望结果。**`input` 里指定了、但没列出的 action,期望 `EFFECT_DENY`** |
| (32) | 可选的[输出值](https://docs.cerbos.dev/cerbos/latest/policies/outputs)匹配列表 |
| (33) | 产生该输出的 action 名 |
| (34) | 期望的输出值列表 |
| (35) | 要测试的 principal group 键列表。可以替代、或同时配合 `principals` |
| (36) | 要测试的 resource group 键列表 |
| (37) | 被测 principal group 的键 |
| (38) | 被测 resource group 的键 |

#### 共享测试 fixtures

> It is possible to share principals, resources and auxData blocks between test suites stored in the same directory. Create a `testdata` directory in the directory containing your test suite files, then define shared resources, principals and auxData in `testdata/resources.yml`, `testdata/principals.yml`, `testdata/auxdata.yml` respectively (`yaml` and `json` extensions are also supported).

可以共享同一目录里多个测试套件之间的 principals、resources 和 auxData 块。
在测试套件文件所在目录建一个 `testdata` 目录,分别把共享的 resources、principals、
auxData 定义在 `testdata/resources.yml`、`testdata/principals.yml`、`testdata/auxdata.yml` 里
(也支持 `yaml` 和 `json` 扩展名)。

```
tests
├── album_object_test.yaml
├── gallery_object_test.yaml
├── slideshow_object_test.yaml
└── testdata
    ├── auxdata.yaml
    ├── principals.yaml
    └── resources.yaml
```

`testdata/principals.yml` 的例子:

```yaml
---
principals: # required
  john:
    id: johnID
    roles:
      - user
      - moderator

principalGroups: # optional
  moderators:
    principals:
      - john
```

`testdata/resources.yml` 的例子:

```yaml
---
resources: # required
  alicia_album:
    id: XX125
    kind: "album:object"
    attr:
      owner: aliciaID
      public: false
      flagged: false

resourceGroups: # optional
  all_albums:
    resources:
      - alicia_album
```

`testdata/auxdata.yml` 的例子:

```yaml
---
auxData: # required
  validJWT:
    jwt:
      iss: my.domain
      aud: ["x", "y"]
      myField: value
```

> YAML anchors and overrides are a great way to reduce repetition and reuse definitions in test cases.

页面给了 YAML anchor / override 的对照例子,用来减少测试用例里的重复。

#### 运行测试

> The `compile` command automatically discovers test files in the policy repository.

`compile` 命令会自动发现策略仓库里的测试文件。

```sh
docker run -i -t     -v /path/to/policy/dir:/policies     ghcr.io/cerbos/cerbos:0.57.0 compile /policies
```

**输出格式**由 `--output` 控制,取值 `tree`(默认)、`list`、`json`。
`--color` 控制着色。要产出机器可读的输出,传 `--output=json --color=never`。

默认跑所有发现的测试。`--skip-tests` 跳过全部测试;`--test-filter` 只跑匹配的测试。

`--test-filter` 接受一个过滤表达式,维度有:

- `suite` —— 按测试套件名过滤
- `test` —— 按测试名过滤
- `principal` —— 按 principal 键过滤
- `resource` —— 按 resource 键过滤
- `action` —— 按 action 名过滤

每个维度接受一个或多个 **glob 模式**。多个维度用**分号**分隔,同一维度内多个值用**逗号**分隔。

```sh
# 跑特定套件和 principal 的测试
ghcr.io/cerbos/cerbos:0.57.0 compile --test-filter='suite=AlbumObjectTestSuite;principal=alicia' /policies

# glob 模式
ghcr.io/cerbos/cerbos:0.57.0 compile --test-filter='test=*Delete*;action=view,edit' /policies
```

多个 `--test-filter` 标志可以组合,**所有过滤维度会合并在一起**:

```sh
ghcr.io/cerbos/cerbos:0.57.0 compile --test-filter='principal=alice,bob' --test-filter='action=view' /policies
```

**跳过测试**:在套件或单个测试上标 `skip: true`,并可给 `skipReason`:

```yaml
---
name: AlbumObjectTestSuite
description: Tests for verifying the album:object resource policy
tests:
  - name: View private album
    skip: true
    skipReason: "Policy under review"
    input:
      principals: ["alicia"]
      resources: ["alicia_private_album"]
      actions: ["view"]
    expected:
      - principal: alicia
        resource: alicia_private_album
        actions:
          view: EFFECT_ALLOW
```

#### CI 环境

**GitHub Actions** —— `cerbos-setup-action`(安装二进制)和 `cerbos-compile-action`(编译并可选测试)。

```yaml
---
name: PR Check
on:
  pull_request:
    branches:
      - main
jobs:
  cerbosCheck:
    name: Check Cerbos policies
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v2

      - name: Setup Cerbos
        uses: cerbos/cerbos-setup-action@v1
        with:
          version: latest

      - name: Compile and test policies
        uses: cerbos/cerbos-compile-action@v1
        with:
          policyDir: policies
```

**GitLab CI** —— 下载二进制、在 `compile` job 里跑。

**Dagger** —— `dagger install github.com/cerbos/dagger-cerbos`,提供 `compile` 函数和 `server` 服务。

```yaml
dagger -m github.com/cerbos/dagger-cerbos call compile --policy-dir=./cerbos
dagger -m github.com/cerbos/dagger-cerbos call server --policy-dir=./cerbos up
dagger -m github.com/cerbos/dagger-cerbos call server --config=storage.driver=sqlite3,storage.sqlite3.dsn=:memory:,server.adminAPI.enabled=true up
```

### 我的理解

**1. 编译和测试是同一个命令。**

`compile` 自动发现测试文件并一起跑。所以「编译通过」意味着「策略有效**且**测试全过」——
这不是两件事。

**2. 「没列出的就是 DENY」这条规则,让测试可以只写例外。**

标注 (28) 和 (31) 说了两处:

- `input` 里有的 principal+resource,`expected` 里没列 → 所有 action 期望 `EFFECT_DENY`
- `input` 里有的 action,`expected` 里没列 → 那个 action 期望 `EFFECT_DENY`

所以测试文件可以用「只写放行项」的方式写。这和本项目 `nativesuite.py` 里的展开逻辑一致。

**3. `options.now` 是让时间相关规则可测的关键。**

它设定 `now()` 函数的返回值 —— 所以「工作时间之外拒绝」这种规则可以用固定的
时间戳测试,而不是依赖跑测试的时刻。

**4. 测试级选项不与套件级选项合并。**

标注 (16) 明确说:「Test-specific options are not merged with suite-wide options,
so any unspecified values revert to the default」。

所以在某个测试里写了 `now`,套件级的 `defaultPolicyVersion` 就**不再生效**,回到默认。
这是「覆盖」而不是「合并」——容易误以为 unset 的会继承。

**5. `testdata/` 是官方的共享 fixture 机制。**

`testdata/{principals,resources,auxdata}.yml` 里的内容被**同目录**下所有测试套件共享。
键名分别是 `principals` / `resources` / `auxData`(required),以及可选的
`principalGroups` / `resourceGroups`。

**6. `skip` 和 `skipReason` 是给「策略正在评审中」这种情况用的。**

带 `skipReason` 说明为什么跳过 —— 跳过的测试在输出里能看出理由。

**7. `--test-filter` 的维度正好对应测试文件的四个键。**

`suite` / `test` / `principal` / `resource` / `action` —— 过滤语法和测试文件的结构
一一对应,支持 glob,多个 `--test-filter` 合并。

### 与本项目的对应关系(仅记录对应关系)

| 页面概念 | 本项目对应物 |
|---|---|
| 测试文件 `_test` 后缀 + yaml/yml/json | `policies/resource_policies/basicResource_test.yaml` |
| `testdata/{principals,resources}.yml` | **本项目的 `policies/resource_policies/testdata/{principals,resources}.yaml` 就是这个机制** |
| `options.strictEvaluation: true` | 本项目的 `basicResource_test.yaml` 已声明 |
| `options.now` | 本项目未用;若加时间相关规则就需要它 |
| 编译 = 校验 + 跑测试 | 本项目用 Python harness 对着**线上 PDP** 跑同一份文件(见下) |
| 「没列出的期望 DENY」 | `nativesuite.py` 的 `expand_suite` 就是这个规则 |
| `principals` / `resources` 批量指定相同期望 | 本项目已用 `principals:` / `resources:` 复数形式 |
| `outputs` 期望匹配 | 本项目未用 |
| `skip` / `skipReason` | 本项目用 pytest 的 `xfail` 表达类似语义(那 3 个已关闭) |

**本项目的一个偏差值得记:** 官方流程是「`cerbos compile` 在 CI 里编译并跑测试」,
需要 cerbos 二进制或容器。本项目没有二进制,所以用 Python harness 把**同一份**
`*_test.yaml` 对着线上 PDP 执行 —— 文件格式和展开语义都是官方的,只是执行器换成了
HTTP + Cerbos SDK。这正是 `cerbos-policy` skill 改成 API 版本的原因。

---

---

## 15. Best practices and recipes · 最佳实践

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/best_practices

### 页面说了什么

#### 策略建模

> With Cerbos, access rules are always resource-oriented and the policies you write map to these resources within your system. A resource can be anything, and the way you model your policies is up to you — you can achieve the same logical outcome in numerous ways; action-led, role-led, attribute-led, or with combinations thereof.

用 Cerbos 时,访问规则**总是面向 resource 的**,你写的策略映射到系统里的这些 resource。
resource 可以是任何东西,建模方式由你决定 —— 同一个逻辑结果可以用多种方式达成:
**action 主导、role 主导、attribute 主导**,或它们的组合。

页面给了一个业务模型:

| _Actions_ | IT_ADMIN | JR_MANAGER | SR_MANAGER | USER | CFO |
|---|---|---|---|---|---|
| run | | x | x | | x |
| view | x | x | x | x | x |
| edit | | | x | | x |
| save | | | x | | x |
| share | | x | x | | x |

**Action-led** —— 聚焦一个 action,列出能做它的所有角色:

```yaml
# 下面三个角色的人可以执行 `run`
  - actions:
      - "run"
    effect: EFFECT_ALLOW
    roles:
      - JR_MANAGER
      - SR_MANAGER
      - CFO

# 所有人都可以执行 `view`
  - actions:
      - "view"
    effect: EFFECT_ALLOW
    roles:
      - ["*"]
```

适用情形:

- 你的角色「做的事差不多」,比如 `JR_MANAGER` 和 `SR_MANAGER`;很可能是前者的权限是后者的子集。虽然两个方向都会有重复,但**从 action 的角度推理通常更容易**。
- 你有**高风险 action** —— 你想能一眼看出哪些角色能碰某个 action。**显式按 action 列出角色,会让「不小心把不该有的权限给了错的人」困难得多。**
- 角色数量相对多、action 数量相对少。

**Role-led** —— 聚焦一个角色,列出它能做的所有 action:

```yaml
  - actions:
      - "run"
      - "view"
      - "share"
    effect: EFFECT_ALLOW
    roles:
      - JR_MANAGER
```

适用情形:角色之间**很少共享 action**;角色少、action 多。

**Hybrid** —— 两者结合:

```yaml
  - actions:
      - "*"
    effect: EFFECT_ALLOW
    roles:
      - SR_MANAGER
      - CFO
```

**Blanket allow, granular deny** —— 显式列出**不能**做的 action:

```yaml
  - actions:
      - "*"
    effect: EFFECT_ALLOW
    roles:
      - "JR_MANAGER"

  - actions:
      - "edit"
      - "save"
    effect: EFFECT_DENY
    roles:
      - "JR_MANAGER"
```

适用:主体几乎能做**所有** action,而你想显式列出不允许的那些。

**Attribute-led** —— 组织把 resource 建模成具体的**数据集**,每个数据集唯一,访问者也唯一。
组织大量使用 JWT 传递身份和上下文信息。**resource policy 与数据集 1:1 映射**,
访问由 JWT 里任意信息决定。

因为受众是动态的,**枚举所有能访问的角色不现实**。于是全局允许所有角色和 action,
再靠 JWT 里的属性决定访问:

```yaml
apiVersion: api.cerbos.dev/v1
resourcePolicy:
  resource: "data_set"
  version: default
  rules:
    - actions: ["*"]
      roles: ["*"]
      effect: EFFECT_ALLOW
      condition:
        match:
          all:
            of:
              - expr: has(request.auxData.jwt.aud)
              - expr: >
                  "my.custom.audience" in request.auxData.jwt.aud
```

#### 自助式自定义角色

场景:多租户系统里,你是管理员,想让租户能**复制一个已有角色**,然后自行选择启用或禁用哪些权限。

**Static Policies / Dynamic Context** —— 这是 Cerbos 里**惯用**的做法。
绝大多数情况下,策略可以静态定义,把动态上下文作为 principal 的属性传进来。
动态上下文可以是任意数据,比如主体的位置、年龄,或他在某个组织单元(部门、租户、项目)
里的具体角色。这些上下文数据在请求时从另一个服务或数据存储里取。

`workspace.yaml` 的例子:

```yaml
apiVersion: "api.cerbos.dev/v1"
resourcePolicy:
  version: "default"
  resource: "workspace"
  rules:
    - actions:
        - workspace:view
        - pii:view
      effect: EFFECT_ALLOW
      roles:
        - USER
      condition:
        match:
          expr: P.attr.workspaces[R.id].role == "OWNER"
```

注意这个 condition 依赖 `P.attr.workspaces` 这个 map 里的上下文,**键是 resource ID**,值是预定义的角色 `"OWNER"`。
于是给一个持有 `USER` 角色的主体发这样的请求就能授权:

```shell
cat <<EOF | curl --silent "http://localhost:3592/api/check/resources?pretty" -d @-
{
  "requestId": "quickstart",
  "principal": {
    "id": "123",
    "roles": ["USER"],
    "attr": {
      "workspaces": {
        "workspaceA": { "role": "OWNER" },
        "workspaceB": { "role": "MEMBER" }
      }
    }
  },
  "resources": [
    { "actions": ["workspace:view", "pii:view"],
      "resource": { "id": "workspaceA", "kind": "workspace" } },
    { "actions": ["workspace:view", "pii:view"],
      "resource": { "id": "workspaceB", "kind": "workspace" } }
  ]
}
EOF
```

页面给出了 cURL、.NET、Go、Java、JS、PHP、Python、Ruby、Rust 九种语言的调用示例
(Python 版正是本项目 `pep.py` 的形态)。

#### Dynamic Policies

有时你需要**即时创建或更新** resource 和 action,比如让租户自己管理策略的多租户平台。
这时可以用 **Admin API** 配合**可变的数据库存储引擎**。
这由你的应用层处理,策略内容通过 API 提供给 PDP。

#### 策略仓库布局

> Cerbos expects the policy repository to have a particular directory layout.

| 规则 | 说明 |
|---|---|
| **目录只能包含** Cerbos 策略文件、策略测试文件和 schema | **任何其他 YAML 或 JSON 文件都会让 Cerbos 认为这个策略仓库无效** |
| `_schemas` 目录必须是**顶层目录** | 在策略仓库根下 |
| 所有策略测试文件名以 `_test` 结尾,扩展名 `.yaml` / `.yml` / `.json` | |
| 名为 `testdata` 的目录可以存放测试数据 | Cerbos **不会**在那些目录里找策略文件 |
| 隐藏文件/目录(名字以 `.` 开头)被忽略 | |

典型布局:

```
.
├── _schemas
│   ├── principal.json
│   └── resources
│       ├── leave_request.json
│       ├── purchase_order.json
│       └── salary_record.json
├── derived_roles
│   ├── backoffice_roles.yaml
│   └── common_roles.yaml
├── principal_policies
│   └── auditor_audrey.yaml
└── resource_policies
    ├── finance
    │   ├── purchase_order.yaml
    │   └── purchase_order_test.yaml
    └── hr
        ├── leave_request.yaml
        ├── leave_request_test.yaml
        ├── salary_record.yaml
        ├── salary_record_test.yaml
        └── testdata
            ├── auxdata.yaml
            ├── principals.yaml
            └── resources.yaml
```

### 我的理解

**1. 四种建模方式不是「优劣」,是「哪个角度更容易推理」。**

页面的判据很一致:**你的角色之间像不像、action 危不危险、角色多还是 action 多。**

- 角色像(权限有包含关系)→ action-led
- 角色不像、action 多 → role-led
- 有高风险 action → action-led(「一眼看出哪些角色能碰它」)
- 权限由属性决定 → attribute-led

**2. 「显式列出」被反复强调为防错手段。**

Action-led 的理由写得很直白:「**显式按 action 列出角色,会让『不小心把不该有的权限给了错的人』困难得多**」。

Blanket allow + granular deny 也是同一个思路的镜像。

**3. Attribute-led 的形状是 `P.attr.<某映射>[R.id].<字段>`。**

`P.attr.workspaces[R.id].role == "OWNER"` —— **用 resource ID 作为 map 的键**。
这让「策略静态、上下文动态」成立:策略不用知道有哪些 workspace,
调用方把「我在每个 workspace 里是什么角色」放进 principal.attr。

**这正是 FDEP 那个场景的自然形态**:principal.attr 里放「我在每个 app 下是什么角色」,
策略写成 `P.attr.apps[R.id].role == "OWNER"`。

**4. 「自助式自定义角色」的答案是「不要动态策略」。**

页面说得很明确:这是 **Static Policies / Dynamic Context** —— **惯用的做法**。
绝大多数情况下策略可以静态定义,把动态上下文作为 principal 属性传进来。

只有在「租户要自己创建/更新 resource 和 action」这种特殊情况下才需要 Dynamic Policies
(Admin API + 可变数据库存储)。

**5. 仓库布局有一条硬规则最容易踩:目录里不能有别的 YAML/JSON。**

「Any other YAML or JSON files will cause Cerbos to consider the policy repository as invalid」——
比如 `coverage-plan.json` 或 `openapi-spec.json` 放在策略目录里,整个仓库就无效了。

**6. `testdata` 目录有豁免。** Cerbos 不在里面找策略文件 —— 这让它可以放任意 YAML。

### 与本项目的对应关系(仅记录对应关系)

| 页面概念 | 本项目对应物 |
|---|---|
| action-led / role-led / hybrid / blanket-allow-granular-deny | 本项目 `basicResource.yaml` 是 **role-led + condition**:按 USER/ADMIN 角色列规则,再用 `R.attr.ownerId == P.id` 之类收窄 |
| attribute-led(`P.attr.<map>[R.id].<field>`) | **本项目 FDEP 方案的形状**:`R.attr.app`/`R.attr.provider` 由服务端从 app id 推导;也可考虑 `P.attr.apps[R.id]` 放「谁在哪个 app 什么角色」 |
| Static Policies / Dynamic Context | **本项目 FDEP 方案的定位**:策略静态,app 注册表和身份动态 |
| Dynamic Policies(Admin API + 可变存储) | 本项目 PDP 用 sqlite3(可变)+ Admin API,**技术上具备**;但设计文档 §9 采用影子模式而非动态策略 |
| 仓库目录只能有策略/测试/schema | **本项目要注意**:`policies/` 下只有 `_schemas/` + 策略 + 测试 + `testdata/`;`coverage-plan.json` 在仓库根、不在 `policies/` 里 |
| `_schemas` 顶层目录 | 本项目 `policies/_schemas/` 正是顶层位置 |
| `testdata` 豁免 | 本项目 `policies/resource_policies/testdata/` 正是这个机制 |
| 隐藏文件被忽略 | 本项目 `.gitignore` 等不影响 |
| 九种语言的 SDK 示例 | 本项目 `pep.py` 就是 Python 版的形态 |

---

---

## 16. Debugging authorization decisions · 调试授权决定

**来源**:https://docs.cerbos.dev/cerbos/latest/policies/debugging

### 页面说了什么

> When a request returns an unexpected `EFFECT_ALLOW` or `EFFECT_DENY`, Cerbos provides several tools to help you understand why.

当请求返回了意料之外的 `EFFECT_ALLOW` 或 `EFFECT_DENY`,Cerbos 提供几个工具来帮你理解原因。

#### 用 `includeMeta`

在 `CheckResources` 请求里加 `"includeMeta": true`,就能拿到 Cerbos 是**怎么**得出每个决定的元数据。

```json
{
  "requestId": "debug-example",
  "includeMeta": true,
  "principal": {
    "id": "alice",
    "roles": ["employee"],
    "attr": { "department": "marketing" }
  },
  "resources": [
    {
      "resource": {
        "kind": "leave_request",
        "id": "xx125",
        "policyVersion": "20210210",
        "attr": { "owner": "alice" }
      },
      "actions": ["view", "approve"]
    }
  ]
}
```

响应里每个 resource 带一个 `meta` 块:

```json
{
  "meta": {
    "actions": {
      "view": {
        "matchedPolicy": "resource.leave_request.v20210210/acme.corp",
        "matchedScope": "acme",
        "effectiveDerivedRoles": ["owner"]
      },
      "approve": {
        "matchedPolicy": "resource.leave_request.v20210210/acme.corp"
      }
    }
  }
}
```

| 字段 | 含义 |
|---|---|
| `matchedPolicy` | 产生这个决定的策略的**完整标识符** |
| `matchedScope` | 做决定时生效的 scope(用 scoped policies 时相关) |
| `effectiveDerivedRoles` | 在这个 resource 上为该主体激活的派生角色。**如果你期望某个角色却没出现,就去查派生角色的定义和它的条件** |

#### 审计日志

开启 decision logging,记录 PDP 做出的每个授权决定。用于事后分析,以及把决定和
应用行为关联起来。

```yaml
audit:
  enabled: true
  decisionLogsEnabled: true
  backend: file
  file:
    path: stdout
```

> Every API response includes a `cerbosCallId` field. Use this identifier to locate the corresponding entry in the audit log.

**每个 API 响应都带 `cerbosCallId` 字段。用这个标识符去审计日志里定位对应条目。**

#### 用 REPL 测试 CEL 表达式

Cerbos REPL 可以交互式求值 CEL 表达式,用来调试行为不符合预期的 condition。
可以载入请求数据、在其上测试表达式,不用跑完整的策略求值循环。

#### 意外 DENY 的常见原因

| 原因 | 说明 |
|---|---|
| **没有匹配的策略** | 请求里的 `kind` 和 `policyVersion` 组合没有对应策略。用 `includeMeta` 确认是否匹配到策略 |
| **缺少派生角色导入** | 派生角色策略没有通过 `importDerivedRoles` 导入 resource policy。**派生角色必须显式导入才生效** |
| **condition 求值为 false** | 匹配到的规则上的 condition 返回了 `false`。确认请求里的属性名和类型与 condition 期望的一致。用 REPL 执行,或写个策略测试并用 `--verbose` 看表达式是怎么求值的 |
| **显式 DENY 匹配** | 同一 action 上有 DENY 规则匹配。**同一角色同一 action 上,拒绝永远优先于允许** |
| **角色不匹配** | 请求里的 `roles` 与策略里任何规则都不匹配。**角色大小写敏感,必须精确匹配;而且必须是真实角色名,不能是派生角色名** |

#### 意外 ALLOW 的常见原因

| 原因 | 说明 |
|---|---|
| **通配符过宽** | 用了 `actions: ['**']` 或 `roles: ['**']` 的规则匹配范围超出预期。**把规则收窄成列出具体的 action 或角色** |
| **派生角色条件过松** | 派生角色的 condition 匹配了比预期更多的主体。检查条件表达式,并在 REPL 里测试 |

#### 校验与检视策略

用 `cerbos compile` 在部署前校验策略并跑测试。**这能抓出语法错误、缺失的导入、失败的测试用例。**

### 我的理解

**1. `matchedPolicy` 的格式把 scope 也纳入了。**

例子里的值是 `resource.leave_request.v20210210/acme.corp` —— 注意结尾的
`/acme.corp`。而 `matchedScope` 是 `acme`。

**所以 scoped policy 的完整标识符是 `<kind>.<version>/<scope>`**,这和本项目
之前实测到的「scoped 策略存成 `resource.fdepApi.vdefault/systemone`」是同一套格式。

**2. `matchedPolicy` 是排查的第一站。**

五种「意外 DENY」里,三种可以用它直接定位:

| 症状 | `matchedPolicy` 显示什么 |
|---|---|
| 没有匹配的策略 | **缺失**(整个 meta.actions[action] 不存在) |
| 缺派生角色导入 | 有,但 `effectiveDerivedRoles` 是空的 |
| condition 求值为 false | 有,`effectiveDerivedRoles` 也有,但结果仍 DENY |
| 显式 DENY 匹配 | 有,且 `effectiveDerivedRoles` 有值 |
| 角色不匹配 | 有,但 `effectiveDerivedRoles` 为空 |

**「`matchedPolicy` 有值但 `effectiveDerivedRoles` 空」** —— 这一组合指向
「角色不匹配」或「派生角色没导入」。

**3. 角色必须是真实角色名,不能是派生角色名。**

页面在「角色不匹配」那条里特别强调:「They must be the actual role names and
not the derived role names」。

这和第 4 页(derived roles)呼应 —— 那里说「不要把派生角色的名字当请求里的 roles」。
**这条现在有了官方排查清单的位置。**

**4. `cerbosCallId` 是决策和审计轨迹之间的唯一桥梁。**

「每个 API 响应都带 `cerbosCallId`,用它去审计日志里定位对应条目」。

本项目实测的正是这个:决策响应里的 `cerbosCallId` 就是审计轨迹里的 `callId`。
本项目查轨迹用的是 `?lookup=<cerbosCallId>`。

**5. 通配符过宽被单独列为「意外 ALLOW」的原因。**

`actions: ['**']` 或 `roles: ['**']` —— 注意页面写的是 `**`(两个星号),
和本项目用的 `*`(一个星号)不一样。**这两个是不同的东西**,值得记一下。

**6. 排查顺序(页面给的清单顺序)本身就是排查流程。**

没匹配策略 → 缺导入 → condition false → 显式 DENY → 角色不匹配。
从「策略存在吗」到「角色对吗」,是一个从外到内的顺序。

### 与本项目的对应关系(仅记录对应关系)

| 页面概念 | 本项目对应物 |
|---|---|
| `includeMeta` → `meta.actions.<action>.matchedPolicy` | 本项目实测用过 `matchedPolicy=resource.fdepApi.vdefault` 和 `NO_MATCH` |
| `matchedPolicy` 含 `/scope` | 实测 scoped 策略 id 是 `resource.fdepApi.vdefault/systemone` —— 同一格式 |
| `effectiveDerivedRoles` | 本项目未用派生角色 |
| `cerbosCallId` ↔ 审计轨迹 `callId` | **本项目实测确认**:决策响应的 `cerbosCallId` 就是轨迹里的 `callId`;查询用 `?lookup=<cerbosCallId>` |
| 审计配置 `backend: file / path: stdout` | 本项目用 `backend: local` + `local.storagePath`,可查(比 file 好) |
| 「没有匹配的策略」用 `includeMeta` 确认 | **本项目实测的 `NO_MATCH` 正是这个症状** |
| 「角色不匹配」:必须真实角色名、大小写敏感 | 实测一致:`roles: ["guests"]` 匹配,`["GUESTS"]` 不匹配 |
| REPL 测表达式 | 本项目没有 cerbos 二进制,**用不了 REPL**;替代是把同一份 `*_test.yaml` 对着线上 PDP 跑 |
| `cerbos compile` 抓语法错误/缺失导入/失败测试 | 本项目 `push-policies.py` 推送返回 200 即编译通过;测试由 Python harness 执行 |
| `actions: ['**']` / `roles: ['**']` | **注意是两个星号**,与本项目用的 `*` 不同 |

---

## 17. Engine block · 引擎配置

**来源**:https://docs.cerbos.dev/cerbos/latest/configuration/engine

这一页不是 Policies 目录里的,但 §8 的 scope 行为要靠它才说得通,所以记在这里。

### 页面说了什么

| 设置 | 默认 | 作用 |
|---|---|---|
| `engine.celErrorLogLevel` | `warn` | 条件求值出错时的日志级别(`none`/`debug`/`info`/`warn`/`error`)。**错误无论如何都会进审计日志条目** |
| `engine.defaultPolicyVersion` | `default` | 请求没指定版本时的兜底版本 |
| `engine.defaultScope` | `""` | 请求没指定 scope 时的兜底 scope |
| `engine.globals` | — | 全局变量,可在条件里用 `globals.xxx` 引用 |
| `engine.lenientScopeSearch` | `false` | **scope 查找的宽松模式**(见下) |
| `engine.strictEvaluation` | `false` | **条件出错时是否拒绝**(见下) |

#### `lenientScopeSearch`

> 默认行为是**期望存在一个与请求 scope 完全对应的 policy 文件**。比如 API 请求定义了
> `a.b.c` 作为 scope,policy 仓库里就**必须**存在 scope 为 `a.b.c` 的 policy 文件。
> 把 `lenientScopeSearch` 设为 `true` 可以覆盖这个行为:开启后,如果 store 里没有
> scope `a.b.c` 的 policy,Cerbos 会依次尝试 `a.b`、`a` 和 `""`。

```yaml
engine:
  lenientScopeSearch: true
```

> **这个设置只影响「缺失叶子 scope」时的查找方式。** store 里已存的 policy
> **必须有不间断的 scope 链**(比如有 `a.b.c`,就必须也有 `a.b`、`a` 和 `""`)。

#### `strictEvaluation`

> 默认情况下,策略条件求值出错(比如比较不兼容的类型、引用不存在的属性)时,
> 受影响的表达式**视为不满足**,求值继续。错误会被日志记录(`celErrorLogLevel`)
> 并写进请求的审计日志条目。
> **因为条件出错的规则永远不匹配,一条 `EFFECT_DENY` 规则可能被静默跳过。**

设成 `true` 后,这类错误会**拒绝**受影响的 action:

- 规则条件里的错误 → 拒绝该规则涉及的所有 action
- 变量里的错误 → 只拒绝引用了该变量的那些 action
- 导入的派生角色的条件出错 → 拒绝引用该派生角色的规则的 action,
  以及访问 `runtime.effectiveDerivedRoles` 的 action;两者都没引用的 action 不受影响

对 check 和 query planner 两个 API 都生效。

```yaml
engine:
  strictEvaluation: false
```

### 我的理解

**1. `strictEvaluation` 默认关,是授权场景里最危险的默认值。**

「一条条件写错的 DENY 规则等于没有」—— 而且没有任何报错,只有日志。
**授权网关应该把它打开**:fail closed 才是对的默认。

**2. `lenientScopeSearch` 是「未知 scope」的兜底,但不能修补断掉的链。**

它只处理「请求的叶子 scope 没有 policy」;store 里已存在的 scope 链仍然必须完整。
所以它能救「新增 org 忘了加 policy」,救不了「链中间缺一层」。

**3. `defaultScope` 可能比 `lenientScopeSearch` 更省事。**

如果 FDEP 只有一个 provider(或所有 provider 共用同一套规则),
把 `defaultScope` 设成它,请求**不传 scope** 就自动落到那一份 policy ——
连 scoped policy 都不用建。

### 与本项目的对应关系

| 页面概念 | 本项目对应物 |
|---|---|
| `strictEvaluation` | 本项目 PDP **没开**;建议开(要改配置并重启共享 PDP) |
| `lenientScopeSearch` | 本项目用 scope 装 provider,建议开(同上) |
| `defaultScope` | 备选方案:只有一个 provider 时用它代替 scoped policy |
| `celErrorLogLevel` | 默认 `warn` 即可;错误会进审计日志条目 |
| `globals` | 本项目未使用 |

---

## 待读(按官方目录顺序)

以下为官方 Policies 目录下的页面,尚未阅读:

- Agent skills — `/cerbos/latest/policies/agent_skills`
