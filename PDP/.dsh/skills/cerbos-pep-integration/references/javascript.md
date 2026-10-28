# JavaScript / TypeScript PEP

权威来源:[`cerbos/cerbos-sdk-javascript`](https://github.com/cerbos/cerbos-sdk-javascript)。所有包都是纯 ESM,需要 Node.js >= 20(在 Node 20.19.5+、22.15+、24+ 上可以从 CommonJS 里 `require`)。

## 选择包

| 包 | 传输方式 | 什么时候用 |
|---|---|---|
| `@cerbos/grpc` | gRPC,端口 3593 | 服务端 Node.js。做强制校验的默认选择。 |
| `@cerbos/http` | REST,端口 3592 | 浏览器、边缘运行时,以及任何只有 `fetch` 可用的场合。需要全局的 `fetch`。 |
| `@cerbos/embedded-client` + `@cerbos/embedded-server` | 无 —— WASM,进程内 | 不走网络的浏览器和边缘权限检查。Hub 功能;见 `cerbos-embedded-pdp` skill([Embedded PDPs](https://docs.cerbos.dev/cerbos-hub/deployments-epdp-rules?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_hub-deployments-epdp-rules))。 |
| `@cerbos/react` | 包装一个客户端 | 基于上面任意一种的 React hooks。 |
| `@cerbos/opentelemetry` | — | 给 `@cerbos/grpc` 和 `@cerbos/http` 提供链路追踪。 |
| `@cerbos/core` | — | 共享类型(`PlanKind`、`Effect`、`PlanExpression`、……)。其他包的依赖;类型从它这里导入。 |

`@cerbos/hub` 和 `@cerbos/files` 是编写策略的工具,不是 PEP 包。

## 连接

```typescript
import { GRPC } from "@cerbos/grpc";

const cerbos = new GRPC("localhost:3593", { tls: false });
```

`GRPC` 必须传 `options`,因为 `tls` 是必填的:`false` 表示明文,`true` 表示对着内置根 CA 证书校验,或者传一个来自 `tls.createSecureContext()` 的 `SecureContext`,用于自定义 CA 或双向 TLS。`target` 也接受 `"unix:/var/run/cerbos.grpc.sock"`,这是 sidecar 场景下延迟最低的选择。`cerbos.close()` 释放 channel。

```typescript
import { HTTP } from "@cerbos/http";

const cerbos = new HTTP("http://localhost:3592");
```

两者共用的 options(`@cerbos/core`):`headers`(静态值,或一个按请求返回 headers 的函数 —— 用来透传 trace header 的钩子)、`onValidationError`(`"throw"`、一个回调,或者不设置,改为从响应上读 `validationErrors`)、`userAgent`、`playgroundInstance`(托管的演示 PDP,仅供原型开发)、`adminCredentials`。

没有超时或 deadline 选项。用 `RequestOptions.signal` 取消请求,它是每个方法的第二个参数:

```typescript
await cerbos.isAllowed(request, { signal: AbortSignal.timeout(500) });
```

## 四种调用

```typescript
// 一个 action、一个 resource —— 守卫语句。
const allowed: boolean = await cerbos.isAllowed({
  principal: { id: "user@example.com", roles: ["USER"], attr: { tier: "PREMIUM" } },
  resource: { kind: "document", id: "1", attr: { owner: "user@example.com" } },
  action: "view",
});

// 同一个 resource 上的多个动作 —— 一次往返,例如用来构建 permissions 映射。
const decision = await cerbos.checkResource({
  principal,
  resource: { kind: "document", id: "1", attr: { owner: "user@example.com" } },
  actions: ["view", "edit", "delete"],
});
decision.isAllowed("view");    // boolean | undefined
decision.allowedActions();     // string[]
decision.allAllowed();         // boolean

// 手头已经拿到的多个 resource。
const decisions = await cerbos.checkResources({
  principal,
  resources: [
    { resource: { kind: "document", id: "1" }, actions: ["view", "edit"] },
    { resource: { kind: "image", id: "1" }, actions: ["delete"] },
  ],
});
decisions.isAllowed({ resource: { kind: "document", id: "1" }, action: "view" });
decisions.findResult({ kind: "document", id: "1" });  // CheckResourcesResult | undefined

// 过滤列表 —— 见 query-plan.md。
const plan = await cerbos.planResources({
  principal,
  resource: { kind: "document" },   // 没有 id:这是一个 ResourceQuery
  actions: ["view"],
});
```

读决策时注意这个不对称:`CheckResourcesResponse` 上的选择器是一个对象(`{ resource, action }`);而单个 `CheckResourcesResult` 上它是一个裸的 action 字符串(`isAllowed("view")`)。`checkResource` 返回结果,`checkResources` 返回响应。

响应上的每个访问器在 resource 不在结果里时都返回 `undefined` —— 把 `undefined` 当成拒绝,永远不要当成允许。`kind` 和 `id` 标识一个结果;当一批里混了不同的策略版本或 scope 时,再加上 `policyVersion` 和 `scope`。

`isAllowed` 和 `checkResource` 都是在 `checkResources` 之上实现的,所以往返次数一样。选那个更能表达意图的。

四种调用都有请求级的附加项:`auxData`、`includeMetadata`(注意 SDK 这里用的是全称,和线上字段 `includeMeta` 不同)、`requestId`(默认是随机 UUID —— 换成你的 trace ID)。

## principal 和 resource

```typescript
interface Principal {
  id: string;                  // 必填
  roles: string[];             // 必填,至少一个
  attr?: Record<string, Value>;
  policyVersion?: string;
  scope?: string;
}

interface Resource {
  kind: string;                // 必填
  id: string;                  // 必填
  attr?: Record<string, Value>;
  policyVersion?: string;
  scope?: string;
}
```

用 `attr`。`attributes` 这个别名已经废弃(如果两个都设了,以 `attr` 为准)。现存的旧例子 —— 包括一些 Cerbos 教程 —— 仍在用 `attributes`;为了和你在策略里写的 `R.attr` / `P.attr` 保持一致,优先用 `attr`。

匿名用户也需要一个角色。定义一个(`"anonymous"`、`"guest"`),然后把它发过去,而不是省略 `roles` —— 省略会导致请求校验失败。

当一个请求 handler 要为同一个用户做多次检查时,把 principal 固定住:

```typescript
const user = cerbos.withPrincipal(principal, { jwt: { token } });
await user.isAllowed({ resource, action: "view" });
```

## JWT 辅助数据

```typescript
await cerbos.isAllowed({
  principal,
  resource,
  action: "view",
  auxData: { jwt: { token: rawJwt, keySetId: "ks1" } },
});
```

`keySetId` 只有在 PDP 只配了一个 keyset 时才可以省略。没有 token 时就完全别传 `auxData` —— SDK 会把这个字段丢掉,而不是发一个空的。语义以及 PDP 端的校验见 [api-shapes.md](api-shapes.md)。

嵌入客户端没有可供校验的服务器,所以它需要一个 `decodeJWTPayload` 选项(它的文档给了一个 `jose` 实现),否则根本不接受 JWT。

## 查询计划

```typescript
import { PlanKind } from "@cerbos/core";

switch (plan.kind) {
  case PlanKind.ALWAYS_ALLOWED: // 不过滤,直接查询
  case PlanKind.ALWAYS_DENIED:  // 不查询,直接返回 []
  case PlanKind.CONDITIONAL:    // plan.condition 是 AST 的根节点
}
```

`PlanResourcesResponse` 是按 `kind` 区分的联合类型,所以 `condition` 只在 conditional 那个分支上存在;`planResourcesResponseIsConditional(plan)` 是导出的类型守卫。AST 节点是类 —— `PlanExpression`(`operator`、`operands`)、`PlanExpressionValue`(`value`)、`PlanExpressionVariable`(`name`) —— 所以用 `instanceof` 就能把它们收窄。

`actions: string[]` 需要 PDP v0.44+;单数的 `action: string` 已废弃但仍然接受,适配器示例里也还在出现。

设置 `includeMetadata: true`,然后读 `metadata.conditionString`,就能在你写映射器的同时看到可读的 CEL 条件。

适配器:`@cerbos/orm-prisma`、`@cerbos/orm-drizzle`、`@cerbos/orm-mongoose`、`@cerbos/orm-convex`、`@cerbos/langchain-chromadb`。见 [query-plan.md](query-plan.md)。

## 错误

- `NotOK` —— PDP 返回了错误状态。带有 `code` 和 `details`。
- `ValidationFailed` —— 当 `onValidationError: "throw"` 且属性 schema 校验拒绝了请求时抛出。不设置这个选项时,错误会作为 `validationErrors` 出现在响应上。
