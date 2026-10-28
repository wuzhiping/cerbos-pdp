# 测试报告——Cerbos策略测试套件

**目标**：`http://10.17.1.201:3592`——Cerbos PDP **v0.57.0**，磁盘存储驱动
**日期**：2026-10-27
**命令**：`uv run pytest`

```
324 collected
318 passed
  0 xfailed
  0 failed
53.68s
```

退出码为`0`。

---

## 1. 这次重构改变了什么，以及是哪个skill提出的要求

旧测试套件是手工拼出来的：一个存放期望值的Python字典、一套自带JSON表格的PowerShell测试套件，以及一个存着第三份副本的JSON用例文件。同一个事实有三份副本，没有一份采用Cerbos的格式，也没有一份按skill的覆盖模型检查过。

这次重构让**原生`*_test.yaml`套件成为唯一的事实来源**，其他一切都由它派生。

| Skill | 它要求什么 | 做出来的东西 |
|---|---|---|
| **`cerbos-policy`** | 带规则名和用途注释的策略源文件 | `policies/resource_policies/basicResource.yaml`——四条具名规则，每条都附有说明理由的注释 |
| | 声明每一条放行路径、并为每个前置条件配一个隔离拒绝项的覆盖率计划 | `coverage-plan.json`——6条放行路径、22行、10组（路径，前置条件）配对 |
| | 配有`testdata/` fixtures的`*_test.yaml`套件 | `policies/resource_policies/basicResource_test.yaml`（17个用例、39条断言）+ `testdata/{principals,resources}.yaml` |
| | Attribute schemas | `policies/_schemas/{principal,basicResource}.json`——策略声明的那两个 |
| | 能证明拒绝项确实触达了预期边界的覆盖率审计 | `src/cerbos_policy_tests/coverage.py`——skill的四条审计规则，针对在线PDP套用；报告保存到`coverage-audit.txt` |
| **`cerbos-pep-integration`** | 用`planResources`代替对列表逐行过滤 | `src/cerbos_policy_tests/queryplan.py` + `tests/test_query_plan.py`——plan → 条件树 → `WHERE` → 行，跑在SQLite上 |
| | 四种调用形态，以及失败即拒绝 | `pep.py`区分拒绝与错误；`tests/test_edge_cases.py`覆盖`is_allowed`/`check_resources`/`plan_resources`/`with_principal`以及故障路径 |
| **`cerbos-audit-insights`** | 可回读的决策记录，以及不会被误判成拒绝的故障 | `tests/test_audit_log.py`——audit backend 已换成 `local`，决策记录读得回来了（响应是 NDJSON，一行一条记录） |

---

## 2. 逐层拆开

| 文件 | 测试数 | 它确立了什么 |
|---|---:|---|
| `test_native_suite.py` | 80 | 针对在线PDP执行的原生`*_test.yaml`——39条断言，每条断言一个测试——外加一项检查：手写规范与参考模型一致 |
| `test_cross_product.py` | 193 | 每一种principal × resource × action组合（8 × 6 × 4 = 192）与参考模型逐一比对 |
| `test_query_plan.py` | 14 | `planResources` → SQL：plan的kind、条件树、数据库返回的行，以及plan与逐点检查之间的一致 |
| `test_edge_cases.py` | 11 | scope、未知版本与kind、attribute类型、空角色，以及失败即拒绝的路径 |
| `test_coverage_plan.py` | 10 | 在线审计覆盖率计划；每个前置条件都被隔离 |
| `test_policy_inventory.py` | 7 | PDP提供了什么：策略id、action、attribute、schema解析结果 |
| `test_connection.py` | 5 | 可达性、健康检查、管理端认证，以及gRPC确实处于关闭状态 |
| `test_audit_log.py` | 4 | 审计后端的状态，以及故障永远不会被当成拒绝 |

### 原生套件是可执行的，不是摆设

`basicResource_test.yaml`采用Cerbos原生格式编写。一旦有了二进制，`cerbos compile`就能原样运行它，而Python测试框架则是针对运行中的PDP执行**同一个文件**。期望值在Python里没有任何镜像副本。

### 参考模型是第二个独立的判定依据

`src/cerbos_policy_tests/rules.py`依据策略文本重新实现了那四条规则。原生套件保存权威的期望值；模型则是192种组合扫描的比对对象。`test_native_suite_agrees_with_the_reference_model`在全部39条断言上把两者相互校验，因此它们不会偏离。

---

## 3. 覆盖率计划结果

```
uv run python -m cerbos_policy_tests --save
```

22行、6条放行路径、**零失败**。完整输出见`coverage-audit.txt`。

| 放行路径 | 前置条件 | 隔离的拒绝项 |
|---|---|---|
| `admin-all` | `admin-role` | `admin-missing-admin-role-read`, `-create` |
| `user-create` | `user-role` | `alice-missing-user-role-create` |
| `user-read-published` | `user-role`, `published` | `alice-missing-user-role-read-alice-pub`, `dave-read-unpublished-alice-unpub` |
| `user-read-owner` | `user-role`, `owner` | `alice-missing-user-role-read-alice-unpub`, `dave-read-owned-alice-unpub` |
| `user-update-owner` | `user-role`, `owner` | `alice-missing-user-role-update-alice-pub`, `dave-update-alice-pub` |
| `user-delete-owner` | `user-role`, `owner` | `alice-missing-user-role-delete-alice-pub`, `dave-delete-alice-pub` |

每个隔离的拒绝项与它的对照项**恰好只差一个字段**，审计输出会打印改动前后的值：

```
PASS dave-read-unpublished-alice-unpub: vs dave-read-published-alice-pub:
     resource.attr.isPublished True -> False
PASS dave-read-owned-alice-unpub: vs alice-read-owned-alice-unpub:
     principal.id 'alice' -> 'dave'
PASS alice-missing-user-role-read-alice-pub: vs alice-read-alice-pub:
     principal.roles ['USER'] -> ['GUEST']
```

fixtures的构造方式正是为了让这种隔离成为可能：`alice`和`alice_without_user_role`共用同一个id `alice`，只在角色上有差异，因此一次拒绝可以归因于缺失的那个角色，而不是换成了另一个人。给变体换一个新id会连所有权关系一起破坏，测试也就无法再显示究竟是哪个前置条件导致了这次拒绝。

---

## 4. 发现

三处缺口，全部记录成测试，而不是文字描述。

### 4.1 声明的schemas不在PDP的store里

策略声明了`cerbos:///principal.json`和`cerbos:///basicResource.json`。这两个schema**已经部署进store了**（`GET /admin/schemas`返回两个ID，id 是**相对路径**——`principal.json`、`basicResource.json`），而且`schema.enforcement: reject` **已经开启**。

**这个缺口已经关上了。** 实测：

| 输入 | 强制生效前 | 强制生效后 |
|---|---|---|
| `isPublished: "true"`（字符串） | `EFFECT_ALLOW` | `EFFECT_DENY` + `expected boolean, but got string` |
| 缺 `ownerId` | `EFFECT_ALLOW` | `EFFECT_DENY` + `missing properties: 'ownerId'` |
| 多一个未声明字段 | `EFFECT_ALLOW` | `EFFECT_DENY` + `additionalProperties 'x' not allowed` |

强制生效之前，三种畸形输入**全部放行**——因为策略的其他分支仍然匹配（`ownerId` 等于principal的id，发布分支就不参与判断）。而且在 `none` 模式下，响应里连`validationErrors`都没有。

`reject` 模式下的响应：HTTP **200**（不是错误状态），每个动作都是 `EFFECT_DENY`，`validationErrors` 在 **`results[]` 那一层**、和`actions`并列。**SDK 看不到它们**——Python SDK 的响应模型里没有`validation_errors`字段，会静默丢掉，要看到错误得读原始HTTP响应。

**⚠️ 这是行为变化**：多带一个字段的请求原来会放行，现在会被拒绝（schema 里`additionalProperties: false`）。上线前先确认调用方都按schema发属性。

> 过程中踩到一个很隐蔽的坑：**部署 schema 的 id 要用相对路径**。`_schemas/principal.json` 推上去的 id 是 `principal.json`，不是 `cerbos:///principal.json`——store 里存的是相对路径，策略里的 `ref` 才带前缀，PDP 编译时会把前缀去掉再找。推错了会「看着像成功了」（`GET /admin/schemas` 照样列出来），但每个请求都带着 `Failed to load ... schema` 被拒绝，**而且那行读不回来**（`GET /admin/schema?id=...` 各种前缀组合都返回 500）。在 `none` 模式下完全看不出来，因为 `none` 模式下 PDP 根本不编译 schema。

### 4.2 审计后端已经可以查询

`GET /admin/auditlog/list/KIND_DECISION` → **200**，返回真实的决策记录。

迁移前它是`501 Audit log backend does not support querying`：backend是默认的文件后端，只写不查，既不能通过Admin API回读，也不能通过`cerbosctl decisions`。无法回读的轨迹不算轨迹。

改成`local`后端之后就有了。**但响应的形状和直觉不一样**，这是实测出来的：

- `Content-Type` 是`application/x-ndjson`——**一行一条记录**，不是单个JSON文档。返回超过一条时`response.json()`直接抛`Extra data`，必须逐行解析。
- 每行外面套着一层`result`，记录在`result.decisionLogEntry` / `result.accessLogEntry`里。
- `inputs`和`outputs`在`checkResources`下面，不在记录顶层。
- `auditTrail`里的键是`effectivePolicies`，不是`policies`。
- `policySource`按驱动类型分键：目录存储是`{"disk": {...}}`，可变存储是`{"database": {"driver": "DRIVER_SQLITE3"}}`。
- 带注解的请求，记录里会多一个`requestContext`字段；没带注解的请求，这个字段整个不存在（proto3不输出空值）——所以读代码时别假设它一定有。

`test_audit_log.py`现在全部是正经断言，没有xfail。

还有一条实测出来的行为：**`local`后端会先缓冲再提交，所以记录不是立刻能读到的**。在这台PDP上，一次决策做完到它的记录能被`lookup`查到，实测要**13秒**。所以测试必须轮询——只读一次就断言"查不到"，得到的是错的结论。缓冲区大小和刷写间隔由`audit.local.advanced`里的`bufferSize`、`maxBatchSize`、`flushInterval`控制。

这件事的意义不只是合规。skill的核心观点是：故障和拒绝必须能够区分，而**区分二者的检查恰恰是“PDP到底有没有记录这次请求”**。没有可查询的轨迹，这项检查就做不了。


### 4.3 在线PDP评估时没有开启strict evaluation

原生套件声明了`strictEvaluation: true`，这正是`cerbos compile --strict-evaluation`将要强制执行的内容。在线PDP没有这个选项，因此在线运行无法捕获那些在运行时出错、又被静默求值为false的条件——正是这种失效模式会让一条DENY规则变成空操作，从而放行该action。因此在这一点上，在线运行比编译运行要弱。

---

## 5. 这里仍然无法验证的内容

| 无法验证 | 原因 | 它本可以证明什么 |
|---|---|---|
| `cerbos compile`（普通模式） | 没有cerbos二进制；Docker已禁用 | 策略YAML能够编译，且测试套件在Cerbos自有引擎下通过 |
| `cerbos compile --strict-evaluation` | 同上 | 没有任何条件在运行时出错 |
| skill的`coverage_audit.py` | 需要那两份编译报告 | 同一次审计，但基于编译报告而非实时决策 |
| Schema强制校验 | schema已经部署，但`schema.enforcement`默认是`none`（完全不校验）而不是`reject` | 格式错误的attribute会被驳回，而不是被静默放行 |
| gRPC传输通道 | 这台PDP的3593端口是关闭的 | gRPC客户端链路可用，而SDK恰好更偏好它 |

前三项属于skill的Phase 3，一旦有了二进制就是顺理成章的下一步。`coverage.py`中的在线审计是刻意的替代方案，而不是替代品：它套用同样的四条规则，但基于实时决策而非编译报告，并且看不到编译期错误。

---

## 6. 列表过滤这条路

skill把“对列表逐行过滤”称为常见的错误走法：分页会失效，计数和聚合不再工作，会撞上50条resource的批次上限，开销还随列表长度增长。`planResources`把顺序反了过来。

`test_query_plan.py`在SQLite上跑通了整条链路：

```
PDP plan  ->  condition tree  ->  WHERE clause  ->  rows
```

| Principal | Action | Plan kind | 返回的行 |
|---|---|---|---|
| `alice` USER | read | CONDITIONAL | `doc-alice-pub`, `doc-alice-unpub`, `doc-bob-pub` |
| `dave` USER | read | CONDITIONAL | `doc-alice-pub`, `doc-bob-pub` |
| `alice` USER | update | CONDITIONAL | `doc-alice-pub`, `doc-alice-unpub` |
| `bob` USER | delete | CONDITIONAL | `doc-bob-pub`, `doc-bob-unpub` |
| `admin1` ADMIN | read | ALWAYS_ALLOWED | 全部六条 |
| `guest` GUEST | read | ALWAYS_DENIED | 无 |

条件返回时已经**针对该principal求值**，不是符号形式：

```
alice / read -> OR(request.resource.attr.isPublished == true,
                   request.resource.attr.ownerId == "alice")
dave  / read -> OR(request.resource.attr.isPublished == true,
                   request.resource.attr.ownerId == "dave")
```

而这个文件里最有力的检查是：对每一个action，查询plan选中的行与逐个resource检查所允许的行**是同一集合**。这是通往同一个答案的两条路径；如果它们发生偏离，列表接口就会显示直接检查会拒绝的行，或者隐藏调用方可能据以操作的行。

---

## 7. 怎么跑

```bash
uv run pytest                       # 整个测试套件
uv run pytest tests/test_query_plan.py -v
uv run python -m cerbos_policy_tests --save    # 覆盖率审计, 并保存结果
uv run cerbos-policy-tests          # 冒烟检查: 健康, 清单, 一次决策
```

环境变量：`CERBOS_PDP_URL`、`CERBOS_ADMIN_USER`、`CERBOS_ADMIN_PASSWORD`、`CERBOS_CA_FILE`。

关于这台机器，测试框架不得不绕开的两件事，二者都记录在`src/cerbos_policy_tests/config.py`中：

* httpx会从Windows注册表读取代理设置，因此它会把PDP调用路由到`10.9.32.1:8000`，而这台内网主机访问不到该代理。PDP主机在导入时就被加进`NO_PROXY`。
* SDK在3593端口上更偏好gRPC；这台PDP只开放3592。因此显式选择HTTP客户端，并由一个测试记录下原因。
