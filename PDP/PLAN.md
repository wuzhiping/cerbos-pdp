# PLAN.md · FDEP 接入 Cerbos PDP 的落地计划

> **来源**:`FDEP-AUTHZ-DESIGN.md`(方案)、`Policies.md`(官方文档阅读笔记)、`PDP.md`(概念映射)。
> **状态**:阶段 0(部分)/ 1 / 2 已落地;阶段 3–5 待 FDEP 侧环境就绪。
> **约定**:本文所有路径都相对于**当前工作目录**。

---

## 0. 本轮做完的事,一句话

把设计里的 PDP 侧(策略 + schema + 原生测试套件)真正部署到线上 PDP 并跑绿,
把 FDEP 侧闸门写成**可直接搬进 `pipe.py` 的参考实现** —— 用 `urllib`(不新增依赖)、
带 PocketFlow 的 `Node`、并把「`do` 取反 / kind 由服务端算 / 403 与 503 分开」这三条
最容易出错的规则用测试钉死。

**结果:489 passed(改造前 328),线上 PDP 策略清单里每个 app 家族的基础和每个 (家族 × provider) 都在。**

---

## 1. 阶段总览

| 阶段 | 内容 | 状态 | 验收 |
|---|---|---|---|
| **0** | 前提确认:PDP 可达性、认证层角色、app 注册表 | **部分完成** | 见 §2 |
| **1** | PDP 侧:policy + schema + 原生测试套件,部署并验证 | **✅ 完成** | 见 §3 |
| **2** | FDEP 侧:闸门骨架 + PDP 客户端,**先全部放行**(影子模式) | **✅ 参考实现完成** | 见 §4 |
| **3** | 影子模式跑真实流量,比对 PDP 决定与业务判断 | ⏸ 待 FDEP 环境 | 见 §5 |
| **4** | 影子模式改成拦截 | ⏸ 待阶段 3 结论 | 见 §5 |
| **5** | 开 FDEP 侧 audit,与 PDP 轨迹对账 | ⏸ 待阶段 4 | 见 §5 |

---

## 2. 阶段 0 · 前提确认

### 2.1 PDP 可达性 —— ✅ 本机已确认

| 检查 | 命令 | 结果 |
|---|---|---|
| 健康检查 | `GET /_cerbos/health` | `200 {"status":"SERVING"}` |
| 管理接口 | `GET /admin/policies`(Basic `cerbos:cerbosAdmin`) | `200`,清单见 §7.1 |

> ⚠️ **健康检查只说进程活着,不说策略在不在。** 策略集为空时每个决策都是 DENY,
> 而 `/admin/policies` 照样 200。**唯一可靠的检查是 `GET /admin/policies` 的清单。**

### 2.2 仍然没有答案的三件事(阻塞阶段 3)

| # | 问题 | 卡住谁 | 为什么重要 |
|---|---|---|---|
| 1 | **FDEP 服务器能连到 PDP:3592 吗?** | 阶段 3 | 连不上,整套闸门不成立 |
| 2 | **认证层能给什么角色?角色名定什么?** | 阶段 4 | 决定 policy 的形状。本轮用 `FDEP_ADMIN` / `FDEP_DEVELOPER` / `FDEP_AUDITOR` / `FDEP_GUEST`。**身份后续从系统抓取 —— 抓来的角色名必须和这几个一模一样**,见 §8 |
| 3 | **app 注册表现在在哪?谁维护?** | 阶段 2 上线 | 决定 `riskLevel` 怎么取得 |

### 2.3 本轮顺带查清的四件事

| # | 事项 | 结论 |
|---|---|---|
| 4 | `engine.strictEvaluation` / `engine.lenientScopeSearch` 开没开? | **都没开** —— `pdp-config/config/.cerbos.yaml` 里**没有 `engine:` 段**。两个都是 Cerbos 默认值 `false` |
| 5 | `push-policies.py` 支不支持 scope? | **不支持**。脚本按文件内容识别策略,scope 只能来自策略 YAML 里的 `scope:` 字段。**文件名带点没用** |
| 6 | **Cerbos 会沿 scope 层级往上找吗?** | **不会。** 请求 `a.b.c` 只由 scope 恰好是 `a.b.c` 的 policy 应答。详见 §3.4 |
| 7 | SDK 能拿到 `matchedPolicy` / `cerbosCallId` 吗? | **拿不到** —— SDK 的响应模型里没有这两个字段。详见 §4.5 |

> 第 4 条的影响:条件写错的 `EFFECT_DENY` 规则会被静默跳过(最危险的失败模式)。
> 两者都要改 `.cerbos.yaml` 并重启 PDP —— **共享服务,需要窗口期**。
>
> 第 6 条的影响见 §3.4 —— 它直接决定了「新增一个 org 要部署几份 policy」。

---

## 3. 阶段 1 · PDP 侧(✅ 完成)

### 3.1 文件

| 文件 | 作用 |
|---|---|
| `pdp-config/orgs.yaml` | **org 注册表** —— 每个 provider 的 kind、它提供的 app 家族、以及每个家族的规则 |
| `pdp-config/general-rules.yaml` | **通用规则** —— 所有 provider 都一样的那几条 |
| `pdp-config/gen-scoped-policies.py` | **生成器** —— 由上面两个文件产出全部 policy,另有 `--verify` 查 store |
| `policies/_schemas/fdep.json` | 所有 FDEP resource 共用的 schema:`accessMode` + `riskLevel` |
| `policies/<kind>.yaml` | **一个 provider 一份 policy** —— 文件名是 store 的拼法(冒号变下划线) |
| `policies/<kind>_test.yaml` | 它的原生测试套件 —— **期望的唯一真源** |
| `policies/testdata/` | FDEP 的 fixture(两个 provider 共用) |

### 3.2 一次调用的形状

FDEP 的 app id 是 `@<org-key>.<c4-path>.<operation>`:

```
@jev.systemone.LAYA.Choice
 │    │            └──► operation = Choice          插件的操作
 │    └───────────────► C4 path  = systemone.LAYA   插件所在的文件夹
 └────────────────────► org      = jev              org map 里的键

@fdep.twseMops.todayMaterial
 │     │              └──► operation = todayMaterial
 │     └─────────────────► C4 path  = twseMops
 └──────────────────────► org      = fdep
```

**最后一段永远是 operation,前面全是 C4 path。** C4 path 本身是**文件夹路径**,
可以有多段 —— `systemone.LAYA` 是文件夹 `systemone/LAYA`。

于是 Cerbos 的 resource 是:

```json
{ "kind": "pip.JEV.LAYA", "id": "systemone.LAYA" }
```

(属性暂时整个关掉了 —— 见 §3.4.1。)

请求里的 action 是**操作名**:`Choice`。

> **action 是操作的名字,不是 py 文件的名字。** py 文件(`Choice.py`)是插件的
> 实现细节 —— 策略说的是「调哪个操作」。

| RESOURCE 字段 | 对应 |
|---|---|
| `kind` | `namespace.task_queue.workflow` |
| `id` | C4 path(全路径) |
| `action` | 操作名 |
| `attr` | **暂时没有**(属性整个关掉了,见 §3.4.1) |

### 3.3 不用 scope —— 一个 provider 一份 policy

**没有 scope。** provider 进 kind,app 家族进 id,操作进 action。

所以 **每个 provider 一份 policy**,没有链、没有层级、没有哪一级会掉链子:

```
policies/
├── _schemas/fdep.json
├── pip.JEV.LAYA.yaml        ← kind pip.JEV.LAYA    (jev 提供 systemone.LAYA)
├── pip.JEV.LAYA_test.yaml
├── pip.FDEP.SOP.yaml        ← kind pip.FDEP.SOP    (fdep 提供 twseMops)
├── pip.FDEP.SOP_test.yaml
├── testdata/                ← FDEP 的 fixture
└── resource_policies/       ← basicResource(它自己的例子)
```

store 里对应:

```
resource.basicResource.vdefault
resource.pip.JEV.LAYA.vdefault
resource.pip.FDEP.SOP.vdefault
```

> **四处拼法一致。** 文件名、policy 的 `resource:`、请求的 `kind`、
> store 的 id —— 全都是同一个字符串:
>
> ```
> policies/pip.JEV.LAYA.yaml
>   resource: pip.JEV.LAYA
>     "kind": "pip.JEV.LAYA"
> resource.pip.JEV.LAYA.vdefault
> ```
>
> 这也是 kind 用**点号**而不是冒号的原因:冒号形式的 kind 会被 store 改写
> (`pip:JEV:LAYA` → `resource.pip.JEV.LAYA.vdefault`),kind 和它的 id 就对不上了。
> 点号的 kind 原样保留(实测)。

> **为什么放弃 scope。** scope 是一条**层级**:Cerbos 要求链上每一级都有
> policy,缺一级就是 NO_MATCH,整族全拒。三段路径要四份,两个家族就是八份。
> 而且 PDP 不让删有后代的层(`400 breaksScopeChain`),所以想精简也精简不掉。
> 冒号也不行 —— Cerbos 的 scope 不接受(`does not match regex pattern`),
> Windows 的目录名也不接受(`WinError 267`)。
>
> **改用 kind 之后,这些全部消失。** 实测:kind 不需要祖先 kind,
> 不带 scope 的请求由 (kind, "") 那一份应答 —— 就是那一份,没有链。

### 3.4 授权是三件事:哪个 app · 哪个操作 · 谁

**which app · which operation · who:**

| 轴 | 在 Cerbos 里是什么 | 例 |
|---|---|---|
| 哪个 app | `R.id` —— resource 的 id(C4 path) | `"systemone.LAYA"` |
| 哪个操作 | `action` —— 操作名 | `"Choice"` |
| 谁 | `P.id`(id 授权)或 `roles`(角色授权) | `"guests"` / `USERS` |

一份 policy 服务这个 provider 的所有 app 家族,靠 `R.id` 分开。

**授权有两种写法,两种都支持:**

**(a) 角色授权** —— 按角色,忽略身份:

```yaml
- name: users-may-use-twseMops
  actions: ["todayMaterial", "materialDetail"]
  roles: ["USERS"]               # FDEP 的 token 里就是这一个角色
  effect: EFFECT_ALLOW
  condition:
    match:
      expr: R.id == "twseMops"
```

**(b) id 授权** —— 按 principal 的 id,忽略角色:

```yaml
- name: someone-may-use-systemone
  actions: ["Choice", "Noul", "Score"]
  roles: ["*"]                    # 忽略角色(官方文档注 12)
  effect: EFFECT_ALLOW
  condition:
    match:
      expr: P.id == "someone" && (R.id == "systemone.LAYA")
```

**(c) 开放授权** —— 只说 app 和操作,谁来都行:

```yaml
- name: guests-may-use-systemone
  actions: ["Choice", "Noul", "Score"]
  roles: ["*"]                    # 忽略角色
  effect: EFFECT_ALLOW
  condition:
    match:
      expr: R.id == "systemone.LAYA"
```

**注册表里只写授权本身,其余生成器补齐:**

```yaml
grants:
  - name: users-may-use-twseMops
    roles: [USERS]                # 或者 principal: <id>;都不写就是开放的
    actions: [todayMaterial, materialDetail]
    effect: EFFECT_ALLOW
```

`R.id == "<C4 path>"` 也是生成器加的 —— 写授权的人只说「哪个 app 的哪个操作」。

> **为什么支持 id 授权。** Cerbos 的 rule 必须写 `roles`,但
> `roles: ["*"]` 的意思是**忽略角色**(官方文档注 12)。所以身份可以由
> `P.id` 表达,角色随便 —— 这解掉了角色名对不上的问题:
> 平台发的 `roles: ["guests"]` 和策略里写的 `FDEP_GUEST` 对不上,
> 角色规则一条都匹配不上,**每一次调用都被拒**。

通用规则没有 app 条件(对所有家族都成立):

| 规则 | 角色 | 条件 | 现在 |
|---|---|---|---|
| `admin-may-call-anything` | `FDEP_ADMIN` | — | **开** |
| `developer-may-execute-non-high-risk` | `FDEP_DEVELOPER` | `accessMode == "execute" && riskLevel != "high"` | 关(读 `R.attr`) |
| `auditor-may-only-read-low-risk` | `FDEP_AUDITOR` | `accessMode == "read" && riskLevel == "low"` | 关(读 `R.attr`) |

**通用规则只有一份**,在 `pdp-config/general-rules.yaml` 里,生成器盖进每个 provider。

**两个 provider 现在的授权:**

| provider | 家族 | 授权 | 谁 |
|---|---|---|---|
| `pip.JEV.LAYA` | `systemone.LAYA` | `Choice` / `Noul` / `Score` | **所有人**(开放) |
| `pip.FDEP.SOP` | `twseMops` | `todayMaterial` / `materialDetail` | 角色 `USERS`(FDEP 的 token 里就是它)+ 管理员 |

### 3.4.1 属性整个关掉了(`attributes: false`)

`pdp-config/orgs.yaml` 里 `attributes: false` —— **没有任何规则读 `R.attr`,
resource 的 schema 也不声明**。属性现在一点作用都没有。

原因:app 注册表还没接上,`riskLevel` 拿不到。**读一个没人供得上的属性,
比没有这条规则更糟。**

> ⚠️ **依赖属性的规则是「整条停用」,不是「只删掉条件」。**
> 条件正是让规则变窄的东西:开发者那条给的是
> `R.attr.accessMode == "execute"` **且** `R.attr.riskLevel != "high"` ——
> 只删掉条件,开发者就能执行高风险 app 了。所以整条规则退出,答案是
> **默认拒绝**,不是更宽的授权。
>
> (访客那条已经不用属性了 —— 它现在按 `P.id` + `R.id` + action 授权,
> 所以访客的授权回来了。)
>
> 规则本身留在 `general-rules.yaml` 和各家族下面,条件原样不动 ——
> 把 `attributes` 改成 `true`,它们全部回来。

**后果:现在只有 `FDEP_ADMIN` 能过**,其余角色一律默认拒绝。

### 3.5 两个 provider,两个 app 家族

| org | kind | 提供的家族 | 操作 | riskLevel |
|---|---|---|---|---|
| `jev` | `pip.JEV.LAYA` | `systemone.LAYA` | `Choice` / `Noul` / `Score` | low |
| `fdep` | `pip.FDEP.SOP` | `twseMops` | `todayMaterial` / `materialDetail` | medium(占位) |

**app 属于提供它的那家 org** —— app id 里就写着 org。所以 (kind, id) 的配对
由 registry 决定,不是笛卡尔积:**没列出的配对没有规则**,请求会落到默认拒绝。

### 3.6 kind 由服务端算,调用方改不了

kind 是 `namespace.task_queue.workflow`,从 **org 的配置**算出来
(`node.provider_kind`)。app id 里写的 org 只是「怎么称呼这个 provider」,
不影响授权 —— 否则调用方就能挑一个宽松的 provider 来给自己开路。

### 3.7 验收(实测)

| 项 | 命令 / 位置 | 期望 | 实测 |
|---|---|---|---|
| 策略清单 | `GET /admin/policies` | 一个 provider 一份 | ✅ `basicResource` + `pip.JEV.LAYA` + `pip.FDEP.SOP` |
| schema 清单 | `GET /admin/schemas` | 有 `fdep.json` | ✅ `['basicResource.json', 'fdep.json', 'principal.json']` |
| 完整性 | `uv run python "pdp-config\gen-scoped-policies.py" --verify` | 每个 provider 一份在 store 里 | ✅ |
| 全量回归 | `uv run pytest` | 全绿 | ✅ **465 passed**,0 failed |
| 覆盖率审计 | `uv run python -m cerbos_policy_tests` | no failures | ✅ |

### 3.8 顺带测出来的运维规则

| 规则 | 实测 |
|---|---|
| **`POST /admin/policy/delete` 是真删** | 删掉的东西不在 `?includeDisabled=true` 里了 |
| **停用的策略只出现在 `?includeDisabled=true`** | 用 `/admin/policies` 看「生效中的」,用带参的那个看「全部」 |
| **PDP 是共享的** | store 里会有别人的 policy —— 清单断言只管自己那几个 kind |

---

## 4. 阶段 2 · FDEP 侧闸门(✅ 参考实现完成)

### 4.1 为什么是「参考实现」

FDEP 的 `pipe.py` 不在本仓库里(本工作目录只有 Cerbos PDP 这一侧)。
所以这一阶段落地的是**一份可以直接搬进 `pipe.py` 的闸门模块**:
纯函数 + 显式输入输出,不依赖 Temporal/BPM,单测不需要网络。

```
src/fdep_authz/
├── __init__.py      # 公开 API
├── appid.py         # api id 解析:systemone.Choice -> (app, operation)
├── registry.py      # app 注册表:riskLevel 的来源
├── token.py         # inbound["_token_"] -> principal;do 取反;roles 兜底
├── client.py        # PDP 客户端(**urllib,标准库**):ALLOW / DENY / ERROR
├── cerbos.py        # cerbos_valid(...) —— 与参考实现同签名同返回形状
├── errors.py        # FdepDenied —— 拒绝时抛的那个异常
├── gate.py          # 闸门本体:403 与 503 的分流 + 影子模式
└── node.py          # PocketFlow 的 Node:调度
```

**不新增依赖**:`client.py` 只用标准库的 `urllib`。FDEP 那台机器不用为此装东西。

### 4.2 拒绝是抛异常,不是返回值

```python
if effect == 'EFFECT_DENY':
    raise outcome.to_exception()      # FdepDenied
```

**为什么不能 `return cerbosRes`**:那把「被拒绝」变成了「正常跑完了,只是结果里没有东西」。
只看「有没有出错」的调用方,会把一次被拦下来的调用当成成功 ——
一次成功但产出为空的业务调用,和一次被网关挡下的调用,在返回值上长得一模一样。

`FdepDenied` 带着四样东西出来,一样都不丢:

| 字段 | 是什么 | 少了会怎样 |
|---|---|---|
| `status_code` | 403(不许)/ 503(判断不了) | 分不清「没权限」和「不知道」 |
| `reason` | 人话的原因 | 只看到一个笼统的「失败」 |
| `cerbos_call_id` | PDP 决策的编号 | 事后对不上 PDP 的轨迹 |
| `result` | PDP 的原始回答 | 上层读不到 `actions` |

上层要把它变成响应:`exc.to_payload()`。

**抛了异常 `post` 就不执行**,所以 `shared['output']` 是空的 ——
流程的产出就是「这次调用失败了」。结果由流程的错误处理送回去。

### 4.2 与参考实现的对接

`fdep_authz/cerbos.py::cerbos_valid(run_id, do, inbound, api, kind)` 与参考实现的
`cerbosValid` **同签名、同返回形状** —— 返回 PDP 的 result entry,
所以 `(result.get("actions") or {}).get(action, "EFFECT_DENY")` 照旧能用。

多出来的东西:

| 多出来的 | 为什么 |
|---|---|
| 返回值里带 `cerbosCallId` | PDP 轨迹与 FDEP 日志的关联键 |
| `PdpUnavailable` / `PdpRejected` 取代裸 `RuntimeError` | **两者都是 `RuntimeError`**,所以只认 `except RuntimeError` 的调用方照旧能接;但想区分 503 与 403 的调用方现在能分 |
| `urlopen` 用空的 `ProxyHandler` | Windows 注册表里的代理会把内网 PDP 的请求吞掉,直到超时。参考实现里没有这一层 |

### 4.3 PocketFlow 的 Node

`fdep_authz/node.py::AuthzDispatchNode` 就是参考实现里那个 `调度(Node)`,
加上闸门:

```
shared ──► prep ──► exec ──────────────► post ──► shared["output"]
              │       │
              │       ├─► gate ──► PDP ──► DENY ──► 抛 FdepDenied,什么都没启动
              │       │            └─► 连不上 ──► 抛 FdepDenied(503),什么都没启动
              │       └─► dispatch ──► Temporal
              │
              └─ api, do, inbound, workflowId, org, run_id
```

**顺序就是全部**:拒绝必须发生在 Temporal 被叫起来之前 —— 工作流一旦跑起来,
再想停下来比一开始就不做难得多。

**抛异常时 `post` 不会执行**,所以 `shared["output"]` 是空的 ——
流程的产出就是「这次调用失败了」。结果由流程的错误处理送回去。

`dispatch` 是注入的:FDEP 传「启动 Temporal 工作流」那个函数,测试传一个桩。
Node 本身不知道 Temporal 是什么,所以它可测。

参考实现里有两处顺序问题,这里改掉了:

| 参考实现 | 改法 |
|---|---|
| `namespace = org["namespace"]` 在 `if not org` **之前** | 先检查再读。缺 org 是 `TypeError`,不是那句说清楚了的 `ValueError` |
| `riskLevel` 写死 `"low"` | 暂时没有 `riskLevel` —— 属性整个关掉了(§3.4.1)。注册表现在只回答「这个 app 存不存在」,不在注册表里是 **403**(调用方的错) |

### 4.4 四条最容易写错的规则,各由一条测试钉住

| # | 规则 | 钉住它的测试 |
|---|---|---|
| 1 | **`share.do == False` 才是「执行」** —— BPM 层取反过一次 | `test_do_false_means_execute` |
| 2 | **kind 一定要带** —— 它是 provider 的身份,漏了就不知道该问哪一份 policy | `test_the_resource_carries_the_kind_the_path_and_the_action` |
| 3 | **403 和 503 必须分开** —— 「判断不了」≠「不允许」 | `test_denied_is_403_and_unreachable_is_503` |
| 4 | **拒绝要抛异常,不能返回** —— 返回会让「被拒」长得像「跑完了没产出」 | `test_the_node_raises_when_the_pdp_denies` |

### 4.5 闸门的判定表

| 情况 | 响应 | 理由 |
|---|---|---|
| PDP 明确拒绝 | **403** | 正常的权限不足 |
| PDP 连不上 / 超时 / 回了非 200 | **503** | 「判断不了」不等于「不允许」。503 让调用方知道可以重试;403 会被当成「没权限」而放弃 |
| app 不在注册表里 | **403** | 调用方点了一个不存在的 app —— 没有东西可调,也没有东西可授权 |
| 注册表里没有这个 app | **403** | 调用方的错:这个 app 不存在,没什么可调、没什么可判 |
| `roles` 为空 | **403** | 未验证的调用,不进 PDP(§3.3) |
| api id 不可用 | **403** | 请求本身不合法 |

### 4.6 影子模式

阶段 2 的闸门**先全部放行**:调用照常进 PDP、照常产生轨迹,但**不拦任何东西**。
错判成本为零,却能用真实流量验证 policy。

```
PDP 的决定 ──► 影子报告 ──► 比对业务实际该不该允许 ──► 调 policy ──► 才开拦截
```

影子模式里 `GateOutcome` 仍然是诚实的:`allowed=True` 但 `denied_by_policy=True`,
`decision` 里留着 PDP 的原话。**影子报告要靠它,不然就白跑了。**

---

## 5. 阶段 3–5(⏸ 待 FDEP 环境)

| 阶段 | 做什么 | 阻塞在 |
|---|---|---|
| **3** | 影子模式跑一段真实流量,出「PDP 说 DENY 但业务上该允许」的清单 | FDEP 服务器 + 阶段 0 的三个答案 |
| **4** | 影子模式改成拦截,真的挡下越权调用 | 阶段 3 的清单为空或已调完 policy |
| **5** | 开 FDEP 侧 audit,与 PDP 轨迹对账,`cerbosCallId` 两边一一对上 | 阶段 4 |

### 5.1 阶段 5 的两个已知坑(实测过)

| 坑 | 后果 | 对策 |
|---|---|---|
| 审计记录约 **13 秒**后才可见 | 读一次就断言「查不到」得到的是错的结论 | **轮询**(`tests/test_fdep_api.py` 里就是这么做的) |
| 审计响应是 **NDJSON**,不是单个 JSON | `response.json()` 直接抛 `Extra data` | **逐行解析** |

### 5.2 阶段 5 的关联已经跑通过一次

`tests/test_fdep_api.py::test_the_decision_carries_the_call_id_that_links_the_two_audit_trails`
已经对着线上 PDP 跑通:闸门拿到的 `cerbosCallId`,在
`GET /admin/auditlog/list/KIND_DECISION?lookup=<callId>` 里能查到同一条记录,
`requestContext.annotations` 里的 `app_id` 也原样在里面。
**阶段 5 要做的只是把 FDEP 侧的日志行写上这个 call id。**

---

## 6. 本轮为「多一套策略」做的框架改造

加第二套策略会让几个「隐含假设只有一个策略家族」的地方失效,必须显式改掉:

| 位置 | 原来的隐含假设 | 改成 |
|---|---|---|
| `src/cerbos_policy_tests/fixtures.py` | `testdata/` 全局只有一份,`rglob` 取第一个 | **按 policy 目录解析**,并**拒绝歧义匹配**(`AmbiguousTestdataError`) |
| `tests/test_native_suite.py` | 只跑 `find_suites(...)[0]` | **跑全部套件**,每个套件用自己的 fixture 集合,各配各的参考模型 |
| `tests/test_policy_inventory.py` | store 里只有 `basicResource` | 断言清单**包含**已知策略 id;inspect 结果**按 id 取**,不取「任意一个」 |
| `src/cerbos_policy_tests/reference.py` | —— | **新增**:按 resource kind 分派到对应的参考模型 |
| `src/cerbos_policy_tests/fdep_rules.py` | kind 集合写死 | **由 `pdp-config/orgs.yaml` 推导** —— 模型和部署不会各说各话 |

> 原来的 `sorted(rglob("testdata"))` 取第一个,加上 `policies/fdep_api/` 之后
> 排序会变成 `systemone.LAYA` 在前 —— **basicResource 的测试会静默地拿到别的家族的 fixture**。
> 这种失败不报错,只是答案全错。所以改成**歧义即报错**。

---

## 7. 实测结果

### 7.1 部署与验证

```powershell
uv run python "pdp-config\gen-scoped-policies.py"          # 生成 policy
uv run python "pdp-config\push-policies.py" --pdp http://10.17.1.201:3592 --policies policies
uv run python "pdp-config\gen-scoped-policies.py" --verify  # 查 store 里有没有漏的
```

```
  schema : 3 条      basicResource.json / fdep.json / principal.json
  policy : 3 条      resourcePolicy ×2 / resourcePolicy basicResource
POST /admin/schema -> 200
POST /admin/policy -> 200
GET  /admin/policies -> ['resource.basicResource.vdefault',
                          'resource.pip.JEV.LAYA.vdefault',
                          'resource.pip.FDEP.SOP.vdefault']
GET  /admin/schemas  -> ['basicResource.json', 'fdep.json', 'principal.json']

the store holds one policy per provider
```

> schema 的 id 是**相对于 `_schemas/` 的路径**,不带 `cerbos:///` 前缀 —— 前缀推错的话,
> 清单照样列出来,但每一行都读不回来,而每个请求都被拒。

### 7.2 测试结果

| 测试文件 | 条数 | 说明 |
|---|---:|---|
| `tests/test_cross_product.py` | 193 | basicResource 的穷举扫描 |
| `tests/test_native_suite.py` | 141 | 三个原生套件都跑:basicResource + `pip.JEV.LAYA` + `pip.FDEP.SOP`,各再与参考模型对一次 |
| `tests/test_fdep_api.py` | **45** | **闸门**:api id 解析、`do` 取反、kind、roles、403/503、影子模式、`cerbos_valid` 对接、**PocketFlow Node(拒绝抛异常)**,外加对着线上 PDP 的端到端 |
| `tests/test_query_plan.py` | 14 | planResources → SQL → 行 |
| `tests/test_fdep_scoped_policies.py` | **17** | **生成的 policy**:每个 provider 一份、生成物与生成器一致、每条规则都写了 roles、**身份层必须发出的角色名**、store 里有每一份 |
| `tests/test_edge_cases.py` | 11 | scope、未知 version/kind、空角色、失败即拒绝 |
| `tests/test_policy_inventory.py` | 12 | 清单、每个 provider 一份、schema 相对路径、schema 强制校验 |
| `tests/test_coverage_plan.py` | 10 | 覆盖率计划 |
| `tests/test_audit_log.py` | 6 | 审计轨迹 |
| `tests/test_connection.py` | 5 | 可达性、健康检查、管理端认证 |
| **合计** | **475** | 改造前 328,**0 failed** |

### 7.3 顺带测出来的三条语义

**① 一个 kind 就是一份 policy —— 没有链。**

| 请求 | 结果 | `matchedPolicy` |
|---|---|---|
| `FDEP_ADMIN`,kind=`pip.JEV.LAYA` | **ALLOW** | `resource.pip.JEV.LAYA.vdefault` |
| `FDEP_GUEST`,kind=`pip.JEV.LAYA` | ALLOW | `resource.pip.JEV.LAYA.vdefault` |
| `FDEP_ADMIN`,kind=`pip.nosuch.org` | DENY | **`NO_MATCH`** |
| `FDEP_ADMIN`,id=`nosuchfamily.LAYA` | DENY | `resource.pip.JEV.LAYA.vdefault` |

store 里没有这个 kind → **NO_MATCH**,答案说的是「没找到 policy」而不是
「不允许」。store 里没有这个 id → 规则不命中 → 默认拒绝。

**② `matchedPolicy` 是产生效果的那一份。**
不用 scope 之后没有链可爬,所以它报的就是判出结果的那份 policy。
对闸门来说这不影响判断 —— 它要的只是 `NO_MATCH` 这个信号(「没部署」),
而那个信号是准的。

**③ `includeMeta: true` 是拿 `matchedPolicy` 的前提。**
不带它,响应里只有 `actions` 和 `cerbosCallId`;带上之后才有
`meta.actions.<action>.matchedPolicy`。
`matchedScope` 不用 scope 时不会出现。

---

## 8. 未决(阶段 3 之前必须有人回答)

| # | 问题 | 影响 |
|---|---|---|
| 1 | FDEP 服务器能连到 PDP:3592 吗? | **前提** |
| 2 | 认证层能给什么角色?角色名定什么? | 决定 policy 的形状 |
| 3 | app 注册表现在在哪?谁维护? | 属性关着的时候不急;打开 `attributes` 之前必须有 |
| 4 | `pipe.py` 上层怎么把异常转成 HTTP 响应? | 决定 403 / 503 怎么送出(`fdep_authz/gate.py` 给了 `status_code`,照着用) |
| 5 | PDP 策略只存在 sqlite3,备援是什么? | PDP 挂掉时闸门会全拒绝(安全但不可用) |
| 6 | 要不要开 `engine.strictEvaluation`? | 要改 `.cerbos.yaml` 并**重启共享 PDP**(`lenientScopeSearch` 不用管了 —— 不用 scope) |
| 7 | 新增 org 的流程:谁改 `orgs.yaml`、谁跑生成器、谁推送? | 漏一步 → 那个 org 全断(`NO_MATCH`) |

> ~~角色名对不上~~ **已解决**:app 授权改用 `P.id`,角色用 `["*"]` 忽略。
> 平台发的 `user_id` 是 `guests`,和策略里的 `P.id == "guests"` 对得上。
> 通用规则(管理员等)还是按角色,那部分等身份层给对角色名。
>
> ~~provider 的真值~~ **已解决**:`jev` 的 org 配置是
> `{ namespace: "pip", task_queue: "JEV", workflow: "LAYA" }`,
> 所以 kind 是 **`pip.JEV.LAYA`**,每个 provider 一份 policy。
> 已生成、已部署、`--verify` 通过。

---

## 9. 常用命令

```powershell
$env:UV_CACHE_DIR = "<当前目录>\.uv-cache"
$env:PYTHONIOENCODING = "utf-8"

# 全部测试
uv run pytest

# 只跑 FDEP 闸门那一组
uv run pytest tests/test_fdep_api.py -v

# 覆盖率审计
uv run python -m cerbos_policy_tests --save

# 生成 scope 链(改了 orgs.yaml 之后)
uv run python "pdp-config\gen-scoped-policies.py"

# 部署策略与 schema
uv run python "pdp-config\push-policies.py" --pdp http://10.17.1.201:3592 --policies policies

# 查链在 store 里是否完整
uv run python "pdp-config\gen-scoped-policies.py" --verify

# 部署后必查清单(健康检查不作数)
curl.exe -s -u "cerbos:cerbosAdmin" http://10.17.1.201:3592/admin/policies
curl.exe -s -u "cerbos:cerbosAdmin" http://10.17.1.201:3592/admin/schemas
```

**部署策略后必查清单** —— 少一个 provider,那个 provider 的请求就是 `NO_MATCH`。

**真正删除策略用 `POST /admin/policy/delete?id=...`** —— `DELETE /admin/policy` 是**停用**,
停用的策略仍出现在 `?includeDisabled=true` 的清单里,会让测试误判。
**而且删不掉有后代的层** —— 先删叶子。
