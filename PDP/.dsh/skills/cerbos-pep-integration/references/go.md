# Go PEP

权威来源:[`cerbos/cerbos-sdk-go`](https://github.com/cerbos/cerbos-sdk-go),API 参考见 [pkg.go.dev](https://pkg.go.dev/github.com/cerbos/cerbos-sdk-go/cerbos)。gRPC。

## 安装

```bash
go get github.com/cerbos/cerbos-sdk-go
```

```go
import "github.com/cerbos/cerbos-sdk-go/cerbos"
```

原来写在仓库内 `github.com/cerbos/cerbos/client` 包上的代码,改用这个导入路径。

## 连接

```go
c, err := cerbos.New("dns:///cerbos.ns.svc.cluster.local:3593", cerbos.WithTLSCACert("/path/to/ca.crt"))
```

`New(address string, opts ...Opt) (*GRPCClient, error)`。地址自带端口 —— 没有任何默认值。任何 gRPC target 都可以:`10.1.2.3:3593`、`dns:///...`,sidecar 用 `unix:/var/sock/cerbos`。

**默认开启 TLS。**`cerbos.WithPlaintext()` 切到 h2c。其他传输选项:`WithTLSAuthority`、`WithTLSInsecure`、`WithTLSCACert`、`WithTLSClientCert(cert, key)`、`WithConnectTimeout`、`WithMaxRetries`、`WithRetryTimeout`、`WithMaxRecvMsgSizeBytes`、`WithMaxSendMsgSizeBytes`、`WithUnaryInterceptors`、`WithStreamInterceptors`、`WithStatsHandler`、`WithUserAgent`、`WithPlaygroundInstance`。

客户端在启动时构建一次,然后往下传。超时来自你传给每次调用的 `context.Context`。

## 检查

```go
allowed, err := c.IsAllowed(ctx,
    cerbos.NewPrincipal("john").
        WithRoles("employee", "manager").
        WithAttr("department", "marketing"),
    cerbos.NewResource("leave_request", "XX125").
        WithAttributes(map[string]any{"owner": "harry", "status": "DRAFT"}),
    "view",
)
```

`NewResource(kind, id)` —— kind 在前。`NewPrincipal(id, roles ...string)` —— id 在前。构建器还提供 `WithPolicyVersion`、`WithScope`、`WithAttrValue`。

### 批量

```go
cc := c.WithPrincipal(principal)

resources := cerbos.NewResourceBatch().
    Add(cerbos.NewResource("leave_request", "XX125"), "view:public", "defer").
    Add(cerbos.NewResource("leave_request", "XX225"), "approve")

result, err := cc.CheckResources(ctx, resources)
allowed := result.
    GetResource("XX125", cerbos.MatchResourcePolicyVersion("20210210")).
    IsAllowed("view:public")
```

`WithPrincipal` 返回一个携带 principal 的上下文对象,这样按 resource 逐个调用时就不必再重复传 principal —— 适合一个请求 handler 为同一个用户检查多项内容的场景。

`cerbos.NewBatchingAdapter(c)` 会把并发的 `CheckResources` 调用合并成批量请求;放在 GraphQL resolver 或 dataloader 后面很有用。

`Client` 接口足够小,可以在测试里伪造:

```go
IsAllowed(ctx context.Context, principal *Principal, resource *Resource, action string) (bool, error)
CheckResources(ctx context.Context, principal *Principal, resources *ResourceBatch) (*CheckResourcesResponse, error)
PlanResources(ctx context.Context, principal *Principal, resource *Resource, actions ...string) (*PlanResourcesResponse, error)
ServerInfo(ctx context.Context) (*ServerInfo, error)
With(opts ...RequestOpt) C
WithPrincipal(principal *Principal) P
```

没有单个 resource 多动作的方法:构造一个只有一条的 `ResourceBatch`。

## 查询计划

```go
plan, err := c.PlanResources(ctx, principal, cerbos.NewResource("leave_request", ""), "approve")
```

`actions ...string` 是可变参数;多个动作需要 PDP 0.44.0 或更高版本。动 condition 之前先按 filter 的 kind 分支 —— 见 [query-plan.md](query-plan.md)。

[Ent](https://github.com/cerbos/query-plan-adapters/tree/main/ent) 和 [pgx](https://github.com/cerbos/query-plan-adapters/tree/main/pgx) 的参考适配器在 `cerbos/query-plan-adapters` 仓库里,可以从 `github.com/cerbos/query-plan-adapters/{ent,pgx}` 导入。两者都提供 `Translate(plan, table, mapper, opts...)`。都还没有发布 tag,所以你需要固定一个 pseudo-version;先读它们的 README。

## 每请求选项

`c.With(opts ...RequestOpt)` 返回一个客户端包装器,所以可以每请求安全地调用:

```go
c.With(cerbos.AuxDataJWT(token, "ks1")).IsAllowed(ctx, principal, resource, "view")
c.With(cerbos.AuxDataJWTs(map[string]cerbos.JWT{"app": {Token: tokenA}})).CheckResources(ctx, principal, batch)
```

还可以用:`IncludeMeta(bool)`、`Headers(keyValues ...string)`、`RequestIDGenerator(func(ctx) string)`(接上你的 trace ID)、`AddAnnotations` / `SetAnnotations`(会记进 PDP 的审计日志)、`AllowPartialRequests()`。

JWT 语义和 keyset 规则见 [api-shapes.md](api-shapes.md)。

## 测试

`github.com/cerbos/cerbos-sdk-go/testutil` 会在容器里启动一台真实的 PDP(`3593/tcp` gRPC、`3592/tcp` HTTP),这样集成测试跑的是真正的引擎,而不是一个假的。只要测的是策略行为,优先用它,而不是 mock 客户端。

## 错误

`IsAllowed` 在传输失败时返回 `(false, err)`。**先看 `err`,再看布尔值** —— 直接写 `if allowed` 会把不可达的 PDP 当成拒绝,这还算安全;但忽略错误会把这次宕机藏起来。绝不要把它反转成允许。

## AuthZEN

仓库里还有 `cerbos-sdk-go/authzen`,提供 `NewClient`(gRPC)和 `NewHTTPClient(baseURL)`,用于 OpenID AuthZEN API。那是给 AuthZEN 消费方做互操作用的,不是普通的强制校验 —— 常规场景用 `cerbos` 包。
