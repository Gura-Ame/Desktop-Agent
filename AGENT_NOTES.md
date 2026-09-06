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
   目前應該是全綠（43 個檔案、320+ 案例）。如果 pull 下來就有紅的，
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

`agent/tool_permissions.py` 不是 Mixin，是獨立模組（風險分級表 +
`PermissionManager`），被 `agent_core.py` 組合進 `AgentWorker` 當一個
屬性（`self.permission_manager`），不是繼承進去的——它管的是「單一工具
呼叫」層級的安全邊界，跟上面那些管「對話/任務流程」的 Mixin 是不同性質
的關注點，混進 Mixin 繼承鏈裡反而會讓人搞混兩者的差異。

`agent/agent_protocol.py` 是給 pyright 用的型別 stub（`AgentWorkerBase`，
方法本體全是 `...`），**改了哪個 Mixin 的方法簽名，記得同步更新這裡**，
不然型別檢查會失準（但不影響 runtime，pytest 不會抓到這個）。

`agent/agent_execution_cycle.py` 現在只是相容 shim（組合
`AgentRoutingMixin` + `AgentTaskProcessorMixin` + `AgentReflectionMixin`），
新程式碼不需要再 import 它。

**`AgentWorker.__init__` 本身拆成 4 個私有方法**（`_init_memory_subsystem`
/ `_register_available_functions` / `_init_llm_client` / `_init_session_state`），
純粹是把「建構順序」變成「有名字的步驟」，不影響任何屬性名稱或外部行為。
加新的記憶子系統物件放 `_init_memory_subsystem`；新增 agent 自己擁有、
要登記進 `available_functions` 的方法（不是 main.py 那種桌面自動化工具）
放 `_register_available_functions`；只在一次 process 生命週期內有意義的
執行期狀態（不用跨 session 存活的那種）放 `_init_session_state`。
`tests/test_agent_worker_bootstrap.py` 專門釘住這四個方法各自該做的事，
改動時記得跟著看一下。

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

### 8. `request_stop()` 會讓 `ask_user`/`request_tool_permission` 的「使用者按停止」路徑變成死碼
`ask_user()`/`request_tool_permission()` 的等待迴圈長這樣：
```python
while self.is_paused_for_xxx:
    if self._stop_event.is_set():
        raise InterruptedError(...)
    time.sleep(0.1)
```
`request_stop()` 會**同時**設定 `_stop_event` 跟把 `is_paused_for_xxx`
直接設回 `False`。如果 `is_paused_for_xxx` 被清掉的時機比迴圈下一次檢查
`_stop_event` 還早（幾乎每次都是這樣，兩行是緊接著執行的），`while`
條件本身就先變成 `False` 讓迴圈正常結束，迴圈**裡面**那個 `raise` 永遠
不會被跑到——結果變成使用者按了停止，`ask_user()` 卻回傳一句看起來像
正常使用者回覆的字串（`"[系統] 使用者已停止 Agent"`），而不是真的中斷。
這是加權限系統時，測 `request_tool_permission` 才意外發現 `ask_user`
也有同一個問題（兩邊等待迴圈是同一種寫法）。**修法：迴圈跑完之後，
在使用迴圈跑出來的結果之前，再補一次一模一樣的 `_stop_event` 檢查**——
不管迴圈是正常等到回覆結束的，還是被 `request_stop()` 提前清旗標結束的，
都會被這第二次檢查攔到。以後任何「等一個旗標被清掉」的暫停/恢復模式，
如果 `request_stop()` 也會去清那個旗標，都要留意同樣的競態，別只在迴圈
內部檢查停止訊號。見 `tests/test_stop_interrupts_waits.py`。

### 9. 新增一個會被 `<|tool_call|>` 呼叫到的工具，測試要考慮權限系統的暫停
`agent/tool_permissions.py` 的權限系統上線後，任何**沒有明確分類**的工具
名稱（`TOOL_RISK_LEVELS` 裡找不到）預設一律當作 `DANGEROUS`，在預設的
`PermissionMode.ASK` 策略下第一次呼叫都會暫停等待授權。這代表：
- 舊測試裡任何用假的 LLM 腳本驅動 `<|tool_call|>run_action(...)`（或其他
  測試用的假工具名稱）的地方，如果那個 agent instance 的權限模式沒有被
  切成 `PermissionMode.AUTO`，**測試會直接 hang 住**，不是失敗、是卡住
  等一個永遠不會來的授權回應，pytest 沒有預設逾時的話會一路卡到你自己
  按 Ctrl+C。上線這個系統的當下，`tests/test_agent_core_helpers.py` 的
  `make_agent()`、`tests/test_code_graph_integration.py`/
  `tests/test_memory_tools.py`/`tests/test_execute_tools_inline.py` 各自
  的本地 `make_agent()`、以及 `test_value_judgment.py` 都因為這樣需要
  補一行 `agent.permission_manager.set_mode(PermissionMode.AUTO)`。
- **判斷一個測試會不會中招的方法**：看它會不會透過 `_execute_tools`
  執行到一個「不是 SAFE 等級」的工具名稱——包含 `AgentWorker.__init__`
  一定會自動注入的 `remember`/`relate`/`record_observation`/
  `build_code_graph*`（這幾個是 MODERATE，不是自己傳進建構子的
  `available_functions` 參數才需要注意，就算建構子傳 `{}` 也一樣會有
  這幾個方法）。純粹呼叫 Python 方法本身（例如測試直接呼叫
  `agent.remember(...)`，不透過 `<|tool_call|>` 文字解析）不會經過
  這道關卡，不受影響。
- 專案已經裝了 `pytest-timeout`（`pip install pytest-timeout`），用
  `pytest tests/ --timeout=250` 執行可以讓任何意外的 hang 在合理時間內
  失敗並印出卡在哪一行，而不是無限期卡住——懷疑新測試可能卡住時，
  先這樣跑一次縮小範圍，比盯著沒有任何輸出的終端機猜快很多。
  `tests/test_reverse_index.py` 的規模測試本身就需要 180 秒以上，
  是正常的慢，不是 hang，用太短的 timeout（例如 20 秒）跑全套件會誤殺它。

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
- 任何新的 `AgentWorker(...)` 建構之後，如果測試會透過 `<|tool_call|>`
  文字驅動工具執行（不是直接呼叫 Python 方法），記得呼叫
  `agent.permission_manager.set_mode(PermissionMode.AUTO)`——原因見
  上面「踩過的坑」第 9 條，不然多半會直接 hang 住而不是測試失敗。

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

`tools/file_search.py` 的 `search_files_by_content`（grep 風格的跨檔案
文字搜尋）、`find_files_by_name`（依檔名找）跟 `tools/shell_exec.py` 的
`run_powershell`/`run_cmd`（43-46 號工具）都是照著上面 4 個步驟加進去的
具體範例：純函式、無狀態，所以直接放進 `tools/automation_tools.py`
統一匯出，走 `main.py` 的 `available_functions` 註冊，不是掛在
`AgentWorker` 的 mixin 上（跟 `remember`/`build_code_graph` 這種需要
`self.memory_store` 的工具是不同類別——會不會用到 agent 自己的狀態，
決定它該是裸函式還是 mixin 方法）。`run_powershell`/`run_cmd` 額外要記得
的一步：在 `agent/tool_permissions.py` 的 `TOOL_RISK_LEVELS` 補上風險等級
（這兩個是 `DANGEROUS`，跟 `execute_python` 同級）——這一步不在上面 4 步
清單裡，但凡是「能執行任意程式碼/系統指令」等級的新工具都必須補，
不然會被 `DEFAULT_RISK` 這個安全預設值擋著問一次（那本身不是壞事，
但明確分類比依賴預設值更清楚，讀程式碼的人不用猜這是不是漏分類了）。
如果之後真的又開始變長，值得考慮的方向（還沒做，只是筆記）：
- 把工具清單本身也分類/分層，只在真的可能用到某類工具時才展開該類的
  一行摘要清單（例如「畫面操作類」「記憶類」「瀏覽器類」），而不是
  一次列出所有 46 個工具的一行摘要。
- 評估是否要把 `PLANNER_SYSTEM_PROMPT` / `THINKING_SYSTEM_PROMPT` /
  `VERIFY_SYSTEM_PROMPT` 等其他階段的 prompt 也做類似的懶加載——目前
  只有主要的工具清單做了，其他階段的 prompt 本來就比較短，還沒有急迫性。
- 這次加權限系統時，在工具清單前面多加了一小段「有些工具會先暫停問
  授權」的說明（見 `config.py` 工具清單前的段落），讓 SYSTEM_PROMPT
  又長了幾行——這是目前唯一一次為了「非工具本身」的原因而加長它，
  值得留意這類系統層級說明會不會之後越疊越多，該考慮搬去 `tool_docs.py`
  用 📖 懶加載（例如放在 `ask_user` 或第一個 DANGEROUS 工具的文件裡），
  而不是放在所有請求都會看到的固定開頭段落。

---

## 已知限制（跟 README 同步，但這裡從「你要不要動手修」的角度寫）

- `web_automation.py`（CDP 瀏覽器自動化）、`llama_client.py`
  （llama.cpp 直接載入）、`vision_tools.py`（Florence-2/PaddleOCR）、
  `shell_exec.py`（PowerShell/cmd）只有 mock 測試過，**這個沙盒環境沒有
  真的 Chrome/GPU/模型權重/Windows shell 可以測**（`shell_exec.py` 的
  測試全部用 `unittest.mock` 把 `subprocess.run` 換掉，驗證的是 wrapper
  自己的行為，不是 PowerShell/cmd 本身），如果使用者回報這幾個模組的
  實際執行問題，先假設是真實環境跟 mock 假設不一致，不要無條件相信
  mock 測試全過就代表沒問題。
- ~~`forgetting_enabled` / `activation_enabled` 開關重啟後會回到關閉~~
  **已修復**：兩個開關現在存在 `MemoryStore` 的 JSON 檔案裡（`"__settings__"`
  區塊），重啟會恢復成上次關掉之前的狀態，不再需要使用者每次都重新打開。
  `permission_mode`（工具授權策略）比照同一套機制，也持久化了。
- ~~前端完全沒有測試~~ **已補上一部分**：`vitest` + `@testing-library/react`
  基礎設施在了（`npm run test`），涵蓋 `parseTaskTree`、`TaskTreeCard`
  的需確認徽章規則、`useAgentEventHandler` 的 chunk/chunk_patch 與
  `permission_request` 事件、`PermissionRequestMessage` 授權卡片、
  `ChatMessage` 拆完之後的整體組裝、以及 `useSidebarAutoCollapse` /
  `useServerHealth` / `useMessageComposer` 這三個從 `App.tsx` 拆出來的
  hook。還沒覆蓋：`SideBar` 系列（除了 `PermissionModeCard` 沒有獨立
  測試）、`ChatInput`、Markdown/KaTeX 顯示。
- Retriever 的關鍵字比對偏簡單（n-gram + 字串比對），沒有語意 embedding——
  要做真的語意檢索需要額外引入 embedding 模型，對一般使用者機器的安裝
  體積/記憶體/啟動時間都會有明顯影響，這是需要跟使用者討論過才能動的
  架構決策，不要自己單方面加進去。
- 權限系統（`tool_permissions.py`）目前只有「工具名稱」這個維度的分級，
  沒有依「參數內容」再細分風險（例如 `run_powershell("Get-Date")` 跟
  `run_powershell("Remove-Item -Recurse C:\\")` 目前被問的方式完全一樣，
  都是「這個工具本身是 DANGEROUS，問一次、之後這個工作階段都放行」）。
  這是刻意的取捨，不是漏做：分析參數內容是不是危險，本質上就是黑名單/
  規則比對，維護成本高又注定有漏洞，見 `tool_permissions.py` 開頭的說明。
  如果之後要做得更細，方向應該是「授權卡片裡把完整參數內容顯示清楚，
  讓使用者自己判斷」（目前 `PermissionRequestMessage` 已經有顯示 `args`），
  而不是程式自己嘗試判斷一段指令字串安不安全。

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
