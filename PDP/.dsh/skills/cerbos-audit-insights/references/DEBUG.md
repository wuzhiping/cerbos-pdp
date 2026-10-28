# 调试看起来不正确的决策

应用放行了不该放行的东西，或拒绝了不该拒绝的东西。按这个顺序往下排查——每一步都排除了它上面的所有可能，多数案例止步于第 2 步或第 4 步。

## 1. 请求到达 PDP 了吗？

「Cerbos 把一切都拒绝了」这句话里，有一半其实是 PEP 从未调用过它，或者调用的是另一个实例。默认拒绝的引擎和完全不可达的引擎，在应用看来毫无区别。

- **打开 access logs**（第 2 步）并发起一次请求。每次调用都有一条 access 记录，说明 PDP 被访问到了；没有记录说明没有。
- **PDP 是活着的**：在 HTTP 端口上访问 `GET /_cerbos/health` 返回 200。
- **端口按协议区分**——`3592` 是 HTTP，`3593` 是 gRPC。gRPC 客户端指向 3592 时的失败，看起来像网络问题。
- **检查客户端实际解析到了什么地址。** 容器里默认的 `localhost` 指向的是容器自身，不是 PDP。在 Kubernetes 中，确认 Service 名称和命名空间。
- **错误不是拒绝。** 传输失败、超时或 TLS 不匹配，必须以 PEP 能处理的错误形式暴露出来，而不是变成 `false`。如果客户端把这些错误吞掉转成拒绝，那么每次故障看起来都像策略 bug——参见 `cerbos-pep-integration` skill。

## 2. 打开日志

**`audit.enabled` 默认为 `false`。** 无内容可读最常见的原因就是这个开关。一旦打开，access log 和 decision log 都会启用——`accessLogsEnabled` 和 `decisionLogsEnabled` 默认为 `true`；生成的配置参考文档把三者都打印成 `false`，那是*示例*值，不是默认值。

到处都能用、最快的办法（容器里只想看着输出时同样适用）：

```yaml
audit:
  enabled: true
  backend: file
  file:
    path: stdout
```

**使用 Cerbos Hub 并不会失去 stdout。** 存储驱动和 audit 后端是彼此独立的配置：策略可以来自一个 Hub 部署，而决策输出到 stdout、文件，或者两者兼有。要既保留 Hub 采集*又*在本地观察，把 Hub 后端管道到第二个后端：

```yaml
storage:
  driver: hub          # 策略来自 Hub
  hub:
    remote:
      deploymentID: "..."
audit:
  enabled: true
  backend: hub         # 决策送到 Hub
  hub:
    storagePath: /var/cerbos/audit
    pipeOutput:
      backend: file    # ……同时也输出到 stdout
      enabled: true
  file:                # hub 的同级项，不是嵌套在里面
    path: stdout
```

脱敏在 `pipeOutput` 之前生效，因此管道出去的副本与送到 Hub 的副本一样，已经被脱敏过。把同样的布局改成真实文件路径，就是得到 masked local file 的办法，因为只有 `hub` 后端会脱敏——参见 [MASKING.md](MASKING.md#a-masked-local-file)。

如果想要交互式查询而不是持续输出，`local` 后端会把记录保存在内嵌存储中保留七天，并使其可查询：

```yaml
audit:
  enabled: true
  backend: local
  local:
    storagePath: /var/cerbos/audit
```

```bash
# 最近十条记录
curl -s -u "cerbos:cerbosAdmin" \
  'http://<pdp>:3592/admin/auditlog/list/KIND_DECISION?tail=10'

# 一个 ISO-8601 时间窗
curl -s -u "cerbos:cerbosAdmin" \
  'http://<pdp>:3592/admin/auditlog/list/KIND_DECISION?between.start=2026-10-27T00:00:00Z&between.end=2026-10-27T23:59:59Z'

# 一次调用，用应用记录下来的 call ID 定位
curl -s -u "cerbos:cerbosAdmin" \
  'http://<pdp>:3592/admin/auditlog/list/KIND_DECISION?lookup=01M5XJG7FGS1MGE9TD60DR79FP'

# 一个相对时间窗
curl -s -u "cerbos:cerbosAdmin" \
  'http://<pdp>:3592/admin/auditlog/list/KIND_DECISION?since=3h'
```

Admin API 是在众多请求中定位单个请求最快的方式，而且无论策略来源是什么都可用。`KIND_ACCESS` 则返回 access 记录。返回 `501` 并带 `Audit log backend does not support querying`，说明这台 PDP 不在 `local` 后端上——参见 skill 里的后端表。

**在 Cerbos Synapse 下**，同一块配置嵌套在 `pdp.inProcess.audit` 之下。顶层的 `audit:` 段会被忽略，只有 `audit.instanceAnnotations` 例外；配置看起来正确却毫无作用，几乎都是这个原因。

## 3. 阅读 decision 条目

decision 记录记录的是 PDP **实际求值时的请求内容**，这正是它的价值：它展示 PEP 真正发送了什么，而不是你以为它发送了什么。

按这个顺序读：

1. **inputs。** 条件读取的每个属性都在吗？调用方从未发送的属性，是意外拒绝最常见的单一原因。
2. **每个动作的效果**，即按动作而非按请求计算——批量请求中部分放行是正常的。
3. **匹配到的那条策略。** 请求带上 `includeMeta: true`，响应就会带上匹配的策略和有效的派生角色，由此可以判断你以为的那条规则是不是实际执行的那条。

## 4. 常见原因，从最常见开始

| 你看到的现象 | 常见原因 |
|---|---|
| 拒绝，而条件看起来正确 | 条件中的某个属性在请求里缺失。条件引用的属性缺失时属于「不满足」，而不是错误，于是规则根本匹配不上，默认拒绝接管结果 |
| 有该角色的用户被拒绝 | 角色字符串不匹配——`admin` 与 `ADMIN`，或者 IdP 用另一个 claim 发出该角色 |
| 策略变更没有生效 | PDP 提供的是旧 bundle。在 Hub 下，把 deployment 的 Decision points 标签页上的 build 与最新的绿色 build 对比；否则检查 PDP 读取的存储 |
| 存在拒绝规则却仍然允许 | 拒绝规则挂在与当前求值不同的角色上。同一角色内拒绝优先于允许，但一个角色上的拒绝不会阻断另一个角色的允许 |
| 规则正确，但 scope 或 version 不对 | 请求的 scope 或策略版本与策略本身不一致。在 decision 记录里核对两者 |
| 间歇出现或只在特定环境出现 | 两个 PDP 用了不同的 bundle，或者某个 PDP 在读取过期的缓存目录 |

**伪装成拒绝的错误。** 默认情况下，求值某个条件时出错会让该规则保持「不满足」，求值继续进行，因此 DENY 规则上一个坏掉的条件会悄无声息地停止拒绝。打开严格求值模式，让这类错误改为拒绝，然后重跑该案例：在严格求值下结果发生变化，说明出错的是条件，而不是策略与你的预期不一致。

## 5. Synapse 在链路中

请求经过 Synapse 时，decision 记录显示的是 proxy extension 运行**之后**的 inputs。如果某个属性缺失，问题在于本该提供它的 extension 到底有没有运行——记录上的 `cerbos.dev/synapse/extensions` 按顺序列出了处理该请求的 extension。记录里有、客户端发送内容里没有的属性，是 extension 加上的；两处都没有的属性，则从未被获取过。

## 脱离应用复现

拿到这个失败的请求后，就可以在不经过应用的情况下重放：把 principal、resource 和动作连同 `includeMeta: true` 发送到 `POST /api/check/resources`，再读取 decision 记录上记录的 `inputs` 和 `outputs`。[Hub playground](https://docs.cerbos.dev/cerbos-hub/playground?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_hub-playground) 会展示每条规则、条件和变量的求值执行轨迹（前提是你有账号）。
