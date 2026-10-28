# 来源

本 skill 不锁定任何版本：它跟踪当前的 Cerbos Hub 文档和 `latest` 版本的 Cerbos PDP 文档。当 PDP 或 Hub 发布了审计方面的变更时，先读发布说明，再按下面的每个页面重新核对它支撑的章节或参考文件——尤其是 `audit` 配置块的默认值、后端列表、脱敏语法、Hub 控制台的标签页名称，以及哪些角色可以查看审计数据。

## 文档

| 页面 | 支撑内容 |
|---|---|
| [Audit configuration](https://docs.cerbos.dev/cerbos/latest/configuration/audit?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_pdp-configuration-audit) | `SKILL.md` 中的后端表、配置与 `storagePath`；决策日志过滤器；MASKING.md 的各节与路径语法；DEBUG.md 中每个后端的最小配置与 `pipeOutput` |
| [Hub audit log collection](https://docs.cerbos.dev/cerbos-hub/audit-log-collection?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_hub-audit-log-collection) | `SKILL.md` 中如何开启采集以及一次请求会记录什么；MASKING.md；READING.md 中的审计日志、导出、留存、数据驻留与合规问题 |
| [Hub Insights](https://docs.cerbos.dev/cerbos-hub/insights?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_hub-insights) | READING.md 中的 Insights 图表、排名与下钻 |
| [Hub usage dashboard](https://docs.cerbos.dev/cerbos-hub/usage-dashboard?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_hub-usage-dashboard) | READING.md 中的用量仪表盘 |
| [Hub user management](https://docs.cerbos.dev/cerbos-hub/user-management?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_hub-user-management) | `SKILL.md` 中哪些角色能看到它；READING.md 中的访问权限与导出角色 |
| [Hub on-premises deployments](https://docs.cerbos.dev/cerbos-hub/on-premises?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_hub-on-premises) | READING.md 中的本地部署存储与数据驻留 |
| [Hub troubleshooting](https://docs.cerbos.dev/cerbos-hub/troubleshooting?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_hub-troubleshooting) | `SKILL.md` 中的验证清单 |
| [Hub playground](https://docs.cerbos.dev/cerbos-hub/playground?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_hub-playground) | DEBUG.md 中在应用之外复现一次决策 |
| [PDP API reference](https://docs.cerbos.dev/cerbos/latest/api/index?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-audit-insights_pdp-api) | `GET /admin/auditlog/list/{kind}` 端点及其 `tail`、`since`、`between` 和 `lookup` 参数，以及 `SKILL.md`、`DEBUG.md`、`READING.md` 中的访问记录与决策记录结构——只有 PDP 使用 `local` 审计后端时才能通过该端点读回审计轨迹，`file` 和 `kafka` 后端只写不答 |

## 工具

- [age](https://age-encryption.org)：READING.md 中的导出加密与解密命令。
