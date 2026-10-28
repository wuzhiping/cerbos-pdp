# Java PEP

权威来源:[`cerbos/cerbos-sdk-java`](https://github.com/cerbos/cerbos-sdk-java)。只有 gRPC —— 没有 HTTP 客户端,也没有异步客户端;全部都是阻塞式的。

## 安装

```kotlin
dependencies {
    implementation("dev.cerbos:cerbos-sdk-java:0.+") // 固定到具体版本,避免意外升级
    implementation("io.grpc:grpc-core:1.+")          // 必须与 SDK 构建时使用的版本一致
}
```

你项目里实际生效的 protobuf 和 gRPC 版本必须与 SDK 要求的版本一致;查一下你固定的那个版本的 `build.gradle.kts`。这种冲突无法避免时,使用 shaded jar,它会把 `com.google.protobuf` 和 `io.grpc` 重定位到 `dev.cerbos.shaded` 之下。

`CerbosContainer`(Testcontainers)就在同一个构件里 —— 不需要额外的测试依赖。它会启动一个 PDP 容器,并给构建器提供 `getTarget()`。它只是本地测试的便利手段:当测试要跑在一台你已有的 PDP 上时,直接把测试指向那台 PDP,完全跳过这个容器。

## 连接

```java
CerbosBlockingClient client = new CerbosClientBuilder("localhost:3593")
    .withPlaintext()
    .buildBlockingClient();
```

构建器方法:`withPlaintext()`、`withInsecure()`、`withAuthority(String)`、`withCaCertificate(InputStream)`、`withTlsCertificate(InputStream)`、`withTlsKey(InputStream)`、`withTimeout(Duration)`、`withPlaygroundInstance(String)`、`withClientInterceptors(List<ClientInterceptor>)`。所有终结方法都会抛受检异常 `CerbosClientBuilder.InvalidClientConfigurationException`。

有两件事要弄对:

- **默认开启 TLS。**`withPlaintext()` 会把它关掉。`withInsecure()` 是另一回事:保留 TLS,但跳过证书校验。
- **默认超时是 1000 ms**,以 gRPC deadline 的形式生效。如果你的 PDP 在负载下隔着网络,就用 `withTimeout(Duration)` 把它调大;这里出现的 `DEADLINE_EXCEEDED` 会表现为 `CerbosException`,而不是一次拒绝。

Unix domain socket 只在 Linux 上可用 —— 这是 `grpc-java` 的限制。

## 检查

```java
import static dev.cerbos.sdk.builders.AttributeValue.stringValue;

CheckResult result = client.check(
    Principal.newInstance("john", "employee")
        .withAttribute("department", stringValue("marketing")),
    Resource.newInstance("leave_request", "xx125")
        .withAttribute("owner", stringValue("john")),
    "view:public", "approve");

if (result.isAllowed("approve")) { … }
```

客户端上没有 `isAllowed`:检查一次,然后从 `CheckResult` 里读动作。`isAllowed(String)` 对请求里没有的动作返回 `false`,这与 PDP 默认拒绝的语义一致。

`CheckResult` 还提供 `getAll()`、`hasValidationErrors()` / `getValidationErrors()`、`getMeta()`(`getEffectiveDerivedRoles()`、`getInfoForAction(...)`)、`getOutputs()`(`asMap()`)、`getCerbosCallId()` 和 `getRaw()`。

### 批量

```java
CheckResourcesResult result = client.batch(principal)
    .addResources(
        ResourceAction.newInstance("leave_request", "XX125")
            .withAttributes(Map.of("owner", stringValue("john")))
            .withActions("view:public", "approve"))
    .check();

boolean canView = result.find("XX125").map(r -> r.isAllowed("view:public")).orElse(false);
```

`CheckResourcesRequestBuilder` 还有 `addResourceAndActions(Resource, String...)`、`withRequestId(String)`、`withAuxData(AuxData)` 和 `withIncludeMeta()`。读结果用 `find(String resourceID)`;当一批里混了不同的策略版本或 scope 时用 `find(String, Predicate<…Resource>)`;或者用 `results()` 拿流。

## principal 和 resource

```java
Principal.newInstance(String id, String... roles)
    .withPolicyVersion(String).withRoles(String...)
    .withAttribute(String, AttributeValue).withAttributes(Map<String, AttributeValue>)
    .withScope(String)

Resource.newInstance(String kind, String id)   // 或 newInstance(kind) — id 默认为 "_NEW_"
    .withPolicyVersion(String)
    .withAttribute(String, AttributeValue).withAttributes(Map<String, AttributeValue>)
    .withScope(String)
```

属性值来自 `AttributeValue` 的工厂方法,通常静态导入:`stringValue`、`doubleValue`、`boolValue`、`listValue`、`mapValue`、`nullValue`。

带默认 id `"_NEW_"` 的 `Resource.newInstance(kind)` 用于“创建之前”式的检查,那时还不存在实例。其他任何地方都要传真实的 id。

## 查询计划

```java
PlanResourcesResult result = client.plan(
    Principal.newInstance("maggie", "manager"),
    Resource.newInstance("leave_request"),
    List.of("approve"));

if (result.isAlwaysAllowed()) {
    return findAll();
} else if (result.isAlwaysDenied()) {
    return List.of();
} else {
    return executeQuery(result.getCondition().get());
}
```

`plan(Principal, Resource, Iterable<String>)` 需要 Cerbos PDP 0.44.0 或更高版本。接收单个 `String` 的重载已废弃但仍然可用,README 示例里还在用它。

**`getCondition()` 永远不会返回 `Optional.empty()`** —— 在无条件的 plan 上,它给回的是 protobuf 的默认实例。按 `isAlwaysAllowed()` / `isAlwaysDenied()` / `isConditional()` 分支,不要按 `Optional` 分支。

通过 `Engine.PlanResourcesFilter.Expression.Operand` 遍历 AST:`getExpression()` 给出 `getOperator()` 和 `getOperands(i)`,每个 operand 是 `value`、`expression` 或 `variable` 三者的 `oneof`。见 [query-plan.md](query-plan.md)。

Maven Central 上没有发布 Java 查询计划适配器。把 plan 变成 `Specification` 的 Spring Data JPA 适配器,以及 Elasticsearch 适配器,都在 [`cerbos/query-plan-adapters`](https://github.com/cerbos/query-plan-adapters) 里,但尚未发布 —— 要 vendor 就心里有数地 vendor,或者自己遍历 AST。

## JWT 辅助数据

```java
client.with(AuxData.withJWT(token))
      .check(principal, resource, "view");

client.with(AuxData.withJWTs(Map.of(
        "app_token", AuxData.JWT.from(tokenA),
        "gateway_token", AuxData.JWT.from(tokenB))))
      .check(principal, resource, "view");
```

`with(AuxData)` 返回一个新的客户端包装器,而不是修改共享的那个,所以每请求调用它是安全的。`AuxData.withJWT(token, keySetId)` 会指定 keyset,当 PDP 配了多于一个 keyset 时这是必填的。批量构建器通过 `batch(principal, auxData)` 或 `withAuxData(...)` 接收同一个对象。语义见 [api-shapes.md](api-shapes.md)。

## 每请求上下文

- `withHeaders(Map<String, String>)` / `withHeaders(Metadata)` —— 透传 trace 或租户 header。
- `withRequestAnnotations(Map<String, AttributeValue>)` —— 与决策一起记录在 PDP 审计日志里的值。传 `null` 表示清空。

两者都返回新的客户端包装器。

## 错误

每次 RPC 失败都会抛 `dev.cerbos.sdk.CerbosException`,里面包着底层的 `StatusRuntimeException`。在能把它映射成 5xx 的地方捕获它;不可达或已超时的 PDP 是宕机,不是拒绝,绝不能落到“允许”上。
