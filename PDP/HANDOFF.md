# HANDOFF · FDEP 授權改造交接手冊

> **主題**：把 Cerbos PDP 接進 FDEP 的調用鏈,讓 app id 成為受控的 resource
> **狀態**：**方案設計已完成,實作尚未開始**
> **日期**：2026-10-29
> **PDP**：`http://10.17.1.201:3592`(Cerbos 0.57.0,sqlite3 store,local audit)
> **方案設計**：[`FDEP-AUTHZ-DESIGN.md`](./FDEP-AUTHZ-DESIGN.md)(745 行,本文的詳細版)

---

## 一、本文是什麼

這是**交接手冊**,不是實作手冊。目的是讓接手的人知道:

1. 為什麼要改、改成什麼樣子(**設計**)
2. 走到這一步的過程裡,**哪些判斷被推翻過、為什麼**(**討論史**)
3. 動手前要先確認什麼(**前提與未決**)
4. 動手時要避開哪些坑(**坑表**)

**本文沒有代碼。** 實作開始後,PDP 側的 policy/schema/測試套件歸屬
`cerbos-pdp` 倉庫的 `PDP/` 目錄;FDEP 側的改動歸屬 FDEP 服務端倉庫。

---

## 二、需求原文與拆解

### 2.1 原始需求

> fdep-api 是一個集中式調用的入口,通過 app id 來區分不同的 resource,
> 並提供對應的業務能力,目前 fdep-api 還沒有權限控制策略。
>
> 現在需要結合 cerbos-pdp + sdk,改造 fdep-api:
> 1. 我在 fdep-api 添加用戶驗證,並提供用戶的身份角色信息
> 2. 提取以 app id 為 resource 的相關控制欄位,以及附加信息:比如 IP,當前時間,其他...
> 3. 結合部署在 cerbos-pdp server 中的策略,在 fdep-api 中使用 sdk 驗證授權
> 4. 提供 audit log

### 2.2 需求 → 設計落點

| # | 需求 | 落點 | 狀態 |
|---|---|---|---|
| 1 | 用戶驗證 + 身份角色 | `_token_.user_id` / `roles` / `email` 換成真值 | **欄位已存在,待確認誰填** |
| 2 | app id 為 resource + 控制欄位 + IP/時間 | resource `fdepApi`,id = 完整 app id;欄位分 principal/resource 兩處 | 設計完成 |
| 3 | PDP 策略 + SDK 驗證 | pipe.py 裡 Cerbos SDK → PDP,DENY 不進 Temporal | 設計完成 |
| 4 | audit log | PDP 決策軌跡(權威)+ FDEP 側呼叫軌跡(補充) | 設計完成 |

---

## 三、討論史:被推翻的判斷

**這一段是本文最有價值的部分。** 走過的路線裡有幾個判斷是錯的,
而且都是「看起來很合理」的錯。記下來是為了不再犯。

### 3.1 險些越界:先做後問 ⚠️

> 第一輪讀到「需要結合 cerbos-sdk 實現權限控制」時,我直接開始建了一整套
> `fdepApi` policy、schema、測試套件、guard 腳本,並部署到 PDP 上。
>
> **使用者指出:「還沒搞清楚需求,就一頓操作,請先 restore 變更,先理解需求。要避免。」**
>
> 處理:全部撤銷——10 個源檔案從倉庫副本還原、4 個新建檔案刪除、
> PDP 上推的策略與 schema 移除。

**教訓:需求不明的時候,先問,不要先做。** 尤其當動作會碰到**共享的線上服務**
(PDP 是多人共用的),撤銷成本遠高於問一句。

> 後續的 PDP 側改動都是**先驗證機制可行、用完立刻清掉**(§3.6),
> 沒有再留下任何未經確認的改動。

### 3.2 `C4.` 不是預設 org,是 Service Provider 的強制路徑依賴規範

我最初以為「不帶 `@` 時 pipe 會補預設 org `C4`」,證據是報錯訊息裡的
`C4.cerbos.pdp 不存在`。

**機制上錯,語義上更錯。** 原始碼:

```python
requestData = {"api": "C4."+api, ...}   # pipe.py,服務端強制加的常量前綴
```

**`C4.` 不是 org,是 SOA 邊界層的強制路徑依賴規範**——所有對外服務
必須註冊在 `C4` 子路徑下(`feg.cn/AIFE/README.md` 說明 C4 是
「邊界 · SOA · C4」那一層)。三個後果:

1. **服務集合封閉在 C4 之下。** 呼叫方控制 `C4.` 後面的任何東西,但跳不出去。
2. **前綴是疊加不是替換。** 實測:`@jev.C4.systemone.Choice` → `C4.C4.systemone.Choice`。
   呼叫方繞不過這個前綴。
3. **org 是 Service Provider 的部署位置,不是服務的一部分。**
   `ToT` 把 org 映射到 `{namespace, task_queue, workflow}`——分散式架構裡
   這個服務被註冊到哪個 queue。

**而且同一個 C4 路徑在不同 org 下是不同的服務。** 實測:

| 呼叫 | docs 指紋 |
|---|---|
| `@jev.systemone.Choice` | `336968f0fd2a`(有) |
| `@fdep.systemone.Choice` | 無(500) |
| `systemone.Choice`(無 `@`,走 fdep) | 無(500) |

**這直接推翻了我原本的 resource 設計。** 我原先說「jev 和 fdep 下的同名 api
是同一個 resource,權限不該按 org 分開」——**錯的**。同一路徑在 jev 有服務、
在 fdep 沒有,策略若只按 C4 路徑判,會把兩邊當成同一個東西。

**修正後:resource id = `C4.systemone.Choice@jev`**——C4 路徑是「服務是什麼」,
provider 是「誰在提供它」。詳見設計文件 §4.1。

### 3.3 `do` 被取反了一次

原始碼:`"do": !i.payload.do`(JS),pipe.py 原樣轉發。

**在 pipe.py 裡 `share.do == false` 才是「執行」。** 寫反了整個授權就反了。
實測:

| 客戶端送出 | 進 `share.do` | 進 Temporal | 語義 |
|---|---|---|---|
| `do: false` | `true` | `true` | 查文件 |
| `do: true` | `false` | `false` | 執行 |

**建議在 pipe.py 裡就算出 action,不要讓 policy 去猜:**

```python
action = "execute" if not share.get("do", True) else "read"
```

### 3.4 身份欄位早就存在

我最初以為「需要新增身份通道」。**錯。** 實測 `_token_` 的完整內容:

```json
{"sk":"63d3f5f8...", "from":"10.17.1.94",
 "user_id":"guests", "roles":[], "email":"guests@feg.cn",
 "now":"2026-10-29T00:46:36.998Z"}
```

**`user_id` / `roles` / `email` / `now` 四個欄位都在,由服務端填,目前填 guest。**
改造是「把 guest 換成真值」,不是「建通道」。

### 3.5 呼叫方的身份全部被丟棄(這條是對的)

實測五種寫法,服務端產生的 `_token_` 完全一樣:

| 客戶端嘗試 | 服務端實際的 `user_id` |
|---|---|
| 不帶任何身份 | `guests` |
| `inbound.user_id = "alice"` | `guests` |
| `inbound._token_ = {user_id:"admin", roles:["R8"]}` | `guests` |
| `Authorization: Bearer ...` | `guests` |
| `Cookie: session=...` | `guests` |

**身份必須由服務端產生,客戶端無法偽造。** 這對設計是好消息。

### 3.6 PDP 側機制的驗證方式:用完就清

要驗證「每個 policy 可以引用自己的 principal schema」,做法是部署一個
臨時 policy 帶自己的 schema,驗完用 `POST /admin/policy/delete?id=...` 清掉。

**踩到的坑:`DELETE /admin/policy?id=...` 是「停用」不是「刪除」**,
停用的策略仍然出現在 `GET /admin/policies?includeDisabled=true` 裡,
會讓測試誤判「策略還在」。真正刪除要用:

```
POST /admin/policy/delete?id=<id>      # 實測回 {"deletedPolicies":2}
```

### 3.7 其他兩個 PDP 側的坑(踩過)

**schema 的 id 要用相對路徑。** store 存的是相對路徑(`principal.json`),
策略裡的 `ref` 才帶前綴(`cerbos:///principal.json`)。推錯了會「看著像成功了」
(`GET /admin/schemas` 照樣列出來)但每個請求都被拒,而且**那行讀不回來**
(`GET /admin/schema?id=...` 各種前綴組合都 500)。

**`schema.enforcement` 預設是 `none`,不是 `warn`。** `none` 模式下 PDP 根本不
編譯 schema,所以策略引用一個不存在的 schema 也沒有任何症狀。改成 `reject`
之後才會全面崩潰——這台 PDP 就這樣炸過一次。

---

## 四、設計概要

完整版在 [`FDEP-AUTHZ-DESIGN.md`](./FDEP-AUTHZ-DESIGN.md)。這裡是骨架。

### 4.1 架構

```
呼叫方 ──HTTPS──► BPM/Node 層(JS) ──► pipe.py(Python) ──► Temporal ──► app 工作流
                                  │              │
                             填 _token_      授權閘門 + sk 校驗
                                             ↓ Cerbos SDK
                                          Cerbos PDP
```

**閘門放 pipe.py,在 `runWF` 之前。** 理由:

1. pipe.py 已經在做 `sk` 校驗——授權和「這次請求是新的」在同一位置
2. pipe.py 拿到的是已剝掉 org 前綴的 `api` 和已填身份的 `_token_`
3. Python 端用 Cerbos SDK 最直接
4. pipe.py 是所有呼叫的必经之路,BPM 層的分支繞不過它

### 4.2 resource 與屬性分工

| 放哪 | 欄位 | 理由 |
|---|---|---|
| resource.kind | `fdepApi` | 一套 policy 管所有服務 |
| resource.id | `C4.systemone.Choice@jev` | C4 路徑 + 提供它的 Service Provider |
| resource.attr | `c4Path`, `provider`, `app`, `domain`, `riskLevel`, `accessMode`, `mutates` | 服務的靜態事實 |
| principal.id | `_token_.user_id` | |
| principal.roles | `_token_.roles` | |
| principal.attr | `clientIp`(from 最後一段), `email`, `requestTime` | **呼叫者**的屬性 |
| annotations | `run_id`, `trace_id` | 只做關聯,**不參與**策略求值 |

**IP 和時間放 principal 而不是 resource**:放 resource 會讓「同一 app 在不同
時間不同 IP」變成不同 resource,規則會爆炸。

**每個 policy 一份自己的 principal schema。** 共享的 `principal.json` 是
`additionalProperties: false`,直接複用會讓 `clientIp` 之類的未聲明屬性
**讓每次調用都被拒**。實測隔離成立:一個 policy 的屬性詞彙表不影響另一個。

### 4.3 action 分兩個

`read`(查文件)和 `execute`(執行),由 `do` 映射(注意 §3.3 的取反)。

查文件只是回傳參數說明,執行會動到業務資料,風險差一個量級。

### 4.4 失敗要區分 403 和 503

| 情況 | 回應 | 理由 |
|---|---|---|
| PDP 明確拒絕 | 403 | 正常拒絕 |
| PDP 連不上 / 超時 | **503** | 「無法判斷」≠「不允許」 |
| PDP 回應格式不對 | **503** | 別把系統故障說成權限不足 |
| `roles` 為空 | 403 | 未驗證訪客,不進 PDP |

**PDP 用「全部拒絕」來表示「我什麼都沒找到」**——這台 PDP 遷移時就見過:
`policySource` 空、`effectivePolicies` 空,但 HTTP 依然 200。
所以 FDEP 側不能只看狀態碼。

### 4.5 落地順序:先影子模式

| 階段 | 內容 | 驗收 |
|---|---|---|
| 0 | 確認 FDEP 服務器能連到 PDP:3592;確認 pipe.py 上層怎麼把 exception 轉成 HTTP 響應 | 兩個答案 |
| 1 | PDP 側:policy + 兩份 schema + 原生測試套件,部署 | 測試套件全綠 |
| 2 | FDEP 側:閘門骨架 + PDP 客戶端,**先全部放行** | 有 PDP 軌跡,但不攔任何東西 |
| 3 | 影子模式跑一段,比對 PDP 的決定與業務實際該不該允許 | 影子報告 → 調 policy |
| 4 | 改成攔截 | 真的擋下越權呼叫 |
| 5 | 開 FDEP 側 audit log,與 PDP 軌跡對帳 | `cerbosCallId` 兩邊對得上 |

**階段 2 的影子模式是關鍵設計。** 直接上攔截會擋掉線上流量;
影子模式錯判成本為零,卻能用真實流量驗證 policy。

---

## 五、動手前必須確認的

| # | 問題 | 影響 |
|---|---|---|
| 1 | **FDEP 服務器能否連到 `10.17.1.201:3592`?** | **方案前提**,不通則整套不成立 |
| 2 | pipe.py 上層怎麼把 exception 轉成 HTTP 響應? | 決定 403 / 503 怎麼送出 |
| 3 | **`_token_.user_id` / `roles` 由誰填?** 實測是 `guests` / `[]` | 決定 §3.4 是「換值」還是「建通道」 |
| 4 | `roles` 的權威來源(人 → 角色的對應)在哪? | 沒有的話策略寫好了也只對 guest 生效 |
| 5 | app 註冊表在哪?哪個行程維護? | 決定控制欄位怎麼取得 |
| 6 | 4KI 矩陣裡的「△ 雙人授權」實際用在哪幾個操作? | 決定要不要先做雙人流程 |
| 7 | FDEP 側的 audit log 寫到哪? | 決定 FDEP 側軌跡怎麼落地 |
| 8 | 角色名怎麼對應?直接用 R1..R8,還是換成 domain 詞彙? | 影響 policy 可讀性 |
| 9 | PDP 策略只存在 sqlite3,備援是什麼? | PDP 掛掉時閘門會全部拒絕(安全但不可用) |

### 5.1 關於第 4 項

`feg.cn/4KI/governance/rbac.md` 定義了 8 個角色(R1 業務 / R2 IT / R3 個資 /
R4 資安 / R5 法務 / R6 治理 / R7 稽核 / R8 董事會)、5 個動作(R/W/A/S/D),
和一張 8×5 矩陣。

**這張表已經是現成的授權模型**,R1..R8 直接當 Cerbos 的 role。
但它給的是「角色 → 權限」,**缺「人 → 角色」的對應**——那一層目前沒有線索。

---

## 六、坑表(全部實測過)

### FDEP 側

| 坑 | 影響 | 對策 |
|---|---|---|
| `do` 被取反一次 | 授權整個反過來 | pipe.py 裡從 `share.do` 反推,並寫測試釘住 |
| **同一 C4 路徑在不同 org 下是不同服務** | 只用 C4 路徑當 resource id,策略會把兩邊當同一個 | resource id 帶 provider 段 |
| **`C4.` 前綴是疊加不是替換** | 呼叫方送 `@jev.C4.x` 得到 `C4.C4.x` | 服務端強制加,繞不過;授權用的 id 用同一字串 |
| `from` 是 XFF 鏈,客戶端可控前綴 | 直接做 IP 白名單會被繞過 | 取最後一段;白名單放網路層 |
| 原始碼裡 `// block ip from internet` 只 `console.log` | **沒真的擋** | 見上 |
| 全部錯誤返回 500,body 是 traceback | 「沒權限」和「伺服器壞了」分不出來 | 引入 `FdepDenied` / `FdepUnavailable` |
| `_token_.roles` 可能是空的 | PDP 要求至少一個 role,空陣列是 400 不是決策 | 身份層給 guest 一個明確角色,或在 pipe 直接擋 |

### PDP 側

| 坑 | 影響 | 對策 |
|---|---|---|
| schema id 帶前綴推上去 | 全部拒絕,且那行讀不回來 | id 用相對路徑 |
| 共享 `principal.json` 是 `additionalProperties: false` | 未聲明的 principal 屬性會讓請求被拒 | 每個 policy 引用自己的 principal schema |
| `DELETE /admin/policy` 是「停用」不是「刪除」 | 停用策略仍出現在清單裡 | `POST /admin/policy/delete?id=...` |
| 審計記錄約 13 秒後才可見 | 讀一次以為查不到 | **輪詢** |
| 審計響應是 NDJSON | `response.json()` 拋 `Extra data` | 逐行解析 |
| `effectivePolicies` 為空是正常的 | 「沒有策略命中」和「記錄缺失」長得像 | 統計時分清「空」和「缺」 |
| PDP 用「全部拒絕」表示「找不到策略」 | 故障被誤讀成權限不足 | 區分 403 / 503 |
| `schema.enforcement` 預設 `none` | 策略引用不存在的 schema 也沒症狀 | 開 `reject` 前先驗 schema id |

### 環境

| 坑 | 對策 |
|---|---|
| httpx 走 Windows 註冊表的代理 | 把 PDP 主機加進 `NO_PROXY` |
| Admin API 要 Basic 認證 | `cerbos` / `cerbosAdmin` |
| 這台 PDP 的 gRPC 端口 3593 關閉 | SDK 走 HTTP(:3592) |
| PDP 決策延遲 p50 14ms / p95 27ms | 可接受,不建議加快取 |

---

## 七、相關檔案

| 檔案 | 位置 | 內容 |
|---|---|---|
| 方案設計(詳細) | `PDP/FDEP-AUTHZ-DESIGN.md` | 本文的完整版,745 行 |
| PDP 現有配置 | `PDP/pdp-config/` | sqlite3 + local audit + `schema.enforcement: reject` |
| 部署腳本 | `PDP/pdp-config/push-policies.py` | 推策略和 schema(id 用相對路徑) |
| PDP 測試套件 | `PDP/policies/resource_policies/` | 原生 `*_test.yaml` 格式,期望的唯一真源 |
| 三個 Cerbos skill | `PDP/.dsh/skills/` | policy / pep-integration / audit-insights |
| FDEP 開發記錄 | `feg.cn/FDEP-API.md` | FDEP 協議、cordis 插件契約、踩坑記錄 |
| FDEP 插件原始碼 | `feg.cn/cordis-plugins/fdep-api-request/` | 客戶端側的 `fdep_call` 工具 |
| 角色權限矩陣 | `feg.cn/4KI/governance/rbac.md` | R1..R8 角色、5 動作、8×5 矩陣 |
| C4 方法論說明 | `feg.cn/AIFE/README.md` | C4 是「邊界 · SOA · C4」那一層;C4/ 下的架構圖 |
| PDP OpenAPI | `PDP/openapi-spec.json` | PDP 自己發布的端點文檔 |

---

## 八、相關討論的位置

FDEP 的調用協議、`_token_` 的欄位含義、`do` 的取反、org 路由表——這些在
`feg.cn/FDEP-API.md` 和 `feg.cn/cordis-plugins/fdep-api-request/` 裡有更詳細的
背景。**本次的授權改造不動客戶端插件**——協議不變,變的是服務端在派發前多問一次 PDP。

---

## 九、交接時的提醒

**PDP 是共享的線上服務。** 動它之前:

- 部署後必查 `GET /admin/policies`——健康檢查會說謊(策略集為空時照樣 SERVING)
- `schema.enforcement` 從 `none` 改成 `reject` 之前,先把 store 裡每條 schema 的
  鍵都核一遍(帶前綴的鍵讀不回來,而且症狀是全部拒絕)
- 用臨時 policy 驗證機制時,驗完用 `POST /admin/policy/delete` 清掉,
  不要留著 `DELETE` 停用狀態的殘留

**需求不明時先問。** 本次最大的教訓就在 §3.1。
