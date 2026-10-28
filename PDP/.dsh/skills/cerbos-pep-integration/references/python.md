# Python PEP

权威来源:[`cerbos/cerbos-sdk-python`](https://github.com/cerbos/cerbos-sdk-python)。在 PyPI 上发布的包名是 `cerbos`,需要 Python 3.10+。

对照 `cerbos` 0.16.0 和 `cerbos-sqlalchemy` 0.4.0 验证。适配器要求 `cerbos>=0.10.4`,文档覆盖 SQLAlchemy 1.4 和 2.0;2.1 不在这个列表里,所以使用时要固定为 `sqlalchemy<2.1`。

## 安装

```bash
pip install cerbos
```

`pip install "cerbos[testcontainers]"` 会额外装上在测试中启动真实 PDP 的辅助工具。

## 两个客户端 —— 选 gRPC

| 导入 | 传输方式 | 状态 |
|---|---|---|
| `from cerbos.sdk.grpc.client import CerbosClient, AsyncCerbosClient` | gRPC,端口 3593 | 用这个。SDK v0.8.0 起提供。 |
| `from cerbos.sdk.client import CerbosClient, AsyncCerbosClient` | HTTP,端口 3592 | 仅为向后兼容保留。 |

两者方法名相同,但请求类型不同,所以不能直接互换。新代码用 gRPC 客户端。

## 连接

```python
from cerbos.sdk.grpc.client import CerbosClient

with CerbosClient("localhost:3593", tls_verify=False) as c:
    ...
```

```python
from cerbos.sdk.grpc.client import AsyncCerbosClient

async with AsyncCerbosClient("localhost:3593", tls_verify=False) as c:
    ...
```

```python
CerbosClient(host, tls_verify=False, playground_instance="", timeout_secs=None,
             request_retries=0, wait_for_ready=False, channel_options=None)
```

`tls_verify` 默认为 `False` —— 与大多数 Cerbos SDK 正好相反,所以生产环境的客户端必须显式设置。它可以是 `True`(操作系统信任库,或 `SSL_CERT_FILE` 指向的文件),也可以是证书的路径。Unix socket 写法:`CerbosClient("unix:/var/cerbos.sock", tls_verify=False)`。

客户端是一个持有 channel 的上下文管理器。在 Web 应用里,启动时打开一次再注入,而不是每个请求都新建一个。

### 超时与失败

默认没有超时(`timeout_secs=None`),所以一台接受了连接却随后卡住的 PDP 会让请求无限期阻塞。一定要设置。在 0.16.0 中,`timeout_secs`、`request_retries` 和 `wait_for_ready` 会被静默忽略:SDK 的 gRPC service config 把服务命名为 `svc.CerbosService`,永远匹配不上真正的 `cerbos.svc.v1.CerbosService`。改为通过 `channel_options` 传一份可用的 service config,它会覆盖 SDK 自带的那份:

```python
import json

SERVICE_CONFIG = json.dumps({"methodConfig": [{
    "name": [{"service": "cerbos.svc.v1.CerbosService"}],
    "timeout": "0.5s",
}]})

client = CerbosClient("cerbos:3593", tls_verify=True,
                      channel_options={"grpc.service_config": SERVICE_CONFIG})
```

请求路径上不要开 `waitForReady`:开启后,PDP 宕机期间发起的调用会一直排队,直到 PDP 恢复或超时,而不是快速失败。

传输失败会抛出 `grpc.RpcError`(PDP 宕机时是 `UNAVAILABLE`,超过超时是 `DEADLINE_EXCEEDED`)。在检查处捕获它并失败即拒绝 —— 返回 503,绝不能落到“允许”上:

```python
import grpc

try:
    allowed = client.is_allowed("view", principal, resource)
except grpc.RpcError:
    log.exception("cerbos check failed")
    raise ServiceUnavailable()
```

## 构造请求

gRPC 客户端直接接收 protobuf 消息:

```python
from cerbos.engine.v1 import engine_pb2
from google.protobuf.struct_pb2 import Value

principal = engine_pb2.Principal(
    id="john",
    roles={"employee"},
    attr={"department": Value(string_value="marketing")},
)

resource = engine_pb2.Resource(
    id="XX125",
    kind="leave_request",
    attr={"owner": Value(string_value="john")},
)
```

属性值是 `google.protobuf.Value`,而不是裸的 Python 对象。用一个辅助函数统一转换 dict 并到处复用;在每个调用点手写 `Value(string_value=...)` 正是这个 SDK 既啰嗦又容易写错的地方:

```python
from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Value

def to_attr(d: dict) -> dict[str, Value]:
    return {k: ParseDict(v, Value()) for k, v in d.items()}

resource = engine_pb2.Resource(id=str(doc.id), kind="document", attr=to_attr({"owner": doc.owner_id, "tags": doc.tags}))
```

`ParseDict` 能处理嵌套 dict、list、`None` 和布尔值;数字会以 double 到达,和走 JSON 时一样。

查询计划用的 resource 是另一种消息:`engine_pb2.PlanResourcesInput.Resource(kind="leave_request")` —— 没有 `id`。

旧的 HTTP 客户端改用 `cerbos.sdk.model` 里的模型类 `Principal`、`Resource` 和 `ResourceDesc`,它们接受普通的 Python 值。

## 检查

```python
if c.is_allowed("view", principal, resource):
    ...

response = c.check_resources(principal, [
    request_pb2.CheckResourcesRequest.ResourceEntry(actions=["view", "edit"], resource=resource),
])
```

- `is_allowed(action, principal, resource, request_id=None, aux_data=None) -> bool`
- `check_resources(principal, resources, request_id=None, aux_data=None)`
- `plan_resources(action, principal, resource, request_id=None, aux_data=None)` —— `action` 接受 `str` 或 `list[str]`
- `server_info()`
- `with_principal(principal, aux_data=None)` 返回一个 `PrincipalContext`,这样针对同一个用户的连续检查就不必反复传 principal

注意参数顺序:**action 在前**,然后是 principal,再是 resource。没有 `check_resource`;`is_allowed` 底层就是一个条目的 `check_resources`,所以要对同一个 resource 检查多个动作时,应该用 `check_resources` 传一个条目加多个动作,而不是循环调用 `is_allowed`。

`AsyncCerbosClient` 方法名相同,只是需要 await。

## 查询计划

```python
plan = c.plan_resources(action="view", principal=principal, resource=plan_resource)
```

读 condition 之前先按 plan 的 kind 分支 —— 见 [query-plan.md](query-plan.md)。

### SQLAlchemy 适配器

```bash
pip install cerbos-sqlalchemy
```

```python
from cerbos_sqlalchemy import get_query

query = get_query(plan, Contact, {
    "request.resource.attr.owner_id": User.id,
    "request.resource.attr.is_active": Contact.is_active,
}, [(User, Contact.owner_id == User.id)])
```

`get_query(plan, table_or_entity, attr_map, table_mapping=None, operator_override_fns=None)` 返回一个 SQLAlchemy `Select`,你可以继续用 `.where(...)` 和 `.with_only_columns(...)` 往上拼。它自己按 plan 的 kind 分支 —— `ALWAYS_DENIED` 得到 `select(t).where(False)`,`ALWAYS_ALLOWED` 得到普通的 `select(t)` —— 而且这个包只导出 `get_query`,没有 `PlanKind` 可导入。第四个参数一旦 `attr_map` 跨了不止一张表就是必填的。逻辑、比较、算术、`in`、`size`、字符串辅助函数、时间戳和层级函数开箱即用;集合类算子需要一条 `operator_override_fns` 条目,`matches()` 以及其他不支持的形状会直接抛错,而不是悄悄放宽查询。`operator_override_fns` 还能把某个算子换成特定方言的版本(`{"in": lambda c, v: c == any_(v)}`)。详见 [SQLAlchemy 适配器](https://docs.cerbos.dev/cerbos/latest/recipes/query-plan-adapters/sqlalchemy?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-recipes-query-plan-adapters-sqlalchemy)。

## JWT 辅助数据

每次调用都接受 `aux_data`(一个 `request_pb2.AuxData`),`with_principal(principal, aux_data=...)` 可以为一系列检查把它固定住。语义见 [api-shapes.md](api-shapes.md)。

## 框架接入

Django、FastAPI 和 Flask 都没有现成的 Cerbos 中间件,自己接:一个依赖或辅助函数把已认证的用户映射成 `Principal`,另一个负责加载 resource,然后在 handler 里显式做检查。[FastAPI + SQLAlchemy 实战演练](https://docs.cerbos.dev/cerbos/latest/recipes/query-plan-adapters/sqlalchemy?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-recipes-query-plan-adapters-sqlalchemy)完整展示了这种依赖注入的写法。
