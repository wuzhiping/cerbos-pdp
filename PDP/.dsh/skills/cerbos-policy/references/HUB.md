# Cerbos Hub 策略存储

把验证过的策略目录放进 Hub 策略存储，再从那里部署到 PDP。

> **本参考不属于仅用 API 的流程。** **存储（store）**、**部署（deployment）** 及其**客户端凭据**是在 Hub 控制台中创建的——没有对应的 API——而上传存储中的文件需要 `cerbosctl` 或控制台。`SKILL.md` 第 5 阶段的仅用 API 流程是通过 `POST /admin/policy` 部署到 PDP，并把 Hub 存储当作交给运维人员的独立一步。本文件记录这一步需要什么，以便完成交接。

**存储（store）** 保存策略文件。**部署（deployment）** 引用一个或多个存储，并在每次变更时编译它们、运行它找到的每个测试套件，然后把签名的策略包推送给与它相连的每个 PDP。单独一个存储不分发任何东西——必须有部署引用它。

## 运维人员需要准备的东西

| 项目 | 来源 | 携带内容 |
|---|---|---|
| 组织 + 工作区 | 控制台 | —|
| 策略存储 | 控制台 | store ID |
| 引用该存储的部署 | 控制台 | deployment ID |
| 存储凭据 | 控制台，**Read & write** | client ID + secret，用于上传 |
| 部署凭据 | 控制台，**Read & write** | client ID + secret，用于 PDP |

这两种凭据**不能**互换：上传需要存储的那一套，PDP 需要部署的那一套。只读凭据无法上传。

## 交接时必须传达的事实

- **上传会替换整个存储。** 要指向策略目录本身，而不是它上一层的目录。存储拒绝的内容会被跳过并列出，但它尝试解析却解析失败的文件会让整个上传失败——因此 `coverage-plan.json`、`normal.json` 和 `strict.json` 必须放在**策略目录之外**。
- **密钥只通过环境变量传递，绝不写在命令行上。** `CERBOS_HUB_CLIENT_ID` 和 `CERBOS_HUB_CLIENT_SECRET` 从环境变量读取；store ID 和 client ID 不是密钥，可以放在命令行上。确认密钥是否存在只看它是否被*设置*，绝不看它的值。
- **进入过对话记录的密钥就等于已泄露。** 对话记录是一份会被滚动查看、屏幕共享、粘贴进工单的日志。让用户在凭据的 **Client credentials** 页签上轮换该密钥。
- **测试套件由存储来跑。** 每次构建时，Hub 都会编译并运行存储中的每个 `*_test.yaml`。构建变红意味着测试套件在 Hub 的引擎下失败，因此要改的是策略或测试套件，而不是部署。

## 对比：仅用 API 的路径

同一个策略包，部署到 API 能访问到的 PDP 时，既不需要控制台也不需要客户端二进制：

```bash
curl -s -u "cerbos:cerbosAdmin" -X POST \
  -H 'Content-Type: application/json' --data-binary @policies.json \
  http://<pdp>:3592/admin/policy
```

PDP 会编译它所存储的内容，因此编译错误会在这里暴露，而不是等到下一次请求。这正是 `SKILL.md` 第 5 阶段所描述的做法，也是 [API-VALIDATION.md](API-VALIDATION.md) 中的验证流程所依据的做法。

## 延伸阅读

- [Hub 入门](https://docs.cerbos.dev/cerbos-hub/getting-started?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_hub-getting-started)
- [策略存储](https://docs.cerbos.dev/cerbos-hub/policy-stores?utm_campaign=brand_cerbos&utm_source=agent_skills&utm_medium=referral&utm_content=cerbos-policy_hub-policy-stores)
- 搭建 Hub 以及把 PDP 连接到部署，属于 `cerbos-hub-setup` 技能的范围。
