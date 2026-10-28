# QUICKSTART — Cerbos 入门:四个动作,全程只走 API

这份文档写给第一次接触 Cerbos 的中文开发者。读完你应该明白:**Cerbos 是什么、一次请求怎么经过它、怎么用四个 API 调用跑通"定义 → 部署 → 决策 → 审计"这条闭环**。

```bash
uv run python quickstart/quickstart.py --pdp http://10.17.1.201:3592
```

目标 PDP:`http://10.17.1.201:3592` — Cerbos **v0.57.0**(commit `43125124efe4`)
Admin 账号:`cerbos` / `cerbosAdmin`(HTTP Basic,只用于 `/admin/*`;决策端点不需要凭据)

这台 PDP 已经完成迁移:**store 是 `sqlite3`(可变,能通过 API 部署),audit backend 是 `local`(审计轨迹读得回来)**。四个步骤现在全部跑得通。

---

## 一、Cerbos 是什么:三个角色

"这个人能不能做这件事"这个判断,在 Cerbos 里被拆成三个角色:

| 角色 | 全称 | 是什么 | 在哪儿 |
|---|---|---|---|
| **策略** | Policy | 一堆 YAML,写着谁能做什么 | 存在 PDP 里 |
| **PDP** | Policy Decision Point | 守着策略、负责回答的进程 | 一台服务器,比如 `10.17.1.201:3592` |
| **PEP** | Policy Enforcement Point | 调用 PDP 并按答案行事的代码 | 你的应用里 |

一次请求的完整链路:

```
   你的 handler
       │  1. 认证:调用方是谁?(Cerbos 不做这件事)
       ▼
   你的代码(PEP)
       │  2. 把请求翻译成 principal + resource + actions
       │  3. POST /api/check/resources
       ▼
   PDP  http://10.17.1.201:3592
       │  4. 取出匹配的策略,逐条求值
       │  5. 返回每个动作的效果:EFFECT_ALLOW / EFFECT_DENY
       ▼
   你的代码(PEP)
       │  6. 放行,或者返回 403
       ▼
   结果
```

**为什么值得多这一跳?**

* **策略改了不用发版。** 改 PDP 上的策略,应用下一次请求就用新规则。
* **一套规则服务多种入口。** Web、CLI、定时任务、AI agent 都是不同的 PEP,共用一个 PDP。
* **决策被记录下来。** 谁在什么时候被允许了什么,`GET /admin/auditlog/list/{kind}` 查得到。
* **规则集中在一处。** 不是散落在几十个 handler 里的 `if`。

**代价也得知道**:每加一次检查就多一次网络往返;PDP 挂了就是拒绝服务(所以出错要拒绝、不能放行);策略写错了要有人改。所以 Cerbos 适合"规则复杂、跨多个入口、需要留痕"的场景,不是所有 `if` 都值得搬过去。

---

## 二、四个动作 → skill → 工具函数

| # | 动作 | skill | 工具函数(API) | 认证 |
|---|---|---|---|---|
| 0 | 探活、读版本、读 API 文档 | `cerbos-pep-integration` | `GET /_cerbos/health`、`GET /api/server_info`、`GET /schema/swagger.json` | 无 |
| 1 | 定义最简 policy | `cerbos-policy` Phase 2 | 写 `policies/hello.yaml` + `policies/_schemas/hello.json` | — |
| 2 | 部署 | `cerbos-policy` Phase 5 | `POST /admin/schema`、`POST /admin/policy` | Basic |
| 3 | 测 ALLOW / DENY | `cerbos-pep-integration` | `CerbosClient.check_resources()` → `POST /api/check/resources` | 无 |
| 4 | 取回 audit log | `cerbos-audit-insights` | `GET /admin/auditlog/list/KIND_DECISION` | Basic |

> 三个 skill 已经改写成 API 版本,原本的 `cerbos compile` / `cerbos test` / `cerbos repl` / `cerbosctl` 全部换成了上表里的 HTTP 调用,说明也改成了中文。

---

## 三、四个动作

### step 0 — 探活

**skill:`cerbos-pep-integration` · 工具函数:`GET /_cerbos/health`**

```bash
curl -s http://10.17.1.201:3592/_cerbos/health
```

```json
{"status":"SERVING"}
```

顺手确认两件事——版本,和 Admin API 是不是真的受保护的:

```bash
curl -s http://10.17.1.201:3592/api/server_info
curl -s http://10.17.1.201:3592/schema/swagger.json | head -c 80
curl -s -o /dev/null -w '%{http_code}\n' http://10.17.1.201:3592/admin/policies
```

```json
{"version":"0.57.0","commit":"43125124efe4b50b83d894635fb2f691e980dc62","buildDate":"2026-10-23T07:10:11Z"}
{"swagger": "2.0", "info": {"title": "Cerbos", "version": "0.57.0"}, ...
401
```

`GET /schema/swagger.json` 返回的是 **PDP 自己发布的 OpenAPI 文档**——16 条路径、122 个定义。写任何客户端代码之前先读它,比凭记忆写端点可靠。完整副本在仓库根目录的 [openapi-spec.json](openapi-spec.json),三个 skill 的 `references/` 里也各放了一份。

---

### step 1 — 定义最简 policy

**skill:`cerbos-policy` Phase 2 · 工具函数:写文件**

最简到不能再简:一个资源、一个动作、一个角色。

[quickstart/policies/hello.yaml](quickstart/policies/hello.yaml)

```yaml
# yaml-language-server: $schema=https://api.cerbos.dev/latest/cerbos/policy/v1/Policy.schema.json
apiVersion: api.cerbos.dev/v1

resourcePolicy:
  resource: hello
  version: default

  schemas:
    resourceSchema:
      ref: cerbos:///hello.json

  rules:
    # 目的:任何 user 角色都可以 read 一个 hello 资源。
    - name: user-may-read
      actions:
        - read
      roles:
        - user
      effect: EFFECT_ALLOW
```

语义就是一句话:**`user` 角色可以 `read` 一个 `hello` 资源,其他人一律拒绝**(Cerbos 默认拒绝)。

配套的属性 schema([quickstart/policies/_schemas/hello.json](quickstart/policies/_schemas/hello.json)):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": { "name": { "type": "string", "description": "Who the greeting is for." } },
  "additionalProperties": false
}
```

规则名 `user-may-read` 不是装饰——它会出现在决策输出的 `policy` 字段和审计记录里,让「哪条规则放行的」可以被追溯。规则上方的「目的」注释同理:半年后有人问"为什么用户能读",答案在策略文件里,不用去翻聊天记录。

---

### step 2 — 部署

**skill:`cerbos-policy` Phase 5 · 工具函数:`POST /admin/policy`、`POST /admin/schema`**

store 换成 `sqlite3` 之后,部署就是一个 API 调用:

```bash
curl -s -u "cerbos:cerbosAdmin" -X POST \
  -H 'Content-Type: application/json' --data-binary @quickstart/deploy-policy.json \
  http://10.17.1.201:3592/admin/policy
```

```json
{"success":true}
```

```bash
curl -s -u "cerbos:cerbosAdmin" http://10.17.1.201:3592/admin/policies
```

```json
{"policyIds":["resource.basicResource.vdefault","resource.hello.vdefault"]}
```

**部署完要核对清单**——`GET /admin/policies` 给的是 PDP 此刻**真的在提供**的策略。这不是可选动作:store 刚换过、或者推送漏了策略,策略集就是空的,而**每一个决策都会变成 DENY,并且没有任何报错**——`/_cerbos/health` 照样是 `SERVING`。只有这份清单会告诉你真相。

**策略 id 跟存储驱动有关**:可变存储用的是编译后的 id(`resource.hello.vdefault`),目录存储用的是源文件名(`hello.yaml`)。别写死成一种。

> **脚本默认不写。** `quickstart.py` 的第 2 步默认只做只读探测,因为往一台共享服务器上写东西是个副作用,不该悄悄发生。要真推,加 `--deploy`:
>
> ```bash
> uv run python quickstart/quickstart.py --pdp http://10.17.1.201:3592 --deploy
> ```
>
> 推完记得清理,否则这台 PDP 会多一条 `resource.hello.vdefault`:
>
> ```bash
> curl -s -u "cerbos:cerbosAdmin" -X POST \
>   'http://10.17.1.201:3592/admin/policy/delete?id=resource.hello.vdefault'
> ```

---

### step 3 — 测 ALLOW 和 DENY

**skill:`cerbos-pep-integration` · 工具函数:`CerbosClient.check_resources()` → `POST /api/check/resources`**

决策端点**不需要认证**,也不需要先部署什么——它问的是 PDP 此刻在服务的策略。

用这台 PDP 真正在服务的 `basicResource` 跑一对相反的请求(脚本把请求体写到 `quickstart/check-allow.json` 和 `quickstart/check-deny.json`):

```bash
uv run python quickstart/quickstart.py --pdp http://10.17.1.201:3592 \
  --demo-kind basicResource --demo-allow-role USER --demo-deny-role GUEST \
  --demo-owner alice --demo-other bob \
  --demo-attr '{\"ownerId\": \"alice\", \"isPublished\": true}'
```

```
-- step 3: 问一次 ALLOW 和 DENY
   skill : cerbos-pep-integration
   call  : POST /api/check/resources
   ALLOW: alice (USER) read basicResource -> EFFECT_ALLOW
   DENY: bob (GUEST) read basicResource -> EFFECT_DENY
```

**ALLOW 和 DENY 都是真的**,两个请求只差 principal 的角色。

裸 curl 的形式:

```bash
curl -s -X POST -H 'Content-Type: application/json' \
  --data-binary @quickstart/check-allow.json \
  http://10.17.1.201:3592/api/check/resources
```

```json
{
  "requestId": "quickstart-allow",
  "results": [{
    "resource": { "id": "greeting-alice", "kind": "basicResource", "policyVersion": "default" },
    "actions": { "read": "EFFECT_ALLOW" },
    "meta": { "actions": { "read": { "matchedPolicy": "resource.basicResource.vdefault" } } }
  }],
  "cerbosCallId": "01M5XJ..."
}
```

`meta.matchedPolicy` 值得看:它区分两种看起来一样的失败——**规则存在但条件不成立**,和**根本没有匹配的策略**(kind / scope / version 对不上)。`includeMeta: true` 才会带上它。

---

### step 4 — 取回 audit log

**skill:`cerbos-audit-insights` · 工具函数:`GET /admin/auditlog/list/KIND_DECISION`**

```bash
curl -s -u "cerbos:cerbosAdmin" \
  'http://10.17.1.201:3592/admin/auditlog/list/KIND_DECISION?tail=1'
```

```json
{
  "result": {
    "decisionLogEntry": {
      "callId": "01M600PTZY4V21HA56WPVNFJ4V",
      "timestamp": "2026-10-28T00:55:38.462515164Z",
      "peer": { "address": "10.17.1.94:3730", "userAgent": "cerbos-python/0.16.1" },
      "checkResources": {
        "inputs":  [ { "requestId": "3d972f35-…", "principal": { "id": "alice", "roles": ["USER"] },
                       "resource": { "kind": "basicResource", "id": "doc1" }, "actions": ["read"] } ],
        "outputs": [ { "resourceId": "doc1",
                       "actions": { "read": { "effect": "EFFECT_ALLOW",
                                             "policy": "resource.basicResource.vdefault" } } } ]
      },
      "auditTrail": { "effectivePolicies": { "resource.basicResource.vdefault": {
                         "attributes": { "driver": "sqlite3", "update_ts": "2026-10-28T00:53:31Z" } } } },
      "policySource": { "database": { "driver": "DRIVER_SQLITE3" } }
    }
  }
}
```

#### ⚠️ 四个容易踩的细节

1. **响应是 `application/x-ndjson`——一行一条记录,不是单个 JSON 文档。** 返回多条时 `response.json()` 直接抛错,必须逐行解析:

   ```python
   entries = [json.loads(line) for line in response.text.splitlines() if line.strip()]
   ```

2. **每行外面套着一层 `result`。** 记录在 `result.decisionLogEntry` / `result.accessLogEntry` 里。

3. **`inputs` 和 `outputs` 在 `checkResources` 下面**,不在记录顶层;`planResources` 的调用则是 `planResources.inputs` / `planResources.outputs`。

4. **`auditTrail` 里的键是 `effectivePolicies`**,不是 `policies`。它记的是当时生效的策略、来源驱动和更新时间。`policySource` 按驱动类型分键(`disk` / `database` / `blob`),别写死。

每个动作的效果是一个对象,`{"effect": "EFFECT_ALLOW", "policy": "…"}`——`policy` 就是放行它的那条策略,排查时最有用。

**对号要用 `lookup`,不要用 `tail`。** `tail=1` 给的是**最近**一条记录,如果这台 PDP 上还有别的流量,那很可能不是你的:

```bash
curl -s -u "cerbos:cerbosAdmin" \
  'http://10.17.1.201:3592/admin/auditlog/list/KIND_DECISION?lookup=01M600PTZY4V21HA56WPVNFJ4V'
```

查询参数:`tail=N`(最近 N 条)、`since=3h`(相对时间窗)、`between.start` / `between.end`(ISO-8601 时间窗)、`lookup=<callId>`(按调用 ID 精确查)。

**把一次决策和它的审计记录对上号:** 每个 API 响应都带 `cerbosCallId`,应用侧记下来就能和 Cerbos 侧的记录接上。请求还能带 `requestContext.annotations`,自定义的键值对会**同时**出现在 access 和 decision 两条记录里——租户、环境、trace id 都适合放这里,密钥不要放。带上了注解的请求,记录里会多一个 `requestContext` 字段;没带注解的请求,这个字段整个不存在(proto3 不输出空值)。

---

## 四、这台 PDP 上什么能跑

| 动作 | 状态 | 说明 |
|---|---|---|
| step 0 探活 | ✅ | |
| step 1 定义 policy | ✅ | 只是写文件 |
| step 2 部署 | ✅ | store 是 `sqlite3`,`POST /admin/policy` 返回 200 |
| step 3 测 ALLOW/DENY | ✅ | |
| step 4 取回 audit log | ✅ | audit backend 是 `local`,`GET /admin/auditlog/list/{kind}` 返回 200 |

```
这台 PDP 上,5 个步骤:完成 4,未执行 1,失败 0
  第 2 步(部署):写入共享服务器要显式要求
```

(第 2 步"未执行"是因为默认只读。加 `--deploy` 就执行。)

---

## 五、迁移是怎么做的

配置在 `wuzhiping/cerbos-pdp` 仓库的 `config/.cerbos.yaml`,`compose.yml` 把 `./config` 挂进容器当 `/config`。改了三处:

```yaml
storage:
  driver: "sqlite3"                                    # disk → sqlite3,store 变可变
  sqlite3:
    dsn: "file:/var/lib/cerbos/cerbos.db?mode=rwc&cache=shared&_fk=true"

audit:
  backend: "local"                                     # file → local,审计轨迹可查
  local:
    storagePath: /var/lib/cerbos/audit
    retentionPeriod: 168h
```

现成的文件在 [pdp-config/](pdp-config/):`.cerbos.yaml`、`compose.yml`、两个一直没被提交的 schema 文件、迁移用的 `push-policies.py`,以及逐条的说明。

### ⚠️ 换存储驱动有一步必须做对

`disk` 从目录读策略,`sqlite3` 从数据库读——**磁盘目录里的策略不会自动进数据库**。切过去之后 PDP 起来了,策略集却是空的,**每个决策都变成 DENY,而且没有任何报错**。

所以推送这步不能省:

```bash
python3 pdp-config/push-policies.py --pdp http://10.17.1.201:3592 \
    --policies pdp-config/config/policies
```

脚本做三件事:把 `_schemas/` 下的每个 JSON 按 `cerbos:///<相对路径>` 推成一条 schema(`definition` 是 base64 字节),把每个 `*.yaml` 策略推成一条 policy(跳过 `*_test.yaml` 和 `testdata/`),最后用 `GET /admin/policies` 和 `GET /admin/schemas` 核对清单。先用 `--dry-run` 看它要推什么。

**推的顺序有讲究**:先 schema,后 policy。先推 policy 的话,策略引用的 schema 还没进 store,编译就会失败。

### 顺带补上的第三个缺口

上游的 `config/policies/basicResource.yaml` 声明了两个 schema,但仓库里从来没有 `_schemas/` 目录,这两个引用**从来没解析成功过**,属性类型完全不生效。补上之后:

```
config/policies/_schemas/principal.json       354 字节
config/policies/_schemas/basicResource.json    451 字节
```

**属性 schema 现在强制生效**：两个 schema 都已经部署好,`schema.enforcement: reject` 也已经开启:

```yaml
schema:
  enforcement: reject
```

`reject` 模式下:响应仍然是 **200**(不是错误状态),动作被置为 `EFFECT_DENY`,`validationErrors` 出现在 **`results[]` 那一层**、和 `actions` 并列。**SDK 看不到它们**——Python SDK 的响应模型里没有 `validation_errors` 字段,会静默丢掉,所以要看到错误得读原始 HTTP 响应。

⚠️ 这是行为变化:多带一个字段的请求原来会放行,之后会被拒绝(schema 里 `additionalProperties: false`)。上线前先确认调用方都按 schema 发属性。

**部署 schema 的 id 要用相对路径**——这个坑很隐蔽:存储里存的是**相对路径**——`_schemas/principal.json` 推上去的 id 是 `principal.json`,而不是 `cerbos:///principal.json`。策略里 `schemas.*Schema.ref` 才带前缀,PDP 编译时会把前缀去掉再去 store 里找。推错了会“看着像成功了”,但每个请求都拒绝,而那行还读不回来。**在 `none` 模式下完全看不出来**——因为 `none` 模式下 PDP 根本不编译 schema。

---

## 六、常见错误对照表

| 症状 | 多半是这个 | 怎么确认 |
|---|---|---|
| `501 Configured store is not mutable` | PDP 的 store 只读 | `POST /admin/policy` 看状态码 |
| `501 Audit log backend does not support querying` | audit 后端只写不查 | `GET /admin/auditlog/list/KIND_DECISION?tail=1` 看状态码 |
| `response.json()` 抛 `Extra data` | 审计端点返回的是 NDJSON | 逐行解析 `response.text.splitlines()` |
| 一直 ALLOW | 策略没部署上,PDP 还在用旧的 | `GET /admin/policies` 看清单 |
| 畸形属性被放行 | `schema.enforcement` 是 `none`,根本不校验 | 看响应里有没有 `results[].validationErrors` |
| **一直 DENY,而且没有报错** | **策略集是空的**(换存储驱动后最常见) | `GET /admin/policies` 看清单,和 `GET /_cerbos/health` 是不是 SERVING 无关 |
| 一直 DENY | 属性没传进来 | 请求带 `includeMeta: true`,看 `matchedPolicy` 和决策记录里的 `checkResources.inputs` |
| `401` | admin API 要 Basic 凭据 | `-u "cerbos:cerbosAdmin"` |
| 请求卡到超时 | httpx 走了 Windows 注册表里的代理 | 把 PDP 主机加进 `NO_PROXY` |
| `ModuleNotFoundError: cerbos` | 没在项目 venv 里跑 | 用 `uv run python ...` |
| 中文输出是乱码 | Python 的 stdout 是 GBK | 脚本已经强制 UTF-8;自己写脚本时 `sys.stdout.reconfigure(encoding="utf-8")` |

---

## 七、下一步

跑通这四步之后,按你要做的事挑:

| 你要做的事 | 去哪个 skill |
|---|---|
| 写新策略、改规则、配 `*_test.yaml` | `cerbos-policy` |
| 在应用代码里加权限判断、过滤列表 | `cerbos-pep-integration` |
| 开关审计、脱敏、查决策日志 | `cerbos-audit-insights` |

本仓库里已经有一套完整的例子:`policies/` 目录是一份带规则名和用途注释的策略加它的原生测试套件,`tests/` 是 328 个对着这台 PDP 跑的用例,`coverage-plan.json` 是覆盖计划。跑法见 [README.md](README.md)。

---

## 八、跑法

```bash
# 全部步骤,逐个打印用了哪个 skill 的哪个 API(默认只读)
uv run python quickstart/quickstart.py --pdp http://10.17.1.201:3592

# 真的把 hello 策略推上去
uv run python quickstart/quickstart.py --pdp http://10.17.1.201:3592 --deploy

# 只看某个 PDP 能做什么(退出码 0 = 没有失败的步骤)
uv run python quickstart/quickstart.py --pdp http://<other-pdp>:3592

# 把 ALLOW/DENY 演示指向另一条策略
uv run python quickstart/quickstart.py --demo-kind basicResource \
  --demo-allow-role USER --demo-deny-role GUEST \
  --demo-owner alice --demo-other bob \
  --demo-attr '{\"ownerId\": \"alice\", \"isPublished\": true}'
```

凭据默认就是 `cerbos` / `cerbosAdmin`,也可以用环境变量 `CERBOS_ADMIN_USER` / `CERBOS_ADMIN_PASSWORD` 覆盖。

生成的文件:

| 文件 | 内容 |
|---|---|
| [quickstart/quickstart.py](quickstart/quickstart.py) | 四个步骤的完整实现 |
| [quickstart/policies/hello.yaml](quickstart/policies/hello.yaml) | step 1 的最简 policy |
| [quickstart/policies/_schemas/hello.json](quickstart/policies/_schemas/hello.json) | 它的属性 schema |
| `quickstart/deploy-policy.json` | step 2 的请求体(脚本生成) |
| `quickstart/deploy-schema.json` | step 2 的 schema 请求体,`definition` 是 base64 字节(脚本生成) |
| `quickstart/check-allow.json` / `check-deny.json` | step 3 的两个请求体(脚本生成) |

---

## 九、工具链约束

这台机器上:

* **只有 `uv` + Python** —— `uv` 自带 CPython 3.12.11,`cerbos` SDK 装在项目的 `.venv` 里
* **没有 Docker**,也没有 cerbos 的 Windows 版本(官方只发 Darwin / Linux / deb / rpm),所以**没有本地 PDP 可用**——所有步骤都打远程 PDP
* `uv` 的缓存必须在工作区内(`UV_CACHE_DIR=.uv-cache`),默认位置在工作区外,写入被沙箱拒
* Windows 注册表里的代理会让 httpx / urllib 把内网 PDP 的请求路由到 `10.9.32.1:8000`,脚本在启动时把 PDP 主机加进 `NO_PROXY`
* Python 的 stdout 在中文 Windows 上默认是 GBK,脚本自己强制成 UTF-8,否则中文输出全是乱码

---

Next with Cerbos Hub: 这台 PDP 现在是 sqlite3 store + local audit backend,四个步骤全通;下一步是把 `schema.enforcement` 设成 `reject`(现在还是 `none`,畸形属性根本不校验),或者把策略搬进 Cerbos Hub 的 policy store(`cerbos-hub-setup` 仍在 `admin/aife/PDP/cerbos-hub-setup/` 备着),让 Hub 在每次改动时自动跑这套 `*_test.yaml` 并把签名 bundle 推给 PDP——Hub 始终不在请求路径上,每次检查仍然走你自己网络里的 PDP。
