# 查询计划:按权限过滤列表

`PlanResources` 回答的是"什么条件下才算允许",而不是"这是不是允许"。PDP 返回资源必须满足的条件,你的 PEP 把这个条件作为谓词推进数据层。过滤由数据库来做。

只要答案是一个用户有权看到的*列表*,就该用它:索引页、搜索结果、导出、计数、仪表盘。

## 为什么不直接检查已经取到的行

取一页再对这一页跑 `checkResources` 看起来更简单,但会在四个地方出问题:

- **分页会错。** `LIMIT 20` 在鉴权之前就把页选好了,所以第 1 页回来 6 行,第 2 页回来 19 行,而且根本不存在诚实的"下一页"。靠多取一些来补偿是猜。
- **计数和聚合根本做不到。** `COUNT`、`SUM`、`GROUP BY` 和 `ORDER BY … LIMIT` 都没法在一个还没过滤的集合上算出来。
- **批量上限会顶到。** `CheckResources` 请求默认每次 50 个资源,所以 500 条的列表要十次往返,而朴素的逐行循环就变成了 500 次。
- **你为没人能看的行付了钱。** 读取、传输和反序列化的开销都随未授权的那部分集合增长,而它通常还是更大的一份。

每个(principal, kind, action)一次 `PlanResources` 调用就把这些全部替掉,而且成本不再随列表长度增长。

## 三种情况都要处理

```
KIND_ALWAYS_ALLOWED  → run the query with no authorization predicate
KIND_ALWAYS_DENIED   → return an empty result without touching the database
KIND_CONDITIONAL     → add the translated predicate to the query
```

大多数集成 bug 都出在这里,而两种失败方式都很严重:把 `ALWAYS_ALLOWED` 当成"没有条件,所以什么都匹配不上",会悄无声息地让你的管理员什么都看不到;把 `ALWAYS_DENIED` 当成"没有条件,所以不用过滤",则会把整张表泄露出去。三分支要显式写出来,并且让默认分支走拒绝。

有些 SDK 会让人很容易踩进这个坑。Java SDK 的 `getCondition()` 即使在无条件的计划上也会返回一个已填充的 `Optional`(那是 protobuf 的默认实例),所以先看 `isConditional()`,而不是 `getCondition().isPresent()`。

## 计划里会有什么

PDP 会针对你发来的内容对策略做部分求值:

- 基于 **principal 属性**的条件在规划期就解析掉了,不会出现在 AST 里。
- 基于 **resource 属性**的条件会变成 `request.resource.attr.<name>` 变量 —— 除非你在 `resource.attr` 里已经给了这个属性,那样它也会被解析掉。

所以 `resource.attr` 里只放那些在你即将查询的整批数据上确实恒定的东西(比如你被限定到的租户)。凡是逐行变化的就别放:那些正是你想用来过滤的列。

如果某条规则的条件引用了一个你的 schema 里没有对应列的 resource 属性,它就无法下推。这是策略设计的信号,不是适配器的 bug。

## 把变量映射到列

所有适配器的工作方式都一样:一个**映射器**,把 `request.resource.attr.<name>` 映射到存储里的列、字段或路径。映射器是策略词汇和 schema 词汇之间的契约 —— 任何条件可能提到的属性都要有一条对应项。缺一条就会抛错,或者更糟:在手写的适配器里悄悄丢掉谓词、放大访问范围。

在请求上设置 `includeMeta` / `includeMetadata`,并记录 `meta.filterDebug`(JS SDK 里是 `metadata.conditionString`)。它把 AST 渲染成可读的 CEL,能立刻告诉你映射器必须覆盖哪些路径。

把映射器放在它所映射的模型旁边,策略条件每多一个新属性就回头改一次。

## 参考适配器

有文档、有发布包,并且写进了 [Cerbos 文档](https://docs.cerbos.dev/cerbos/latest/recipes/query-plan-adapters/index?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-pep-integration_pdp-recipes-query-plan-adapters):

| 包 | 语言 | 目标 | 入口 | 结果 |
|---|---|---|---|---|
| `@cerbos/orm-prisma` | TypeScript | Prisma(PostgreSQL、MySQL、SQLite、SQL Server、MongoDB) | `queryPlanToPrisma({ queryPlan, mapper })` | `{ kind, filters }` → 一个 `where` 参数 |
| `@cerbos/orm-drizzle` | TypeScript | Drizzle(PostgreSQL、MySQL、SQLite、PlanetScale) | `queryPlanToDrizzle({ queryPlan, mapper })` | `{ kind, filter }` → `.where(...)` |
| `@cerbos/orm-mongoose` | TypeScript | 通过 Mongoose 的 MongoDB | `queryPlanToMongoose({ queryPlan, mapper })` | `{ kind, filters }` → `Model.find(...)` |
| `@cerbos/orm-convex` | TypeScript | Convex | `queryPlanToConvex({ queryPlan, mapper, allowPostFilter })` | `{ kind, filter, postFilter }` |
| `@cerbos/langchain-chromadb` | TypeScript | 通过 LangChain.js 的 ChromaDB | `queryPlanToChromaDB({ queryPlan, fieldNameMapper })` | `{ kind, filters }` → 一个 `Where` 过滤器 |
| `cerbos-sqlalchemy` | Python | SQLAlchemy 1.4 / 2.0 | `get_query(plan, Table, attr_map, joins?)` | 一个你可以继续加工的 `Select` |

它们全都需要同一门语言的 SDK 提供 Cerbos 客户端。TypeScript 适配器从 `@cerbos/core` 重新导出 `PlanKind`,并返回 `kind` 供你分支判断。`cerbos-sqlalchemy`(0.4.0)只导出 `get_query`,并自己分支:`ALWAYS_DENIED` 变成 `select(t).where(False)`,`ALWAYS_ALLOWED` 变成一个光秃秃的 `select(t)`,所以直接用它返回的 `Select`,别再去找什么 kind。

更多的参考实现放在 [`cerbos/query-plan-adapters`](https://github.com/cerbos/query-plan-adapters) 里,但还没进文档,所以依赖它们之前先确认现状。写这份文档时核实过:Go 的 [Ent](https://github.com/cerbos/query-plan-adapters/tree/main/ent) 和 [pgx](https://github.com/cerbos/query-plan-adapters/tree/main/pgx) 适配器可以通过模块代理 `github.com/cerbos/query-plan-adapters/{ent,pgx}` 解析到,但没有打过 tag 的发布;仓库里还有一个 Spring Data JPA 适配器(`dev.cerbos:cerbos-spring-data`,把计划翻译成 JPA `Specification`)、一个 Elasticsearch 适配器和一个 Ruby ActiveRecord 适配器,但都没有发布到 Maven Central 或 RubyGems。接进来之前先读适配器自己的 README。

Cerbos 就是把它们作为参考实现发布的 —— 文档里明确这么写。为了适配你的 schema 而 fork 其中一个,是预期之内的结果,不是失败。

### 映射器的形状各不相同

每个适配器都按自己的方式命名;在它们之间照搬映射器行不通。

```typescript
// Prisma / Mongoose — objects, with relations
mapper: {
  "request.resource.attr.ownerId": { field: "ownerId" },
  "request.resource.attr.tags": { relation: { name: "tags", type: "many", field: "name" } },
}
```

```typescript
// Drizzle — straight to column objects
mapper: { "request.resource.attr.status": resources.status }
```

```typescript
// LangChain / ChromaDB — plain strings, via fieldNameMapper
fieldNameMapper: { "request.resource.attr.department": "department" }
```

```python
# SQLAlchemy - 映射到 ORM 列,joins 作为第四个参数
attr_map = {"request.resource.attr.owner_id": User.id}
query = get_query(plan, Contact, attr_map, [(User, Contact.owner_id == User.id)])
```

Prisma、Drizzle、Mongoose 和 ChromaDB 还接受**函数式**映射器(`(attr) => …`),适合那些只要去掉 `request.resource.attr.` 前缀就完事的 schema。

### 算子覆盖并不一致

你写的策略决定了哪些存储能把它表达出来。

- **Prisma** 覆盖最广:标量算子(`and or not eq ne lt gt lte gte in startsWith endsWith contains isSet`)、关系算子(`is isNot some none every exists exists_one all filter except hasIntersection`),以及任意嵌套的关系。
- **Drizzle** 覆盖逻辑、比较、字符串、`isSet`,集合类算子则通过相关的 `EXISTS` 子查询实现。
- **Mongoose** 映射到 `$and/$or/$nor`、`$eq/$ne/$lt/$lte/$gt/$gte`、`$in`、`$elemMatch`,字符串算子用转义过的正则实现。`exists_one` 的行为是"至少一个",不是"恰好一个"。
- **SQLAlchemy**(0.4.0)覆盖逻辑、比较、算术、`in`、`size`、`contains`/`startsWith`/`endsWith`、时间戳以及层级函数。集合类算子(`exists`、`all`、`filter`、`hasIntersection`、……)和 `matches()` 会抛 `ValueError: Unrecognised operator`,除非你通过 `operator_override_fns` 提供它们 —— 这个参数还能把某个算子换成特定方言的版本。它的 README 记了一处规划器行为分叉:`has(R.attr.x)` 在计划里会折叠成 `ALWAYS_ALLOWED`,而 `check` 会拒绝缺少该属性的行,所以对有数据库支撑的属性,优先用 `R.attr.x != null`。被映射的列需要大小写敏感的排序规则,否则字符串比较会多放行。
- **Convex** 只把逻辑、比较、`in` 和 `isSet` 下推给数据库;字符串和集合类算子退回到 JavaScript 的 `postFilter`。这个后置过滤在行被读出*之后*才跑,于是又把查询计划要解决的问题请了回来 —— 所以 `allowPostFilter` 默认关闭,适配器会直接抛错。让它保持关闭是一道有用的绊线。
- **ChromaDB** 只存扁平的标量元数据,所以字符串、存在性和集合类算子都会抛错。`not` 的处理方式是取反内层算子并套用德摩根律,因为 Chroma 没有 `$not`。

当适配器表达不了某个条件时,诚实的做法是重塑策略,或者把该属性反规范化成一列 —— 而不是把全部数据拉回来在内存里过滤。

## 自己写适配器

AST 很小,遍历它是一天的活。节点形状和算子列表见 [api-shapes.md](api-shapes.md)。四条规则:

1. 先按三种情况分支,再看条件。
2. 通过一份明确的允许清单 —— 也就是你的映射器 —— 来解析变量,绝不要把 `variable` 名字插进 SQL 里。这些名字来自策略,没有映射的名字必须报错。
3. **失败即关闭。** 你没处理的算子要抛错;它绝不能悄悄丢掉谓词,因为丢掉谓词等于放行。
4. 正确绑定 `lambda`:第一个操作数是循环变量,第二个是循环体,而循环体里对该变量的引用,作用域限于正在被过滤的那个集合。

拿策略来测它,别拿手写的 AST 来测:改一个条件,重新做计划,断言返回的行。

## 和你自己的过滤条件组合

用 `AND` 把鉴权谓词和应用自己的过滤条件组合起来 —— 永远不要用 `OR`,也永远不要让用户传来的过滤条件把它替换掉。

```typescript
await prisma.contact.findMany({ where: { AND: [plan.filters, { archived: false }] } });
```

```typescript
await Model.find({ $and: [filters ?? {}, { archived: false }] });
```

```python
query = get_query(plan, Contact, attr_map).where(Contact.archived.is_(False))
```

## 缓存

一个计划取决于 principal、resource kind、动作,以及你发来的任何 resource 属性 —— 而不是那些行。当一个 handler 对同一种资源跑多个查询时,按请求缓存它是免费的,也很值得做。跨请求缓存则等于缓存了一次鉴权决策:给它一个短 TTL,用进入请求的所有东西做键,并且要能说清楚策略或角色变更之后的那个窗口期里会发生什么。
