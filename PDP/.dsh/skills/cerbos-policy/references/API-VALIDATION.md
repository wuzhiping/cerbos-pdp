# 仅通过 API 验证

如何**通过运行中的 PDP 的 HTTP API** 验证 Cerbos 策略包，无需 `cerbos` 二进制，无需 `cerbosctl`，也无需 Docker。

PDP 同时是编译器、测试执行器和审计数据源。你把策略交给它，向它提问，再把答案读回来。

**默认凭据**：`cerbos` / `cerbosAdmin`，以 HTTP Basic 的形式随每个 `/admin/*` 调用一起发送。

```bash
curl -s -u "cerbos:cerbosAdmin" http://<pdp>:3592/admin/policies
```

---

## 1. 接口

以下内容以 PDP 自带的 OpenAPI 文档 `GET /schema/swagger.json` 为依据。请阅读你所面对的那个版本对应的文档，而不是直接相信这张表。

| 用途 | 端点 | 鉴权 |
|---|---|---|
| 健康检查 | `GET /_cerbos/health` | 无 |
| 服务器信息 | `GET /api/server_info` | 无 |
| Prometheus 指标 | `GET /_cerbos/metrics` | 无 |
| **OpenAPI 文档** | `GET /schema/swagger.json` | 无 |
| 单次决策 | `POST /api/check` | 无 |
| 批量决策 | `POST /api/check/resources` | 无 |
| 查询计划 | `POST /api/plan/resources` | 无 |
| 列出已提供的策略 | `GET /admin/policies` | Basic |
| 查看已编译的策略 | `GET /admin/policies/inspect` | Basic |
| 获取单个策略 | `GET /admin/policy?id=<policyId>` | Basic |
| **新增或更新策略** | `POST /admin/policy` | Basic |
| 新增或更新 schema | `POST /admin/schema` | Basic |
| 列出 / 获取 schema | `GET /admin/schemas`, `GET /admin/schema?id=<id>` | Basic |
| 重载存储 | `GET /admin/store/reload?wait=<bool>` | Basic |
| 删除 / 禁用 / 启用 | `POST /admin/policy/delete?id=`, `POST /admin/policy/disable?id=`, `POST /admin/policy/enable?id=` | Basic |
| 审计轨迹（只有 `local` 后端可查询） | `GET /admin/auditlog/list/{kind}` | Basic |

审计轨迹的 `kind` 取值为 `KIND_UNSPECIFIED`、`KIND_ACCESS`、`KIND_DECISION` 之一。

它的响应是 `application/x-ndjson`——**一行一条记录，不是单个 JSON 文档**。每行外面套着一层 `result`，记录本身在 `result.decisionLogEntry` / `result.accessLogEntry` 里。用一次性的 `response.json()` 解析，只要返回超过一条记录就会抛错；逐行解析才对。

---

## 2. 预检

在写入任何内容之前先跑这些命令。它们只花两次调用，却能告诉你后续流程是否可行。

```bash
# 是否已启动，以及版本是什么？
curl -s http://<pdp>:3592/_cerbos/health
curl -s http://<pdp>:3592/api/server_info

# 管理 API 是否需要凭据，我们的凭据是否有效？
curl -s -o /dev/null -w '%{http_code}\n' http://<pdp>:3592/admin/policies
curl -s -u "cerbos:cerbosAdmin" http://<pdp>:3592/admin/policies
```

第一个请求返回 `401`、第二个返回 `200`，这是预期的组合：说明管理 API 已启用并受到保护。

### 存储是否可变，决定了部署方式

```bash
curl -s -u "cerbos:cerbosAdmin" -X POST -H 'Content-Type: application/json' \
  -d '{"policies":[]}' http://<pdp>:3592/admin/policy
```

* `200` ——存储是可变的。你可以通过 API 部署，PDP 会编译你发送的内容。
* `501` 且响应为 `{"code":12,"message":"Configured store is not mutable"}` ——存储不可变。部署归运维人员负责；你只能针对 PDP 当前所提供的策略进行验证。

在可变存储上，提交空的 `policies` 数组是一次无副作用的写入。

---

## 3. 第 1 步——编译

你把一个策略交给 PDP，PDP 就会编译它。

```bash
curl -s -u "cerbos:cerbosAdmin" -X POST -H 'Content-Type: application/json' \
  --data-binary @policies.json http://<pdp>:3592/admin/policy
```

请求体为 `{"policies": [<policy>, ...]}`，其中每个策略的形状与对应的 YAML 文件相同，只是把 YAML 转成了 JSON：

```json
{
  "policies": [
    {
      "apiVersion": "api.cerbos.dev/v1",
      "resourcePolicy": {
        "resource": "document",
        "version": "default",
        "schemas": { "resourceSchema": { "ref": "cerbos:///resources/document.json" } },
        "rules": [
          {
            "name": "owner-may-read",
            "actions": ["read"],
            "roles": ["user"],
            "condition": { "match": { "expr": "request.resource.attr.ownerId == request.principal.id" } },
            "effect": "EFFECT_ALLOW"
          }
        ]
      }
    }
  ]
}
```

schema 需要单独一次调用，而且它的 `definition` 是**字节流**，因此 JSON Schema 要做 base64 编码：

```bash
curl -s -u "cerbos:cerbosAdmin" -X POST -H 'Content-Type: application/json' \
  --data-binary @schemas.json http://<pdp>:3592/admin/schema
```

```json
{
  "schemas": [
    {
      "id": "cerbos:///resources/document.json",
      "definition": "eyJ0eXBlIjoib2JqZWN0In0..."
    }
  ]
}
```

### 各响应的含义

| 响应 | 含义 | 应对方式 |
|---|---|---|
| `200` | 策略编译通过并已存储 | 进入测试步骤 |
| `400` `{"code":3,"message":"..."}` | 策略未通过编译，或请求结构有误 | 错误信息会指出有问题的规则、导入或变量——修正后重新发送 |
| `501` `{"code":12,"message":"Configured store is not mutable"}` | 该 PDP 无法接收策略 | 由运维人员部署；针对它实际所提供的内容进行验证 |

编译错误以 gRPC 风格的 JSON 错误返回，而不是 HTTP 500。请阅读 `message`——其中包含出错文件、规则和原因。

---

## 4. 第 2 步——测试

`*_test.yaml` 测试套件中的每条断言，都对应一次决策请求。

```bash
curl -s -X POST -H 'Content-Type: application/json' --data-binary @request.json \
  http://<pdp>:3592/api/check/resources
```

请求体：

```json
{
  "requestId": "suite-name",
  "includeMeta": true,
  "principal": {
    "id": "alice",
    "roles": ["user"],
    "policyVersion": "default"
  },
  "resources": [
    {
      "resource": {
        "kind": "document",
        "id": "doc1",
        "policyVersion": "default",
        "attr": { "ownerId": "alice" }
      },
      "actions": ["read", "update"]
    }
  ]
}
```

响应：

```json
{
  "requestId": "suite-name",
  "results": [
    {
      "resource": { "id": "doc1", "kind": "document", "policyVersion": "default" },
      "actions": { "read": "EFFECT_ALLOW", "update": "EFFECT_DENY" },
      "meta": {
        "actions": {
          "read": { "matchedPolicy": "resource.document.vdefault" }
        }
      }
    }
  ]
}
```

### 部署 schema：id 是**相对路径**,不带 `cerbos:///` 前缀

`POST /admin/schema` 的 id 必须是**相对于 `_schemas/` 的路径**：

| 文件 | 正确的 id | 常见的错误 |
|---|---|---|
| `_schemas/principal.json` | `principal.json` | `cerbos:///principal.json` |
| `_schemas/resources/foo.json` | `resources/foo.json` | `cerbos:///resources/foo.json` |

**store 里存的是相对路径**；策略里 `schemas.*Schema.ref` 写的是带前缀的 `cerbos:///<相对路径>`。PDP 编译 schema 时把 ref 的前缀去掉，拿相对路径去 store 里找。

推错了会怎样：

* `POST /admin/schema` 返回 200，`GET /admin/schemas` 也照原样把它列出来——**看着像成功了**；
* 但编译时永远找不到，每一个请求都带着 `Failed to load ... schema` 变成拒绝；
* 而且**这种行读不回来**：`GET /admin/schema?id=...` 各种前缀组合都返回 500（`could not get the schema with id ...`），内容就卡在数据库里了。

**在 `schema.enforcement: none`（默认）下这件事完全看不出来**——`none` 模式下 PDP 根本不编译 schema，所以策略引用了一个不存在的 schema 也没有任何症状。改成 `reject` 之后，每一个请求都直接失败。

所以：**先确认 `GET /admin/schemas` 里的 id 是相对路径，再把 enforcement 打开。**

### `schema.enforcement`：默认是 `none`

| 取值 | 行为 |
|---|---|
| `none`（**默认**） | 完全不校验。属性不合 schema 也照样求值，响应里没有 `validationErrors` |
| `warn` | 校验，但只在日志里记警告，决策照常 |
| `reject` | 校验不通过就**拒绝这次检查里的每个动作**，响应里带 `validationErrors` |

`reject` 模式下的响应形状：

* HTTP **200**，不是错误状态；
* 动作被置为 `EFFECT_DENY`；
* `validationErrors` 在 **`results[]` 那一层**，和 `actions`、`meta` 并列——**不在响应顶层**；
* **SDK 看不到它们**：Python SDK 的响应模型里没有 `validation_errors` 字段，会静默丢掉。要看到错误得读原始 HTTP 响应。
* 策略的 `resourceSchema.ignoreWhen` 列出的 action 不做资源校验（例如 `create`）。

每个响应都要断言三件事：

1. **`results[].actions.<action>`** 等于测试套件预期的效果。
2. **`results[].validationErrors` 不存在或为空。** 出现校验错误意味着请求与已声明的 schema 不匹配。
3. 当 `includeMeta` 为 true 时，**`meta.actions.<action>.matchedPolicy`** 指出做出该决策的策略。区分“规则未匹配”和“完全没有策略匹配”时，这是最快的办法。

### 根据测试套件构造请求

测试套件的 `input` 是一个笛卡尔积：列出的每个 principal 与列出的每个 resource 配对，再对列出的每个 action 求值。凡是 `expected` 中未出现的配对，预期对所有 action 都是 DENY；已列出的配对中，`expected` 未提及的 action 同样预期为 DENY。

fixture 的键通过 `testdata/principals.yaml` 和 `testdata/resources.yaml` 解析为真实值；某个测试套件内联的 `principals`/`resources` 会覆盖这些共享文件。

### HTTP API 做不到的事

决策类端点上**没有严格求值（strict evaluation）开关**。`requestContext` 只携带 annotations——这一点已在 PDP 的 OpenAPI 文档中确认：`v1RequestContext` 只有一个属性 `annotations`。

因此，运行时出错的条件会被求值为 false，而不是以拒绝作为终态结果。最值得关注的失败模式是：某条 DENY 规则的条件出错——该拒绝会静默失效，动作反而被放行。只用 API 时的替代做法是让这种情况不可能发生，而不是事后再去检测：

* 每个 fixture 都带上其条件所读取的每一个属性，这样属性缺失就一定是 fixture 自身的问题；
* 测试套件在每个响应上都断言 `validationErrors` 为空；
* 条件读取可选属性的规则要对它做保护，例如 `has(request.resource.attr.ownerId) && request.resource.attr.ownerId == request.principal.id`。

在报告中直白地写明：严格求值不可用。

---

## 5. 第 3 步——覆盖率审计

```bash
python3 <skill-dir>/scripts/coverage_audit_api.py --pdp http://<pdp>:3592 \
  --policies policies --plan coverage-plan.json
```

该脚本需要 Python 3 标准库和 PyYAML。它会解析计划中的 fixture 键，针对 PDP 执行计划里的每一行，并应用以下审计规则：

1. 计划中的每一行都必须在 PDP 上成立；
2. 计划中的 `facts` 必须与解析后的 fixture 相符，而不是与它的名字相符；
3. 带 `control` 的行必须具有相反的效果和相同的 action，且两个请求恰好在 `change` 指定的字段上不同；
4. 每条已声明授权路径的每个前置条件，都必须有一行孤立的拒绝用例，且该行在该路径 kind 的资源上 control 通过。

审计通过时退出码为 0，否则为 1，并且先打印失败项，再打印通过项。

如果 PDP 的 check 端点需要凭据，则从环境变量中读取：

```bash
export CERBOS_ADMIN_USER=... CERBOS_ADMIN_PASSWORD=...
```

没有 PyYAML 时脚本会以退出码 2 结束并说明原因；此时请根据计划、测试套件和 fixture 文件手工完成同样的检查，并在报告中说明可执行审计未能运行。

---

## 6. 回读 PDP 所提供的内容

```bash
curl -s -u "cerbos:cerbosAdmin" http://<pdp>:3592/admin/policies
curl -s -u "cerbos:cerbosAdmin" http://<pdp>:3592/admin/policies/inspect
curl -s -u "cerbos:cerbosAdmin" 'http://<pdp>:3592/admin/policy?id=basicResource.yaml'
```

`/admin/policies/inspect` 是编译后的视图——即 PDP 实际持有的 action 和属性；当 YAML 与所提供的策略不一致时，它才是事实依据。

```json
{
  "results": {
    "resource.basicResource.vdefault": {
      "actions": ["*", "create", "delete", "read", "update"],
      "policyId": "basicResource.yaml",
      "attributes": [
        { "kind": "KIND_RESOURCE_ATTRIBUTE", "name": "isPublished" },
        { "kind": "KIND_RESOURCE_ATTRIBUTE", "name": "ownerId" }
      ]
    }
  }
}
```

`/admin/store/reload?wait=true` 要求监听目录的存储去拾取变更后的文件，并等待重载完成。

---

## 7. 仅用 API 的流程的局限

| 不可用项 | 后果 | 替代方案 |
|---|---|---|
| 严格求值 | 运行时 CEL 错误会被求值为 false，而不是拒绝 | 保护可选属性；断言 `validationErrors` 为空；让 fixture 完整 |
| 在只读存储上编译 | PDP 永远看不到候选策略 | 由运维人员部署；用 `/admin/policies/inspect` 验证所提供的策略 |
| 单条规则的查询计划 | `POST /api/plan/resources` 是按资源 kind 做计划，不是按规则 | 用于列表过滤；它不是逐规则的解释器 |
| 向 Hub 存储上传 | 需要 `cerbosctl` 或 Hub 控制台 | 不在本流程范围内；策略包已验证完毕，可以交付 |
| 单次隔离的决策 | `POST /api/check` 只覆盖一个资源和一个 principal | `POST /api/check/resources` 批量处理 |
