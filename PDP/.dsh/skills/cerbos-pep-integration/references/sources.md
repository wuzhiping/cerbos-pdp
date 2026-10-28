# 来源

本 skill 中的指引是按 `SKILL.md` 里 `targetsCerbosVersion` 指定的 Cerbos 版本核对的,各语言参考则按当时的 SDK 版本核对。升级到新版本时,运行 `evals/update_cerbos_version.py`,读该版本的发布说明以及下面每个 SDK 的发布说明,然后逐页对照它所支撑的章节或参考文件重新核对 —— 尤其是请求与响应字段、批量上限、`auxData` 密钥集规则、各客户端的 TLS 默认值,以及哪些查询计划适配器有文档。

## 文档

| 页面 | 支撑内容 |
|---|---|
| [The Cerbos API](https://docs.cerbos.dev/cerbos/latest/api/index?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-api) | `api-shapes.md` 里的端点、`CheckResources` 与 `PlanResources` 的请求与响应结构、curl 和 grpcurl,以及不借助 SDK 与 PDP 通信;`SKILL.md` 里的无 SDK 路线 |
| [Server configuration](https://docs.cerbos.dev/cerbos/latest/configuration/server?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-configuration-server) | `api-shapes.md` 里的批量上限与 `server.requestLimits`;`SKILL.md` 里的 50 × 50 默认值 |
| [Auxiliary data](https://docs.cerbos.dev/cerbos/latest/configuration/auxdata?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-configuration-auxdata) | `SKILL.md` 和 `api-shapes.md` 里的 JWT 辅助数据:`auxData.jwt.keySets`、签名与 `exp`/`nbf` 校验、claim 路径 |
| [Scoped policies](https://docs.cerbos.dev/cerbos/latest/policies/scoped_policies?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-policies-scoped-policies) | `api-shapes.md` 里 principal 和 resource 上的 `scope` 字段 |
| [Outputs](https://docs.cerbos.dev/cerbos/latest/policies/outputs?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-policies-outputs) | `api-shapes.md` 里 `CheckResources` 响应中的 `outputs` |
| [Schemas](https://docs.cerbos.dev/cerbos/latest/policies/schemas?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-policies-schemas) | `api-shapes.md` 里 `CheckResources` 响应中的 `validationErrors` |
| [Policies](https://docs.cerbos.dev/cerbos/latest/policies/index?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-policies) | `SKILL.md` 的适用范围(Scope)里指向 `cerbos-policy` 的那条 |
| [Query plan adapters](https://docs.cerbos.dev/cerbos/latest/recipes/query-plan-adapters/index?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-recipes-query-plan-adapters) | `SKILL.md` 里的列表过滤;`query-plan.md` 里有文档的适配器 |
| [SQLAlchemy adapter](https://docs.cerbos.dev/cerbos/latest/recipes/query-plan-adapters/sqlalchemy?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-recipes-query-plan-adapters-sqlalchemy) | `python.md` 里的 SQLAlchemy 适配器与框架接入 |
| [Deployment](https://docs.cerbos.dev/cerbos/latest/deployment/index?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-deployment) | `SKILL.md` 的"连接 PDP"一节里的 service、sidecar 或 DaemonSet |
| [Kubernetes sidecar](https://docs.cerbos.dev/cerbos/latest/deployment/k8s-sidecar?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-deployment-k8s-sidecar) | `SKILL.md` 的"连接 PDP"一节里走 Unix domain socket 的 sidecar |
| [Hub getting started](https://docs.cerbos.dev/cerbos-hub/getting-started?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_hub-getting-started) | `SKILL.md` 的"连接 PDP"一节里连着 Hub 的 PDP |
| [RAG authorization](https://docs.cerbos.dev/cerbos/latest/recipes/ai/rag-authorization/index?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-recipes-ai-rag-authorization) | `SKILL.md` 里 AI agent 与 MCP 工具中的检索过滤 |
| [Embedded PDPs](https://docs.cerbos.dev/cerbos-hub/deployments-epdp-rules?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_hub-deployments-epdp-rules) | `SKILL.md` 的"检查跑在哪里?"一节里的浏览器 UI 检查;`javascript.md` 的"选择包"一节里的嵌入式包 |

## SDK 与协议

- [cerbos-sdk-javascript](https://github.com/cerbos/cerbos-sdk-javascript)、[cerbos-sdk-go](https://github.com/cerbos/cerbos-sdk-go) (API 见 [pkg.go.dev](https://pkg.go.dev/github.com/cerbos/cerbos-sdk-go/cerbos))、[cerbos-sdk-python](https://github.com/cerbos/cerbos-sdk-python)、[cerbos-sdk-java](https://github.com/cerbos/cerbos-sdk-java)、[cerbos-sdk-net](https://github.com/cerbos/cerbos-sdk-net)、[cerbos-sdk-rust](https://github.com/cerbos/cerbos-sdk-rust)、[cerbos-sdk-php](https://github.com/cerbos/cerbos-sdk-php)、[cerbos-sdk-laravel](https://github.com/cerbos/cerbos-sdk-laravel) 与 [cerbos-sdk-ruby](https://github.com/cerbos/cerbos-sdk-ruby):对应 `references/<language>.md` 里的安装、连接、TLS 默认值、四种调用、查询计划、JWT 辅助数据与错误;以及 `SKILL.md` 里的语言表。
- PyPI 上的 `cerbos` 0.16.0 与 `cerbos-sqlalchemy` 0.4.0 包,直接读过并跑过:版本锁定、service config 的 deadline 绕行办法、`grpc.RpcError`,以及 `python.md` 和 `query-plan.md` 里适配器对 kind 的处理与算子覆盖。这两个包每次发版都要重新核对。
- [cerbos/query-plan-adapters](https://github.com/cerbos/query-plan-adapters),包括 [Ent](https://github.com/cerbos/query-plan-adapters/tree/main/ent) 和 [pgx](https://github.com/cerbos/query-plan-adapters/tree/main/pgx):`query-plan.md`、`go.md`、`java.md`、`ruby.md` 里那些没有文档的参考适配器。它们都没有打过 tag 的发布,每次都要重新确认现状。
- [`cerbos/cerbos/api/public`](https://github.com/cerbos/cerbos/tree/main/api/public) 以及运行中的 PDP 在 `/schema/swagger.json` 提供的 OpenAPI 文档:`api-shapes.md` 里的线上协议结构。
- [OpenID AuthZEN](https://openid.github.io/authzen/):`api-shapes.md` 里的 AuthZEN 门面,以及 `go.md` 里的 AuthZEN。
