# 阅读已采集的决策

这里讲的全部是 Cerbos Hub 控制台，数据来自启用了 `hub` audit 后端的 PDP。这些页面上的时间都是 UTC。

## Audit logs

workspace 的 **Audit logs** 标签页下有 **Decision logs**、**Access logs** 和 **Exports**。

**Decision logs** 每条记录占一行，包含 timestamp、call ID、请求类型（`CheckResources` 或 `PlanResources`）、principal ID、resource kind、resource ID，以及该动作的决策结果。可以在 **Decision** 视图（紧凑摘要）和 **JSON** 视图（原始记录）之间切换。可按时间范围、PDP ID、策略来源、principal、resource kind、动作或策略决策结果过滤。

点击某一行会打开详情面板：

- **Principal**——ID、角色、有效的派生角色、属性
- **Resource**——kind、ID、scope、属性
- **Decisions**——每个动作的效果，以及产生它的策略；每个策略名都是链接，可直接跳到 policy store 里的那条策略
- **Outputs**——策略规则返回的值
- **Raw JSON**——完整记录

**Access logs** 记录 PDP 收到的每一个 API 请求，包括那些无效或未通过认证、因而从未走到决策环节的请求。可按 PDP 和时间范围过滤。一次有效的 `CheckResources` 或 `PlanResources` 调用，会有一条 call ID 相同的 decision 记录。

## 解释一次允许或拒绝

1. 从调用方应用自己的日志里取出 `cerbosCallId`——Cerbos 会在每个响应中返回它，这正是把两边对上的关键。
2. 在 **Decision logs** 中把范围缩小到该 principal、resource kind，以及请求前后的时间窗，找到对应记录。
3. 打开它并阅读 **Decisions**：目标动作的效果，以及产生它的策略。顺着策略链接找到那条规则。
4. 阅读记录下来的属性和有效的派生角色，就能看到条件求值时实际使用的 inputs。意外的拒绝通常是属性缺失，或者某个角色没有被派生出来，两者在这里都能看到。
5. 只有 access 记录、没有 decision 记录？说明请求根本没走到求值这一步——检查 access 记录上的 status code 和 peer。

如果这台 PDP 用的是 `local` 后端，同样的排查就通过 Admin API 进行：`GET /admin/auditlog/list/KIND_DECISION`，配合 `lookup=<callID>`、`tail=N`、`since=3h`，或者 `between.start` 与 `between.end`。

响应的 `Content-Type` 是 `application/x-ndjson`——**一行一条记录**，不是单个 JSON 文档，所以要逐行解析，每行外面还套着一层 `result`。记录里的字段和控制台对应：`checkResources.inputs`（principal、resource、actions）、`checkResources.outputs`（每个动作的效果和放行它的策略）、`auditTrail.effectivePolicies`（当时生效的策略）、`policySource`（策略来自哪个存储驱动）、`requestContext`（请求带的注解，没带注解时这个字段不存在）。所以控制台和 API 回答的是同一个问题。

`lookup` 是按调用 ID 精确查那一次请求；`tail` 给的是最近 N 条——要用它对上某次具体的调用，得确认那期间没有别的流量。

```bash
curl -s -u "cerbos:cerbosAdmin" \
  'http://<pdp>:3592/admin/auditlog/list/KIND_DECISION?lookup=01M5XJG7FGS1MGE9TD60DR79FP'
```

## Insights

基于已经到达的决策数据构建——采集打开后无需额外配置。

| 可视化 | 时间窗 | 显示内容 |
|---|---|---|
| 每小时决策数 | 最近 7 天 | 按小时堆叠的允许与拒绝次数，并提供 Allowed / Denied / Combined 切换。适合看短暂的尖峰，比如发布之后突然冒出来的一批拒绝。 |
| 每日决策数 | 最近 30 天 | 按天的同样拆分，平滑小时级噪声。适合看趋势。 |
| 每日活跃 principal | 最近 30 天 | 每天发起请求的不同 principal。看采用情况、季节性和异常下跌。 |
| 最活跃的 principal | 最近 30 天 | 按请求数排名的 principal ID 前列。 |
| 最活跃的 resource kind | 最近 30 天 | 按请求数排名的 kind 前列——应用的哪些部分在被检查。 |
| 最活跃的 resource 与动作组合 | 最近 30 天 | kind 与动作的组合，例如 `document:view` 对 `document:delete`。 |

每个排名行都带一个 **View** 链接，打开的 audit log 已经按该 principal、resource kind，或者 resource 与动作的组合预先过滤过。从「这里看起来不对劲」追到背后那条条具体决策，正是这条下钻路径的用法，不必手工重建过滤条件。

解读拒绝比例的波动：可能是比预期更严格的策略变更、配置错误的客户端，或者应用 bug，比如 resource 或动作名称拼错了。

## 用量面板（Usage dashboard）

按月统计，而不是运维指标。当前月份的汇总指标，每项都与上个月对比：**Active principals**、**Decisions**（Check API——一次调用可以检查多个动作，所以这个数字大于调用次数）和 **Query plans**。趋势图把 Check 调用拆分为允许与拒绝，把 Plan 调用拆分为允许、拒绝和条件性结果。下方还有一个逐月对比的表格。在 organization 级别，这个面板会汇总所有 workspace。

Insights 回答「现在发生了什么」；Usage 回答「每月有多少，逐月对比」。

## Exports（导出）

需要 **Owner** 角色。本地部署不支持，因为数据本来就在你自己的基础设施里。

在 **Decision logs** 或 **Access logs** 上设置好想要的过滤条件和时间范围，然后点 **Export**。对话框会确认这些过滤条件，并允许调整范围；不选范围时默认是最近 24 小时。点 **Add to export queue** 会在后台开始导出，**Exports** 标签页负责跟踪进度——不需要一直开着页面。每个 workspace 每小时只能启动有限的导出次数；每个导出在创建满一小时之后，就不再计入这个上限。

每次导出都用 [age](https://age-encryption.org) 加密。可以提供你自己密钥对的公钥那一半（以 `age1` 开头），也可以留空，让 Hub 生成一对并展示一次。**Hub 不会保留私钥，也无法重新签发**——一旦丢失，唯一的补救办法就是重新导出。

下载文件是 age 加密、gzip 压缩的 JSON Lines，每个记录一个对象：

```bash
age -d -i age.key <exported-file> | gunzip
```

它可以直接管道给 `jq`、数据仓库或 SIEM，无需任何转换。导出文件可下载七天，之后会被删除；底层的记录不受影响，因此只要它们还在保留期内，就可以重新导出。

## 保留期、数据驻留与访问

- **Hub cloud** 把 audit log 存在 Cerbos 管理的基础设施里（位于荷兰，GCP `europe-west6`），按套餐的保留策略保留。
- **On-premises** 把它们存在你自己基础设施中的一个 ClickHouse 实例里；数据驻留、保留和访问都由你负责。参见 [on-premises deployments（本地部署）](https://docs.cerbos.dev/cerbos-hub/on-premises?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_hub-on-premises)。
- 删除一个 organization 会连同其他一切一起永久删除它的 audit log。
- 若要持续转发到已有的 SIEM 或 UEBA 管道，请在 PDP 上配置 `pipeOutput` 次级后端，而不是反复导出。

## 合规问题

Cerbos 文档把 SOC 2、ISO 27001、HIPAA、PCI DSS 和 GDPR 列为聚合式 decision log 要满足的审计要求。遇到下面的问题该查什么：

| 问题 | 从哪里找答案 |
|---|---|
| 「把这个季度内所有对这类记录的访问都列出来」 | 按 resource kind、principal 和时间范围过滤的 Decision logs；或者从排名行的 **View** 下钻 |
| 「为什么这个具体的请求被允许了？」 | 应用侧的 call ID，然后是记录的 Decisions 面板，以及它链接到的那条策略 |
| 「证明拒绝确实被执行了」 | 决策图表上的 Deny 数据系列，以及点明做出拒绝的那条策略的单个记录 |
| 「谁可以读取审计轨迹？」 | 只有 Owner 和 Analyst 角色可以读取，导出则仅限 Owner——skill 的角色一节有详细说明 |
| 「怎样把保留的个人数据降到最少？」 | 脱敏在记录被缓冲或传输之前，就在 PDP 处移除字段——参见 [MASKING.md](MASKING.md) |
| 「数据存在哪里、保留多久？」 | 上面的「保留期、数据驻留与访问」 |
| 「把证据交给我们的审计师」 | 加密的 JSON Lines 导出，或者用 `pipeOutput` 转发到审计师已经在使用的系统 |
| 「和应用日志做关联」 | `cerbosCallId`，两边都有记录 |

权威参考：[audit log collection（审计日志采集）](https://docs.cerbos.dev/cerbos-hub/audit-log-collection?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_hub-audit-log-collection)、[Insights](https://docs.cerbos.dev/cerbos-hub/insights?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_hub-insights)、[usage dashboard（用量面板）](https://docs.cerbos.dev/cerbos-hub/usage-dashboard?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_hub-usage-dashboard)、[user management（用户管理）](https://docs.cerbos.dev/cerbos-hub/user-management?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_hub-user-management)、[PDP API reference（PDP API 参考）](https://docs.cerbos.dev/cerbos/latest/api/index?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_pdp-api)。
