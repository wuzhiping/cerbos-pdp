# HANDOFF.md · Cerbos PDP 项目交接

> **项目**:把 FDEP 的集中式调用入口接到 Cerbos PDP 上,让它有权限控制。
> **状态**:设计已定,实现未开始。测试套件 328 通过。
> **日期**:2026-10-30

---

## 1. 三份文档的分工

| 文件 | 是什么 | 什么时候看 |
|---|---|---|
| **`FDEP-AUTHZ-DESIGN.md`** | **方案本身** —— 要做什么、怎么做、分几步 | 要动手时 |
| `Policies.md` | 官方文档 0.57.0 的**逐页阅读笔记**(16 节) | 想确认某个 Cerbos 语义时 |
| `PDP.md` | 把 Cerbos 翻译成**防火墙管理员的直觉** + 一条真实请求的完整生命周期 | 理解概念、或给不熟 Cerbos 的人讲时 |

**先读 `FDEP-AUTHZ-DESIGN.md`。** 另外两份是它的依据和展开。

---

## 2. 现状

### 2.1 已经跑起来的东西

| | 状态 |
|---|---|
| PDP | `http://10.17.1.201:3592`,Cerbos **0.57.0**,admin `cerbos` / `cerbosAdmin` |
| 存储 | **sqlite3**(可变,策略可走 Admin API 部署) |
| 审计 | **local** 后端,`GET /admin/auditlog/list/KIND_DECISION` 可查 |
| schema 校验 | `schema.enforcement: reject`(开着) |
| 策略 | `resource.basicResource.vdefault` + `basicResource.json` / `principal.json` |
| 测试套件 | **328 passed**,对着线上 PDP 跑 |
| 覆盖率审计 | 22 行 / 6 条路径,全过 |

**仓库**:`C:\Users\shawoo\Desktop\feg.cn\cerbos-pdp\PDP\`(工作区在 `C:\Users\shawoo\Desktop\PDP\`)。

### 2.2 还没做的

**FDEP 侧的改造一行都没动。** 授权闸门、身份验证、audit 落地 —— 全是设计,没有实现。

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
| 13 | **带 scope 但 store 里没有对应 policy → `NO_MATCH`** | 基础 policy **不会**被咨询,全部拒绝。新增 org 忘了加 policy 就中招 |
| 14 | **scope 存储 id 是 `<kind>.v<version>/<scope>`** | `resource.fdepApi.vdefault/jev` |
| 15 | **scope 存在时,更具体的 scope 覆盖基础 policy** | 同一角色:scoped 的 DENY 赢过基础的 ALLOW |
| 16 | **`engine.strictEvaluation` 默认关** | 条件写错的 `EFFECT_DENY` 规则会被**静默跳过** —— 最危险的失败模式 |

### 3.2 FDEP 源码侧

| # | 结论 | 影响 |
|---|---|---|
| 17 | **`do` 被取反一次**(`"do": !i.payload.do`) | pipe.py 里 `share.do == False` 才是「执行」 |
| 18 | **`C4.` 前缀是服务端强制加的,且是叠加** | 调用方绕不过;`@jev.C4.x` → `C4.C4.x`。**它不进 resource** |
| 19 | **同一 C4 路径在不同 org 下是不同的服务** | provider 必须表达在授权里 —— 用 scope |
| 20 | **客户端给的身份全被丢弃** | 身份必须由服务端产生 —— 授权的主体可信 |

### 3.3 概念映射(防火墙视角)

从 `PDP.md` 逐条确认过:

| Cerbos | 防火墙直觉 |
|---|---|
| `principal` | **From(源)** |
| `resource` | **To(目标)** |
| `rules` | **管控策略** |
| `principal.roles` | **用户组** |
| `scope` / `action` / `kind` / `id` / `derivedRoles` | **决定不映射** —— 用 Cerbos 自己的术语 |

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

**resource**:app id 的三段各有归属 ——

```
app id  @jev.systemone.Choice
          │      │        └──► action      = Choice
          │      └───────────► id          = systemone(一族服务,精确匹配)
          └──────────────────► scope       = jev(哪个 provider)
attr: { accessMode: read|execute, riskLevel: low|medium|high }
```

**`attr` 只有 2 个字段** —— `app` 去了 id,`provider` 去了 scope,`operation` 去了 action。

**policy 两份**:`fdepApi.yaml`(基础,无 scope,三条通用规则)+
`fdepApi.jev.yaml`(scope: jev,guest 规则在这)。**不加 catch-all DENY。**

**三条最要紧的**:

1. **`do` 取反** —— 判断写反,整个授权就反了
2. **403 和 503 要分开** —— 「判断不了」不等于「不允许」;403 会被当成没权限而放弃重试
3. **影子模式先跑** —— 阶段 2 只观察不拦截,用真实流量验证 policy,错判成本为零

---

## 5. 下一步

| 阶段 | 内容 | 验收 |
|---|---|---|
| **0** | 确认 FDEP 服务器能连到 PDP:3592;确认认证层能给什么角色 | 两个答案 |
| 1 | PDP 侧:`fdepApi` policy + schema + 原生测试套件,部署 | 套件全绿;`GET /admin/policies` 有清单 |
| 2 | FDEP 侧:闸门骨架 + PDP 客户端,**先全部放行** | 调用进 PDP、产生轨迹,但不拦 |
| 3 | 影子模式跑一段,比对 PDP 的决定与业务实际该不该允许 | 影子报告 → 调 policy |
| 4 | 改成拦截 | 真的挡下越权调用 |
| 5 | 开 FDEP 侧 audit,与 PDP 轨迹对账 | `cerbosCallId` 两边对得上 |

**阶段 0 的两个答案是前提** —— 连不上,后面全部不成立。

---

## 6. 未决

| # | 问题 | 影响 |
|---|---|---|
| 1 | **FDEP 服务器能连到 PDP:3592 吗?** | 前提 |
| 2 | 认证层能给什么角色?角色名定什么? | 决定 policy 的形状 |
| 3 | app 注册表现在在哪?谁维护? | 决定控制栏位怎么取得 |
| 4 | pipe.py 上层怎么把异常转成 HTTP 响应? | 决定 403 / 503 怎么送出 |
| 5 | PDP 策略只存在 sqlite3,备援是什么? | PDP 挂掉时闸门会全拒绝(安全但不可用) |
| 6 | 与 4KI `rbac.md` 的 R1..R8 怎么对应? | 角色体系 |
| 7 | 每个 org 一份 scoped policy,谁负责同步? | 漏一份 → 那个 org 全断 |
| 8 | 要不要开 `engine.lenientScopeSearch` / `engine.strictEvaluation`? | 都要改配置并重启共享 PDP |

---

## 7. 环境注意事项

| | |
|---|---|
| **PDP 是共享的线上服务** | 改它之前先确认影响面。策略集为空时**健康检查照样 SERVING** —— 唯一可靠的检查是 `GET /admin/policies` |
| **httpx 会走 Windows 注册表里的代理** | 内网主机连不上 → `config.py::bypass_proxy` 把 PDP 加进 `NO_PROXY` |
| **只装 uv + Python** | 没有 cerbos 二进制、没有 Docker、没有 Go |
| **uv 缓存必须在工作区内** | `UV_CACHE_DIR=<workspace>\.uv-cache` |
| **Python stdout 在中文 Windows 上是 gbk** | 脚本里 `sys.stdout.reconfigure(encoding="utf-8")` |
| **pytest 的缓存目录被沙箱拒绝** | `-p no:cacheprovider` |
| **文件读写用 Python 或编辑工具,别用 PowerShell** | `Get-Content -Raw` → `WriteAllText` 会破坏 UTF-8 中文(本项目踩过) |
| **3593 端口状态变过** | 早期关闭,现在开着并服务 gRPC。HTTP 路径一直可用,不必为 gRPC 叠依赖 |
| **scope 不是兜底** | 请求带了 scope 而 store 里没有对应 policy → 全拒。基础 policy 不救场 |
| **`strictEvaluation` 默认关** | 条件写错的 DENY 规则会被静默跳过 —— 授权场景应当打开 |

---

## 8. 常用命令

```powershell
$env:UV_CACHE_DIR = "C:\Users\shawoo\Desktop\PDP\.uv-cache"
$env:PYTHONIOENCODING = "utf-8"
cd C:\Users\shawoo\Desktop\PDP

uv run pytest                                    # 328 passed
uv run python verify_api_skills.py               # 端点 vs OpenAPI 文档
uv run python "pdp-config\push-policies.py" --pdp http://10.17.1.201:3592 --policies policies
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
| `FDEP-AUTHZ-DESIGN.md` | **方案** |
| `Policies.md` | 官方文档阅读笔记 |
| `PDP.md` | 防火墙视角的映射 + 完整请求生命周期 |
| `policies/resource_policies/` | `basicResource.yaml` + 原生测试套件 + `testdata/` |
| `pdp-config/` | PDP 配置(sqlite3 + local audit + `schema.enforcement: reject`)与部署脚本 |
| `src/cerbos_policy_tests/` | 测试框架:`pep.py` 是强制执行点辅助模块 |
| `tests/` | 328 个对着线上 PDP 跑的用例 |
| `.dsh/skills/cerbos-policy/` | 三个 Cerbos skill(API 版本,中文) |
| `feg.cn/4KI/governance/rbac.md` | 角色与权限矩阵(R1..R8)—— 角色体系的来源 |
| `feg.cn/FDEP-API.md` | FDEP 协议与插件开发记录 |
