# HANDOFF.md · Cerbos PDP 项目交接

> **项目**:把 FDEP 的集中式调用入口接到 Cerbos PDP 上,让它有权限控制。
> **状态**:阶段 0(部分)/ 1 / 2 已落地。测试套件 453 通过。
> **日期**:2026-11-02

---

## 1. 三份文档的分工

| 文件 | 是什么 | 什么时候看 |
|---|---|---|
| **`PLAN.md`** | **落地计划 + 实测结果** —— 分几步、每步验收是什么、做到哪了 | 要动手时 |
| **`FLOW.md`** | **一次调用走过的路** —— 六站流程图、名词表、实测出来的坑 | 想搞清整条链时 |
| **`FDEP-AUTHZ-DESIGN.md`** | **方案本身** —— 要做什么、怎么做、分几步 | 要动手时 |
| `Policies.md` | 官方文档 0.57.0 的**逐页阅读笔记**(16 节) | 想确认某个 Cerbos 语义时 |
| `PDP.md` | 把 Cerbos 翻译成**防火墙管理员的直觉** + 一条真实请求的完整生命周期 | 理解概念、或给不熟 Cerbos 的人讲时 |

**先读 `PLAN.md`。** 另外三份是它的依据和展开。

---

## 2. 现状

### 2.1 已经跑起来的东西

| | 状态 |
|---|---|
| PDP | `http://10.17.1.201:3592`,Cerbos **0.57.0**,admin `cerbos` / `cerbosAdmin` |
| 存储 | **sqlite3**(可变,策略可走 Admin API 部署) |
| 审计 | **local** 后端,`GET /admin/auditlog/list/KIND_DECISION` 可查 |
| schema 校验 | `schema.enforcement: reject`(开着) |
| 策略 | `resource.basicResource.vdefault` + **每个 provider 一份**(`resource.pip.JEV.LAYA.vdefault` / `resource.pip.FDEP.SOP.vdefault`) |
| schema | `basicResource.json` / `principal.json` / `fdep.json` |
| 测试套件 | **453 passed**,对着线上 PDP 跑 |
| 覆盖率审计 | 22 行 / 6 条路径,全过 |

**仓库**:当前工作目录。本文档里的路径都相对于它。

### 2.2 已经做了一半的事

| | 状态 |
|---|---|
| PDP 侧 | **已完成**:每个 app 家族一份基础 + 每个 (家族 × provider) 一份 + schema + 原生测试套件,已部署,清单核对过 |
| FDEP 侧 | **参考实现已完成**:`src/fdep_authz/` —— api id 解析、principal/resource 组装、PDP 客户端(标准库 `urllib`)、闸门本体(403 / 503 分流、影子模式)、PocketFlow 的 `调度` Node。**但还没搬进 `pipe.py`**,也没接上身份层 |

### 2.3 还没做的

| | |
|---|---|
| FDEP 侧落地 | 闸门搬进 `pipe.py`;身份层填真实 `user_id` / `roles`;FDEP 侧 audit 写 `cerbosCallId` |
| 阶段 3–5 | 影子模式跑真实流量 → 改拦截 → 两边 audit 对账。见 `PLAN.md` |

---

## 3. 已确定的关键结论

每一条都有实测依据,出处见 `Policies.md` 或 `PDP.md`。

### 3.1 Cerbos 侧

| # | 结论 | 影响 |
|---|---|---|
| 1 | **默认拒绝,不存在「没有意见」** | 策略集为空时每个请求都被拒,而健康检查照样 `SERVING` |
| 2 | **同角色内拒绝优先;跨角色取并集** | 一个主体持有多角色 → 权限取并集,不是取最严 |
| 3 | **规则省略 `roles` → 整个 policy 失效** | 所有请求被拒,而 policy「看起来部署成功」 |
| 4 | **省略 `roles` 不等于「所有人」** | 对所有人要写 `roles: ["*"]` |
| 5 | **schema 按 policy 声明** | 每个 policy 有自己的属性词汇表,互不影响 |
| 6 | **schema id 用相对路径** | 带 `cerbos:///` 前缀 → 「看着成功」但每请求被拒,且读不回来 |
| 7 | **`requestContext.annotations` 不参与求值** | 关联信息放这里,放 `principal.attr` 就成了策略输入 |
| 8 | **`cerbosCallId` ↔ 审计日志条目** | 决策与日志的唯一桥梁 |
| 9 | **审计记录约 13 秒后才可见** | 读轨迹要轮询 |
| 10 | **审计响应是 NDJSON** | `response.json()` 会抛 `Extra data` |
| 11 | **`DELETE /admin/policy` 是停用不是删除** | 真删要用 `POST /admin/policy/delete` |
| 12 | **`roles` 为空数组 → PDP 返回 400** | 不是决策,是请求不合法 |
| 13 | **store 里没有这个 kind 的 policy → `NO_MATCH`** | 全部拒绝,答案说的是「没找到 policy」而不是「不允许」。**一个 provider 一份 policy,没有链** |
| 14 | **kind 里的冒号在 store id 里变成下划线** | `resource.pip.JEV.LAYA.vdefault` |
| 15 | **不用 scope 了** | provider 进 kind,app 家族进 id(`R.id`),操作进 action |
| 15b | **app 授权按 `P.id` 判,角色用 `["*"]` 忽略** | `roles: ["*"]` 是官方文档注 12 的「忽略角色」。这解掉了角色名对不上的问题 —— 平台发的 `user_id` 是 `guests` |
| 16 | **`engine.strictEvaluation` 默认关** | 条件写错的 `EFFECT_DENY` 规则会被**静默跳过** —— 最危险的失败模式 |

### 3.2 FDEP 源码侧

| # | 结论 | 影响 |
|---|---|---|
| 17 | **`do` 被取反一次**(`"do": !i.payload.do`) | pipe.py 里 `share.do == False` 才是「执行」 |
| 18 | **`C4.` 前缀是服务端强制加的,且是叠加** | 调用方绕不过;`@jev.C4.x` → `C4.C4.x`。**它不进 resource** |
| 19 | **同一 C4 路径在不同 org 下是不同的服务** | provider 必须表达在授权里 —— 用 kind |
| 20 | **客户端给的身份全被丢弃** | 身份必须由服务端产生 —— 授权的主体可信 |

### 3.3 概念映射(防火墙视角)

从 `PDP.md` 逐条确认过:

| Cerbos | 防火墙直觉 |
|---|---|
| `principal` | **From(源)** |
| `resource` | **To(目标)** |
| `rules` | **管控策略** |
| `principal.roles` | **用户组** |
| `action` / `kind` / `id` / `derivedRoles` | **决定不映射** —— 用 Cerbos 自己的术语 |

**唯一需要特别理解的语义差异**:防火墙 ACL 是「第一条匹配就赢」,
Cerbos 是「同角色内拒绝优先,跨角色取并集」。详见 `PDP.md` §3.1。

---

## 4. 方案要点

完整版在 `FDEP-AUTHZ-DESIGN.md`。这里是骨架:

```
调用方 ──► BPM/Node 層 ──► pipe.py ──► Temporal ──► app 工作流
              ① 验证身份      ⑤ 授权判断
              ② 拆 app id    ⑥ DENY → 403,不进 Temporal
              ③ 组 _token_    ⑦ ALLOW → runWF
              ④ 组 resource   ⑧ 写 FDEP 侧 audit
```

**闸门放在 pipe.py**,因为它已经在做 `sk` 时效校验 —— 授权和「这次请求是不是新的」
在同一个位置,而且它是所有调用的必经之路。

**resource**:app id 的两段各有归属,provider 进 kind ——

```
app id  @jev.systemone.LAYA.Choice
          │      │        └──► action      = Choice
          │      └───────────► id          = systemone.LAYA(C4 path,精确匹配)
          └──────────────────► kind       = pip.JEV.LAYA(哪个 provider)
```

**没有 attr** —— `accessMode` 和 `riskLevel` 暂时整个关掉了
(`pdp-config/orgs.yaml` 的 `attributes: false`):没有任何规则读它们,
schema 也不声明。**后果:现在只有 `FDEP_ADMIN` 能过。**

**没有 scope。** kind 由服务端从 org 配置算出,调用方改不了。

**`attr` 暂时是 0 个字段** —— `app` 去了 id(C4 path),`provider` 去了 kind,`operation` 去了 action(操作名);剩下的两个控制栏位等 app 注册表接上再回来。

**policy 是每个 provider 一份**:`policies/pip.JEV.LAYA.yaml` 等(**通用规则 + 各家族的规则都在里面,家族靠 `R.id` 分开**)。**不加 catch-all DENY。**

**三条最要紧的**:

1. **`do` 取反** —— 判断写反,整个授权就反了
2. **403 和 503 要分开** —— 「判断不了」不等于「不允许」;403 会被当成没权限而放弃重试
3. **影子模式先跑** —— 阶段 2 只观察不拦截,用真实流量验证 policy,错判成本为零

---

## 5. 下一步

**完整的计划、验收标准和实测结果在 `PLAN.md`。** 当前的进度:

| 阶段 | 内容 | 状态 |
|---|---|---|
| **0** | 确认 FDEP 服务器能连到 PDP:3592;确认认证层能给什么角色 | PDP 可达性已确认;另两个答案还没有 |
| 1 | PDP 侧:policy + schema + 原生测试套件,部署 | ✅ 完成 —— 套件全绿,清单里每个家族的基础和每个配对都在 |
| 2 | FDEP 侧:闸门骨架 + PDP 客户端,**先全部放行** | ✅ 参考实现完成(`src/fdep_authz/`,含 PocketFlow 的 Node);**待搬进 `pipe.py`** |
| 3 | 影子模式跑一段,比对 PDP 的决定与业务实际该不该允许 | ⏸ 待 FDEP 环境 |
| 4 | 改成拦截 | ⏸ 待阶段 3 |
| 5 | 开 FDEP 侧 audit,与 PDP 轨迹对账 | ⏸ 待阶段 4 |

**阶段 0 剩下的两个答案是前提** —— 连不上,后面全部不成立。

---

## 6. 未决

| # | 问题 | 影响 |
|---|---|---|
| 1 | **FDEP 服务器能连到 PDP:3592 吗?** | 前提 |
| 2 | 认证层能给什么角色?角色名定什么? | 决定 policy 的形状 |
| 3 | app 注册表现在在哪?谁维护? | 决定 `riskLevel` 怎么取得 |
| 4 | pipe.py 上层怎么把异常转成 HTTP 响应? | 决定 403 / 503 怎么送出 |
| 5 | PDP 策略只存在 sqlite3,备援是什么? | PDP 挂掉时闸门会全拒绝(安全但不可用) |
| 6 | 与外部权限矩阵(R1..R8)怎么对应? | 角色体系 |
| 7 | 新增 org 的流程:改 `orgs.yaml` → 跑生成器 → 推送,谁负责? | 漏一步 → 那个 org 全断 |
| 8 | 要不要开 `engine.lenientScopeSearch` / `engine.strictEvaluation`? | 都要改配置并重启共享 PDP |

> ~~provider 的真值~~ **已解决**:`jev` 的 org 配置是
> `{ namespace: "pip", task_queue: "JEV", workflow: "LAYA" }`,
> kind 是 **`pip.JEV.LAYA`**,每个 provider 一份 policy。
> 已生成、已部署、`--verify` 通过。

---

## 7. 环境注意事项

| | |
|---|---|
| **PDP 是共享的线上服务** | 改它之前先确认影响面。**store 里会有别人的 policy** —— 别删别人的,清单断言也只管自己那几个 kind。策略集为空时**健康检查照样 SERVING** —— 唯一可靠的检查是 `GET /admin/policies` |
| **httpx 会走 Windows 注册表里的代理** | 内网主机连不上 → `config.py::bypass_proxy` 把 PDP 加进 `NO_PROXY` |
| **只装 uv + Python** | 没有 cerbos 二进制、没有 Docker、没有 Go |
| **uv 缓存必须在工作区内** | `UV_CACHE_DIR=<workspace>\.uv-cache` |
| **Python stdout 在中文 Windows 上是 gbk** | 脚本里 `sys.stdout.reconfigure(encoding="utf-8")` |
| **pytest 的缓存目录被沙箱拒绝** | `-p no:cacheprovider` |
| **文件读写用 Python 或编辑工具,别用 PowerShell** | `Get-Content -Raw` → `WriteAllText` 会破坏 UTF-8 中文(本项目踩过) |
| **3593 端口状态变过** | 早期关闭,现在开着并服务 gRPC。HTTP 路径一直可用,不必为 gRPC 叠依赖 |
| **kind 不是兜底** | store 里没有这个 kind 的 policy → 全拒,答案说 NO_MATCH |
| **不用 scope 了** | provider 进 kind,一个 provider 一份 policy,没有链 |
| **缺了祖先再补上,救不回已经坏掉的叶子** | 链必须是**推的时候**就完整;一批推送是原子的,所以一次推整条链就够 |
| **scope 链里的层删不掉** | `POST /admin/policy/delete` 返回 400 `breaksScopeChain`,先删叶子 —— 现在不用 scope 了,但记着 |
| **`strictEvaluation` 默认关** | 条件写错的 DENY 规则会被静默跳过 —— 授权场景应当打开 |

---

## 8. 常用命令

```powershell
$env:UV_CACHE_DIR = "<当前目录>\.uv-cache"
$env:PYTHONIOENCODING = "utf-8"

uv run pytest                                    # 453 passed
uv run python verify_api_skills.py               # 端点 vs OpenAPI 文档
uv run python "pdp-config\gen-scoped-policies.py"            # 生成 policy
uv run python "pdp-config\push-policies.py" --pdp http://10.17.1.201:3592 --policies policies
uv run python "pdp-config\gen-scoped-policies.py" --verify   # 查 store 里有没有漏的 provider
uv run python -m cerbos_policy_tests --save      # 覆盖率审计
```

**部署策略后必查清单:**

```powershell
curl.exe -s -u "cerbos:cerbosAdmin" http://10.17.1.201:3592/admin/policies
curl.exe -s -u "cerbos:cerbosAdmin" http://10.17.1.201:3592/admin/schemas
```

---

## 9. 相关文件

| 路径 | 内容 |
|---|---|
| `PLAN.md` | **落地计划 + 实测结果** |
| `FDEP-AUTHZ-DESIGN.md` | **方案** |
| `Policies.md` | 官方文档阅读笔记 |
| `PDP.md` | 防火墙视角的映射 + 完整请求生命周期 |
| `policies/resource_policies/` | `basicResource.yaml` + 原生测试套件 + `testdata/` |
| `policies/<kind>.yaml` | **一个 provider 一份 policy**;`<kind>_test.yaml` 是它的原生套件,`policies/testdata/` 是 FDEP 的 fixture |
| `policies/_schemas/` | `principal.json` / `basicResource.json` / `fdep.json` |
| `pdp-config/` | PDP 配置(sqlite3 + local audit + `schema.enforcement: reject`)与部署脚本 |
| `pdp-config/orgs.yaml` | **org 注册表** —— 每个 provider 的 kind、它提供的 app 家族、每个家族的规则 |
| `pdp-config/gen-scoped-policies.py` | **生成器** —— 由注册表和通用规则产出全部 policy,`--verify` 查 store |
| `src/cerbos_policy_tests/` | 测试框架:`pep.py` 是强制执行点辅助模块,`fdep_rules.py` 是 FDEP 各家族的参考模型 |
| `src/fdep_authz/` | **FDEP 侧闸门参考实现** —— api id 解析、token 组装、PDP 客户端(标准库)、闸门本体、`FdepDenied`、PocketFlow 的 Node |
| `tests/` | 453 个对着线上 PDP 跑的用例 |
| `FLOW.md` | **一次调用走过的路** —— 六站流程图、名词表、实测出来的坑 |
| `.dsh/skills/cerbos-policy/` | 三个 Cerbos skill(API 版本,中文) |
