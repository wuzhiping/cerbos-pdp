# 敏感字段的 mask

脱敏在 PDP 处应用，在记录写入本地缓冲区之前就已经完成，因此被脱敏的值既不会落盘，也不会被传到 Cerbos Hub。Cerbos Hub 会保留它收到的一切，所以这里是唯一能把数据留在边界之内的地方。

`mask` 是 `hub` audit 后端的一项配置。`local`、`file` 和 `kafka` 后端都没有对应设置；对这些后端，要么用 `includeMetadataKeys` / `excludeMetadataKeys`（见下文）在源头就把数据挡在外面，要么根本别把它放进请求。

要写出一个 **masked local file**，就运行 `hub` 后端并把它管道到 `file`——见下文的 *A masked local file*。

## 四个分区

```yaml
audit:
  enabled: true
  backend: hub
  hub:
    storagePath: /var/cerbos/audit
    mask:
      metadata:
        - "['x-api-key']"
      peer:
        - address
        - forwardedFor
      checkResources:
        - inputs[*].principal.attr.ssn
        - inputs[*].auxData
      planResources:
        - input.principal.attr.ssn
```

| 分区 | 路径的根位置 | 适用范围 |
|---|---|---|
| `metadata` | 记录中采集到的请求元数据 map | access **和** decision 记录 |
| `peer` | 记录中的 `peer` message | access **和** decision 记录 |
| `checkResources` | `decisionLogEntry.checkResources` | 来自 `CheckResources` 调用的 decision 记录 |
| `planResources` | `decisionLogEntry.planResources` | 来自 `PlanResources` 调用的 decision 记录 |

某个分区里只有 `'*'` 这一项时，它会被整体清空——`peer: ['*']` 会从每个记录中移除 peer 信息。

## 路径语法

JSONPath 的一个受支持子集：

| 形式 | 示例 |
|---|---|
| 点号访问 | `input.principal.attr.ssn` |
| 方括号访问 | `['input']['principal']['attr']['ssn']` |
| 混用 | `inputs[*]['principal']['attr']['ssn']` |
| 列表下标 | `inputs[0].principal.id` |
| 列表通配符 | `inputs[*].principal.attr.ssn` |

含 `-` 或其他非标识符字符的 key 必须使用方括号形式：`['x-api-key']`。点号形式 `x-api-key` 会让 PDP 在启动时报错停止：`unexpected character for accessor: -`。

嵌套可以穿过 map 继续往下，因此 `inputs[*].principal.attr.profile.dateOfBirth` 能命中属性对象内部的 key。

**指代 protobuf 字段的路径段必须使用 lowerCamelCase 的 JSON 名称**：`forwardedFor`、`auxData`、`filterDebug`、`requestId`、`checkResources`。指代 *map key* 的路径段——`metadata`、`principal.attr`、`resource.attr` 或 `auxData.jwt` 以下的任何内容——按字面匹配，与 key 在数据中的写法完全一致。

这一点之所以重要，是因为**匹配不到任何内容的路径不算错误**。它会在启动时被接受，然后悄无声息地什么也没脱敏，于是拼写错误或者 snake_case 的字段名看起来像一个正常工作的脱敏，数据照样被发出去。Cerbos Hub 文档中发布的 `peer` 示例用了 `forwarded_for`，它匹配不到任何字段；可用的写法是 `forwardedFor`。在信任每一条脱敏之前，先拿真实数据验证它。

是删除，不是遮盖：被脱敏的字段会从记录中移除，而不是替换成占位符；移除 map 中最后一个剩下的 key，也会把整个 map 移除。

## 实例

| 不让它进入审计轨迹 | Mask |
|---|---|
| `Authorization` 头 | 无需处理——它从来不会被采集。见下文 *请求元数据*。 |
| 另一个带密钥的请求头，例如 `x-api-key` | `metadata: ["['x-api-key']"]`，更好的做法是用 `excludeMetadataKeys`，这样对所有后端都生效 |
| 调用方的 IP 地址 | `peer: [address, forwardedFor]` |
| 一个含 PII 的 principal 属性 | `checkResources: ['inputs[*].principal.attr.ssn']` 和 `planResources: ['input.principal.attr.ssn']`——两个都要，因为两种调用类型分属不同分区 |
| 属性内部嵌套的 PII | `inputs[*].principal.attr.profile.dateOfBirth` |
| JWT 携带的全部内容 | `checkResources: ['inputs[*].auxData']` 和 `planResources: ['input.auxData']` |
| JWT 里的单个 claim | `checkResources: ['inputs[*].auxData.jwt.email']` 和 `planResources: ['input.auxData.jwt.email']` |
| resource 内容——文档正文、金额 | `checkResources: ['inputs[*].resource.attr.body']` |
| 策略 `output` 块产生的值 | `checkResources: ['outputs[*].outputs']` |

原始 token 从来不会被记录；记录里只有 `auxData.jwt` 下的已解码 claim。因此「脱敏这个 JWT」实际指的是脱敏那些 claim。

凡是只提到 `checkResources` 的行，当 plan 调用携带相同数据时，都需要在 `planResources` 下补上对应的 `input.*` 版本。

单独脱敏 `outputs` 等于脱敏整个 `CheckOutput` 列表：每个动作的效果、有效的派生角色、校验错误，以及规则输出。脱敏掉它之后，记录就不再记录哪些动作被允许或拒绝了。如果目标只是策略产生的值，就如上所述再往下取一层。

同样的提醒也适用于 `inputs[*].principal.id` 和 `inputs[*].resource.id`：它们可以脱敏，但这样记录就无从归属决策了，Hub 的 principal 排名和过滤器也会跟着失去这条记录。

## 请求元数据

元数据采集发生在脱敏运行之前，它决定了哪些数据存在、可供脱敏。这两项都是顶层 `audit` 配置，因此对所有后端都生效。

| `includeMetadataKeys` | `excludeMetadataKeys` | 采集到的内容 |
|---|---|---|
| 空 | 空 | 什么都不采集 |
| 已设置 | 空 | 只采集列出的 key |
| 空 | 已设置 | 除了列出的 key 之外全部采集 |
| 已设置 | 已设置 | include 列表里的内容，减去同时也在 exclude 列表里的 key |

两者默认为空，因此在你主动要求之前，**请求元数据完全不会被记录**。无论列表怎么写，`authorization` 和 `grpc-trace-bin` 都会被无条件排除。HTTP 头以 gRPC metadata 的形式到达，所以这里的 key 就是头名称。

要整体去掉某个请求头，优先用这两项配置；`metadata` 脱敏留给 Hub 特有的额外需求。

## 查找与验证路径

查路径的方法是看一条真实记录。在开发环境中，用 `local` 后端运行 PDP，再读回一条：

```bash
curl -s -u "cerbos:cerbosAdmin" \
  'http://<pdp>:3592/admin/auditlog/list/KIND_DECISION?tail=1'
```

返回的 JSON 就是脱敏路径所针对的结构，只是不带 `checkResources` 或 `planResources` 提供的那段分区前缀。

验证脱敏的办法是观察 `hub` 后端实际输出了什么。脱敏在写入次级输出之前应用，因此管道到 stdout 的内容与 Hub 将收到的记录完全一致：

```yaml
audit:
  enabled: true
  backend: hub
  hub:
    storagePath: /var/cerbos/audit
    mask:
      checkResources:
        - inputs[*].principal.attr.ssn
    pipeOutput:
      enabled: true
      backend: file
  file:
    path: stdout
```

发一个有代表性的请求，然后读那一行。这个顺序同时也是一条警告：`pipeOutput` 不是完整保真的本地副本——由它喂给 SIEM 的也是被脱敏过的记录，因此下游系统需要的任何内容都必须在脱敏之后依然存在。`hub` 后端不能管道到自身。

`file` 是 `audit` 下 `hub` 的同级项，不是嵌套在它里面；写成 `audit.hub.file` 会让 PDP 在启动时报错停止：`field file not found in type hub.Conf`。

## A masked local file

同样的布局是把 masked 记录写进本地文件的唯一办法：`backend: hub`，脱敏放在 `audit.hub.mask` 下，`pipeOutput` 指向 `file`，并把 `audit.file.path` 设成该文件而不是 stdout。

`hub` 后端需要 `hub.credentials`。没有它，PDP 会拒绝启动。填上占位值之后，它能启动、能提供决策、也能写出管道文件，只会记录上传失败的警告；对一台永远不会连上 Hub 的 PDP 来说，这样是可行的。

## 体积保护

大于约 4 MiB 的记录会被自动剥离 `principal.attr` 和 `resource.attr`（plan 还会多剥离 `output.filterDebug`），并在记录上标记 `oversized`。这是传输层面的保护，不是隐私控制——请有意识地使用脱敏，而不是依赖它。

## 没有 mask 的内容

`callId`、`timestamp`、`method`、`statusCode`、`policySource`、有效策略的 `auditTrail`，以及 `requestContext.annotations` 都没有对应的脱敏分区。尤其是 annotations，会按调用方发送的原样记录下来，所以要把这个字段当成 workspace 内公开可见。

## What Synapse adds

Synapse 在 PDP 求值之前丰富请求，因此 decision 记录记录的是实际求值的内容，而不是客户端发来的内容。proxy extension 从内部目录取到的属性，会和客户端自己的属性一起出现在记录的 inputs 中。

Synapse 还会为每个请求标注 `requestContext`，这些 annotations 会一路带到 Hub 摄取的每一个记录：

| Annotation | 值 |
|---|---|
| `cerbos.dev/synapse/version` | 正在运行的 Synapse 版本。始终添加。 |
| `cerbos.dev/synapse/extensions` | 处理该请求的 proxy extensions，按运行顺序排列。配置了任意 extension 时添加。 |
| 你自己的 key | 来自顶层 `audit.instanceAnnotations` 块的字符串、数字或布尔值——环境、区域、集群。 |

使用内嵌 PDP 时，audit 块嵌套在 `pdp.inProcess` 之下：

```yaml
pdp:
  inProcess:
    audit:
      enabled: true
      backend: hub
      hub:
        storagePath: /var/lib/synapse/audit
```

如果改为代理已有的 PDP 集群（`pdp.external`），Hub 凭据和 audit 块都放在上游 PDP 上；顶层的 `audit.instanceAnnotations` 仍然生效，因为 Synapse 会在转发之前加上它们。

权威参考：[Cerbos Hub audit log collection](https://docs.cerbos.dev/cerbos-hub/audit-log-collection?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_hub-audit-log-collection) 以及 [audit configuration block（audit 配置块）](https://docs.cerbos.dev/cerbos/latest/configuration/audit?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_pdp-configuration-audit)。
