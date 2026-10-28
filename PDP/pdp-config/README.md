# Cerbos PDP 推荐配置(sqlite3 + local audit)

这套文件是 `wuzhiping/cerbos-pdp` 那台 PDP(`10.17.1.201:3592`)**的推荐配置**。相对上游的 `config/.cerbos.yaml`,改了三处。

## 先看结论

| 问题 | 现在 | 改完 | 要改什么 |
|---|---|---|---|
| 部署策略 `501 Configured store is not mutable` | store 只读,只能靠运维拷文件 | `POST /admin/policy` 直接成功 | `storage.driver` → `sqlite3` |
| 读不回审计轨迹 `501 does not support querying` | `audit.backend: file` 只写不查 | `audit.backend: local` 可查 | `audit` 一块 |
| 属性 schema 完全没生效 | schema 文件从没被提交,且 `schema.enforcement` 默认是 `none` | schema 部署 + `enforcement: reject` | 加两个文件 + 改一个开关 |

## ⚠️ 换存储驱动是一次迁移

**这是整套改动里唯一有风险的一步。**

`disk` 驱动从目录读策略;`sqlite3` 驱动从数据库读。**切过去之后,磁盘目录里的策略不会自动进数据库。**

所以顺序是:

1. 磁盘目录里有策略 → 切到 sqlite3 → **数据库是空的**
2. PDP 起来了,但一份策略都没有
3. **每个决策都变成 DENY**,而且没有任何报错——`GET /admin/policies` 返回空列表,`GET /_cerbos/health` 照样是 `SERVING`

从"全部允许"变成"全部拒绝",而且看起来一切正常。所以推送这步不能省:

```bash
python3 pdp-config/push-policies.py --pdp http://<pdp>:3592 \
    --policies config/policies
```

## 文件

```
pdp-config/
  compose.yml                          推荐编排:加了独立数据卷
  push-policies.py                     迁移用的推送脚本(标准库 + PyYAML)
  config/
    .cerbos.yaml                        推荐配置
    policies/
      basicResource.yaml                策略(和上游那份规则相同,只是给规则加了名字)
      _schemas/
        principal.json                  新增:principal 属性 schema
        basicResource.json              新增:resource 属性 schema
```

`config/policies/` 这一份是**自包含**的,可以直接推。`_schemas/` 的 id 是从文件路径推出来的:`_schemas/principal.json` → `cerbos:///principal.json`,和策略里 `schemas.principalSchema.ref` 写的那一串对得上。

## 迁移步骤

```bash
# 1. 换配置
cp pdp-config/config/.cerbos.yaml  <repo>/config/.cerbos.yaml
cp pdp-config/compose.yml          <repo>/compose.yml

# 2. 重建容器(改了 .cerbos.yaml 必须重启;这里换了驱动,所以必须)
cd <repo> && docker compose up -d

# 3. 立刻确认策略集是空的 —— 这一步是预期的,但必须知道
curl -s -u "cerbos:cerbosAdmin" http://10.17.1.201:3592/admin/policies
#   -> {"policyIds": []}     空的!还没推送

# 4. 推送策略和 schema
python3 pdp-config/push-policies.py --pdp http://10.17.1.201:3592 \
    --policies pdp-config/config/policies

# 5. 核对
curl -s -u "cerbos:cerbosAdmin" http://10.17.1.201:3592/admin/policies
#   -> {"policyIds": ["basicResource.yaml"]}
curl -s -u "cerbos:cerbosAdmin" http://10.17.1.201:3592/admin/schemas
#   -> {"schemaIds": ["cerbos:///basicResource.json", "cerbos:///principal.json"]}

# 6. 发一个真实请求,确认策略真的生效了
curl -s -X POST -H 'Content-Type: application/json' \
  --data-binary @quickstart/check-allow.json \
  http://10.17.1.201:3592/api/check/resources
```

**第 3 步和第 5 步之间有一个窗口,PDP 会对所有请求返回 DENY。** 如果这台 PDP 服务着线上流量,在这个窗口里做迁移,或者提前用 `--set=storage.disk...` 之类的方式让两套并存(**Cerbos 没有这种模式**——所以只能选一个窗口期)。

推完之后建议立刻跑一遍本仓库的测试套件,确认行为没变:

```bash
uv run pytest        # 328 passed, 0 xfailed
```

## 四处改动,以及为什么

### 1. `storage.driver: disk` → `sqlite3`

```yaml
storage:
  driver: "sqlite3"
  sqlite3:
    dsn: "file:/var/lib/cerbos/cerbos.db?mode=rwc&cache=shared&_fk=true"
```

dsn 里三个参数:

* **`mode=rwc`** —— 文件不存在就创建。缺了它,PDP 第一次启动会因为找不到文件而起不来。
* **`cache=shared`** —— 官方要求,配合连接池用。
* **`_fk=true`** —— 打开外键约束。

**得到什么:** `POST /admin/policy` 返回 200,PDP 在存的时候就编译,编译错误当场报出来。策略部署从此是一个 API 调用,不再需要往磁盘目录拷文件。

**付出什么:**

* **策略来源从 git 变成数据库。** 仓库里的 `config/policies/` 不再决定 PDP 在提供什么,`GET /admin/policies` 才是事实来源。
* **git 成了"源",数据库成了"发布产物"。** 策略本身仍然应该放在 git 里版本管理,只是要多一步"推送到 PDP"(CI 里跑 `push-policies.py` 就行)。
* 审计记录里的 `policySource.driver` 从 `disk` 变成 `sqlite3`。
* `watchForChanges` 失去意义——策略更新现在要走 API。
* **SQLite 不适合多副本同时写。** 单机 compose 没问题;要横向扩,换 postgres / mysql 驱动(DSN 格式见 Cerbos 文档)。
* 数据库就是全部策略,**必须备份**。备份 = 把卷里的 `cerbos.db` 拷出来。

### 2. `audit.backend: file` → `local`

`file` 后端把每条决策写成 NDJSON 行,**按设计就不回答查询**。所以 `GET /admin/auditlog/list/{kind}` 会回 `501 Audit log backend does not support querying`。

`local` 后端是内嵌的 BadgerDB,能被 Admin API 查到:

```bash
curl -s -u "cerbos:cerbosAdmin" \
  'http://10.17.1.201:3592/admin/auditlog/list/KIND_DECISION?tail=5'
```

**取舍**:`pipeOutput`(把一份副本送去别的后端)是 **`hub` 后端专属的**,它在 `audit.hub` 下面,不在 `audit` 下面。所以选了 `local` 就没有"NDJSON 文件 + stdout"那份镜像了,二选一。要同时又要脱敏,只能上 `hub` 后端。

### 3. `schema.enforcement: reject`

```yaml
schema:
  enforcement: reject
```

三个取值:`none`(**默认**,完全不校验)、`warn`(校验但只记警告)、`reject`(校验不过就拒绝这次检查里的每个动作)。

**默认值 `none` 就是这个缺口的原因。** 上游的 `config/policies/basicResource.yaml` 声明了两个 schema,但仓库里从来没有 `_schemas/` 目录,这两个引用从来没解析成功过。现在文件补上了、引用也解析成功了,但 PDP 仍然不校验——因为 `enforcement` 默认是 `none`,属性不合 schema 也照样求值,响应里连 `validationErrors` 都没有。

`reject` 模式下:

* 响应仍然是 **200**,不是错误状态
* 动作被置为 `EFFECT_DENY`
* `validationErrors` 出现在 **`results[]` 那一层**,和 `actions`、`meta` 并列,不是响应顶层
* **SDK 看不到它们** —— Python SDK 的响应模型没有 `validation_errors` 字段,会静默丢掉。要看到就得读原始 HTTP 响应

⚠️ **这是行为变化**:一个多带了一个字段的请求(原来会放行,之后会被拒绝(schema 里 `additionalProperties: false`)。上线前先确认调用方都按 schema 发属性。

⚠️ **部署 schema 的 id 要用相对路径**——`_schemas/principal.json` 推上去的 id 是 `principal.json`,不是 `cerbos:///principal.json`。store 里存的是相对路径;策略里 `schemas.*Schema.ref` 才带 `cerbos:///` 前缀,PDP 编译时会把前缀去掉。推错了会“看着像成功了”(“`GET /admin/schemas` 照样列出来”),但每个请求都会拒绝,而那行还读不回来。在 `none` 模式下完全看不出来。

### 4. 路径挪出 git 工作区

上游的 `audit.file.path: /config/audit.log` 会把日志**直接写进仓库的 git 工作区**(`compose.yml` 里是 `./config:/config`)。改用 `local` 之后,审计库同样需要一个地方放。数据库更是必须——它是全部策略。

所以给 compose 加一个独立卷:

```yaml
    volumes:
      - ./config:/config
      - cerbos-data:/var/lib/cerbos
```

## 加了 schema 之后会发生什么

上游的 `config/policies/basicResource.yaml` 声明了两个 schema:

```yaml
  schemas:
    principalSchema:
      ref: cerbos:///principal.json
    resourceSchema:
      ref: cerbos:///basicResource.json
```

但仓库里从来没有 `_schemas/` 目录,所以这两个引用**从来没解析成功过**,属性类型完全不生效。

补上之后,属性校验会真正起作用:

* 畸形属性(类型不对、多出未声明的字段、缺少必填属性)会让整个检查失败:每个动作都是 `EFFECT_DENY`,响应里带 `validationErrors`
* `additionalProperties: false` 意味着请求里多带一个字段就会被拒

这是**行为变化**,不是纯粹的补文件。本仓库测试套件里那条 xfail(`test_malformed_attributes_are_rejected_by_schema_validation`)就是记录这件事的——补上之后它会翻成 XPASS,套件会失败,那正是提醒你更新那条测试的信号。现在它已经翻成了 XPASS,既有的测试已经改成正经断言,套件全绿。

## 没改的东西,以及为什么

* **admin 凭据**:`cerbos` / `cerbosAdmin` 的 bcrypt 哈希原样保留
* **gRPC**:没有显式配置,走默认 `:3593`,compose 里也没映射——决策 API 只需要 HTTP
* **Kafka 服务**:保留在 compose 里,只有 `audit.backend` 换成 `kafka` 时才用得上
* **`basicResource.yaml` 的规则**:和上游那份**完全相同**。本仓库那份是从运行中的 PDP 用 `GET /admin/policy?id=basicResource.yaml` 取回后重建的,规则语义一致,只是给四条规则加了名字——决策输出的 `src` 和审计记录里会显示规则名,能看出"是哪条规则放行的"。想保持上游原样,用上游那份也行。
