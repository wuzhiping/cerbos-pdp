# Ruby PEP

权威来源:[`cerbos/cerbos-sdk-ruby`](https://github.com/cerbos/cerbos-sdk-ruby)。gem `cerbos`,gRPC。需要 Ruby 3.3+ 和 Cerbos PDP 0.16+。

## 安装

```console
$ bundle add cerbos
```

```ruby
require "cerbos"
```

## 连接

```ruby
client = Cerbos::Client.new("localhost:3593", tls: false)
```

```ruby
Cerbos::Client.new(target, tls:, grpc_channel_args: {}, grpc_metadata: {},
                   on_validation_error: :return, playground_instance: nil, timeout: nil)
```

`tls:` 是没有默认值的必填关键字参数 —— SDK 要求你明确表态。明文传 `false`;也可以传 `Cerbos::TLS.new(root_certificates_pem: nil)` 或 `Cerbos::MutualTLS.new(client_certificate_pem:, client_key_pem:, **tls_settings)`。`target` 接受 `"host"`、`"host:port"` 或 `"unix:/var/run/cerbos.grpc.sock"`。

`on_validation_error:` 接受 `:return`(默认值 —— 从响应上读错误)、`:raise`,或者一个可调用对象。

**会 fork 的服务器**(集群模式下的 Puma、Unicorn、Passenger)要当心:底层的 `grpc` gem 要求版本 1.57.0+、`GRPC_ENABLE_FORK_SUPPORT=1`,并且要在 fork 前后挂上 `GRPC.prefork` / `GRPC.postfork_parent` / `GRPC.postfork_child` 钩子。支持仅限于 Linux,而且是实验性的。更简单的替代方案是 fork 之后、在每个 worker 里懒创建客户端。

## 检查

```ruby
decision = client.check_resource(
  principal: { id: "user@example.com", roles: ["USER"] },
  resource: { kind: "document", id: "1", attr: { owner: "author@example.com" } },
  actions: ["view", "edit"]
)

decision.allow?("view") # => true
```

```ruby
decision = client.check_resources(
  principal: { id: "user@example.com", roles: ["USER"] },
  resources: [
    { resource: { kind: "document", id: "1" }, actions: ["view", "edit"] },
    { resource: { kind: "image", id: "1" }, actions: ["delete"] }
  ]
)

decision.allow?(resource: { kind: "document", id: "1" }, action: "view")
```

```ruby
client.allow?(principal:, resource:, action: "view") # => Boolean
```

三个方法,全是关键字参数:`allow?` 用于单个动作,`check_resource` 用于同一个 resource 上的多个动作,`check_resources` 用于批量。注意选择器的不对称 —— 单个 resource 的结果上,`allow?` 接受裸的动作字符串;批量结果上,它接受一个 hash。

principal 和 resource 可以传普通的 Hash,也可以传显式的 `Cerbos::Input::Principal`、`Input::Resource`、`Input::ResourceCheck` 和 `Input::ResourceQuery` 对象,后者会让构造函数替你做校验。

每次调用还可以带 `aux_data:`、`include_metadata:`、`request_id:`、`request_context:` 和 `grpc_metadata:`。

客户端上还有:`check_health(service: "cerbos.svc.v1.CerbosService")` 和 `server_info`。

## 查询计划

```ruby
plan = client.plan_resources(
  principal: { id: "user@example.com", roles: ["USER"] },
  resource: { kind: "document" },
  actions: ["view"]
)

if plan.conditional?
  apply(plan.condition)
end
```

`actions:` 需要运行 Cerbos v0.44+ 的 PDP。单数的 `action:` 已废弃。读 `condition` 之前先按 kind 分支 —— `conditional?` 及其同类 —— 见 [query-plan.md](query-plan.md)。

没有发布到 RubyGems 的 Ruby 查询计划适配器。[`cerbos/query-plan-adapters`](https://github.com/cerbos/query-plan-adapters) 里有一个 ActiveRecord 适配器,但只是一个进行中的原型,还没上 RubyGems,所以把它当作可以 vendor 下来再自行完成的起点,而不是一个现成的依赖。

## JWT 辅助数据

```ruby
client.check_resource(
  principal:, resource:, actions: ["view"],
  aux_data: Cerbos::Input::AuxData.new(jwt: Cerbos::Input::JWT.new(token: raw, key_set_id: "ks1"))
)
```

`jwt` 和 `jwts` 互斥;只有当 PDP 只配置了一个 JWKS 时,才可以省略 `key_set_id`。语义见 [api-shapes.md](api-shapes.md)。

## Rails

SDK 里没有 Rails engine,也没有 `before_action` 辅助方法。自己接:一个方法把 `current_user` 映射成 principal hash,controller action 里显式调用 `check_resource`,列表 action 用 `plan_resources`。把 principal 的映射集中在一处,这样新增一个属性就能同时到达所有检查。
