# FDEP-AUTHZ-DESIGN.md · FDEP 接入 Cerbos PDP 的授权改造

> **状态**:方案已定,未实现。
> **原则**:start small。只做让「谁能调哪个 FDEP app」这件事成立所必需的东西。
> 每一个组件都要能说出它防住了什么 —— 说不出的就不加。
>
> **依据**:官方文档 0.57.0 的逐页阅读笔记见 `Policies.md`;
> 面向防火墙管理员的迁移学习记录见 `PDP.md`(本设计里每个「实测」结论的出处都在那里)。

---

## 1. 要解决什么

FDEP 是集中式调用入口:一个 endpoint,按 app id 派发到各 app 的业务流程。
**现在没有权限控制** —— 拿到任何 app id 就能调。

四件事:

| # | 需求 | 落点 |
|---|---|---|
| 1 | 加用户验证,提供身份与角色 | `_token_.user_id` / `roles`(字段已存在,目前是 `guests` / `[]`) |
| 2 | 以 app id 为 resource,提取控制栏位 + IP、时间等 | resource `fdepApi`;栏位来自 app 注册表 |
| 3 | 用 cerbos-sdk 对 PDP 上的策略做授权判断 | pipe.py 里,`runWF` 之前 |
| 4 | 提供 audit log | PDP 决策日志 + FDEP 侧调用轨迹,靠 `cerbosCallId` 关联 |

---

## 2. 整体流程

```
调用方 ──HTTPS──► BPM/Node 層 ──► pipe.py ──► Temporal ──► app 工作流
                   ① 验证身份        ⑤ 授权判断
                   ② 拆 app id      ⑥ DENY → 403,不进 Temporal
                   ③ 组 _token_      ⑦ ALLOW → runWF
                   ④ 组 resource      ⑧ 写 FDEP 侧 audit
```

**授权闸门在 pipe.py,不是 BPM 层。** 三个理由:

1. pipe.py 已经在做 `sk` 的时效校验 —— **授权和「这次请求是不是新的」在同一个位置**,语义一致
2. pipe.py 拿到的是**已填好身份的** `_token_` 和**已剥掉 org 前缀的** `api`,不用回头解析
3. pipe.py 是**所有调用的必经之路**,BPM 层的分支绕不过它

### 2.1 FDEP 源码里两个必须知道的细节

**① `do` 被取反过一次。** BPM 层里是 `"do": !i.payload.do`,pipe.py 原样转发。

| 客户端发的 | `share.do` | 语义 |
|---|---|---|
| `do: false` | `true` | **查文件** |
| `do: true` | `false` | **执行** |

**所以在 pipe.py 里:`share.do == False` 才是「执行」。** 判断写反,整个授权就反了。

**② `C4.` 前缀是服务端强制加的。** pipe.py 里 `"api": "C4." + api`。

`C4` 是 Service Provider 的**强制路径依赖规范** —— 所有对外服务必须注册在 C4 子路径下,
调用方绕不过(实测:`@jev.C4.x` → `C4.C4.x`,前缀是**叠加**不是替换)。

而**同一个 C4 路径在不同 org 下是不同的服务**(实测:`@jev.systemone.Choice` 有 docs,
`@fdep.systemone.Choice` 没有)。所以 resource id 里必须带 provider。

---

## 3. 身份

### 3.1 现状

`_token_` 的字段**已经存在**,由服务端填,客户端给的一律被丢弃(实测五种写法:不带、
`inbound.user_id`、`inbound._token_`、`Authorization`、`Cookie` —— 结果全是 `guests`)。

```
_token_ = {
  sk:      "<加密的时间戳>",   pipe.py 校验:5 分钟内有效
  from:    "<来源 IP>",         XFF 链,客户端可控前缀
  user_id: "guests",            ← 要填真值
  roles:   [],                  ← 要填真值
  email:   "guests@feg.cn",     ← 要填真值
  now:     "<服务器时间>",
}
```

### 3.2 要做的

**身份层把真实的 user_id / roles 填进 `_token_`。** 客户端仍然不能伪造 —— 实测已确认。

### 3.3 一个硬约束:roles 不能是空数组

**实测:principal 的 roles 为空数组或缺失,PDP 直接返回 HTTP 400**
(`principal.roles: value is required`)—— 那不是决策,是请求不合法。

所以**未验证的调用也必须带一个明确角色**(比如 `FDEP_GUEST`),不能让 roles 为空。
这条同时决定了 policy 的形状:角色得是「所有调用者都有」的,不能靠「没角色就默认拒绝」。

> ⚠️ **不要用「省略 roles 的规则」来表达「拒绝所有人」。** 实测:**省略 `roles` 的规则
> 会让整个 policy 失效** —— 所有请求落到默认拒绝,而 policy 在管理接口里**看起来部署成功了**。
> 要对所有人生效,写 `roles: ["*"]`。

### 3.4 角色名

先用 `FDEP_ADMIN` / `FDEP_DEVELOPER` / `FDEP_AUDITOR` / `FDEP_GUEST`。

**与 4KI `rbac.md` 的 R1..R8 的对应关系待定** —— 那是身份层的决定,不在本次范围内。

---

## 4. Resource:以 app id 为准

### 4.1 app id 的结构对应 Cerbos 的四个位置

FDEP 的 app id 是 `@jev.systemone.Choice`。**三段各有归属:**

| app id 段 | Cerbos | 理由 |
|---|---|---|
| `@jev` | **scope** | org 决定 `namespace.task_queue.workflow` —— 就是「哪个 Service Provider 实例在提供这个服务」。而 scope 在 Cerbos 里正是「同一个 kind+version 的不同实例」的定位方式 |
| `systemone` | **resource.id** | 一族服务。**精确匹配** —— `R.id == "systemone"` 就是「systemone 这一族」,没有前缀陷阱 |
| `Choice` | **action** | 具体的业务操作 |

> `C4.` 前缀**不进 resource**。它是服务端转给 Temporal 时加的
> (`"api": "C4." + api`),对授权没有意义 —— 授权看的是调用方要的那个 app。

于是 resource 长这样:

```json
{
  "kind": "fdepApi",
  "id": "systemone",
  "scope": "jev",
  "attr": {
    "accessMode": "read",
    "riskLevel": "low"
  }
}
```

| 字段 | 来源 |
|---|---|
| `id` | app id 去掉 `@org.` 前缀和末段 |
| `scope` | app id 的 org 段 |
| `action` | app id 的末段 |
| `attr.accessMode` | FDEP 的 `do` 旗标 → `read`(查文件)/ `execute`(执行) |
| `attr.riskLevel` | app 注册表 |

**`attr` 从 4 个字段缩到 2 个。** 之前的 `app` 去了 id,`provider` 去了 scope,
`operation` 去了 action —— 三个都不再是「附加信息」,而是 Cerbos 的一等位置。

`app` 和 `provider` 不再需要重复放进 attr:
- 「一族」判断靠 `R.id` 精确匹配
- 「哪个 provider」由 scope 表达

### 4.2 控制栏位从哪来

**来自 app 注册表**(FDEP 侧),不是调用方。需要的字段最少:

```yaml
# app 注册表条目(示意)——键是 (app, operation)
systemone.Choice:
  accessMode: read        # 查文件还是执行
  riskLevel: low         # low | medium | high
```

`accessMode` 其实来自 FDEP 的 `do` 旗标(见 §2.1),`riskLevel` 来自注册表。
两者合起来构成 resource 的 attr。

### 4.3 附加信息:放 principal,不放 resource

| 字段 | 放哪 | 理由 |
|---|---|---|
| `clientIp` | `principal.attr` | 是**呼叫者**的属性。取 `_token_.from` 的**最后一段**(前面是客户端可控的 XFF 链) |
| `email` | `principal.attr` | 呼叫者的一部分 |
| `requestTime` | `principal.attr` | 这次呼叫的时间(`_token_.now`) |

**IP 和时间放 principal 而不是 resource** —— resource 的属性应该是这个 resource 自身的静态事实。
放 resource 会让「同一 app 在不同时间不同 IP」变成不同 resource,规则会爆炸。

> `clientIp` 只用于**记录和审计**,不用于准入 —— IP 白名单放网络层。理由见 §5.6。

---

## 5. PDP 侧的策略

### 5.1 两份 policy:基础 + 每个 org 一份

```
policies/
├── fdepApi.yaml            # 无 scope —— 与 org 无关的通用规则
└── fdepApi.jev.yaml       # scope: jev —— 这个 provider 特有的规则
```

**基础 policy(无 scope)**放跨 org 通用的规则:

```yaml
apiVersion: api.cerbos.dev/v1

resourcePolicy:
  resource: fdepApi
  version: default

  schemas:
    resourceSchema:
      ref: cerbos:///fdepApi.json

  rules:
    # 平台管理员:任何服务、任何操作
    - name: admin-may-call-anything
      actions: ["*"]
      roles: [FDEP_ADMIN]
      effect: EFFECT_ALLOW

    # 开发者:可以执行,但不碰高风险
    - name: developer-may-execute-non-high-risk
      actions: ["*"]
      roles: [FDEP_DEVELOPER]
      effect: EFFECT_ALLOW
      condition:
        match:
          expr: R.attr.accessMode == "execute" && R.attr.riskLevel != "high"

    # 审计:只读低风险
    - name: auditor-may-only-read-low-risk
      actions: ["*"]
      roles: [FDEP_AUDITOR]
      effect: EFFECT_ALLOW
      condition:
        match:
          expr: R.attr.accessMode == "read" && R.attr.riskLevel == "low"
```

**每个 org 一份 scoped policy** 放该 provider 特有的规则:

```yaml
apiVersion: api.cerbos.dev/v1

resourcePolicy:
  resource: fdepApi
  version: default
  scope: jev

  rules:
    # 访客:只能调 systemone 这一族,而且只能查文件
    - name: guests-may-call-the-systemone-apps
      actions: ["*"]
      roles: [FDEP_GUEST]
      effect: EFFECT_ALLOW
      condition:
        match:
          expr: R.id == "systemone" && R.attr.accessMode == "read"
```

### 5.2 三个要点

**① 不加 catch-all `EFFECT_DENY`。** 默认拒绝本来就是这个行为(实测:只有允许规则时,
没命中任何规则的 action → DENY,`matchedPolicy` 正常)。加一条无 `roles` 的 DENY 会**拖垮整个 policy**。

**② `actions: ["*"]` 匹配任意 action 名**(实测:`Choice`、`Choice:read`、`a:b:c` 全中)。
所以 operation 放进 action 之后,通配规则照样覆盖所有操作。

**③ `accessMode` 是 condition,不是 action。** 因为 action 已经被 operation 占了。
代价是「只读」这类规则要多一个条件 —— 换来的是 attr 少两个字段。

### 5.3 实测:整个设计跑通了

对着线上 PDP 实测(基础 policy + `scope: jev` 的 policy + schema):

| 请求 | 结果 |
|---|---|
| ADMIN,任何 app | ALLOW |
| DEVELOPER,execute,low | ALLOW |
| DEVELOPER,execute,**high** | DENY |
| DEVELOPER,read | DENY |
| AUDITOR,read,low | ALLOW |
| AUDITOR,execute,low | DENY |
| GUEST,id=systemone,read | **ALLOW** |
| GUEST,id=other,read | DENY |
| GUEST,id=systemone,execute | DENY |
| GUEST,id=**systemoneX**,read | DENY ← 精确匹配,没有前缀陷阱 |
| `accessMode: bogus` | DENY + `value must be one of "read", "execute"]` |

### 5.4 ⚠️ scope 的坑:每个 org 必须有一份 scoped policy

实测:**请求带了 scope,而 store 里没有这一份 → `NO_MATCH`,基础 policy 根本不被查。**

| 请求 | 结果 |
|---|---|
| scope=`jev`(有这份 policy) | 按 jev 的规则判 |
| scope=`other`(**没有**这份 policy) | **NO_MATCH** → 全部拒绝 |
| scope=`jev.child`(jev 有,jev.child 没有) | **NO_MATCH** → 全部拒绝 |

**所以:新增一个 org(在 FDEP 的 `ToT` map 里加一条),如果没同时加一份 scoped policy,
那个 org 的所有调用都会被拒** —— 而且报错是 NO_MATCH,不是「权限不足」。

两个缓解手段:

1. **PDP 打开 `engine.lenientScopeSearch: true`**(官方引擎配置)。
   开启后,请求的 scope 没有对应 policy 时,会按 `a.b` → `a` → `""` 继续找,
   而不是直接 NO_MATCH。

   > 但注意官方说明:**这个设置只影响「缺失叶子 scope」的处理**。
   > store 里已存在的 scope 链**必须完整** —— 有 `a.b.c` 就必须也有 `a.b`、`a` 和无 scope 的。

2. **部署流程把「新增 org」和「新增 scoped policy」绑在一起** —— 见 §8。

### 5.5 schema:只要 resource 的一份

```json
// _schemas/fdepApi.json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "accessMode": { "type": "string", "enum": ["read", "execute"] },
    "riskLevel":  { "type": "string", "enum": ["low", "medium", "high"] }
  },
  "required": ["accessMode", "riskLevel"],
  "additionalProperties": false
}
```

**为什么要 schema**:policy 的 condition 依赖 `accessMode` / `riskLevel`。
没有 schema,这些字段缺失时是**运行时错误** → condition 视为不满足 → **静默拒绝**。
schema 让「字段缺失」变成明确的校验错误,而不是悄悄的拒绝。

**只给 resource 配 schema,暂不给 principal 配。** 理由:principal 的 attr(IP/邮箱/时间)
只用于审计,不被 condition 分支;而且 `additionalProperties: false` 会让 FDEP 以后加字段时
突然全部被拒(这个坑本项目已经踩过)。

> ⚠️ **部署 schema 时 id 用相对路径**(`fdepApi.json`),**不是** `cerbos:///fdepApi.json`。
> store 存的是相对路径,策略里的 `ref` 才带前缀。
> **推错的后果:「看起来部署成功了」但每个请求都被拒,而且那行读不回来**
> (`GET /admin/schema?id=...` 各种前缀组合都 500)。本项目已经踩过一次。

### 5.6 IP 白名单不放在 policy 里

`_token_.from` 是 XFF 链,客户端可以往前加内容(实测:`XFF: 203.0.113.9` →
`from = "203.0.113.9, 10.17.1.94"`)。

**所以:policy 里只用 `clientIp` 做记录,不做准入。** IP 白名单放网络层。
要在 policy 里挡 IP,得先定义清楚「可信 IP」是哪一段 —— 那是网络层的事。

### 5.7 建议打开 `engine.strictEvaluation`

官方引擎配置里 `strictEvaluation` 默认是 `false`,后果是:

> 因为条件出错的规则永远不匹配,**`EFFECT_DENY` 规则可能被静默跳过**。

对授权网关来说这是最危险的失败模式 —— 一条条件写错的 DENY 规则等于没有。

`strictEvaluation: true` 让条件出错时**拒绝该规则涉及的动作**(fail closed)。

⚠️ **本机 PDP 现在没开这个。** 它是配置项,**要改 `.cerbos.yaml` 并重启 PDP 才生效** ——
本次没有验证它对现有 `basicResource` 策略的影响(会需要重启共享服务,留到实施阶段)。

---

## 6. Audit

### 6.1 两处轨迹

**PDP 决策日志**(权威,可查):

```
GET /admin/auditlog/list/KIND_DECISION?lookup=<cerbosCallId>
```

实测一条记录里有:`callId`、`timestamp`、`peer`(IP + userAgent)、
`checkResources.inputs`(决策时看到的完整上下文)、`checkResources.outputs`(决定 + 命中哪条策略)、
`auditTrail.effectivePolicies`(命中的策略及其版本)、
`requestContext.annotations`(trace id、app id)、`policySource`(策略来自哪个存储)。

**FDEP 侧调用轨迹**(补充 PDP 没有的):原始 app id、原始 inbound、业务结果、耗时、
以及 `cerbosCallId`。

**两边的关联键就是 `cerbosCallId`** —— 决策响应里带着它,FDEP 写进自己的日志行;
PDP 轨迹里它是主键。

### 6.2 两个实测的坑

**① 约 13 秒后才可见。** `local` 后端先缓冲再提交。**读轨迹要轮询**,
读一次就断言「查不到」得到的是错的结论。

**② NDJSON,不是单个 JSON。** 一行一条记录,外面套 `{"result": {...}}`。
返回超过一条时 `response.json()` 直接抛 `Extra data`。

### 6.3 `annotations` 放关联信息

FDEP 在请求里带 `requestContext.annotations`:

```json
{ "trace_id": "...", "app_id": "..." }
```

**它只做关联,不参与策略求值** —— 实测原样进审计轨迹,不影响决策结果。
这正是它该放的东西:如果放 `principal.attr`,就成了策略输入,调用方能影响授权。

---

## 7. FDEP 侧改造清单

### 7.1 pipe.py 的 `One.exec`

```python
# app id = "@jev.systemone.Choice" -> scope=jev, id=systemone, action=Choice
org, rest = app_id[1:].split(".", 1)      # "jev", "systemone.Choice"
app, operation = rest.rsplit(".", 1)      # "systemone", "Choice"

principal = {
    "id":    token["user_id"],
    "roles": token["roles"] or ["FDEP_GUEST"],     # 空不行,见 §3.3
    "attr": {
        "clientIp":   token["from"].split(",")[-1].strip(),   # 取最后一段
        "email":      token["email"],
        "requestTime": token["now"],
    },
}

resource = {
    "kind":  "fdepApi",
    "id":    app,                    # 一族服务 -> 精确匹配
    "scope": org,                    # 哪个 provider
    "attr": {
        "accessMode": "execute" if not share.get("do", True) else "read",  # 注意取反,§2.1
        "riskLevel":  registry[app][operation]["riskLevel"],
    },
}

effect = cerbos_check(principal, resource, operation)     # action = api id 的末段

if effect != "ALLOW":
    raise FdepDenied(...)      # → 403,不进 runWF

result = runWF(...)           # 原有流程不动
```

**scope 一定要带上。** 漏了 scope 会走到无 scope 的基础 policy(它也在链上),
但**带 scope 而 store 里没有对应 policy 时是 NO_MATCH → 全部拒绝**(见 §5.4)。

### 7.2 用 SDK,不用裸 HTTP

`cerbos-sdk` 的 `CerbosClient` 处理了连接、超时、重试、错误分类。

**走 HTTP(:3592)。** 理由不是「端口关了」,而是**现在装的就是 HTTP 客户端**。
SDK 的 gRPC 客户端需要额外安装 `cerbos[grpc]`(本机没有 `grpcio`)。

> 注:3593 端口的状态变过 —— 早期它是关闭的,现在**已经开了并服务 gRPC**
> (实测返回的是 HTTP/2 SETTINGS 帧)。但这不影响本方案 —— HTTP 路径一直可用,
> 也不值得为了 gRPC 叠加一个依赖。

**实测延迟 p50 14ms / p95 27ms**(本机,30 次取样)。相对 Temporal 的工作流时间可以忽略。
**不建议加快取** —— 授权判断要反映当下的角色,缓存失效就是绕过闸门。

### 7.3 失败要区分 403 和 503

**这是整套设计里最重要的一条。**

| 情况 | 响应 | 理由 |
|---|---|---|
| PDP 明确拒绝 | **403** | 正常的权限不足 |
| PDP 连不上 / 超时 | **503** | 「判断不了」≠「不允许」。503 让调用方知道可以重试;403 会被当成「没权限」而放弃 |
| PDP 响应格式不对 | **503** | 同上 |
| `roles` 为空 | **403** | 未验证的调用,不进 PDP(§3.3) |

**为什么必须区分:PDP 用「全部拒绝」来表示「我什么都没找到」。** 实测过:
策略集为空时,每个请求都被拒绝,而 `GET /_cerbos/health` 照样返回
`{"status":"SERVING"}`。

**健康检查只说进程活着,不说策略在不在。** 唯一可靠的检查是 `GET /admin/policies` 看清单。

### 7.4 响应里四种「拒绝」长得不一样

| 拒绝类型 | effect | matchedPolicy | validationErrors |
|---|---|---|---|
| 策略没匹配上 | DENY | **`NO_MATCH`** | — |
| schema 拦截 | DENY | 正常 | **有** |
| condition 不成立(默认拒绝) | DENY | 正常 | — |
| 规则命中了 DENY | DENY | 正常 | — |

**后两种在响应里完全一样。** FDEP 侧至少要能区分「策略没找到」(可能是故障)
和「策略判了拒绝」。

### 7.5 身份验证

**在 FDEP 的认证层做,不在 PDP 侧做。** PDP 只负责「按你给的 id 和 roles,这个操作允不允许」。

**待定:** 认证层用什么(现有的 OAuth2?LDAP?)、角色从哪来。
`_token_.roles` 现在是 `[]`,`user_id` 是 `guests`。

---

## 8. PDP 侧改造清单

| # | 事项 | 说明 |
|---|---|---|
| 1 | `fdepApi.yaml` | **基础 policy**(无 scope),§5.1 的三条通用规则 |
| 2 | `fdepApi.jev.yaml` | **scope: jev** 的 policy,guest 规则在这 |
| 3 | `fdepApi.json` | schema(§5.5) |
| 4 | `fdepApi_test.yaml` | 原生测试套件 —— **期望的唯一真源** |
| 5 | `testdata/{principals,resources}.yaml` | 共享 fixtures |
| 6 | 部署 | `POST /admin/schema` + `POST /admin/policy` |
| 7 | 验证 | `GET /admin/policies` 看清单(要有 `fdepApi.vdefault` **和** `fdepApi.vdefault/jev`);跑测试套件 |

**第 7 项的「和」字很要紧** —— 少了 scoped 那份,所有带 scope 的请求都是 NO_MATCH。

**schema 的 id 用相对路径**(§5.2)。

**真正删除策略用 `POST /admin/policy/delete?id=...`** —— `DELETE /admin/policy` 是**停用**,
停用的策略仍出现在 `?includeDisabled=true` 清单里,会让测试误判。

---

## 9. 分阶段

| 阶段 | 内容 | 验收 |
|---|---|---|
| **0** | 确认 FDEP 服务器能连到 PDP:3592;确认认证层能给什么角色 | 两个答案 |
| **1** | PDP 侧:policy + schema + 测试套件,部署 | 套件全绿;`GET /admin/policies` 有清单 |
| **2** | FDEP 侧:闸门骨架 + PDP 客户端,**先全部放行**(影子模式) | 调用会进 PDP、产生轨迹,但不拦任何东西 |
| **3** | 影子模式跑一段,比对 PDP 的决定与业务实际该不该允许 | 影子报告:PDP 说 DENY 但业务上该允许的清单 → 调 policy |
| **4** | 影子模式改成拦截 | 真的挡下越权调用 |
| **5** | 开 FDEP 侧 audit,与 PDP 轨迹对账 | 两边的 `cerbosCallId` 能一一对上 |

**阶段 2 的影子模式是关键。** 直接上拦截会挡掉线上流量;
影子模式错判成本为零,却能用真实流量验证 policy。

---

## 10. 坑表(都实测过)

| 坑 | 后果 | 对策 |
|---|---|---|
| **`do` 被取反一次** | 授权判断整个反过来 | pipe.py 里从 `share.do` 反推,**写测试钉住** |
| **省略 `roles` 的规则** | **整个 policy 失效**,全拒绝,而 policy 看起来部署成功 | `roles` 必填;对所有人用 `roles: ["*"]` |
| **catch-all DENY 掩蔽允许** | 不符合的允许也被拒 | 不加 catch-all;默认拒绝已足够 |
| **`roles` 为空数组** | PDP 返回 **400**,不是决策 | 身份层保证至少一个角色 |
| **schema id 带前缀** | 每请求被拒,且那行读不回来 | id 用相对路径 |
| **策略集为空但 health 说 SERVING** | 全部静默拒绝 | 部署后查 `GET /admin/policies` |
| **审计轨迹约 13 秒后才可见** | 读一次以为查不到 | 轮询 |
| **审计响应是 NDJSON** | `response.json()` 抛 `Extra data` | 逐行解析 |
| **`DELETE /admin/policy` 是停用不是删除** | 停用项仍在清单里 | 用 `POST /admin/policy/delete` |
| **策略文件扩展名不被接受时静默忽略** | 策略不生效 | 用 `.yaml` / `.yml` / `.json` |
| **带 scope 但 store 里没有对应 policy** | **NO_MATCH → 全部拒绝**,基础 policy 也不被查 | 每个 org 一份 scoped policy;或开 `engine.lenientScopeSearch` |
| **`strictEvaluation` 默认关** | 条件写错的 `EFFECT_DENY` 规则会被静默跳过 | 建议开 `engine.strictEvaluation: true`(要改配置并重启) |

---

## 11. 未决

| # | 问题 | 影响 |
|---|---|---|
| 1 | **FDEP 服务器能连到 PDP:3592 吗?** | **前提**,不通则整套不成立 |
| 2 | 认证层能给什么角色?角色名定什么? | 决定 policy 的形状 |
| 3 | app 注册表现在在哪?谁维护? | 决定控制栏位怎么取得 |
| 4 | pipe.py 上层怎么把异常转成 HTTP 响应? | 决定 403 / 503 怎么送出 |
| 5 | PDP 策略只存在 sqlite3,备援是什么? | PDP 挂掉时闸门会全拒绝(安全但不可用) |
| 6 | 与 4KI `rbac.md` 的 R1..R8 怎么对应? | 角色体系 |
| 7 | 每个 org 一份 scoped policy,谁负责同步? | 漏一份 → 那个 org 全断(§5.4) |
| 8 | 要不要开 `engine.lenientScopeSearch` / `engine.strictEvaluation`? | 都要改配置并重启共享 PDP |

---

## 附:本次设计用到的官方结论

全部出自 `Policies.md`(逐页读 0.57.0 文档的笔记):

| 结论 | 出处 |
|---|---|
| 默认拒绝,不存在「没有意见」 | §2 求值流程 |
| 同角色内拒绝优先;跨角色取并集 | §2 冲突解决 |
| 规则省略 `roles` → 整个 policy 失效;对所有人用 `roles: ["*"]` | §5 资源策略 标注 (12) |
| `do` 的取反、`C4.` 前缀是叠加 | FDEP 源码(用户提供) |
| 同一个 C4 路径在不同 org 下是不同服务 | 实测(docs 指纹对照) |
| schema 按 policy 声明;`ignoreWhen` 按 action 豁免;`reject` → 全部 DENY + validationErrors | §13 Schemas |
| `requestContext.annotations` 只做关联,不参与求值 | §10 条件 |
| `cerbosCallId` ↔ 审计日志条目 | §16 调试 |
| 测试套件:`_test` 后缀;`testdata/` 共享;没列出的期望 DENY | §14 校验与测试 |
