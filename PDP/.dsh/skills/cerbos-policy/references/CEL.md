# CEL、条件与常见错误

## 特殊对象

- `P`（Principal）：`P.id`、`P.roles`、`P.attr.*`
- `R`（Resource）：`R.id`、`R.kind`、`R.attr.*`
- `V`（本地或导入的变量，`variables` 的别名）：`V.is_owner` 等
- `request.auxData.jwt.CLAIM`：单个 JWT 里的 claims
- `request.auxData.jwts.NAME.claims.CLAIM`：具名 JWT 里的 claims（v0.55+，支持多个 token）。`claims` 这一段是必需的。方括号写法：`request.auxData.jwts["NAME"].claims["CLAIM"]`
- `runtime.effectiveDerivedRoles`：本次请求匹配到的派生角色

同一个请求上 `jwt` 与 `jwts` 互斥——选一种写法，在各份策略和 fixture 里保持一致。

## 常见 CEL 模式

```cel
R.attr.owner == P.id                              # 归属关系
"admin" in P.roles                                # 角色检查
P.id in R.attr.members                            # 列表成员关系
R.attr.dept == P.attr.dept                        # 属性匹配
R.attr.environment == "production"                # 直接比较 (优先用这种)
```

优先直接比较属性，而不是加防御性的 `has()` 守卫。避免 `has(R.attr.environment) && R.attr.environment == "production"` 这类写法——当 schema 把该属性标为必填时，守卫只增加复杂度而没有价值。只有当属性确实是可选的时才用 `has()`：在严格求值下（见下文），不加守卫地读取一个不存在的字段是终止性错误，会拒绝该动作，所以可选属性必须加守卫，不能放任它求值为假。

经验法则：交给 schema 决定。必填属性 → 直接比较；可选属性 → 用 `has()` 守卫。

## Function Catalogue

Cerbos 内置的函数远多于 CEL 标准库，所以看到一个眼生的函数名时，它通常确实存在。在断定某个函数不存在之前，先查这张表，并在 REPL 里确认（[TESTING.md](TESTING.md)）。标注 **0.55+** 的条目要求 Cerbos v0.55.0 或更高版本。

| 分组 | 函数 |
|---|---|
| 核心 | `has()`, `size()`, `type()`, `in`, 三元 `? :` |
| 列表 | `all()`, `exists()`, `exists_one()`, `filter()`, `map()`, `sort()`, `sortBy()`, `reverse()`, `distinct()`, `flatten()`, `slice()`, `lists.range()` |
| 集合（旧版） | `except()`, `hasIntersection()`, `intersect()`, `isSubset()` |
| 集合 **0.55+** | `sets.contains()`, `sets.equivalent()`, `sets.intersects()` |
| 字符串 | `matches()`, `contains()`, `startsWith()`, `endsWith()`, `indexOf()`, `lastIndexOf()`, `charAt()`, `replace()`, `split()`, `join()`, `substring()`, `trim()`, `upperAscii()`, `lowerAscii()`, `format()` |
| 正则 **0.55+** | `regex.extractAll(str, pattern)`, `regex.replace(str, pattern, replacement, [limit])` |
| 编码 | `base64.encode()`, `base64.decode()`, `json.encode()` **0.55+** |
| 时间 | `now()`, `timestamp()`, `duration()`, `timeSince()`, 以及 `getFullYear()`/`getMonth()`/`getDayOfWeek()`/`getHours()`/… 等访问器（多数可带一个可选时区） |
| 数学 | `math.abs()`, `math.sign()`, `math.round()`, `math.ceil()`, `math.floor()`, `math.trunc()`, `math.greatest()`, `math.least()`, `math.bitAnd()`/`bitOr()`/`bitXor()`/`bitNot()`, `math.bitShiftLeft()`/`bitShiftRight()`, `math.isFinite()`/`isInf()`/`isNaN()` |
| 层级 | `hierarchy()`, `.ancestorOf()`, `.descendentOf()`, `.immediateParentOf()`, `.immediateChildOf()`, `.siblingOf()`, `.overlaps()`, `.commonAncestors()` |
| IP / CIDR **0.55+** | `ip()`, `isIP()`, `cidr()`, `isCIDR()`, `ip.isCanonical()`；IP 方法 `.family()`, `.isLoopback()`, `.isUnspecified()`, `.isGlobalUnicast()`, `.isLinkLocalUnicast()`, `.isLinkLocalMulticast()`；CIDR 方法 `.containsIP()`, `.containsCIDR()`, `.isMask()`, `.masked()`, `.prefixLength()`。取代旧版的 `inIPAddrRange()` |
| 路径 | `basePath()`, `dirPath()`, `extPath()`, `joinPath()`, `relPath()`, `pathHasPrefix()`, `pathMatch()`, `pathMatchAnyOf()` |
| SPIFFE | `spiffeID()`, `spiffeTrustDomain()`, `.trustDomain()`, `.path()`, `.isMemberOf()`, `spiffeMatchExact()`, `spiffeMatchOneOf()`, `spiffeMatchTrustDomain()`, `spiffeMatchAny()` |

新策略里优先用 `sets.contains` / `sets.equivalent` / `sets.intersects`，而不是旧版的 `isSubset` / `hasIntersection` 一族——旧函数在比较混合数字类型（int 与 double）时行为不一致，这一问题在 v0.55 已修复。

## Strict Evaluation (v0.55+)

默认情况下，条件里的运行时错误——访问不存在的字段、比较不匹配的类型——求值为 **false**。放在 `EFFECT_DENY` 规则上就是一个安全漏洞：拒绝静默失效，优先级更低的 ALLOW 就会胜出。

```yaml
# 如果资源上不存在 R.attr.nonexistent, 下面的 DENY 永远不会触发.
# 默认求值下, 该 principal 是 ALLOWED.
- actions: ["view"]
  effect: EFFECT_DENY
  roles: ["user"]
  condition:
    match:
      expr: R.attr.nonexistent == "blocked"
- actions: ["view"]
  effect: EFFECT_ALLOW
  roles: ["user"]
```

严格求值让这类错误变成终止性的——受影响的动作会被直接拒绝。它是 **可选开启、默认关闭** 的，可以在三个层次上打开：

| 位置 | 方式 |
|---|---|
| 测试运行 | `options: { strictEvaluation: true }` —— 见 [TEST-SUITES.md](TEST-SUITES.md) |
| 单个套件或测试用例 | `options: { strictEvaluation: true }` —— 见 [TEST-SUITES.md](TEST-SUITES.md) |
| 已部署的 PDP | 服务器配置里的 `engine.strictEvaluation: true` |

**HTTP 决策 API 没有严格求值开关。** `requestContext` 只携带注解——已对照 PDP 的 OpenAPI 文档确认，其中 `v1RequestContext` 只有一个属性 `annotations`。因此发往 `POST /api/check/resources` 的请求永远是非严格求值，运行时 CEL 错误会求值为 false，而不是终止性地拒绝。

在只用 API 的前提下，替代做法是让这种情况不可能发生，而不是事后再去检测：每个 fixture 都带上它的条件会读取的每一个属性，并由套件断言响应里没有 `validationErrors`。

拒绝会扩散：规则条件出错会拒绝该规则覆盖的动作；变量出错会拒绝所有条件引用了它的动作；派生角色条件出错会拒绝引用该派生角色或 `runtime.effectiveDerivedRoles` 的动作。

在 `--strict-evaluation` 下失败、不加它却通过，意味着某个条件在运行时出错——无论生产环境跑哪种模式，这都是一个潜伏的 bug。修表达式或修 fixture。

运行时 CEL 错误会由 PDP 记入日志（`engine.celErrorLogLevel`，默认 `warn`），也会记录在审计条目里，所以这类 bug 在运行中的部署里同样能被发现。

## 条件嵌套（优先于内联 CEL）

为了可读性，用结构化的条件块，而不是复杂的内联 CEL。

### 单表达式

```yaml
condition:
  match:
    expr: R.attr.owner == P.id
```

### `all`（AND）

```yaml
condition:
  match:
    all:
      of:
        - expr: R.attr.status == "DRAFT"
        - expr: R.attr.dept == P.attr.dept
        - expr: P.attr.level >= 3
```

### `any`（OR）

```yaml
condition:
  match:
    any:
      of:
        - expr: R.attr.owner == P.id
        - expr: P.id in R.attr.editors
        - expr: R.attr.public == true
```

### `none`（NOT）

```yaml
condition:
  match:
    none:
      of:
        - expr: R.attr.archived == true
        - expr: R.attr.deleted == true
```

### 嵌套运算符

```yaml
condition:
  match:
    all:
      of:
        - expr: R.attr.status == "DRAFT"
        - any:
            of:
              - expr: R.attr.owner == P.id
              - expr: P.id in R.attr.editors
        - none:
            of:
              - expr: R.attr.archived == true
```

表达式里需要带引号的字符串时，用 YAML 块标量语法：

```yaml
expr: >
  "GB" in R.attr.geographies
```

## 命名约定

| 元素 | 约定 | 示例 |
|---|---|---|
| 资源 | 单数、小写 | `document`、`expense_report` |
| 动作 | 小写动词或 `verb_noun` | `view`、`approve`、`view_comments` |
| 派生角色 | snake_case、有描述性 | `document_owner`、`same_department` |
| 导出变量 | snake_case，带 `is_`/`has_`/`can_` 前缀 | `is_owner`、`has_approval` |
| 角色策略文件 | snake_case 的角色名 | `release_manager.yaml` |

## 导出变量的抽取规则

抽取或导入变量时参见[变量依赖设计](POLICIES.md#variable-dependency-design)；它覆盖内联与本地表达式、聚焦的导出集合，以及传递依赖。

## 常见陷阱

这些是最常见、也最难察觉的策略 bug。校验之前先逐条排查。

### 1. 同一条规则上同时写 `roles` 和 `derivedRoles` 是 OR，不是 AND

```yaml
# 错误 — 会匹配任何 "user" 角色或 owner 的人
- actions: ["edit"]
  roles: ["user"]
  derivedRoles: ["owner"]
  effect: EFFECT_ALLOW
```

要同时要求两者，就把角色检查写进派生角色里：

```yaml
# 正确
derivedRoles:
  definitions:
    - name: user_owner
      parentRoles: ["user"]
      condition:
        match:
          expr: R.attr.owner == P.id
```

### 2. 通配 DENY 会压过具体的 ALLOW

```yaml
# 错误 — DENY 会胜出
- actions: ["*"]
  roles: ["guest"]
  effect: EFFECT_DENY
- actions: ["view"]
  roles: ["guest"]
  effect: EFFECT_ALLOW
```

要么在 DENY 上写明确的动作列表，要么依赖默认拒绝。

### 3. 带条件的动作不能再无条件出现

如果 `reopen` 对某个角色在一条规则里带了条件，它就不能在同一资源的该角色的任何无条件规则里再出现——无条件规则会胜出，条件就被悄悄绕过了。

### 4. 派生角色依赖 `P.attr.context.*`

如果派生角色检查 `has(P.attr.context.case_id)`，那么每个测试 principal fixture 都必须填上 `attr.context.case_id`，否则派生角色会悄悄地永远不生效，测试结果翻成 DENY。

### 5. 条件在运行时出错的 DENY 规则

最危险的静默失败。触碰了缺失属性或类型不匹配的 `EFFECT_DENY` 条件默认求值为 false，拒绝永不触发，于是 ALLOW 接管。测试照样通过。参见[严格求值](#strict-evaluation-v055)——用 `--strict-evaluation` 校验才能把它抓出来。JWT claims 同理：没有 token 时 `request.auxData.jwt` 是空 map，所以 `request.auxData.jwt.groups` 会出错。用 `has()` 守卫 claims（在 DENY 里写成 `!has(request.auxData.jwt.groups) || !("finance" in request.auxData.jwt.groups)`），并且要测一个没有 `auxData` 的请求。

### 6. 可用正则识别的语法错误

| 错误 | 正确 |
|---|---|
| `match.all: [...]` | `match.all.of: [...]`（同样适用于 `any.of`、`none.of`） |
| `P.role == "admin"` | `"admin" in P.roles` |
| `request.aux_data.jwt.sub` | `request.auxData.jwt.sub` |
| `request.auxData.jwts.NAME.sub` | `request.auxData.jwts.NAME.claims.sub`（`claims` 是必需的） |
| 不用块标量、直接用双引号写内联 CEL | `expr: >` 块标量 |

## 错误速查表

按症状在这里查；SKILL.md 的 Phase 4 给出了处理顺序。

| 错误 | 常见原因 | 修法 |
|---|---|---|
| CEL 语法错误 | 内联 `expr` 里引号没转义 | 改用块标量 `expr: >` |
| 未知 CEL 函数 | 拼写错误，或在旧版 PDP 上用了 v0.55+ 的函数 | 查[函数清单](#function-catalogue)；重写之前先确认 PDP 版本 |
| 时间戳 / 正则字面量无效 | 表达式里的常量写坏了 | 自 v0.55 起在编译期就会被抓出来——修字面量；错误信息里带行列号 |
| 测试里报 `additional property not allowed` | 测试 schema 上多了字段 | 删掉该字段——测试 schema 是严格的 |
| 输出表达式为空 | `output` 块里没有表达式 | 自 v0.54 起是编译错误——补上表达式或删掉这个块 |
| 派生角色永远不匹配 | `parentRoles` 里缺 principal 的角色 | 加上这个角色，或修 principal fixture |
| 动作被意外放行 | 重复的无条件规则，或某条 DENY 的条件出错 | 找找有没有别的规则授予了这个动作；用 `--strict-evaluation` 重跑 |
| 动作被意外拒绝 | 文件靠前位置有通配 DENY | 收窄这条 DENY 或调整顺序 |
| 平时通过，在 `--strict-evaluation` 下失败 | 某个条件在运行时出错并静默求值为 false | 真 bug——修表达式或补上缺失的 fixture 属性 |
| `import` 了未知的派生角色 | 文件没被加载，或名字对不上 | 检查 derived_roles 文件里的 `name:` |

自 v0.54 起，YAML 和策略错误都带行列号——先看位置，再去手工翻文件。
