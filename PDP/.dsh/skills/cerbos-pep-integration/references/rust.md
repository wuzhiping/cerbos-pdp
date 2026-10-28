# Rust PEP

权威来源:[`cerbos/cerbos-sdk-rust`](https://github.com/cerbos/cerbos-sdk-rust)。crate `cerbos`,基于 tonic 的 gRPC。

## 安装

```bash
cargo add cerbos
```

可选 feature:`admin`、`hub`、`testcontainers`、`serde`。

## 连接

```rust
use cerbos::sdk::{CerbosAsyncClient, CerbosClientOptions, CerbosEndpoint, Result};

let opt = CerbosClientOptions::new(CerbosEndpoint::HostPort("localhost", 3593));
let mut client = CerbosAsyncClient::new(opt).await?;
```

`CerbosSyncClient::new(opt)` 是等价的阻塞版本。`CerbosEndpoint` 要么是 `HostPort(host, port)`,要么在 Unix 上是 `UnixDomainSocket(path)`。

**默认开启 TLS** —— `CerbosClientOptions::new` 会装上 `ClientTlsConfig`,channel 的 scheme 随之变成 `https`。README 的示例省略了 `.with_plaintext()`,所以直接照抄去连本地明文 PDP 是连不上的。用于本地开发:

```rust
let opt = CerbosClientOptions::new(CerbosEndpoint::HostPort("localhost", 3593)).with_plaintext();
```

其他选项:`with_tls_domain_name`、`with_tls_ca_cert_pem`、`with_timeout(Duration)`(默认 2 秒)、`with_request_id_gen(fn)`(默认 UUID v4 —— 换成你的 trace ID)、`with_user_agent`、`with_playground_instance`,以及开启 `admin` feature 后的 `with_admin_credentials`。

客户端方法需要 `&mut self`,所以要么用 `Mutex` 包起来共享,要么为每个任务克隆底层的 channel。

## 检查

```rust
use cerbos::sdk::attr::attr;
use cerbos::sdk::model::{Principal, Resource};

let principal = Principal::new("alice", ["employee"])
    .with_attributes([attr("department", "marketing"), attr("geography", "GB")]);

let resource = Resource::new("XX125", "leave_request")
    .with_attributes([attr("owner", "alice"), attr("approved", true)]);

let allowed = client.is_allowed("view:public", principal, resource, None).await?;
```

**`Resource::new(id, kind)` 是 id 在前** —— 和 Go、PHP、.NET SDK 正好相反。写反会造出一个 kind 为 `"XX125"` 的 resource,它匹配不到任何策略,结果是一律拒绝。`Principal::new(id, roles)` 如预期是 id 在前。

方法,两个客户端上相同,除非另有说明:

```rust
is_allowed<S>(&mut self, action: S, principal: Principal, resource: Resource, aux_data: Option<AuxData>) -> Result<bool>
check_resources(&mut self, principal: Principal, resources: ResourceList, aux_data: Option<AuxData>) -> Result<CheckResourcesResponse>
plan_resources<S>(&mut self, action: S, principal: Principal, resource: ResourceKind, aux_data: Option<AuxData>) -> Result<PlanResourcesResponse>
plan_resources_for_actions<A, S>(&mut self, actions: A, principal: Principal, resource: ResourceKind, aux_data: Option<AuxData>)  // 仅异步客户端
```

没有单个 resource 多动作的方法:构造一个 `ResourceList`。

```rust
use cerbos::sdk::model::ResourceList;

let resources = ResourceList::new()
    .add(Resource::new("XX125", "leave_request"), ["view:public", "defer"])
    .add(Resource::new("XX225", "leave_request"), ["approve"]);

let resp = client.check_resources(principal, resources, None).await?;
let allowed = resp.find("XX125").map(|r| r.is_allowed("view:public")).unwrap_or(false);
```

`CheckResourcesResponse` 还有 `find_with_predicates(...)` 和 `iter()`;`ResourceResult` 有 `is_allowed(action)`、`output(key)` 和 `output_entry(key)`。

构建器:`Principal` 提供 `add_role`、`with_policy_version`、`with_scope`、`with_attributes`、`add_attr`。`ResourceKind::new(kind)` 是 plan 一侧的 resource。属性值来自 `cerbos::sdk::attr::attr(key, value)`。

## 查询计划

```rust
use cerbos::sdk::model::ResourceKind;

let plan = client
    .plan_resources("view", principal, ResourceKind::new("leave_request"), None)
    .await?;

let filter = plan.filter();
```

`plan_resources_for_actions`(多动作,PDP 0.44.0+)只存在于 `CerbosAsyncClient` 上 —— 同步客户端只有 `plan_resources`。

没有 Rust 查询计划适配器。自己遍历 filter AST —— 节点形状见 [api-shapes.md](api-shapes.md),规则见 [query-plan.md](query-plan.md)。读 condition 之前先按 filter 的 kind 分支。

## JWT 辅助数据

每次调用的最后一个位置参数都是 `aux_data: Option<AuxData>` —— 没有 token 时传 `None`。

```rust
use cerbos::sdk::model::AuxData;

let aux = AuxData::new().with_jwt(token, Some("ks1"));
client.is_allowed("view", principal, resource, Some(aux)).await?;
```

`with_jwt` 和 `with_jwts` 互相清除;两种形式在线路上互斥。语义见 [api-shapes.md](api-shapes.md)。

## 错误

每个方法都返回 `Result<_>`。传输错误不是拒绝:用 `?` 把它往上传播,在边界处映射成 5xx,而不是在调用点写 `unwrap_or(false)` —— 后者会把一次 PDP 宕机伪装成一大片拒绝。
