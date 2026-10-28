# 来源

本 skill 里的指导都要对着 `SKILL.md` 中 `targetsCerbosVersion` 指定的 Cerbos 版本校验。切换到新版本时，运行 `evals/update_cerbos_version.py`，读该版本的发布说明，然后按下面的每个页面重新核对它支撑的参考文件。

## 文档

| 页面 | 支撑内容 |
|---|---|
| [Release notes](https://github.com/cerbos/cerbos/releases) | 新的 CEL 函数（CEL.md 中的 **0.55+** 标记）、策略字段、编译器与测试运行器的变更 |
| [Resource policies](https://docs.cerbos.dev/cerbos/latest/policies/resource_policies.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-resource-policies-html) | POLICIES.md 的资源策略结构 |
| [Role policies](https://docs.cerbos.dev/cerbos/latest/policies/role_policies.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-role-policies-html) | POLICIES.md 的角色策略、`parentRoles` |
| [Principal policies](https://docs.cerbos.dev/cerbos/latest/policies/principal_policies.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-principal-policies-html) | POLICIES.md 的 principal 策略 |
| [Derived roles](https://docs.cerbos.dev/cerbos/latest/policies/derived_roles.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-derived-roles-html) | POLICIES.md 的派生角色 |
| [Variables](https://docs.cerbos.dev/cerbos/latest/policies/variables.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-variables-html) | POLICIES.md 的导出变量与局部变量、变量依赖设计 |
| [Scoped policies](https://docs.cerbos.dev/cerbos/latest/policies/scoped_policies.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-scoped-policies-html) | POLICIES.md 的 scope 与 scope 权限 |
| [Schemas](https://docs.cerbos.dev/cerbos/latest/policies/schemas.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-schemas-html) | `_schemas/` 的目录结构与强制校验 |
| [Outputs](https://docs.cerbos.dev/cerbos/latest/policies/outputs.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-outputs-html) | POLICIES.md 的输出 |
| [Conditions](https://docs.cerbos.dev/cerbos/latest/policies/conditions.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-conditions-html) | CEL.md 的对象、函数与条件嵌套 |
| [Compile and test](https://docs.cerbos.dev/cerbos/latest/policies/compile.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-compile-html) | TEST-SUITES.md 的套件与 fixture 格式 |
| [Best practices](https://docs.cerbos.dev/cerbos/latest/policies/best_practices.html?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-policies-best-practices-html) | SKILL.md 中的策略目录结构与命名 |
| [PDP API reference](https://docs.cerbos.dev/cerbos/latest/api/index?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_pdp-api) | API-VALIDATION.md 的端点、请求体与错误结构；PDP 对外提供的 `GET /schema/swagger.json` 文档 |

## Schema 与工具

- `https://api.cerbos.dev/latest/cerbos/policy/v1/*.schema.json`：POLICIES.md 和 TEST-SUITES.md 中的 `yaml-language-server` 头。
- PDP 上的 `GET /schema/swagger.json`：本 skill 所依据的 OpenAPI 文档，也是你手上这个版本的端点与请求结构的权威来源。
- `evals/tasks/` 下的评测任务按摘要锁定同一个版本，并拿真实 PDP 检验这些指导。
