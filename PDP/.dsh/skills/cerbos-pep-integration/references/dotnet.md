# .NET PEP

权威来源:[`cerbos/cerbos-sdk-net`](https://github.com/cerbos/cerbos-sdk-net)。NuGet 包 `Cerbos.Sdk`,gRPC,目标框架为 `netstandard2.0`、`netstandard2.1` 和 `net8.0`。

## 安装

```bash
dotnet add package Cerbos.Sdk
```

## 连接

```csharp
using Cerbos.Sdk.Builder;

var client = CerbosClientBuilder.ForTarget("http://localhost:3593").WithPlaintext().Build();
```

target 必须带 **scheme** —— 底层是 `GrpcChannel.ForAddress`,所以要写 `http://host:3593` 或 `https://host:3593`,不能只写 `host:3593`。

`WithPlaintext()` 不接受参数。默认开启 TLS。`WithCaCertificate`、`WithTlsCertificate` 和 `WithTlsKey` 都接受 `StreamReader`,不是路径也不是字符串。另外还有 `WithMetadata(Metadata)`、`WithPlaygroundInstance(string)` 和 `WithGrpcChannelOptions(GrpcChannelOptions)`。当 TLS 证书和明文同时配置,或者 playground 和明文同时配置时,`Build()` 会抛异常。

在 DI 里把客户端注册成单例;它包装着一个 channel。

## 检查

```csharp
var request = CheckResourcesRequest.NewInstance()
    .WithRequestId(RequestId.Generate())
    .WithPrincipal(
        Principal.NewInstance("john", "employee")
            .WithAttribute("department", AttributeValue.StringValue("marketing"))
    )
    .WithResourceEntries(
        ResourceEntry.NewInstance("leave_request", "XX125")
            .WithAttribute("owner", AttributeValue.StringValue("john"))
            .WithActions("approve", "view:public")
    );

var result = (await client.CheckResourcesAsync(request)).Find("XX125");
if (result.IsAllowed("approve")) { … }
```

客户端接口是同步/异步成对的:

```csharp
CheckResourcesResponse CheckResources(CheckResourcesRequest request, Metadata headers = null);
Task<CheckResourcesResponse> CheckResourcesAsync(CheckResourcesRequest request, Metadata headers = null);
PlanResourcesResponse PlanResources(PlanResourcesRequest request, Metadata headers = null);
Task<PlanResourcesResponse> PlanResourcesAsync(PlanResourcesRequest request, Metadata headers = null);
HealthCheckResponse CheckHealth(HealthCheckRequest request, Metadata headers = null);
```

**客户端上没有 `IsAllowed`,也没有单个 resource 的方法。**所有检查都走 `CheckResources`,然后 `CheckResourcesResponse.Find(string id)` 返回一个 `ResultEntry`,它的 `IsAllowed(string action)` 给出决策。`ResultEntry` 还暴露 `Actions`、`Resource`、`Meta`、`Outputs`、`ValidationErrors`、`Output(string src)` 和 `OutputByAction(string action)`。

在 ASP.NET Core 的请求 handler 里用 `Async` 版本 —— 同步版本会在网络调用上占住线程池的一个线程。

构建器:`Principal.NewInstance(string id, params string[] roles)`,外加 `WithRoles`、`WithAttribute`、`WithAttributes(Dictionary<string, AttributeValue>)`、`WithPolicyVersion`、`WithScope`。`ResourceEntry.NewInstance(string kind, string id)` 或 `ResourceEntry.NewInstance(Resource resource, params string[] actions)`。`CheckResourcesRequest` 还有 `WithIncludeMeta`、`WithAuxData`、`WithAllowPartialRequests`、`WithRequestContext`。

属性值是 `AttributeValue.StringValue(...)` 之类的,永远不要传裸的 .NET 值。

## 查询计划

```csharp
var request = PlanResourcesRequest.NewInstance()
    .WithRequestId(RequestId.Generate())
    .WithPrincipal(principal)
    .WithResource(Resource.NewInstance("leave_request"))
    .WithActions("approve");

var result = await client.PlanResourcesAsync(request);

if (result.IsAlwaysAllowed())      { /* no filter */ }
else if (result.IsAlwaysDenied())  { /* empty result */ }
else                               { ApplyFilter(result); }
```

`WithActions(params string[])` 需要 Cerbos PDP v0.44.0 或更高版本;`WithAction(string)` 是单动作的形式。`PlanResourcesRequest` 还接受 `WithAuxData`、`WithIncludeMeta` 和 `WithRequestContext`。

没有 .NET 查询计划适配器。自己遍历 filter AST —— 节点形状见 [api-shapes.md](api-shapes.md),安全做法见 [query-plan.md](query-plan.md)。惯用的目标是写一个能产出 LINQ `Expression<Func<T, bool>>` 的表达式翻译器,因为这样 EF Core 才能把它下推进 SQL。

## JWT 辅助数据

```csharp
request.WithAuxData(AuxData.WithJwt(token, "ks1"));
request.WithAuxData(AuxData.WithJwts(new Dictionary<string, AuxData.Types.JWT> { … }));
```

`CheckResourcesRequest` 和 `PlanResourcesRequest` 上都有。`AuxData.Types.JWT.NewInstance(token, keySetId)` 和 `FromToken(token)` 用来构造条目。语义见 [api-shapes.md](api-shapes.md)。

## ASP.NET Core

包里没有 Cerbos 的授权处理器。惯用的接法是一个基于 resource 的 requirement 之上的 `IAuthorizationHandler`,它解析出那个单例客户端并调用 `CheckResourcesAsync`,这样 `AuthorizeAsync(user, resource, policy)` 就能通过框架自己的管道走到 Cerbos。把 `ClaimsPrincipal` → `Principal` 的映射集中在一处。
