# PHP PEP

权威来源:[`cerbos/cerbos-sdk-php`](https://github.com/cerbos/cerbos-sdk-php)。gRPC,请求对象风格。

README 里的 PDP 示例有已知缺陷 —— 构建器链后面缺分号、没有 `use` 语句,还有一段把裸字符串传到了需要 `AttributeValue` 的位置。用下面的写法,不要照抄 README。

## 安装

```bash
composer require cerbos/cerbos-sdk-php
```

PSR-4 把 `Cerbos\Sdk\` 映射到 `src/Sdk`,所以命名空间是 `Cerbos\Sdk\CerbosClient`、`Cerbos\Sdk\Builder\{CerbosClientBuilder, CheckResourcesRequest, PlanResourcesRequest, Principal, Resource, ResourceEntry, AttributeValue, AuxData}` 和 `Cerbos\Sdk\Utility\RequestId`。

## 连接

```php
use Cerbos\Sdk\Builder\CerbosClientBuilder;

$client = CerbosClientBuilder::newInstance("localhost:3593")
    ->withPlaintext(true)
    ->build();
```

这里 `withPlaintext()` 需要显式传一个布尔值。默认开启 TLS。证书相关的 setter 接受 PEM 的**内容**,不是路径:`withCaCertificate(string)`、`withTlsCertificate(string)`、`withTlsKey(string)`。另外还有 `withMetadata(array $headers)` 和 `withPlayground(string $playgroundInstanceId)` —— 明文加 playground 会抛异常。

## 检查

```php
use Cerbos\Sdk\Builder\{CheckResourcesRequest, Principal, ResourceEntry, AttributeValue};
use Cerbos\Sdk\Utility\RequestId;

$request = CheckResourcesRequest::newInstance()
    ->withRequestId(RequestId::generate())
    ->withPrincipal(
        Principal::newInstance("john")
            ->withRole("employee")
            ->withAttribute("department", AttributeValue::stringValue("marketing"))
    )
    ->withResourceEntry(
        ResourceEntry::newInstance("leave_request", "xx125")
            ->withActions(["view:public", "approve"])
            ->withAttribute("owner", AttributeValue::stringValue("john"))
    );

$response = $client->checkResources($request);

if ($response->find("xx125")->isAllowed("view:public")) {
    // ...
}
```

客户端接口只有两个调用:

```php
public function checkResources(CheckResourcesRequest $request, $headers = null): CheckResourcesResponse
public function planResources(PlanResourcesRequest $request, $headers = null): PlanResourcesResponse
```

**客户端上没有 `isAllowed`,也没有单个 resource 的方法。**每次检查都走 `checkResources`,然后 `CheckResourcesResponse::find(string $id)` 给你一个 `ResultEntry`,`ResultEntry::isAllowed(string $action)` 给出决策。

属性值永远是 `AttributeValue` 对象 —— `AttributeValue::stringValue(...)` 以及它的同类 —— 不要传裸的 PHP 标量。

构建器:`CheckResourcesRequest` 还提供 `withResourceEntries(array)`、`withAuxData`、`withIncludeMeta`、`withAllowPartialRequests`。`Principal` 提供 `withRoles(array)`、`withPolicyVersion`、`withAttributes(array)`、`withScope`。

## 查询计划

```php
use Cerbos\Sdk\Builder\{PlanResourcesRequest, Resource};

$request = PlanResourcesRequest::newInstance()
    ->withRequestId(RequestId::generate())
    ->withActions(["approve"])
    ->withPrincipal($principal)
    ->withResource(Resource::newInstance("leave_request", "")->withPolicyVersion("20210210"));

$response = $client->planResources($request);

if ($response->isAlwaysAllowed()) {
    // 无过滤
} elseif ($response->isAlwaysDenied()) {
    // 空结果
} else {
    applyFilter($response->getFilter());
}
```

`withActions(array)` 需要 Cerbos PDP v0.44.0 或更高版本;`withAction(string)` 是旧的单动作形式。响应还带有 `getAction()`、`getActions()`、`hasValidationErrors()` 和 `getValidationErrors()`。

没有 PHP 查询计划适配器。自己遍历 filter AST —— 节点形状见 [api-shapes.md](api-shapes.md),安全做法见 [query-plan.md](query-plan.md)。

## JWT 辅助数据

```php
use Cerbos\Sdk\Builder\AuxData;

$request->withAuxData(AuxData::withJwt($token, "ks1"));
$request->withAuxData(AuxData::withJwts([...]));   // Cerbos\Sdk\Builder\AuxData\JWT::newInstance($token, $keySetId)
```

两个请求构建器上都有。语义见 [api-shapes.md](api-shapes.md)。

## Laravel

```bash
composer require cerbos/cerbos-sdk-laravel
```

[`cerbos/cerbos-sdk-laravel`](https://github.com/cerbos/cerbos-sdk-laravel) 会自动发现 `CerbosServiceProvider`,并把 `Cerbos\Sdk\CerbosClient` 绑定成单例 —— 于是在 controller 或 gate 里对 `CerbosClient` 做类型提示,就能用上面那套 API。`php artisan vendor:publish` 会写出 `config/cerbos.php`:

```php
'host'        => env('CERBOS_HOST', '127.0.0.1'),
'port'        => env('CERBOS_PORT', '3593'),
'plaintext'   => env('CERBOS_PLAINTEXT', true),
'caCertPath'  => env('CERBOS_CA_CERT_PATH', ''),
'tlsCertPath' => env('CERBOS_TLS_CERT_PATH', ''),
'tlsKeyPath'  => env('CERBOS_TLS_KEY_PATH', ''),
```

这个包会读取那些路径下的证书文件,并把内容交给构建器。注意 `CERBOS_PLAINTEXT` 默认是 `true`,与不依赖框架的裸 SDK 相反 —— 任何 PDP 不是本机 sidecar 的部署,都要把它设成 `false` 并提供证书。

这个包本身不带使用文档。一个解析注入进来的 `CerbosClient` 并返回 `$response->find($id)->isAllowed($action)` 的 Laravel `Gate::define`,就是自然的接入点。
