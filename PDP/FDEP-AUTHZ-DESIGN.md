# FDEP 授权改造方案设计

> 把 Cerbos PDP 接进 FDEP 的调用链,让 app id 成为受控的 resource。
>
> 本文是**方案设计**。所有「实测」结论都来自对 `https://abc.feg.com.tw/oauth2/fdep`
> 和 `http://10.17.1.201:3592` 的探测,以及用户提供的 FDEP 源码。
> 没有实测过的部分明确标注为「待确认」。

---

## 0. 现状

### 0.1 FDEP 是什么

一个**集中式转发 endpoint**。同一个 URL、同一套 header,靠 `do` 布尔值区分
「查文件」和「执行」:

```
POST https://abc.feg.com.tw/oauth2/fdep
Content-Type: application/json
{ "api": "@jev.systemone.Choice", "do": false, "inbound": {} }
```

处理分两段:

```
调用方 ──HTTPS──► BPM/Node 層 ──► pipe.py ──► Temporal ──► app 工作流
                   (JS)              (Python)      (10.17.1.26:17233)
```

**BPM/Node 層(JS)** 做三件事:

1. 拆 app id → `org` 和 `api`
2. 按 org 選 task_queue / workflow
3. 組 `inbound._token_`(`sk` + `from`)

**pipe.py(Python)** 做三件事:

1. 校驗 `sk` 的時間戳(5 分鐘內)
2. `EXEC(flow, ...)` 走 PocketFlow
3. 轉發到 Temporal:`requestData["api"] = "C4." + api`

### 0.2 沒有權限控制

任何能到達這個 endpoint 的人,拿到任何 app id 就能調。

---

## 1. 實測事實

### 1.1 app id 與 org 路由

`@<org>.<api>` 三段式。實測:

| 呼叫方送出 | `share.api` | `share.org` |
|---|---|---|
| `@jev.systemone.Choice` | `systemone.Choice` | `{pip, JEV, LAYA}` |
| `@fdep.systemone.Choice` | `systemone.Choice` | `{pip, FDEP, SOP}` |
| `systemone.Choice`(無 `@`) | `systemone.Choice` | `{pip, FDEP, SOP}` |
| `@bogus.systemone.Choice` | — | **拋錯**:`Invalid API or unknown ToT` |

`ToT` 只有兩個條目:`fdep` 和 `jev`。**org 決定走哪條 Temporal 隊列和工作流**,
但 `api` 名本身不帶 org 前綴。

### 1.2 `C4.` 是 Service Provider 的強制路徑依賴規範

**這是整個設計的關鍵,不是一個字串前綴。**

`pipe.py` 裡:

```python
requestData = {
    "start_to_close_timeout": 600,
    "api": "C4." + api,       # ← 服務端強制加上的
    "do": do,
    "inbound": inbound
}
```

**`C4.` 由服務端加,呼叫方無法繞過。** 實測:

| 呼叫方送出 | 進 Temporal |
|---|---|
| `@jev.systemone.Choice` | `C4.systemone.Choice` |
| `@jev.C4.systemone.Choice` | `C4.C4.systemone.Choice` ← 前綴被疊加,不是被替換 |
| `@jev.foo.C4.bar` | `C4.foo.C4.bar` |
| `@jev....` | `C4....` |

**任何服務都必須註冊在 `C4` 子路徑下。** 這是 Service Provider 的**強制路徑依賴
規範**:C4 是 SOA 邊界層,所有對外服務都必須掛在這個命名空間底下
(`feg.cn/AIFE/README.md` 說明 C4 是「邊界 · SOA · C4」那一層)。

**所以 `C4.` 這個前綴有三個後果,設計上都必須考慮:**

1. **服務集合是封閉在 C4 之下的。** 呼叫方能指定 `C4.` 後面的任何東西,
   但不能跳出 C4。授權的 resource 集合因此是 C4 子樹,不是任意字串。
2. **org 不是服務的一部分,是 Service Provider 的部署位置。**
   `ToT` 把 org 映射到 `{namespace, task_queue, workflow}`——那是**分散式架構裡
   這個服務被註冊到哪個 queue**。
3. **同一個 C4 路徑在不同 org 下是不同的服務。** 實測:

   | 呼叫 | docs 指紋 |
   |---|---|
   | `@jev.systemone.Choice` | `336968f0fd2a`(有) |
   | `@fdep.systemone.Choice` | 無(500) |
   | `systemone.Choice`(無 `@`,走 fdep) | 無(500) |

   同一個 `C4.systemone.Choice` 路徑,在 jev 的 queue 上存在、在 fdep 的 queue 上不存在。
   **服務識別 = C4 路徑 + 提供它的 Service Provider 實例。**

### 1.3 `do` 的取反(容易踩)

JS 裡是 `do: !i.payload.do`,pipe.py 原樣轉發。實測:

| 呼叫方送出 | 進 `share.do` | 進 Temporal | 結果 |
|---|---|---|---|
| `do: false`(查文件) | `true` | `true` | 回傳文件 |
| `do: true`(執行) | `false` | `false` | 執行工作流 |

**`do` 在進 pipe 之前被取反了一次。** 在 pipe.py 裡做授權判斷時,
要決定「這次呼叫是查文件還是執行」,必須知道**原始的** `do`。
`share.do == false` 才是「執行」。

### 1.4 身份:呼叫方給的全被丟棄,服務端自己填

實測五種寫法,服務端產生的 `_token_` 完全一樣:

| 呼叫方嘗試 | 服務端實際的 `_token_.user_id` |
|---|---|
| 不帶任何身份 | `guests` |
| `inbound.user_id = "alice"` | `guests` |
| `inbound._token_ = {user_id:"admin", roles:["R8"]}` | `guests` |
| `Authorization: Bearer ...` | `guests` |
| `Cookie: session=...` | `guests` |

**結論:呼叫方無法偽造身份。** 身份由 BPM/Node 層填入,這是對的。

### 1.5 但身份欄位**已經存在**,而且是空的

`_token_` 的完整內容(實測):

```json
{
  "sk":     "63d3f5f8...",              // 加密的時間戳,pipe.py 校驗
  "from":   "10.17.1.94",              // 來源 IP(逗號分隔的 XFF 鏈)
  "user_id": "guests",                 // ← 身份,目前是訪客
  "roles":  [],                        // ← 角色,目前是空的
  "email":  "guests@feg.cn",           // ← 信箱
  "now":    "2026-10-29T00:46:36.998Z" // ← 伺服器時間
}
```

**這四個欄位就是改造的落點。** `user_id` / `roles` / `email` / `now` 已經在
`_token_` 裡,已經由服務端填(目前填的是 guest)。

`shared['token']` 裡另有 `run_id` / `user_id` / `session_id` / `trace_name`,
其中 `user_id` 和 `session_id` 是空字串。

### 1.6 `from` 是逗號分隔的 XFF 鏈,客戶端可控前綴

實測:

| 送出的 header | `_token_.from` |
|---|---|
| 無 | `10.17.1.94` |
| `X-Forwarded-For: 203.0.113.9` | `203.0.113.9, 10.17.1.94` |
| `X-Forwarded-For: 198.51.100.7, 203.0.113.9` | `198.51.100.7, 203.0.113.9, 10.17.1.94` |

**真實的來源 IP 是最後一段**,前面全是客戶端塞的。

⚠️ 這正好是原始碼裡那兩行 `// block ip from internet` 留下的坑:
現在只 `console.log(i.payload.from)`,**沒有真的擋**。
所以 `from` 目前**不能直接用來做 IP 白名單**——必須取最後一段,或者改用
一個客戶端碰不到的位置。

### 1.7 PDP 側已具備的能力

| 事實 | 實測 |
|---|---|
| 決策 API | `POST /api/check/resources` → 200,帶 `cerbosCallId` |
| 命中的策略 | `includeMeta: true` → `results[].meta.actions.<action>.matchedPolicy` |
| 決策延遲 | **p50 14ms / p95 27ms / max 29ms**(30 次取樣,本機) |
| 審計軌跡 | `GET /admin/auditlog/list/KIND_DECISION` → NDJSON,`local` 後端可查 |
| 軌跡裡的 principal | `{"id","policyVersion","roles","attr"}` —— **角色和屬性都在** |
| 軌跡裡的 peer | `{"address","userAgent","forwardedFor"}` —— **IP 已經在** |
| `requestContext.annotations` | 原樣進軌跡(`{"app_id","trace_id"}`) |
| 軌跡可延遲 | **13 秒**左右才可見 |

### 1.8 已有的角色與權限矩陣

`feg.cn/4KI/governance/rbac.md` 定義了 8 個角色(R1 業務 / R2 IT / R3 個資 /
R4 資安 / R5 法務 / R6 治理 / R7 稽核 / R8 董事會)、5 個動作(R 讀 / W 寫 /
A 審 / S 簽核 / D 刪),和一張 8×5 矩陣,含「△ 需共同授權」的雙人規則。

**這張表已經是現成的授權模型。** R1..R8 直接當 Cerbos 的 role。

---

## 2. 整體架構

```
┌──────────────┐
│ 呼叫方        │  內網使用者 / agent / CI
└──────┬───────┘
       │ HTTPS
       ▼
┌───────────────────────────────────────────────────────────────┐
│ BPM/Node 層 (JS)                                               │
│                                                               │
│  ① 驗證身份 → 填 _token_.user_id / roles / email              │
│  ② 拆 app id → org + api;按 org 選 task_queue / workflow      │
│     (org = Service Provider 實例;api 最終會被加上 C4. 前綴)        │
│  ③ 組 inbound._token_ = { sk, from, user_id, roles, email, now }│
│  ④ 【新增】組 principal + resource,交給 pipe.py 授權            │
└──────┬────────────────────────────────────────────────────────┘
       │
       ▼
┌───────────────────────────────────────────────────────────────┐
│ pipe.py (Python)                                               │
│                                                               │
│  ⑤ 校驗 sk 時間戳(5 分鐘內)                                    │
│  ⑥ 【新增】Cerbos SDK → PDP 授權判斷                            │
│  ⑦ DENY → 403,不進 Temporal                                    │
│  ⑧ ALLOW → 轉發到 Temporal                                     │
│  ⑨ 【新增】寫 FDEP 側 audit log(含 cerbosCallId)                │
└──────┬────────────────────────────────────────────────────────┘
       │  Cerbos SDK (HTTP, :3592)
       ▼
┌───────────────────────────────────────────────────────────────┐
│ Cerbos PDP  10.17.1.201:3592                                  │
│  storage: sqlite3   audit: local   schema.enforcement: reject │
└───────────────────────────────────────────────────────────────┘
```

**授權閘門放在 pipe.py,不是 BPM 層。** 理由:

1. pipe.py 已經在做 `sk` 校驗——**授權和「這次請求是新的」在同一個位置**,
   語義一致:兩件事都是「這次呼叫能不能成立」
2. pipe.py 拿到的是**已經剝掉 org 前綴的** `api` 和**已填好身份的** `_token_`,
   組裝 principal/resource 不需要回頭解析
3. Python 端用 Cerbos Python SDK 最直接(本 repo 已在用)
4. pipe.py 是**所有呼叫的必经之路**,BPM 層的分支不會繞過它

---

## 3. ① 身份驗證與角色提取

### 3.1 現成的落點

`_token_` 已經有 `user_id` / `roles` / `email` / `now`。**要做的是把它們填上
真實值,而不是 `guests` 和 `[]`。**

### 3.2 三種取法

| 方案 | 做法 | 評估 |
|---|---|---|
| **A(推薦)** | BPM 層在驗證身份後,把 `user_id` / `roles` 寫進 `_token_` | 改動最小,欄位已經在,只是值是 guest |
| B | pipe.py 自己去查身份(帶 token 問某個服務) | pipe 要多一次網路往返;而且 pipe 拿到的已經是加工過的 `_token_`,分層更亂 |
| C | 呼叫方在 `inbound` 自帶 | **不可接受**,實測已被丟棄 |

選 **A**。理由:**欄位已經在那裡了**,現在填的是 guest。把 guest 換成真實身份,
就是把「未驗證的訪客」變成「已驗證的使用者」。

### 3.3 `roles` 從哪來

**待確認:** 有沒有「某人有哪些角色」的權威來源?

`rbac.md` 的矩陣是**角色 → 權限**,不是**人 → 角色**。人 → 角色的對應
(HR 或組織架構系統)目前沒有線索。

設計上**先不假設**:`roles` 欄位存在,值由身份層決定。PDP 側照樣按
「角色集合」寫規則;角色集合是空的(或只有 guest),PDP 就會拒絕——預設拒絕,
不需要額外規則。

### 3.4 guest 怎麼處理

現在未驗證的呼叫拿到 `user_id: "guests"`、`roles: []`。

**PDP 要求 principal 至少有一個 role**(實測:空 roles 陣列是 400 驗證錯誤,
不是決策)。所以「完全沒角色」到不了 policy。

兩個選項:

| 選項 | 做法 | 評估 |
|---|---|---|
| **A(推薦)** | 身份層給未驗證呼叫一個明確角色,比如 `FDEP_GUEST` | policy 裡顯式寫「FDEP_GUEST 只能做什麼」,可讀可控 |
| B | pipe.py 在 roles 為空時直接拒絕,不問 PDP | 少一次 PDP 往返,但「為什麼拒絕」不在 policy 裡,審計軌跡上只剩一次 HTTP 錯誤 |

選 **A**,但要**同時**做 B 作為兜底:PDP 不可達時本來就要拒絕(見 §7.3),
roles 為空也直接拒絕,不進 PDP。這樣「未驗證」在兩層都被擋住。

---

## 4. ② app id 作為 resource

### 4.1 resource 的形狀

| app id 段 | 進到 Cerbos 的哪裡 |
|---|---|
| `C4`(服務端強制加的) | `attr.c4Path` 的前綴 |
| `systemone` | `attr.app` |
| `Choice` | `attr.operation` / resource id 的一部分 |
| `jev` / `fdep` | `attr.provider`——**哪個 Service Provider 實例** |

**resource kind 用 `fdepApi`,id 用完整的 C4 路徑 + provider。**

| 選項 | kind | id |
|---|---|---|
| **A(推薦)** | `fdepApi` | `C4.systemone.Choice@jev` |
| B | `fdepApi` | `C4.systemone.Choice` ← **不夠** |
| C | 每個 provider 一個 kind | — |

選 **A**,理由:

* **B 是錯的**:§1.2 實測證明 `C4.systemone.Choice` 在 jev 有服務、在 fdep 沒有。
  把它們當成同一個 resource,權限就管不到東西——jev 上有的服務,在 fdep 上
  根本不存在,但策略會以為兩邊一樣。
* **A 保留 C4 路徑的完整形狀**,軌跡裡看得出「C4 底下的某個服務、由某個
  provider 提供」,和 SOA 邊界層的語義一致
* provider 用 `@` 綴在後面,因為它是**部署位置**而不是路徑的一部分——
  路徑規範不該被 provider 的綁定方式污染

> 換個說法:**C4 路徑是「服務是什麼」,provider 是「誰在提供它」。**
> 授權主要管前者,但光有前者不夠——同一路徑在不同 provider 上的能力和風險
> 可能不同,那正是 §1.2 實測到的情況。

### 4.2 控制欄位:從 app 註冊表來

「以 app id 為 resource 的相關控制欄位」——指的是 **服務本身的屬性**:
它屬於哪個業務域、危險等級多高、是不是只讀。

**待確認:** app 註冊表现在在哪?是檔案還是資料庫?哪個行程維護它?

設計上這些欄位必須來自**權威來源**,不能來自呼叫方。兩個位置:

| 位置 | 優點 | 缺點 |
|---|---|---|
| **A(推薦)** BPM 層的 app 註冊表 | 就在派發路徑上,改註冊表即改策略輸入 | 註冊表要維護 |
| B PDP 側獨立 policy | 策略集中一處 | 加 app 要改 policy,兩處真相源 |

選 **A**。理由:app 註冊表本來就得存在(不然不知道怎麼派發),把控制欄位掛在上面
是自然延伸。而且**註冊表是「這個 app 是什麼」的事實,policy 是「誰可以做什麼」
的決定**,兩者變化節奏不同。

### 4.3 建議的控制欄位

**註冊表的鍵要和 §4.1 的 resource 身份對齊**——(C4 路徑, provider):

```yaml
# app 註冊表條目(示意)
C4.systemone.Choice:
  provider: jev          # 哪個 Service Provider 提供它
  app: systemone
  operation: Choice      # 這個 C4 路徑下的具體操作
  domain: 客服對話        # 業務域,來自 4KI 的維度
  riskLevel: low         # low | medium | high
  accessMode: read       # read | execute | write
  mutates: false         # 是否會改變狀態
```

⚠️ **注意 `operation` 和 `accessMode` 是兩件事:**
`operation` 是**服務自己**有什麼操作(`Choice` 是哪個操作),
`accessMode` 是**這次呼叫**要做什麼(查文件 / 執行 / 寫入)。
§5.2 說明 action 怎麼從 `do` 推導。

`riskLevel` / `accessMode` 用 `enum` 在 schema 裡約束(見 §5.3),
和註冊表的取值一致——註冊表寫錯的值會在 PDP 側被擋下,
而不是靜默變成「不高風險」。

### 4.4 附加資訊:放哪

| 欄位 | 來源 | 放哪 | 為什麼 |
|---|---|---|---|
| `clientIp` | `_token_.from` 的**最後一段** | `principal.attr` | 是**呼叫者**的屬性 |
| `requestTime` | `_token_.now` | `principal.attr` | 描述這次呼叫 |
| `email` | `_token_.email` | `principal.attr` | 呼叫者的一部分 |
| `apiId` | 呼叫方送的 app id | `resource.id` | 被訪問的東西 |
| `c4Path` | 服務端加前綴後的完整路徑 | `resource.attr` | C4 邊界層的規範路徑 |
| `provider` | app id 的 org 段 | `resource.attr` | 哪個 Service Provider 實例在提供它 |
| `app` | C4 路徑第二段 | `resource.attr` | 業務能力域 |
| `domain` / `riskLevel` / `accessMode` / `mutates` | app 註冊表 | `resource.attr` | 服務的靜態事實 |
| `traceId` | `shared['token'].run_id` | `annotations` | 只做關聯 |

**IP、時間、信箱放 principal.attr;服務的靜態屬性放 resource.attr。**
理由:resource 是「被訪問的東西」,它的屬性應該是這個 resource 本身的靜態事實。
把 IP 和時間放進 resource 會讓「同一個服務在不同時間不同 IP」變成不同 resource,
那樣每種組合都要一條 policy,規則會爆炸。

**`traceId` 走 `requestContext.annotations`,不放 attr。**
實測 annotations 原樣進審計軌跡,而且**不參與**策略求值——trace id 是關聯用的,
不該影響授權結果。

### 4.5 IP 的處理要小心

`_token_.from` 是逗號分隔的 XFF 鏈,**客戶端可控前綴**(見 §1.6)。

**規則:`clientIp` 取最後一段**,不是整串。理由:真實的來源 IP 是最後一段,
前面全是客戶端塞的。

但更穩的做法是**不要用 `from` 做 IP 白名單**——在反向代理後面,
`from` 的最後一段是代理的 IP,不是用戶的。原始碼裡那兩行
`// block ip from internet` 就是在說這件事,現在只 `console.log` 沒擋。

**建議:** IP 白名單在**網路層**(防火牆 / nginx)做,不做在 policy 裡。
policy 裡的 `clientIp` 只用於**記錄和稽核**,不用於准入。
如果一定要在 policy 裡擋 IP,得先把「可信 IP」定義清楚——比如只信任第一跳代理
之後的值,並且明確記錄這個假設。

---

## 5. ③ PDP 策略設計

### 5.1 policy 骨架

kind `fdepApi`,actions 兩個:`read`(查文件)和 `execute`(執行)。

```yaml
apiVersion: api.cerbos.dev/v1

resourcePolicy:
  resource: fdepApi
  version: default

  schemas:
    principalSchema:
      ref: cerbos:///fdepPrincipal.json
    resourceSchema:
      ref: cerbos:///fdepApi.json

  rules:
    # R1:平台管理員——任何 app、任何操作
    - name: platform-admin-may-call-anything
      actions: ["read", "execute"]
      roles: [FDEP_ADMIN]
      effect: EFFECT_ALLOW

    # R2:稽核——只讀低風險
    - name: auditor-may-only-read-low-risk
      actions: ["read"]
      roles: [FDEP_AUDITOR]
      effect: EFFECT_ALLOW
      condition:
        match:
          expr: R.attr.riskLevel == "low"

    # R3:開發者——可執行,但不碰高風險
    - name: developer-may-execute-non-high-risk
      actions: ["read", "execute"]
      roles: [FDEP_DEVELOPER]
      effect: EFFECT_ALLOW
      condition:
        match:
          expr: R.attr.riskLevel != "high"

    # 其餘全部拒絕
    - name: everyone-else-is-denied
      actions: ["read", "execute"]
      effect: EFFECT_DENY
```

**「其餘全部拒絕」用最後一條 catch-all `EFFECT_DENY` 顯式寫出來。**
理由:審計軌跡裡看得出這是**故意**拒絕,而不是「沒有規則命中」;
而且未來加規則時不容易忘記順序。

### 5.2 `read` 和 `execute` 為什麼要分開

FDEP 的 `do` 布爾值本來就區分「查文件」和「執行」,而查文件比執行風險低得多
——查文件只是回傳參數說明,執行會動到業務資料。

**所以 `do` 決定 action:`do == false`(查文件)→ `read`,`do == true`(執行)→ `execute`。**

⚠️ **但注意 §1.2 的取反**:在 pipe.py 裡 `share.do` 已經被取反過一次。
`share.do == false` 才是「執行」。這一步寫錯,整個授權就反了。

**建議在 pipe.py 裡把 action 算出來,不要讓 policy 去猜:**

```python
# share.do 已經被 JS 取反過: share.do == False 才是「執行」
action = "execute" if not share.get("do", True) else "read"
```

### 5.3 schema:每個 policy 一份自己的

⚠️ **實測踩到的坑:屬性 schema 是「按 policy 聲明」的,不是全局的。**

這台 PDP 上已部署的 `principal.json` 聲明了 `department` 和 `tenant`,
並且 `additionalProperties: false`。於是**任何未聲明的屬性都會被直接拒絕**:

| principal.attr | 決策 | 原因 |
|---|---|---|
| `{}` | `EFFECT_ALLOW` | 沒有未聲明的屬性 |
| `{"department": "ops"}` | `EFFECT_ALLOW` | `department` 已聲明 |
| `{"department":"ops","clientIp":"10.17.1.94"}` | **`EFFECT_DENY`** | `additionalProperties 'clientIp' not allowed` |

如果直接複用這份 `principal.json`,§4.4 設計的 `clientIp` / `email` / `requestTime`
會讓**每一次調用都被拒絕**——而且報的是 schema 校驗錯誤,不是權限錯誤,排查起來繞。

**解法(已實測):每個 policy 可以引用自己的 principal schema。**

實測把一個臨時 policy 連同自己的 `probePrincipal.json` 部署上去:

| 檢查 | 結果 |
|---|---|
| `principal.attr = {clientIp}` | `EFFECT_ALLOW` —— 新屬性被接受 |
| `principal.attr = {nope}` | `EFFECT_DENY` + `additionalProperties 'nope' not allowed` |
| `resource.attr = {}`(缺必填) | `EFFECT_DENY` + `missing properties: 'riskLevel'` |
| `resource.attr = {riskLevel: "bogus"}` | `EFFECT_DENY` + `value must be one of "low", "medium", "high"` |
| 同一時刻 `basicResource` 的檢查 | **不受影響**,照常 `EFFECT_ALLOW` |

**隔離成立:一個 policy 的屬性詞彙表不影響另一個 policy。**

所以 PDP 側要新增兩份 schema:

| 檔案 | 聲明 |
|---|---|
| `fdepPrincipal.json` | `clientIp`, `email`, `requestTime` |
| `fdepApi.json` | `c4Path`, `provider`, `app`, `domain`, `riskLevel`(enum), `accessMode`(enum), `mutates` |

> ⚠️ **schema 的 id 要用相對路徑**(`fdepPrincipal.json`),不是
> `cerbos:///fdepPrincipal.json`。store 存的是相對路徑,策略裡的 `ref` 才帶前綴。
> 推錯了會「看著像成功了」但每個請求都被拒,而且那行還讀不回來。

### 5.4 雙人授權怎麼表達

`rbac.md` 矩陣裡的「△」是**多人共同授權**。Cerbos 是單請求單決策,
沒有原生 multi-auth。三種做法:

| 方案 | 說明 | 代價 |
|---|---|---|
| **A(推薦)** FDEP 側聚合 | FDEP 收兩次調用(兩人各簽一次),湊齊了才派發 | FDEP 要有暫存狀態 |
| B PDP 側簽章 | 第一人簽名產生 token,第二人帶 token 來 | 需要簽章機制 |
| C 簡化 | 矩陣裡的 △ 一律當 ✅ | **放寬了管控**,違背原意 |

**建議 A**,但先確認 △ 規則的實際使用頻率——如果只有少數幾個高風險操作需要,
可以先只在 policy 裡擋掉那幾個,雙人流程留到後續。

---

## 6. ④ Audit log

有**兩處**軌跡,缺一不可。

### 6.1 PDP 側的決策軌跡(權威)

實測每條記錄裡有:

```json
{
  "callId": "01M62GYKXZ3M5X3QQ0C94HVKPE",
  "timestamp": "2026-10-29T00:31:05.123Z",
  "peer": {"address": "10.17.1.94:40728", "userAgent": "...", "forwardedFor": "10.17.1.94"},
  "checkResources": {
    "inputs": [{"principal": {"id":"alice","roles":["R2"],"attr":{...}},
                "resource": {"kind":"fdepApi","id":"@jev.systemone.Choice","attr":{...}}}],
    "outputs": [{"actions": {"execute": {"effect":"EFFECT_ALLOW","policy":"..."}}}]
  },
  "auditTrail": {"effectivePolicies": {"resource.fdepApi.vdefault": {...}}},
  "requestContext": {"annotations": {"trace_id":"t-99","app_id":"systemone"}},
  "policySource": {"database": {"driver": "DRIVER_SQLITE3"}}
}
```

這一側已經具備:身份、角色、IP、屬性、命中了哪條策略、來源儲存。**不用另做。**

⚠️ **三個實測坑**:
1. **響應是 NDJSON,一行一條記錄**,外面套 `{"result": {...}}`。一次 `response.json()`
   在返回超過一條時直接拋 `Extra data`。
2. **記錄約 13 秒後才可見**(`local` 後端先緩衝再提交)。**讀軌跡要輪詢**,
   讀一次就斷言「查不到」得到的是錯的結論。
3. **`effectivePolicies` 為空是正常的,不是錯誤。** 實測:

   | principal 的角色 | 決策 | `effectivePolicies` |
   |---|---|---|
   | `USER`(命中規則) | `EFFECT_ALLOW` | `["resource.basicResource.vdefault"]` |
   | `R2`(沒有規則點名它) | `EFFECT_DENY` | **`[]`** |
   | `NOBODY` | `EFFECT_DENY` | **`[]`** |

   **「沒有策略命中」和「命中了某條 deny 規則」在軌跡裡長得不一樣。**
   前者 `effectivePolicies` 是空的。統計時不能把「空」當成「記錄缺失」。

### 6.2 FDEP 側的呼叫軌跡(補充)

PDP 記的是「**授權決定**」,不記「**這次呼叫的業務結果**」。FDEP 側要補上:

| 欄位 | 為什麼 PDP 沒有 |
|---|---|
| `apiId`, `do`, `inbound` | PDP 只看到授權用的 attr,看不到原始請求體 |
| 派發結果(成功/業務異常/超時) | PDP 在派發之前就返回了 |
| 耗時 | PDP 只測自己的決策耗時 |
| `cerbosCallId` | 需要 FDEP 自己記,這是兩邊的關聯鍵 |
| `run_id` / `trace_name` | 來自 `shared['token']`,PDP 不知道 |

**兩邊的關聯鍵:`cerbosCallId`。**
決策響應裡帶著它,FDEP 把它寫進自己的日誌行;PDP 軌跡裡它是主鍵。
`run_id` 也放進 `requestContext.annotations`,於是同一個請求在三處都能對上:
呼叫方日誌 → FDEP 日誌 → PDP 軌跡。

### 6.3 查詢方式

```
GET /admin/auditlog/list/KIND_DECISION?lookup=<cerbosCallId>
GET /admin/auditlog/list/KIND_DECISION?tail=50
```

`lookup` 精確查一次調用,`tail` 取最近 N 條。**後者可能拿到別人的流量**,
對單次調用要用 `lookup`。

---

## 7. FDEP 側改造清單

### 7.1 閘門位置

pipe.py 的 `One.exec` 裡,`runWF` 之前:

```
prep() 取 api / do / inbound / org / token
   ↓
exec():
   ├─ 取出 _token_.user_id / roles / email / now
   ├─ 算出 action:share.do == False → execute,否則 read
   ├─ 組 resource:
   │    id     = "C4." + api + "@" + org      ← 和 pipe.py 轉發給 Temporal 的完全一致
   │    attr   = { c4Path: "C4."+api, provider: org, app, domain,
   │              riskLevel, accessMode, mutates }   ← 後四項來自 app 註冊表
   ├─ 組 principal:
   │    id     = _token_.user_id
   │    roles  = _token_.roles
   │    attr   = { clientIp: from 最後一段, email, requestTime }
   ├─【新增】Cerbos SDK → PDP
   ├─ DENY → 拋 FdepDenied,⛔ 不呼叫 runWF
   └─ ALLOW → runWF(...)  ← 原有流程不變
   ↓
post(): 寫 FDEP 側 audit log(含 cerbosCallId + 業務結果)
```

⚠️ **resource 的 id 必須和 pipe.py 轉發給 Temporal 的字串完全一致**:
```python
requestData = {"api": "C4." + api, ...}     # pipe.py 既有程式碼
```
授權用的 id 就是 `"C4." + api + "@" + org`——**多一段 provider 是為了區分
同一 C4 路徑在不同 Service Provider 上的不同服務**(見 §4.1)。

**別忘了 provider 段:** 如果只用 `"C4." + api`,jev 上有的服務在 fdep 上不存在
的情況就分不出來,策略會錯管。

**`runWF` 之前必須擋。** 授權閘門是**前置**的,不是業務邏輯裡的一個分支。

### 7.2 用 SDK

**用 Cerbos Python SDK。** `cerbos-sdk` 的 `CerbosClient` 處理了連接、逾時、
重試、錯誤分類。

**走 HTTP(:3592)。** 這台 PDP 的 **gRPC 端口 3593 是關閉的**(實測),
SDK 的 gRPC 客戶端用不了。SDK 的 HTTP 客戶端預設就是這個,不用改。

**延遲可接受**:本機實測 p50 14ms / p95 27ms。而 Temporal 的
`execution_timeout` 是 30 秒,PDP 往返佔比很小。

### 7.3 失敗時怎麼辦(重要)

PDP 不可達時**必須拒絕**,不能放行。閘門壞了等於沒有閘門。

但要區分三種失敗,給不同的回應:

| 情況 | 回應 | 理由 |
|---|---|---|
| PDP 明確拒絕 | **403** | 正常的拒絕 |
| PDP 連不上 / 超時 | **503**,不是 403 | 「無法判斷」和「不允許」是兩件事。503 讓呼叫方知道可以重試;403 會被當成「沒權限」而放棄重試 |
| PDP 回應格式不對 | **503** | 同上,別把系統故障說成權限不足 |
| `roles` 為空 | **403** | 未驗證的訪客,不進 PDP(見 §3.4) |

**這一條容易寫錯。** 這台 PDP 遷移時就見過:`policySource` 空、
`effectivePolicies` 空,但 HTTP 依然 200 —— **PDP 用「全部拒絕」來表示
「我什麼都沒找到」**。所以 FDEP 側不能只看 HTTP 狀態碼,
要看響應裡有沒有有效的決策結果。

### 7.4 FDEP 目前的 HTTP 狀態碼全是 500

實測:未知 org、未知 api、工作流失敗——**全部返回 500**,而且 500 的 body
是 Python traceback。

**這是現有的一個問題,不是本方案引入的。** 但授權改造會讓 403 有意義
(「你沒權限」vs「伺服器壞了」),所以順手把 pipe.py 的
`raise ValueError(f"错误信息: {e}")` 改成能區分:

```python
class FdepDenied(Exception): ...    # → 403
class FdepUnavailable(Exception): ... # → 503
```

外層再各自映射。這需要看 pipe.py 上面那層怎麼把 exception 轉成 HTTP 響應
——**待確認**。

### 7.5 效能

每次 FDEP 呼叫多一次 PDP 往返(p50 14ms)。相對於 Temporal 的工作流時間可以忽略。

**不建議加快取。** 授權判斷要反映當下的角色和風險等級;快取一旦失效就是
繞過閘門。而且延遲本來就夠低。

---

## 8. PDP 側改造清單

| # | 事項 | 說明 |
|---|---|---|
| 1 | 新增 `fdepApi` policy | kind `fdepApi`,actions `read` / `execute`,規則見 §5.1 |
| 2 | 新增 `fdepPrincipal.json` + `fdepApi.json` schema | **各自的詞彙表**,不要複用共享的 `principal.json`(見 §5.3) |
| 3 | 部署到 PDP | `POST /admin/schema` + `POST /admin/policy` |
| 4 | 原生測試套件 | `fdepApi_test.yaml`,與 policy 同格式,作為期望的唯一真源 |
| 5 | fixtures | `policies/fdep_policies/testdata/{principals,resources}.yaml` |
| 6 | 覆蓋計畫 | `coverage-plan.json` 加 fdepApi 的行 |

**注意 id 的坑(踩過一次):** 部署 schema 時 id 用**相對路徑**(`fdepApi.json`),
不是 `cerbos:///fdepApi.json`。store 存的是相對路徑,策略裡的 `ref` 才帶前綴。
推錯了會「看著像成功了」但每個請求都被拒,而且那行還讀不回來。

**刪除策略用哪個端點:** `DELETE /admin/policy?id=...` 是**停用**,
停用的策略仍然出現在 `GET /admin/policies?includeDisabled=true` 裡。
要真正刪掉用 `POST /admin/policy/delete?id=...`(實測回 `{"deletedPolicies":2}`)。

---

## 9. 分階段落地

| 階段 | 內容 | 可驗證的成果 |
|---|---|---|
| **0** | 確認 FDEP 服務器能連到 PDP:3592;確認 pipe.py 怎麼把 exception 轉成 HTTP 響應 | 兩個答案 |
| **1** | PDP 側:policy + 兩份 schema + 測試套件,部署 | 測試套件在 PDP 上全綠;`GET /admin/policies` 看得到 |
| **2** | FDEP 側:閘門骨架 + PDP 客戶端,**先全部放行**(影子模式) | FDEP 呼叫會產生 PDP 軌跡,但不攔任何東西 |
| **3** | 影子模式跑一段,比對 PDP 的決定與業務實際該不該允許 | 影子報告:PDP 說 DENY 但業務上該允許的清單 → 調 policy |
| **4** | 影子模式改成攔截 | 真的擋下越權呼叫 |
| **5** | 開啟 FDEP 側 audit log,與 PDP 軌跡對帳 | 兩邊的 `cerbosCallId` 能一一對上 |

**階段 2 的影子模式是關鍵設計。** 直接上攔截會擋掉線上流量;
影子模式只觀察不動作,錯判的成本是零,但能拿真實流量驗證 policy。

---

## 10. 風險與未決事項

### 已知的坑(都實測過)

| 坑 | 影響 | 對策 |
|---|---|---|
| **`do` 被取反一次** | 授權判斷整個反過來 | 在 pipe.py 裡從 `share.do` 反推,並寫測試釘住 |
| **同一 C4 路徑在不同 org 下是不同服務** | 只用 C4 路徑當 resource id,策略會把兩邊當同一個 | resource id 帶 provider 段(§4.1) |
| **`C4.` 前綴疊加而非替換** | 呼叫方送 `@jev.C4.x` 會得到 `C4.C4.x` | 服務端強制加前綴,呼叫方繞不過;授權用的 id 要用同一個字串 |
| **共享的 `principal.json` 是 `additionalProperties: false`** | 未聲明的 principal 屬性會讓請求被拒 | 每個 policy 引用自己的 principal schema |
| **schema id 帶前綴推上去** | 全部拒絕,且那行讀不回來 | id 用相對路徑 |
| **`DELETE /admin/policy` 是「停用」不是「刪除」** | 停用的策略仍出現在 `?includeDisabled=true` 裡 | 真正刪除用 `POST /admin/policy/delete?id=...` |
| **PDP 審計記錄約 13 秒後才可見** | 讀一次以為查不到 | 輪詢 |
| **PDP 審計響應是 NDJSON** | `response.json()` 拋 `Extra data` | 逐行解析 |
| **`effectivePolicies` 為空** | 預設拒絕的請求沒有策略命中,空列表**不是**記錄缺失 | 統計時分清「空」和「缺」 |
| **`from` 是 XFF 鏈,客戶端可控前綴** | 直接拿來做 IP 白名單會被繞過 | 取最後一段;IP 白名單放網路層(見 §4.5) |
| **FDEP 全部返回 500** | 「沒權限」和「伺服器壞了」分不出來 | 引入 `FdepDenied` / `FdepUnavailable` 區分 403 / 503 |
| **PDP 用「全部拒絕」表示「找不到策略」** | 故障被誤讀成權限不足 | FDEP 側要區分 403 和 503 |
| **PDP 的 `storage.driver` 是 `sqlite3`** | 策略在資料庫裡,**PDP 掛掉時策略也沒了** | 要有備援來源(見下) |

### 未決(需要決策或確認)

| # | 問題 | 影響 |
|---|---|---|
| 1 | **FDEP 服務器能否連到 `10.17.1.201:3592`?** | **方案前提**,不通就整套不成立 |
| 2 | pipe.py 上層怎麼把 exception 轉成 HTTP 響應? | 決定 403 / 503 怎麼送出(§7.4) |
| 3 | `roles` 的權威來源在哪?(人 → 角色的對應) | 決定角色是全局還是 per-app;不解決則只有 guest |
| 4 | app 註冊表現在在哪?哪個行程維護? | 決定控制欄位怎麼取得(§4.2) |
| 5 | 4KI 矩陣裡的「△ 雙人授權」實際用在哪幾個操作? | 決定要不要先做雙人流程(§5.4) |
| 6 | FDEP 側的 audit log 寫到哪?(既有日誌系統?DB?) | 決定 §6.2 的落地方式 |
| 7 | 角色名怎麼對應?直接用 R1..R8,還是換成 domain 詞彙? | 影響 policy 可讀性 |
| 8 | **`_token_.user_id` / `roles` 是由誰填的?** 實測看到 `guests` / `[]` | 決定 §3.2 選 A 還是 B |
| 9 | PDP 的策略只存在 sqlite3 裡,備援是什麼? | PDP 掛掉時閘門會全部拒絕(安全但不可用) |

---

## 附:已確認可用的 PDP 端點

```
GET  /_cerbos/health                        健康
GET  /api/server_info                       版本
POST /api/check/resources                   決策(帶 cerbosCallId,約 14ms)
GET  /admin/policies                        策略清單
GET  /admin/policies/inspect                策略詳情
POST /admin/policy                          部署策略(store 可變時)
DELETE /admin/policy?id=...                 停用策略(不是刪除!)
POST /admin/policy/delete?id=...            真正刪除策略
GET  /admin/schemas                         schema 清單
POST /admin/schema                          部署 schema(id 用相對路徑)
DELETE /admin/schema?id=...                 刪除 schema(這個是真的刪)
GET  /admin/auditlog/list/KIND_DECISION     決策軌跡(NDJSON,約 13s 延遲)
GET  /admin/auditlog/list/KIND_ACCESS       存取軌跡
```

PDP:`http://10.17.1.201:3592` · admin:`cerbos` / `cerbosAdmin` · 版本 0.57.0

---

## 附:本文的驗證方式

方案裡每一條「實測」結論都有可重跑的檢查:

| 對象 | 怎麼驗 |
|---|---|
| app id 與 org 路由 | `POST /oauth2/fdep` 分別帶 `@jev` / `@fdep` / 無 `@` / 未知 org,看 `share.api` 和 `share.org` |
| 身份不可偽造 | 五種寫法(不帶、`inbound.user_id`、`inbound._token_`、`Authorization`、`Cookie`),看 pipe 產生的 `_token_` |
| `do` 的取反 | 送 `do:false` / `do:true`,看 `share.do` |
| `from` 的 XFF 鏈 | 送不同 `X-Forwarded-For`,看 `_token_.from` |
| PDP 決策與軌跡 | `POST /api/check/resources` + `GET /admin/auditlog/list/KIND_DECISION?lookup=<cerbosCallId>`,**輪詢** |
| schema 隔離 | 部署一個臨時 policy 帶自己的 principal schema,驗證完用 `POST /admin/policy/delete` 清掉 |
| PDP 延遲 | 連打 30 次 `check_resources`,取 p50 / p95 |
| 端點形狀 | `openapi-spec.json`——PDP 自己發布的 OpenAPI 文檔 |

**PDP 上的現狀(設計時的基線):**

```
GET /admin/policies  -> resource.basicResource.vdefault, resource.risk_case.vdefault
GET /admin/schemas   -> basicResource.json, principal.json, resources/risk_case.json
```

`risk_case` 那條策略和它的 schema 不在 `cerbos-pdp` 倉庫裡——倉庫不是「PDP 現在在
提供什麼」的完整記錄。設計 fdepApi 時要注意別犯同樣的錯:**PDP 實際持有的東西,
和倉庫裡提交的東西,是兩份。**
