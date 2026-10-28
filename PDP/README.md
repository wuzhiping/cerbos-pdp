# cerbos-policy-tests

这是一个TDD项目：通过官方的`cerbos` Python SDK，针对**远程**Cerbos PDP（`10.17.1.201:3592`）上的`basicResource`策略进行验证。

不用Docker，不用本地PDP，也**不会向PDP写入任何内容**——测试套件只读取决策结果、管理清单和审计轨迹。PDP的store现在已经是可变的（`sqlite3`），`POST /admin/policy`能用，但套件不碰它；策略的部署是另一个动作（`pdp-config/push-policies.py`）。

```bash
uv run pytest                       # 323 通过, 3 个 xfail
uv run python -m cerbos_policy_tests --save   # 覆盖率审计, 并保存结果
uv run cerbos-policy-tests          # 冒烟检查: 健康, 清单, 一次决策
uv run python verify_api_skills.py  # 核对三个 skill 引用的端点是否都在 OpenAPI 文档里
```

完整报告见 [TEST-REPORT.md](TEST-REPORT.md),上手指南见 [QUICKSTART.md](QUICKSTART.md)。

## 核心理念

**`policies/resource_policies/basicResource_test.yaml`是唯一的事实来源。** 它采用Cerbos原生的`*_test.yaml`格式编写，因此同一个文件既驱动PDP自带的测试运行器，也驱动这里的Python测试框架——Python框架通过HTTP决策API，针对运行中的PDP执行**同一个文件**。期望值没有在Python里复制一份，也不存在需要同步维护的第二张表。

其他一切都由它派生：

* `policies/resource_policies/testdata/{principals,resources}.yaml`——共享的fixtures，采用Cerbos的fixture格式。
* `coverage-plan.json`——放行路径和被隔离的拒绝项，格式为`cerbos-policy` skill的`coverage_audit_api.py`所期望的形式。
* `src/cerbos_policy_tests/rules.py`——根据策略文本写成的四条规则的参考实现，用作穷举扫描的判定基准。有一个测试在每条断言上把它与原生套件比对，因此两者不会发生偏离。

## 目录结构

```
.dsh/skills/                        三个 Cerbos skill(API 版本,中文说明)
  cerbos-policy/
  cerbos-pep-integration/
  cerbos-audit-insights/

policies/                           策略包的事实来源
  _schemas/
    principal.json                  策略声明的两个属性 schema
    basicResource.json
  resource_policies/
    basicResource.yaml              规则名、目的注释、schema 引用
    basicResource_test.yaml         原生测试套件——唯一的期望来源
    testdata/
      principals.yaml               共享 fixtures
      resources.yaml

coverage-plan.json                  放行路径和被隔离的拒绝项
coverage-audit.txt                  覆盖率审计的输出,存在计划旁边
openapi-spec.json                   PDP 自己发布的 OpenAPI 文档(16 条路径)

pdp-config/                         那台 PDP 的推荐配置(可直接拷进上游仓库)
  README.md                         三处改动逐条说明 + 迁移步骤
  compose.yml                       加了独立数据卷
  config/.cerbos.yaml               sqlite3 store + local audit backend
  config/policies/                  自包含的一套策略和 schema
  push-policies.py                  把策略和 schema 推进 store 的脚本

quickstart/                         Hello World:四个动作的完整实现
  quickstart.py
  policies/hello.yaml               最简策略
  policies/_schemas/hello.json

src/cerbos_policy_tests/
    config.py      设置,httpx 的代理豁免
    client.py      Cerbos SDK 客户端的构造
    pep.py         强制执行点辅助模块:拒绝 vs 错误
    fixtures.py    加载原生 fixture 文件
    nativesuite.py 加载并展开原生 *_test.yaml 套件
    testplan.py    覆盖计划:路径、行、扁平化、差异
    coverage.py    覆盖率审计,对线上 PDP 执行
    queryplan.py   planResources -> SQL
    rules.py       策略的参考模型

tests/
    test_native_suite.py     原生套件,对着 PDP 跑
    test_cross_product.py    每个 principal x resource x action
    test_coverage_plan.py    覆盖计划,对着线上审计
    test_query_plan.py       planResources -> WHERE -> 结果行
    test_edge_cases.py       scope、类型、空角色、失败即拒绝
    test_policy_inventory.py PDP 在提供什么,以及它的 schema 状态
    test_audit_log.py        审计轨迹的读取(NDJSON)
    test_connection.py       可达性、健康检查、认证
```

## 配置

| 变量 | 默认值 | 用途 |
|---|---|---|
| `CERBOS_PDP_URL` | `http://10.17.1.201:3592` | PDP基础URL |
| `CERBOS_ADMIN_USER` | `cerbos` | 管理API的basic-auth用户名 |
| `CERBOS_ADMIN_PASSWORD` | `cerbosAdmin` | 管理API的basic-auth密钥 |
| `CERBOS_CA_FILE` | *(系统信任存储)* | 面向`https` PDP的CA证书包 |

## 关于这台机器需要知道的三件事

**用HTTP客户端，而不是gRPC。** Python SDK在3593端口上更偏好gRPC，但这台PDP只开放3592——3593端口是关闭的。`client.py`显式构造HTTP客户端，`test_connection.py::test_grpc_port_is_not_exposed`记录了原因，免得日后有人把测试套件"升级"到gRPC，却纳闷它为什么突然不能用了。

**httpx会读取Windows注册表里的代理设置。** 在Windows上，`urllib.request.getproxies()`不管环境变量怎么说，都会返回`HKCU\...\Internet Settings\ProxyServer`里的代理。httpx默认就读取这个设置，于是把每一次PDP调用都路由到`10.9.32.1:8000`——这台内网主机用不了这个代理——请求因此一直挂起直到超时。`config.py::bypass_proxy`在导入时把PDP主机加入`NO_PROXY`，只豁免PDP这一个目标，其他一切照旧走代理。

（curl不受影响，因为它只读环境变量，不读注册表。正是这个差异让curl能用而httpx不能用。）

**审计轨迹的响应是NDJSON,而且不会立刻可读。** `GET /admin/auditlog/list/{kind}`返回的是`application/x-ndjson`——一行一条记录，每行外面套着一层`result`，记录本身在`result.decisionLogEntry`里。一次性的`response.json()`只要返回超过一条就会抛`Extra data`，必须逐行解析。

而且`local`后端会**先缓冲再提交**，所以一次决策刚做完是查不出来的——实测这台PDP要**13秒**。读轨迹要轮询，只读一次就断言"查不到"得到的是错的结论。

## 强制执行点辅助模块

`pep.py`是应用在某个操作边界处会调用的代码。它把两件容易混淆的事情分开：

* **拒绝**——策略不允许，`authorize()`返回`False`；
* **错误**——PDP不可达、超时或拒绝了请求，`authorize()`抛出`PdpError`（或`PdpUnavailable`）。

当PDP不可用时仍然"放行"，等于把一次故障变成授权绕过，因此这个辅助模块绝不会这么做。SDK自带的`is_allowed()`在API出错时返回`False`，正好把两者混为一谈；出于这个原因，辅助模块改用`check_resources()`并自行检查响应。

## 已知差距

三项发现，每一项都记录成测试而不是注释，这样原因一旦修复，对应的测试就会翻转：

1. **属性schema已经部署了，但`schema.enforcement`默认是`warn`而不是`reject`。** 所以畸形属性（类型不对、多出未声明的字段）仍然是被**静默拒绝**，而不是作为校验错误被驳回。在PDP配置里加 `schema.enforcement: reject` 就能关掉这个缺口——那会改变行为（无效的principal或resource会让这次检查里每个动作都被拒绝），所以单独做。
2. **在线PDP在评估时没有开启strict evaluation**，因此在线运行无法发现那些在运行时出错、并被静默求值为false的条件。**HTTP决策API根本没有这个开关**（`requestContext`只带`annotations`）——这是API的固有限制，任何PDP都一样。API下的替代做法是让情况不可能发生：每个fixture带上它条件读到的每个属性，并断言响应里没有`validationErrors`。
3. **API看不到编译期错误。** 策略编译是通过 `POST /admin/policy` 完成的，所以策略确实会被编译——但"编译通过"和"行为正确"是两件事，后者由测试套件和覆盖率审计来保证。仍然需要cerbos二进制的是 `cerbos compile` 的两种模式，用来捕获API看不到的编译期错误。

覆盖率审计本身已经不需要二进制——skill的`coverage_audit_api.py`针对实时决策而非编译报告套用同样的四条规则，而且今天就能对远程PDP运行（22行、6条路径，32行检查全过）。
