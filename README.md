# Desktop-Agent

精簡、具備自我演進能力與長期知識庫的桌面自動化 AI Agent。

---

## 核心理念：`Storage ≠ Memory ≠ Context`

傳統 LLM 依賴長上下文累積對話，導致 Token 膨脹與記憶遺忘。本系統採用三層分離設計：

```
Disk (永久知識庫 / 圖譜) ──[Retriever 自動檢索 + 關聯擴展]──> Working Memory (LRU 暫存) ──[Attention Manager 打分與預算控制]──> Context (精煉上下文)
```

- **Context 是建構出來的，不是累積出來的**：每個新任務/新一輪對話開始前，Working Memory 會先被清空重建，再由 Retriever 依當下內容重新載入相關節點——不會讓上一個任務的活躍節點無限期賴著不走，佔用這一輪的 Context 空間。
- **只存事實與規則，不存重複推導**：抽象知識共享（`INSTANCE_OF`）、情境局部覆寫（Event Override）、結論新鮮度追蹤（`Observation` 與 version 雜湊）。
- **同一件事不該散落成好幾個 id**：`remember()` 寫入時會用摘要相似度比對既有節點，發現很像既有記憶時附上提醒，引導模型用 `relate()`/`recall()` 收斂，而不是任由重複悄悄發生。

---

## 系統架構與核心功能

### 1. 跨 Session 長期記憶與 Context Compression System (CCS)
- **Disk Memory (`MemoryStore` / `MemoryNode`)**：基於雙向關聯圖的永久記憶中心（支援 `CALLS`、`INSTANCE_OF`、`ABOUT`、`MENTIONS` 等關聯與 O(1) 反向索引）。
- **Retriever**：使用者發送請求或任務開始前，自動提取關鍵字並沿圖譜延伸一階關聯，跨 Session 將相關知識精準啟動至 Working Memory——模型不需要主動呼叫工具就能「想起」相關的東西。
- **Working Memory**：LRU 活躍節點池，每個任務/每輪對話開始前會重建，維持時間戳與使用頻率。
- **Attention Manager**：依據關聯度、confidence、時效性、確定性、**Activation**（見下）動態打分，嚴格在 Token 預算內（如 ~650 tokens）進行選擇性屬性展開，杜絕爆窗。
- **Activation（跨 Session 記憶啟用度，預設關閉）**：節點被 `recall`/`search_memory` 命中時分數會疊加，並隨時間以 3 天半衰期衰減——常被想起的東西在排序時更容易被優先看到。使用者可在側邊欄開關。
- **漸進式遺忘（`ForgettingManager`，預設關閉）**：長期沒被存取的節點自動降低解析度而非直接刪除——先回收 Event 的局部覆寫（回到 Parent 預設值），很久之後再用一次 LLM 呼叫把摘要精煉得更抽象。可標記 `pinned` 保護特定節點永不遺忘。使用者可在側邊欄開關。
- **自動對話濃縮 (`ContextCompressor`)**：對話長度超過門檻時自動壓縮為結構化事實，並建立實體關聯。
- **自動記憶寫入**：不只是模型主動呼叫 `remember()`——每輪直接對話結束後會有一次「價值判斷」自動決定值不值得長期記住；任務完成後的 Reflect 也可以在 `===MEMORY===` 區塊裡自動萃取事實。

### 2. Observation：讓結論直接影響 Runtime 決策
`record_observation` 存下的結論不只是給模型看的文字。透過 `runtime_action` 參數，一個結論可以直接指示 Runtime：
- `context`（預設）：純資訊性，不影響流程。
- `skip_task`：下次有相關任務要執行時，直接跳過並標記完成。
- `replan`：暫停該任務，觸發 Reflect 重新檢視並調整整個 Task Tree。

系統會用 `version` 雜湊判斷結論是否過期，並在指令生效後標記 `applied`，避免同一個結論對後續任務無限期反覆生效。

### 3. Code Graph 程式碼關聯與影響分析
- **AST 跨模組靜態分析**：支援類別限定名、相對匯入解析、裝飾器與動態呼叫標記、外部庫參照。
- **連帶影響預掃**：任務執行前後，自動由呼叫圖查出可能受影響的相依函式並排入 Task Tree 驗證；自動產生的「影響檢查」任務標記為終點，不會對自己再次觸發掃描。

### 4. 自適應任務規劃引擎 (`TaskEngine`)
- **Markdown DSL 任務樹**：階層化結構、confidence 評估、風險操作確認。解析失敗時把錯誤原因回饋給模型重試。
- **動態拆解與反思**：複雜任務自動分解為子步驟；步驟完成後 Reflect 調整後續規劃。
- **邊做邊重新規劃（`<|replan|>` 標記）**：執行/思考中途發現足以推翻計畫的新資訊時，主動觸發 Reflect。
- **卡關升級階梯**：think_count 到頂時先判斷信心值是否還在進步（延長預算）；真的卡住則依序嘗試拆解、擴大記憶檢索範圍，最後才向使用者求助。

### 5. 多模型架構：用專門模型取代單一多模態模型
- **文字模型**：直接用 `llama-cpp-python` 載入 GGUF，也支援指向任意 OpenAI 相容 API。載入完全由使用者在 UI 決定。
- **視覺模型**：Florence-2 + PaddleOCR v4 作為獨立工具按需載入/卸載。
- **瀏覽器自動化（CDP）**：用 Chrome DevTools Protocol 開一個獨立的 debug 模式 Chrome，讓模型讀取網頁內容、點擊或輸入文字。

### 6. 工具文件懶加載
SYSTEM_PROMPT 只列一行摘要，規則較多的工具在模型第一次呼叫時才自動夾帶完整說明。

### 7. Agent 安全 / 權限系統
跟 Task Tree 既有的「需要確認」（模型自己對任務的判斷）是不同層級的獨立防線：
`agent/tool_permissions.py` 依照工具本身的風險把 43 個工具分成 SAFE
（唯讀查詢，永不詢問）/ MODERATE（有副作用但範圍有限，如記憶寫入、網頁互動）/
DANGEROUS（難以復原或範圍幾乎沒有邊界，如執行程式碼、真實滑鼠鍵盤、
執行系統指令）三級，不管模型自己怎麼判斷、也不管呼叫發生在 Task Tree 還是
Direct Mode 裡，只要工具風險等級需要確認，就會暫停並跳出授權卡片
（允許一次 / 本次工作階段永久允許 / 拒絕），由使用者當場決定。整體授權策略
（要問到什麼程度）可在側邊欄調整並跨 session 保留；「這個工作階段已經允許
哪些工具」則刻意不持久化——每次重開程式都是新的信任判斷。

### 8. 桌面自動化與現代化操作介面
滑鼠鍵盤操作、視窗探測、畫面識別、Python 腳本動態執行、PowerShell/cmd
系統指令執行（跟 execute_python 同等級的高風險工具，見上）、檔案系統搜尋
（依內容用正則表達式找，或依檔名用萬用字元找）、等待工具（固定時間等待，
或連續比對螢幕截圖等到畫面安靜下來——適合「不知道要等多久但知道停止
變動就是做完了」的情境，例如編譯、頁面載入）、PyQt6 螢幕 Overlay 標記；
React + TypeScript + Vite 前端（對話分枝樹、即時串流、工具調用視覺化、
授權請求卡片）。

### 9. 檔案上傳（路徑導向，不搬運檔案內容）
聊天室的附加檔案按鈕跳出原生系統檔案選擇對話框，只拿到選中的路徑字串，
不讀取檔案內容、不編碼成 base64、也沒有大小限制——這是本機 agent 才有的
優勢：檔案本來就在這台機器的磁碟上，agent 隨時能用 `execute_python`、
`search_files_by_content` 等既有工具直接依路徑存取，不需要先把整份內容
搬進瀏覽器記憶體再傳一次。圖片維持走原本的多模態訊息路徑（會被壓縮後
以 data URL 形式送給支援視覺的模型），跟一般檔案是兩條不同的路。

### 10. 開發時的 Console/Debug 輸出合併
開發模式下，前端 webview 的 `console.log/warn/error` 跟未捕捉的例外會被
轉送到 Python process 的 stdout 印出來（`src/lib/devConsoleBridge.ts` +
`main.py` 的 `log_from_frontend`）。用 VS Code 的 debugpy 掛
`python main.py` 偵錯時，Debug Console 會同時看到前端跟後端發生的事，
不用另外開瀏覽器 DevTools 對照兩份 log。正式打包後不會啟用（只在
`import.meta.env.DEV` 為真時安裝）。

---

## 目錄結構（後端重點）

```
src/python/
├── main.py                        # JsApi：對外暴露給前端的方法
├── webview_bootstrap.py           # pywebview 視窗啟動流程
├── config.py                      # SYSTEM_PROMPT 與各階段 prompt
├── agent/
│   ├── agent_core.py              # AgentWorker：組合所有 Mixin
│   ├── agent_routing.py           # 狀態機進入點、direct/plan 路由判斷
│   ├── agent_task_processor.py    # 單一任務生命週期
│   ├── agent_reflection.py        # Reflect、<|replan|> 標記偵測
│   ├── agent_direct_mode.py       # 直接對話模式
│   ├── agent_llm_client.py        # LLM API 呼叫核心
│   ├── agent_history.py           # 對話歷史管理、重複偵測
│   ├── agent_tool_execution.py    # <|tool_call|> 解析與執行、文件懶加載、權限檢查
│   ├── agent_memory_extraction.py # 自動記憶萃取
│   ├── agent_memory_mixin.py      # remember/recall/relate 等記憶工具
│   ├── tool_permissions.py        # 工具風險分級 + PermissionManager（安全/權限系統）
│   ├── llama_client.py            # llama-cpp-python 的 OpenAI SDK 相容 adapter
│   ├── task_system.py             # TaskEngine、TaskNode、DSL 解析
│   ├── retriever.py / attention_manager.py / working_memory.py / forgetting.py
│   └── tool_docs.py               # 工具詳細文件（懶加載內容）
├── memory/
│   ├── memory_node.py             # MemoryNode 資料模型（含 Activation）
│   └── memory_store.py            # MemoryStore 儲存/查詢引擎
└── tools/
    ├── code_graph.py / code_ast_visitor.py / code_import_resolver.py
    ├── code_impact.py / relation_impact.py
    ├── vision_tools.py            # Florence-2 / PaddleOCR
    ├── web_automation.py          # Chrome DevTools Protocol 瀏覽器工具
    ├── file_search.py             # 依內容(grep 風格)或依檔名搜尋檔案，跟 code_graph 互補
    ├── shell_exec.py              # PowerShell/cmd 系統指令執行（DANGEROUS 等級）
    └── automation_tools.py        # 桌面自動化工具彙整入口
```

前端 `src/components/sidebar/` 下拆有 `LlmClientCard`、`ExecutionModeCard`、`PermissionModeCard`（工具授權策略）、`ToggleFeatureCard`（漸進式遺忘/Activation 共用）、`SidebarFooterActions`；`src/components/chat/` 下拆有 `MessageAvatar`、`MessageActions`、`MessageEditForm`、`MessageBody`、`MessageImageAttachments`、`TaskTreeMessage`、`PermissionRequestMessage`（授權請求卡片）。

---

## 快速開始

### 後端 (Python)
```bash
pip install openai llama-cpp-python pywebview PyQt6 pyautogui pywinauto websocket-client
# 選用：視覺工具需要 transformers、torch、paddleocr
python src/python/main.py
```

### 前端 (React + TypeScript + Vite)
```bash
npm install
npm run dev
```

### 單元測試
```bash
# 後端
cd src/python
PYTHONPATH=".:tests" python -m pytest tests/ -q

# 前端
npm run test
```

目前後端共 43 個測試檔、320+ 個測試案例；前端 43 個測試案例，涵蓋 `parseTaskTree` 解析、`TaskTreeCard` 徽章規則、`useAgentEventHandler` 的串流標記處理與授權請求事件、`ChatMessage` 整體組裝、`PermissionRequestMessage` 授權卡片，以及從 `App.tsx` 拆出來的 `useSidebarAutoCollapse` / `useServerHealth` / `useMessageComposer` 三個 hook。

---

## 已知限制 / 尚在規劃

- `web_automation.py`、`llama_client.py`、`vision_tools.py` 目前只有 mock 測試，尚未接過真實模型/瀏覽器驗證——這幾個模組依賴真的 Chrome、真的 GGUF 模型檔、真的 GPU/PaddleOCR 環境，沒辦法在一般 CI/沙箱環境裡跑，需要開發者自己在有這些條件的機器上手動驗證一輪。
- 前端元件目前沒有測試覆蓋。→ **已補上一部分**：`vitest` + `@testing-library/react` 基礎設施（`npm run test`），並針對這次修復直接相關、風險最高的邏輯寫了測試——`parseTaskTree.ts` 的 DSL 解析、`TaskTreeCard.tsx` 的「需確認」徽章顯示規則（不該在任務已完成/已拆解時還顯示）、`useAgentEventHandler.ts` 的 `chunk`/`chunk_patch`/`reset_message` 事件處理（內部路由標記 `<|direct|>`/`<|plan|>` 就是靠這條路徑從畫面上被拿掉的）。其餘元件（Sidebar 系列、ChatMessage 渲染、Markdown/KaTeX 顯示等）仍待補。
- ~~`forgetting_enabled` / `activation_enabled` 開關重啟後會回到關閉，尚未持久化。~~ **已修復**：兩個開關現在會跟著 `MemoryStore` 的 JSON 檔案一起存進 `"__settings__"` 區塊（`memory_store.py`），重開程式會恢復成上次關掉之前的狀態。真正的分數（`activation` 欄位、`resolution_level`）本來就一直是隨 `MemoryNode` 存進磁碟的，這次補的只是「開關本身要不要打開」這個布林值。
- Retriever 的關鍵字比對偏簡單（n-gram + 字串比對），沒有語意 embedding——這次沒有動這一項：要做真的語意檢索需要額外引入一個 embedding 模型（例如 sentence-transformers 或重用 `transformers`），對一般使用者的機器來說會明顯增加安裝體積、記憶體用量與啟動時間，這是一個需要開發者自己權衡取捨的架構決策，不適合在沒有共識的情況下直接加進去。

深入開發前建議先讀 `AGENT_NOTES.md`——那是專門寫給 AI 協作者的專案導覽。
