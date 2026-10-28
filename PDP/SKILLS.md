# SKILLS.md — `.dsh/skills/*` 使用说明

`.dsh/skills/` 现在只保留 **3 个** Cerbos skill(Zenauth, Apache-2.0)。

| 保留 | 一句话定位 |
|---|---|
| **`cerbos-policy`** | 写策略、改规则、配 `*_test.yaml` 测试套件 |
| **`cerbos-pep-integration`** | 在应用代码里调 PDP 做权限校验(PEP) |
| **`cerbos-audit-insights`** | 开关审计日志、脱敏 PII、查决策日志 |

**说明语言已改成中文**,三个 `SKILL.md` 和主要参考文件都换成了中文说明;端点、YAML、JSON 字段名和代码保持原样。**Admin 账号是 `cerbos` / `cerbosAdmin`**(HTTP Basic),skill 里所有 `/admin/*` 调用都直接用它,也可以用 `CERBOS_ADMIN_USER` / `CERBOS_ADMIN_PASSWORD` 覆盖。

> **这三个已经是 API 版本。** 原版依赖 `cerbos compile` / `cerbos test` / `cerbos repl` / `cerbosctl`,在本机一律跑不通(没有 cerbos 的 Windows 版本、没有 Docker、只有 uv + Python)。三个 skill 已按 PDP 自己发布的 OpenAPI 文档重写,每个动作都落到一个 HTTP 端点上:
>
> | 原本 | 现在 |
> |---|---|
> | `cerbos compile` 编译校验 | `POST /admin/policy` —— PDP 就是编译器(需要可变 store) |
> | `cerbos test` 跑测试套件 | `POST /api/check/resources` —— 每个断言一次决策请求 |
> | `cerbos repl` 调试条件 | `includeMeta` 的 `matchedPolicy` + `GET /admin/policies/inspect` + 决策记录 |
> | `cerbosctl audit` / `cerbosctl decisions` | `GET /admin/auditlog/list/{kind}` |
> | `coverage_audit.py`(吃编译报告) | `scripts/coverage_audit_api.py`(吃线上真实决策) |
>
> 原版依赖 CLI,备份曾放在 `.dsh/skills-backup/`,**迁移验证通过后已删除**——API 版本是这三者的超集,原版随时可以从上游取回。`openapi-spec.json`(PDP 自己发布的 OpenAPI 文档)同时放在仓库根目录和三个 skill 的 `references/` 里。


---

## 一句话选型

| 你要做的事 | 用哪个 |
|---|---|
| 决定谁能做什么——角色、权限、按属性的条件 | **`cerbos-policy`** |
| 从应用代码调用 PDP;`planResources` 过滤列表;传 JWT claims | **`cerbos-pep-integration`** |
| 开启审计/决策日志;日志出网前脱敏;回答合规问题 | **`cerbos-audit-insights`** |

判断口诀:**规则要改 → policy;代码要调 → integration;历史要看 → audit。**

---

## ⚠️ 选型入口没有了,路由要人来判

原先这 8 个里有一个 `cerbos` 充当**总入口**:它是一张"用户描述的需求 → 该用哪个组件、哪个 skill"的映射表,本身不写任何策略或代码。它已被移除,所以现在**跨 skill 的路由需要人工判断**——上表的口诀就是替代品。

下面三段是移除的另外 4 个 skill 覆盖的领域。**本项目当前都不涉及**,但记下来是为了将来遇到时知道该去哪里:

| 移除的 skill | 覆盖的领域 | 本项目是否需要 | 将来需要时怎么办 |
|---|---|---|---|
| `cerbos-hub-setup` | Hub 搭建运维:policy store、deployment、凭证、bundle 推送、冻结回滚 | **否**——当前是单 PDP + sqlite3 驱动,不依赖 Hub | 桶里已经没有了(见下方说明);`cerbos-policy/references/HUB.md` 里仍保留了上传动作的说明 |
| `cerbos-embedded-pdp` | 浏览器/React Native/边缘函数/无服务器里的嵌入式 PDP(WASM) | **否**——当前架构是后端 PDP + Python SDK | 桶里已经没有了;或查 [docs.cerbos.dev](https://docs.cerbos.dev/cerbos/latest/deployment/serverless-faas) |
| `cerbos-authz-migration` | 把散落在代码里的权限检查迁到 Cerbos | **否**——本项目是**新建**授权,没有存量要迁 | 桶里已经没有了 |
| `cerbos-synapse-extension` | Synapse 扩展:call mapper / data source / proxy / route / Envoy ext_authz | **否**——当前没有 Synapse,授权点在应用进程内 | 桶里已经没有了 |

被删的 5 个 skill **已经不在桶里了**:`admin/aife/PDP/` 这个前缀一度整个丢失,恢复时只找回了保留的这 3 个。它们可以从 Cerbos 官方仓库取回(Apache-2.0),但**本机没有副本**。

---

## 1. `cerbos-policy` —— 写策略和测试套件

**触发场景**:从需求或规格文档(含 PDF)生成访问控制规则;改现有策略的放行范围;策略编译不过;策略测试跑不过;策略要经 Hub policy store 送到 PDP。

**产出**:
- `_schemas/`(principal + 各资源的 JSON Schema)
- `derived_roles/`(共享角色、导出变量)
- `resource_policies/` / `role_policies/`
- `testdata/` fixtures
- `*_test.yaml` 测试套件

**方法论**:六问才算一条规则——**主体**、**动作**、**资源**、**条件**、**结论(allow/deny)**、**目的**。其中结论和目的必须跟人确认,不靠推断(Cerbos 默认拒绝,漏写一条 deny 就是个洞;规则名是审计线索)。

**覆盖计划**:强制先写 `coverage-plan.json`,再用自带的 `coverage_audit_api.py` 核对"每条放行路径的每个前提都有独立的拒绝用例"——只数编译通过的用例数,证明不了某个拒绝真的触到了预期边界。

**校验**:全走 API——`POST /admin/policy` 编译(PDP 存的时候就编译,错误当场报出来),`POST /api/check/resources` 把每条断言跑一遍,再跑 `coverage_audit_api.py` 对着**线上真实决策**核对覆盖计划。**没有 strict evaluation**:HTTP 决策 API 根本没这个开关,所以要靠"每个 fixture 带上它条件读到的每个属性"让运行时错误无处可藏。

**随附**:`references/{POLICIES,CEL,TEST-SUITES,TESTING,HUB,COVERAGE-REVIEW,API-VALIDATION}.md`、`references/openapi-spec.json`(PDP 自己发布的 OpenAPI 文档)、`scripts/coverage_audit_api.py`(对着线上 PDP 执行,只需 Python 3 标准库 + PyYAML)

**版本**:1.18 · 目标 Cerbos 0.57.0 · **只走 HTTP API**,不需要 cerbos CLI 或 Docker

---

## 2. `cerbos-pep-integration` —— 应用代码里的权限闸门

**触发场景**:在 handler 里加权限校验;用 `planResources` 过滤列表或查询;把 JWT claims 传给 PDP;给 agent / MCP 工具调用加权限;挑选 SDK(JS/Go/Python/Java/.NET/Rust/PHP/Ruby)。

**四种问法对应四种 API**:

| 问题 | 调用 |
|---|---|
| 这个人能不能对这东西做 X? | `isAllowed` → bool |
| 这个人能对这东西做哪些? | `checkResource` → 多个 action,一次往返 |
| 这一批我已持有的东西里,哪些能动? | `checkResources` → 批量(默认 50 资源 × 50 action) |
| 哪些东西我能看到? | `planResources` → 条件树,交给 ORM 转成 `WHERE` |

**最常见的错误**:拿 `checkResources` 逐条过滤列表。分页会被破坏(数据库先选了页,授权后跑)、计数和聚合算不出来、撞上 50 条上限,而且代价随列表长度线性涨。正确做法是 `planResources` 把顺序倒过来,让数据库先过滤。

**另一条铁律**:**报错即拒绝**。PDP 不可达是故障不是许可,让它以 5xx 冒出来;落到"默认允许"就是把一次故障变成授权绕过。而且拒绝和故障要在日志里分得开,否则遥测里看着像策略 bug。

**Agent / MCP 的额外规矩**:principal 取**真人用户**,不是 agent 的服务身份(否则任何用户都能借它的权限),也不是模型自己填的 user id;工具当资源,每次调用前校验;失败即拒绝。

**随附**:`references/{python,javascript,go,java,dotnet,rust,php,ruby}.md`、`api-shapes.md`(线上报文与响应,命名有歧义时以它为准)、`query-plan.md`(查询计划与 ORM 适配器)

**版本**:1.18 · 目标 Cerbos 0.57.0

---

## 3. `cerbos-audit-insights` —— 审计与洞察

**触发场景**:开启审计或决策日志;让 PDP 真的吐出决策;排查"应用放行/拒绝错了";日志出网前脱敏 PII / token / header;回答合规审计问题(SOC 2、ISO 27001、HIPAA、PCI DSS、GDPR)。

**四种后端,差别在"记录落到哪、怎么查、能否跨实例"**:

| 后端 | 记录落在 | 怎么查 | 跨实例 |
|---|---|---|---|
| `local` | PDP 内嵌 KV 存储 | **Admin API**:`GET /admin/auditlog/list/{kind}`(响应是 NDJSON,一行一条记录,要逐行解析) | 一次一个 PDP |
| `file` | NDJSON 文件或 stdout/stderr | 你自己的采集器 | 只有你自己搭的那部分 |
| `kafka` | Kafka topic | 你的消费者 | 只有你自己搭的那部分 |
| `hub` | PDP 本地缓冲,流向 Cerbos Hub | Hub 控制台:审计检索、Insights、导出 | ✅ |

**归属边界**:策略为什么那样求值 → `cerbos-policy`;永远不调 PDP、把错误吞成拒绝、传错属性的 PEP → `cerbos-pep-integration`;Synapse 该补却没补的属性 → 已移除的 `cerbos-synapse-extension`(可从桶里恢复)。

**随附**:`references/{READING,MASKING,DEBUG,sources}.md`、`references/openapi-spec.json`

**版本**:1.18 · 目标 Cerbos 0.57.0

---

## 典型任务链路

**1. 写一条新规则**
`cerbos-policy`(写策略 + `*_test.yaml`)→ `cerbos-pep-integration`(在 handler 里接 SDK)→ `cerbos-policy`(两遍编译 + 覆盖审计)

**2. 把列表按权限过滤**
`cerbos-pep-integration` 的 `planResources` + ORM 适配器(`cerbos-sqlalchemy`、`@cerbos/orm-prisma` 等)

**3. 排查"为什么放行了/拒绝了"**
`cerbos-audit-insights`(查决策日志找到那条 entry)→ `cerbos-policy`(改它指向的规则)

**4. 合规留痕**
`cerbos-audit-insights`(开 `audit.enabled`、选后端、配脱敏 mask、查日志)

> 这三条链路里,原本还有"推到所有 PDP"、"前端按权限显示"、"迁移存量"等环节,分别依赖已移除的 `cerbos-hub-setup`、`cerbos-embedded-pdp`、`cerbos-authz-migration`。本项目当前不需要。

---

## 本机环境对这三个 skill 的实际影响

| 现象 | 影响 | 处理 |
|---|---|---|
| **Docker 被禁用** | 原本是 `cerbos-policy` 的编译校验跑不了 | **已经不再是问题**——API 版本的 skill 不需要容器,编译由 PDP 自己完成 |
| **没有 cerbos 二进制** | 同上 | 同上 |
| **curl 的 Schannel 拿不到证书**(`SEC_E_NO_CREDENTIALS`) | 任何走 Windows Schannel 的 TLS 工具连不上外网 | 用 uv(rustls)或 Python(OpenSSL);curl 只对内网 HTTP 可用 |
| **httpx 走注册表里的代理** | 默认把内网 PDP 的请求路由到 `10.9.32.1:8000`,直接超时 | 把 PDP 主机加进 `NO_PROXY`,见 `src/cerbos_policy_tests/config.py` |
| **uv 默认缓存在工作区外**,写入被沙箱拒 | `uv` 任何子命令失败 | `UV_CACHE_DIR` 指到工作区内的 `.uv-cache/` |
| **没有系统 Python**,但 uv 自带 CPython 3.12.11 | 审计脚本需要 Python 3 | `uv run python` 即可,无需安装 |
| **PDP 的 gRPC 端口 3593 关闭** | SDK 的 gRPC 客户端用不了 | 用 HTTP 客户端连 3592,见 `src/cerbos_policy_tests/client.py` |

---

## 跑不动的部分(重要)

**API 版本的 skill 已经不需要 cerbos 二进制了**,`coverage_audit_api.py` 直接对线上 PDP 执行审计(本机实测 **32 passed, 0 failed**)。这台 PDP 迁移完成后,原本受配置限制的两项也都通了:

| 校验 | 作用 | 现状 |
|---|---|---|
| `POST /admin/policy` 编译校验 | 证明这份 YAML 能编译 | ✅ store 已换成 `sqlite3`,`POST /admin/policy` 返回 200,PDP 存的时候就编译 |
| `GET /admin/auditlog/list/{kind}` | 读回决策记录 | ✅ audit backend 已换成 `local`,返回 200。**注意响应是 NDJSON**,一行一条记录,要逐行解析 |
| **strict evaluation** | 把运行时 CEL 错误变成拒绝 | ❌ **HTTP 决策 API 没有这个开关**——`requestContext` 只带 `annotations`。API 下的替代做法是让情况不可能发生:每个 fixture 带上它条件读到的每个属性,并断言响应里没有 `validationErrors` |

前两项原本是 PDP 的配置问题,一次调用就能判断(store 可变性、audit backend 可查询性)。这台 PDP 已经改成了可变 store 和 `local` 后端,两项都通了。**第三项是 HTTP API 的固有限制**,任何 PDP 都一样。

这台 PDP 的配置在 `wuzhiping/cerbos-pdp` 仓库的 `config/.cerbos.yaml`,**具体怎么改、迁移时哪一步不能省**,见 [QUICKSTART.md](QUICKSTART.md#五迁移是怎么做的)。现成的推荐配置在 [pdp-config/](pdp-config/):一份 `.cerbos.yaml`(`storage.driver` 换成 `sqlite3`、`audit.backend` 换成 `local`)、一份 `compose.yml`、两个一直没被提交的 schema 文件、迁移用的 `push-policies.py`,以及逐条的改动说明。

**换存储驱动是有风险的一步**:`disk` 从目录读策略,`sqlite3` 从数据库读,磁盘里的策略**不会**自动进数据库。切过去之后策略集是空的,**每个决策都变成 DENY 却毫无报错**——`/_cerbos/health` 照样 `SERVING`,只有 `GET /admin/policies` 会说实话。所以推送策略这步不能省。




剩下的一条 xfail 是**属性 schema 校验**:schema 已经部署了(两个引用都解析成功),但 `schema.enforcement` 默认是 `warn`,所以畸形属性是**被静默拒绝**而不是被**校验错误**挡下来。改成 `reject` 之后它会翻成 XPASS 并让套件失败——那正是提醒更新该文件的信号。


---

## 与本仓库当前产物的对应关系

| 产物 | 对应 skill / 章节 |
|---|---|
| [policies/resource_policies/basicResource.yaml](policies/resource_policies/basicResource.yaml) | `cerbos-policy` Phase 2 的产出(从 admin API 反推,非磁盘原件);带规则名与目的注释 |
| [policies/resource_policies/basicResource_test.yaml](policies/resource_policies/basicResource_test.yaml) | `cerbos-policy` Phase 2 的 `*_test.yaml` 测试套件——**唯一的期望来源** |
| [policies/resource_policies/testdata/](policies/resource_policies/testdata) | `cerbos-policy` 的共享 fixtures |
| [policies/_schemas/](policies/_schemas) | `cerbos-policy` 的属性 schema(已经部署进 PDP 的 store,两个引用都解析成功) |
| [coverage-plan.json](coverage-plan.json) | `cerbos-policy` 的覆盖计划,格式与 `coverage_audit_api.py` 一致 |
| [coverage-audit.txt](coverage-audit.txt) | 覆盖审计的输出 |
| [src/cerbos_policy_tests/pep.py](src/cerbos_policy_tests/pep.py) | `cerbos-pep-integration` 的 PEP 形态 + "报错即拒绝" |
| [src/cerbos_policy_tests/queryplan.py](src/cerbos_policy_tests/queryplan.py) | `cerbos-pep-integration` 的 `planResources` → SQL 链路 |
| [src/cerbos_policy_tests/coverage.py](src/cerbos_policy_tests/coverage.py) | `cerbos-policy` 的覆盖审计规则,改为对**线上 PDP** 执行 |
| [src/cerbos_policy_tests/rules.py](src/cerbos_policy_tests/rules.py) | 策略的参考实现,作为穷举扫描的 oracle |
| [tests/test_audit_log.py](tests/test_audit_log.py) | `cerbos-audit-insights` 的审计后端状态 |
| [pdp-config/](pdp-config) | 那台 PDP 的推荐配置(sqlite3 store + local audit)和迁移脚本 |
| [quickstart/quickstart.py](quickstart/quickstart.py) | 四个动作的完整实现,只走 API;默认只读,`--deploy` 才写 |
| [openapi-spec.json](openapi-spec.json) | PDP 自己发布的 OpenAPI 文档,`verify_api_skills.py` 拿它核对端点 |
| [README.md](README.md) / [TEST-REPORT.md](TEST-REPORT.md) / [QUICKSTART.md](QUICKSTART.md) | 项目说明、测试报告与中文上手指南 |

---

## 版本与兼容性

| skill | 版本 | 依赖 / 限制 |
|---|---|---|
| `cerbos-policy` | 1.18 | 只走 HTTP API;目标 Cerbos 0.57.0 |
| `cerbos-pep-integration` | 1.18 | 目标 Cerbos 0.57.0 |
| `cerbos-audit-insights` | 1.18 | 目标 Cerbos 0.57.0 |

> 本机 PDP 是 **Cerbos 0.57.0**,和 skill 声明的目标版本一致。API 形状全部对着这台 PDP 实测过:`/admin/policies`、`/admin/policies/inspect`、`/admin/policy?id=`、`POST /api/check/resources`、`GET /admin/auditlog/list/{kind}`。**注意审计端点返回的是 NDJSON**,形状和 OpenAPI 文档里的描述对不上,实测形状以 `cerbos-audit-insights/SKILL.md` 为准。
