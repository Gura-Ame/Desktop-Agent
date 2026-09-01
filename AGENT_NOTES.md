# 給接手這個專案的 AI 協作者（也就是未來的我自己）

這份文件不是給人類看的產品文件（那是 `README.md`），是寫給下一個接手這個
專案的 Claude 看的：假設你完全沒有這個 session 的記憶，剛 clone 下來，
使用者丟了一句話要你改東西——這份文件的目的是讓你不用重新踩過我踩過的坑。

---

## 專案一句話說明

桌面自動化 Agent，核心賣點是「Context-centric Cognitive Memory」：
Disk（永久圖譜）→ Retriever（自動檢索）→ Working Memory（LRU 暫存）→
Attention Manager（打分+預算）→ Context。細節看 `README.md`，這裡只講
你動手改程式碼之前必須知道的事。

使用者是 Windows 桌面應用開發者，主要用 Traditional Chinese 溝通，混一些
英文技術詞。整個 codebase 的註解、commit message、變數命名的中文說明
全部是 Traditional Chinese——**你寫新程式碼時的註解也要用中文**，不要
突然切成英文，風格要跟現有的一致。

---

## 開工前一定要做的事

1. **先 `git pull`**：使用者常常自己/透過別的 session 推新 commit 上去，
   你手上這份 checkout 很可能已經過時。如果你本地有未 commit 的修改，
   `git stash` 再 pull 再 `git stash pop`，衝突多半能自動合併。
2. **跑一次完整測試套件當基準線**：
   ```bash
   cd src/python
   PYTHONPATH=".:tests" python -m pytest tests/ -q
   ```
   目前應該是全綠（39 個檔案、260+ 案例）。如果 pull 下來就有紅的，
   先搞清楚是不是新 commit 帶來的既有問題，不要急著算在自己頭上。
3. **改完之後一定要重跑全部測試**，不是只跑你新寫的那幾個檔案的測試——
   這個專案好幾次「修 A 壞了 B」都是全套測試才抓到的（見下方「踩過的坑」）。
4. 前端也要驗證：
   ```bash
   npm install  # node_modules 通常沒被打包進交付的 zip，需要重裝
   npx tsc -b
   npx vite build
   ```

---

## 架構速覽：Mixin 組合模式

`AgentWorker`（`agent/agent_core.py`）不是一個大類別，是十幾個 Mixin
組合出來的：

```python
class AgentWorker(
    AgentMemoryMixin, AgentLLMClientMixin,
    AgentHistoryMixin, AgentToolExecutionMixin, AgentMemoryExtractionMixin,
    AgentRoutingMixin, AgentTaskProcessorMixin, AgentReflectionMixin,
    AgentDirectModeMixin,
):
```

每個 Mixin 只做一件事，彼此之間單純透過 `self.xxx()` 互相呼叫——**加新
方法時，先想清楚這個方法屬於哪個關注點，放到對應的檔案，不要什麼都塞進
`agent_core.py` 或隨便找一個現有檔案硬塞**。目前的切法：

| 檔案 | 管什麼 |
|---|---|
| `agent_routing.py` | 最外層狀態機、IDLE 狀態的 direct/plan 路由判斷 |
| `agent_task_processor.py` | 單一任務生命週期（思考/卡住偵測/執行/驗證/拆解） |
| `agent_reflection.py` | Reflect、`<\|replan\|>` 標記偵測 |
| `agent_direct_mode.py` | 直接對話模式（含 tool-call 迴圈） |
| `agent_llm_client.py` | 純粹的 LLM API 呼叫（`_call_llm`/`_call_llm_stream`）、組 multimodal 訊息 |
| `agent_history.py` | `self.history` 的持久化、壓縮觸發、重複偵測 |
| `agent_tool_execution.py` | 解析 `<\|tool_call\|>`、執行、文件懶加載 |
| `agent_memory_extraction.py` | 自動記憶萃取（價值判斷、Reflect 的 `===MEMORY===` 區塊） |
| `agent_memory_mixin.py` | `remember`/`recall`/`relate`/`record_observation`、影響預掃 |

`agent/agent_protocol.py` 是給 pyright 用的型別 stub（`AgentWorkerBase`，
方法本體全是 `...`），**改了哪個 Mixin 的方法簽名，記得同步更新這裡**，
不然型別檢查會失準（但不影響 runtime，pytest 不會抓到這個）。

`agent/agent_execution_cycle.py` 現在只是相容 shim（組合
`AgentRoutingMixin` + `AgentTaskProcessorMixin` + `AgentReflectionMixin`），
新程式碼不需要再 import 它。

---

## 踩過的坑（花了很多輪才抓到，別重蹈覆轍）

### 1. `_reflect()` 會整個換掉 TaskNode 物件，屬性會憑空消失
`apply_reflected_dsl`（`task_system.py`）對所有非 `COMPLETED`/`DECOMPOSED`
狀態的任務，一律用**重新解析出來的新 TaskNode 實例**取代舊的，只繼承
`parent_id`。這代表：

- 如果你在呼叫 `self._reflect(task, ...)` **之前**在 `task` 物件上設了
  什麼旗標，指望它在 reflect 之後還在——它不會還在，因為 `task` 這個
  區域變數現在指向一個沒人要的舊物件。**要嘛在 reflect 之前用完那個狀態，
  要嘛在 reflect 之後重新 `next(t for t in self.engine.tasks if t.id == task.id)`
  撈一次。**
- 這個坑真實發生過：`TaskNode.is_auto_impact_check`（標記「這是自動產生
  的影響檢查任務，不要再對它自己觸發下一輪掃描」）在任務完成、觸發
  Reflect 之後，屬性會被重置回 `False`，導致遞迴保護形同虛設，
  在測試環境裡造成無限連鎖生成任務。**最後的修法是改用「id 命名規則」
  （`.impact\d+` / `.rel_impact\d+` 結尾）判斷，而不是相信物件屬性**，
  因為 id 是 DSL 文字格式的一部分，才真的保證撐得過物件替換。
  以後任何「需要在多輪 Reflect 之間存活的狀態」，優先考慮塞進 id 命名
  規則或 DSL 欄位本身，不要只放在 Python 物件屬性上。

### 2. `_auto_queue_impact_checks` 一個任務生命週期會被呼叫兩次
任務開始前（潛在影響預掃）、任務完成後（結果已知後再掃一次）都會呼叫，
用的是同一份**純機械式、確定性**的 id（`f"{task_id}.rel_impact{i}"`），
不去重就會插入兩份一模一樣的任務。`tools/relation_impact.py` 和
`tools/code_impact.py` 現在都有 `existing_ids` 檢查，新增類似的自動插入
邏輯時記得比照辦理。

### 3. Working Memory 現在會在任務/對話輪次邊界被清空
`working_memory.clear()` 在 `agent_routing.py`（新一輪對話開始前）跟
`agent_task_processor.py`（每個任務開始前）都會被呼叫，呼應設計文件
「Context 該重建、不該累積」的想法。**寫測試時如果假設某個節點會一直留在
`working_memory.active_ids()` 裡跨好幾個任務，現在不成立了**——Disk 上的
資料不會不見，但 Working Memory 這個「目前載入的子集合」會被重置。

### 4. Retriever 的關鍵字比對很鬆，寫測試小心巧合命中
n-gram + 字串比對沒有語意理解，兩段文字只要剛好共用一個常見詞（例如
中文的「任務」「東西」這種泛用詞）就可能被判定相關。寫涉及 Retriever
行為的測試時，remember 的摘要跟 task 的 title/method 要用有區辨度的
詞彙（例如具體名詞：牛排、財務報表），不要用「這是任務 A」「跟任務相關」
這種會跟其他測試資料巧合撞詞的寫法。

### 5. 工具呼叫格式已經簡化，不再有 `call:` 前綴
舊格式：`<|tool_call|>call:func_name(args)<|tool_call|>`
新格式：`<|tool_call|>func_name(args)<|tool_call|>`
（commit `381b1e0 Delete call tag`）。如果你看到任何測試或文件字串裡還有
`call:` 前綴，那是沒跟上這次改動，要更新。

### 6. `difflib.SequenceMatcher` 相似度閾值是憑經驗調的
`remember()` 的重複偵測（0.72）、串流重複偵測 `_is_repeating_tail`
（0.72）、`_similar_to_previous_reply`（0.6）都是試出來的數字，沒有
理論依據。改動前先看對應測試檔（`test_duplicate_fact_detection.py`、
`test_bugfixes_2026_08.py`）裡的邊界案例，確保新閾值不會讓既有案例
翻盤。

### 7. `MAX_SUMMARY_LENGTH`（60 字）是強制在儲存層做的，不是靠 prompt 拜託
本地小模型不可靠，不會每次都乖乖把摘要寫短。`MemoryNode.__init__`
（`memory/memory_node.py`）無條件截斷，這是刻意的設計，不要為了「讓
摘要更完整」而把這個拿掉或大幅調高。

---

## 測試撰寫慣例

- 大多數測試用 `tests/fake_llm.py` 的 `FakeOpenAIClient` + 分類腳本
  （`{"system": [...], "thinking": [...], "verify": [...], "reflect": [...]}`），
  依 prompt 內容的關鍵字自動分類（`CATEGORY_MARKERS`）。每個分類的腳本
  用完會用 `AssertionError` 報「沒準備夠」，這是特意設計的，不是 bug——
  代表你的測試腳本數量算錯了。
- `tests/test_agent_core_helpers.py` 有 `make_agent(scripts, mode=...)`、
  `send_turn(agent, prompt)`、`wait_until(predicate, timeout=...)` 這幾個
  共用 helper，新測試優先重用，不要重新發明。
- `ECHO_REFLECT`（`fake_llm.py`）是最常用的 reflect 假回應：原封不動把
  目前的任務樹文字回傳，適合「這次測試不在乎 Reflect 改了什麼、只在乎
  Reflect 有沒有被呼叫」的情境。
- 涉及 `_auto_queue_impact_checks` 的測試：只要 `remember()` +
  `record_observation()` 建立了一條 `ABOUT` 關聯，之後任何任務摸到那個
  節點、完成時都會觸發一次額外的 `rel_impact` 任務（多一輪
  system/verify/reflect），這是正確行為不是雜訊，寫測試時要預先算好
  腳本數量或直接用 `.count(...)` 斷言而不是精確比對整個 list。
- 單元測試（不需要真的跑 agent 狀態機的）用 `unittest.TestCase`
  （見 `test_llama_client.py`、`test_web_automation.py`）或純 pytest
  function 都可以，這個專案兩種風格併存，跟著被測目標旁邊已有的檔案
  風格走就好。

---

## SYSTEM_PROMPT 目前的狀態（截至這份文件寫的時候）

`config.py` 的 `SYSTEM_PROMPT` 大約 4200 字元，每個工具只列一行摘要，
標 📖 的工具有額外文件在 `agent/tool_docs.py`，模型第一次真的呼叫該
工具時才自動夾帶。**新增工具時**：
1. `SYSTEM_PROMPT` 加一行摘要（跟著現有編號接下去）。
2. 如果這個工具規則複雜/容易用錯，在 `tool_docs.py` 的 `TOOL_DOCS` dict
   加一筆詳細說明，摘要那行加 📖 標記。
3. 在 `main.py` 的 `available_functions` dict 註冊實際的函式參照。
4. 簡單、一看參數名就懂的工具（例如 `move_mouse(x, y)`）不需要 📖，
   一行摘要就夠，不要為了「完整」硬寫文件、把 SYSTEM_PROMPT 撐大。

這個機制目前運作得不錯，SYSTEM_PROMPT 沒有隨著工具數量線性膨脹。
如果之後真的又開始變長，值得考慮的方向（還沒做，只是筆記）：
- 把工具清單本身也分類/分層，只在真的可能用到某類工具時才展開該類的
  一行摘要清單（例如「畫面操作類」「記憶類」「瀏覽器類」），而不是
  一次列出所有 40 幾個工具的一行摘要。
- 評估是否要把 `PLANNER_SYSTEM_PROMPT` / `THINKING_SYSTEM_PROMPT` /
  `VERIFY_SYSTEM_PROMPT` 等其他階段的 prompt 也做類似的懶加載——目前
  只有主要的工具清單做了，其他階段的 prompt 本來就比較短，還沒有急迫性。

---

## 已知限制（跟 README 同步，但這裡從「你要不要動手修」的角度寫）

- `web_automation.py`（CDP 瀏覽器自動化）、`llama_client.py`
  （llama.cpp 直接載入）、`vision_tools.py`（Florence-2/PaddleOCR）
  只有 mock 測試過，**這個沙盒環境沒有真的 Chrome/GPU/模型權重可以測**，
  如果使用者回報這幾個模組的實際執行問題，先假設是真實環境跟 mock
  假設不一致，不要無條件相信 mock 測試全過就代表沒問題。
- `forgetting_enabled` / `activation_enabled` 開關重啟後會回到關閉，
  這是刻意的（安全預設），不是忘記做持久化，除非使用者明確要求才需要改。
- 前端完全沒有測試。如果要開始補，`vitest` + `@testing-library/react`
  是最順的選擇（專案已經是 Vite，設定成本低）。

---

## 使用者的溝通習慣（給你抓語氣用）

- 訊息通常很短、跳著講，常常一句話裡塞好幾個不相關的需求，需要自己
  拆解成待辦清單處理，不用每個都回問，能合理判斷就先做。
- 傾向要「先做完再給我看」而不是「邊做邊報告細節」，交付時給簡潔的
  結果摘要就好，不需要逐步敘述思考過程（除非使用者主動問「為什麼」）。
- 對 bug 的描述常常很精簡（例如「不能對話」「vision不知道能不能用」），
  背後往往是更具體的技術問題，值得先自己動手重現/追蹤根因，
  而不是直接照字面意思猜一個小修法就交差。
- 常常同時人工在改 GitHub（自己動手，或透過別的工具/session），
  合併時的衝突通常代表雙方都在動同一塊邏輯，值得仔細看一下兩邊改了
  什麼、而不是無腦選一邊蓋過去。
