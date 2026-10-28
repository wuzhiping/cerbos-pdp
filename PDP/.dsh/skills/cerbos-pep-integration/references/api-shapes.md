# Cerbos PDP API 形态

协议层的事实基准。每个 SDK 都是这两个调用的类型化封装,所以当某个 SDK 的命名有歧义时,就看它针对本页构造出来的请求。

运行中的 PDP 在 `http://localhost:3592/` 上提供自己的 OpenAPI 浏览器。那才是你所用版本的权威 schema;本页只是摘要。

## 端点

| | REST(默认端口 3592) | gRPC(默认端口 3593) |
|---|---|---|
| 检查 | `POST /api/check/resources` | `cerbos.svc.v1.CerbosService/CheckResources` |
| 查询计划 | `POST /api/plan/resources` | `cerbos.svc.v1.CerbosService/PlanResources` |
| 服务器信息 | `GET /api/server_info` | `cerbos.svc.v1.CerbosService/ServerInfo` |

PDP 还在 `/access/v1/evaluation` 和 `/access/v1/evaluations` 上提供了一个 [OpenID AuthZEN](https://openid.github.io/authzen/) 门面,把 subject→principal、resource→resource、action→action 映射起来。只有当第三方系统支持 AuthZEN 时才用它;原生 API 功能要丰富得多。

## CheckResources

```json
{
  "requestId": "test",
  "principal": {
    "id": "alice",
    "roles": ["employee"],
    "attr": { "department": "accounting", "geography": "GB" },
    "policyVersion": "20210210",
    "scope": "acme.corp"
  },
  "resources": [
    {
      "resource": {
        "id": "XX125",
        "kind": "leave_request",
        "attr": { "owner": "john", "status": "PENDING_APPROVAL" },
        "policyVersion": "20210210",
        "scope": "acme.corp"
      },
      "actions": ["view:public", "approve", "create"]
    }
  ],
  "auxData": { "jwt": { "token": "xxx.yyy.zzz", "keySetId": "ks1" } },
  "includeMeta": true
}
```

必填项,由请求校验强制执行(`cerbos/engine/v1/engine.proto`):

- `principal.id` —— 非空字符串。
- `principal.roles` —— 至少一个,不能重复,每个都不能为空。
- `resource.kind` —— 非空;决定用哪条 resource 策略。
- `resource.id` —— 非空;实例标识符,在条件里以 `R.id` 的形式使用。

可选:任意一侧的 `attr`(自由格式的 JSON,ABAC 条件的全部依据)、`policyVersion`、`scope`(点号分隔,决定[作用域策略](https://docs.cerbos.dev/cerbos/latest/policies/scoped_policies?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-policies-scoped-policies)的继承)、`requestId`(原样回传;把你的 trace ID 放这里)、`includeMeta`。

**批量上限**:每次请求 50 个资源、每个资源 50 个动作,两者都是默认值,都可以在 PDP 配置的 `server.requestLimits` 下调高([服务器配置](https://docs.cerbos.dev/cerbos/latest/configuration/server?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-configuration-server))。更大的批次请在客户端切块,而不是抬高上限。

### 响应

```json
{
  "requestId": "test",
  "results": [
    {
      "resource": { "id": "XX125", "kind": "leave_request" },
      "actions": { "view:public": "EFFECT_ALLOW", "approve": "EFFECT_DENY" },
      "outputs": [ { "src": "resource.leave_request.vdefault#rule-001", "val": "create_allowed:john" } ],
      "validationErrors": [
        { "path": "/department", "message": "value must be one of \"marketing\", \"engineering\"", "source": "SOURCE_PRINCIPAL" }
      ],
      "meta": {
        "actions": { "view:public": { "matchedPolicy": "resource.leave_request.vdefault/acme.corp", "matchedScope": "acme" } },
        "effectiveDerivedRoles": ["any_employee"]
      }
    }
  ],
  "cerbosCallId": "01HHENANTHFD5DV3HZGDKB87PJ"
}
```

- `results` 按请求顺序返回,每个资源一条。
- 每个动作都映射到 `EFFECT_ALLOW` 或 `EFFECT_DENY`。Cerbos 默认拒绝:没有任何规则允许的动作就是 `EFFECT_DENY`,策略加载失败时给出的也是拒绝,而不是错误。
- `outputs` 携带[策略输出表达式](https://docs.cerbos.dev/cerbos/latest/policies/outputs?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-policies-outputs)——返回字段级安全所需的允许字段清单,靠的就是它。
- 启用 [schema 校验](https://docs.cerbos.dev/cerbos/latest/policies/schemas?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-policies-schemas)后,如果你发来的属性没有匹配上,就会出现 `validationErrors`。开发时要把它们暴露出来;它们说明 PEP 发出的结构不对。
- `meta` 只在请求里设置了 `includeMeta` 时才有内容。它指出命中的策略和生效的派生角色 —— 决策结果出乎意料时,先看它。
- `cerbosCallId` 把这次决策和 PDP 的审计日志条目对应起来。把它和你自己的请求 ID 一起记下来。

### curl

```bash
cat <<EOF | curl --silent "localhost:3592/api/check/resources?pretty" -d @-
{
  "principal": { "id": "alice", "roles": ["employee"], "attr": {} },
  "resources": [
    { "resource": { "kind": "leave_request", "id": "XX125", "attr": {} }, "actions": ["view:public", "approve"] }
  ]
}
EOF
```

## PlanResources

```json
{
  "requestId": "test01",
  "actions": ["approve"],
  "principal": { "id": "alicia", "roles": ["user"], "attr": { "geography": "GB" } },
  "resource": { "kind": "leave_request", "attr": { "owner": "alicia" } },
  "includeMeta": true
}
```

这里的 resource 是一份*描述*,不是一个实例:`kind` 是必填的,并且没有 `id`。`resource.attr` 装着你对整批待查资源已经知道的信息 —— 你省略掉的东西会作为变量留在返回的 AST 里,而对于你打算在数据库里做过滤的那些列,这正是你要的效果。

`action`(单数)与 `actions` 互斥,而且必须恰好设置其中一个。proto 把单数的 `action` 标记为已废弃;`actions` 最多接受 20 个不重复的动作,返回的计划是各动作计划的逻辑 AND。有些 SDK 和适配器示例还在用单数形式 —— 两种都能用。

### 响应

```json
{
  "requestId": "test01",
  "action": "approve",
  "resourceKind": "leave_request",
  "filter": {
    "kind": "KIND_CONDITIONAL",
    "condition": {
      "expression": {
        "operator": "eq",
        "operands": [ { "variable": "request.resource.attr.status" }, { "value": "PENDING_APPROVAL" } ]
      }
    }
  },
  "meta": { "filterDebug": "(request.resource.attr.status == \"PENDING_APPROVAL\")" },
  "cerbosCallId": "01HHENANTHFD5DV3HZGDKB87PJ"
}
```

`filter.kind` 是 `KIND_ALWAYS_ALLOWED`、`KIND_ALWAYS_DENIED`、`KIND_CONDITIONAL` 三者之一;只有最后一种才会填 `condition`。三种情况都必须处理 —— 见 [query-plan.md](query-plan.md)。

`meta.filterDebug` 在设置了 `includeMeta` 时会把 AST 渲染成可读的 CEL 字符串。开发映射器时把它记下来;它能立刻告诉你映射器必须覆盖哪些属性路径。

### 条件 AST

表达式节点是 `{ "operator": ..., "operands": [...] }`;操作数要么是嵌套的 `expression`,要么是 `{ "variable": "request.resource.attr.foo" }`,要么是 `{ "value": ... }`。

会产生的算子:`add`、`and`、`div`、`eq`、`ge`、`gt`、`in`、`index`、`lambda`、`le`、`list`、`lt`、`mod`、`mult`、`ne`、`not`、`or`、`sub`。集合类条件还会额外产生 `filter`、`exists`、`exists_one`、`all`、`map`、`hasIntersection`。

嵌套示例 —— `(R.attr.department == "marketing") && (R.attr.team != "design")`:

```json
{ "expression": { "operator": "and", "operands": [
  { "expression": { "operator": "eq", "operands": [ { "variable": "request.resource.attr.department" }, { "value": "marketing" } ] } },
  { "expression": { "operator": "ne", "operands": [ { "variable": "request.resource.attr.team" }, { "value": "design" } ] } }
] } }
```

lambda(`R.attr.values.filter(t, t > 0)`)会嵌套一个 `operator: "lambda"` 节点,它的第一个操作数是绑定好的 `{ "variable": "t" }`,第二个是循环体。

## 辅助数据(JWT)

在两个调用里 `auxData` 都是可选的,并且有两种互斥的形式:

```json
"auxData": { "jwt": { "token": "xxx.yyy.zzz", "keySetId": "ks1" } }
```

```json
"auxData": { "jwts": {
  "app_token":     { "token": "xxx.yyy.zzz", "keySetId": "ks1" },
  "gateway_token": { "token": "aaa.bbb.ccc", "keySetId": "ks2" }
} }
```

- `jwts`(多个具名 token)需要 Cerbos PDP 0.55.0 或更高版本。
- PDP 只配置了一个密钥集时 `keySetId` 是可选的,一旦超过一个就**必须**填。
- 在策略条件里,单数形式的 claim 落在 `request.auxData.jwt.<claim>`,具名形式落在 `request.auxData.jwts.<name>.claims.<claim>` —— `claims` 这一段不能省。

PDP 会校验签名以及 `exp`/`nbf` claim,密钥集来自 `auxData.jwt.keySets` 的配置([auxdata 配置](https://docs.cerbos.dev/cerbos/latest/configuration/auxdata?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-configuration-auxdata))—— 可以是 JWKS URL、本地 `.jwks` 文件、内联的 base64,或者 PEM。刷新遵循 `Cache-Control`/`Expiry` 头,除非设置了 `refreshInterval`(默认一小时)。

Cerbos 把自身的 JWT 校验当作便利措施,而不是权威判定:调用 PDP 之前先在网关或应用里校验 token。发 JWT 省掉了你手工把 claim 拆进 `principal.attr` 的麻烦,但它并没有把认证搬进 PDP。

## 不借助 SDK 与 PDP 通信

gRPC 反射是开启的,所以 `grpcurl` 可以直接打 3593 端口:

```bash
cat <<EOF | grpcurl -plaintext -d @ localhost:3593 cerbos.svc.v1.CerbosService/CheckResources
{ "principal": { "id": "alice", "roles": ["employee"] },
  "resources": [ { "resource": { "kind": "leave_request", "id": "XX125" }, "actions": ["view:public"] } ] }
EOF
```

如果你的语言没有 Cerbos SDK,可以基于 PDP 在 `/schema/swagger.json` 提供的 OpenAPI 文档生成客户端,或者基于 [`cerbos/cerbos/api/public`](https://github.com/cerbos/cerbos/tree/main/api/public) 里的 protobuf 定义生成。完整说明见 [Cerbos API](https://docs.cerbos.dev/cerbos/latest/api/index?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-api)。
