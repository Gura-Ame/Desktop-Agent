# 給接手這個專案的 AI 協作者（也就是未來的我自己）

這份文件不是給人類看的產品文件（那是 `README.md`），是寫給下一個接手這個
專案的 Claude 看的：假設你完全沒有這個 session 的記憶，剛 clone 下來，
使用者丟了一句話要你改東西——這份文件的目的是讓你不用重新踩過我踩過的坑。

---

## 交接筆記（讀這份文件的當下最優先看這裡）

這是一個橫跨非常多輪對話的巨大 session 留下的交接紀錄，上一個我（也就是
你）因為 context 太長被使用者主動截斷，很多東西做到一半。**先看這一段，
再看下面完整的文件內容**——下面的內容有些已經涵蓋這裡提到的東西，這裡
只是把「現在具體卡在哪」講清楚，避免你重新探索一次已經探索過的地方。

### 已經完成、測試全綠的功能（這些不用重做，但可以繼續往上疊）
- Agent 安全/權限系統（`agent/tool_permissions.py`，SAFE/MODERATE/DANGEROUS
  三級 + `PermissionManager`，`ask`/`ask_dangerous_only`/`auto` 三種策略）
- 等待工具（`tools/wait_tools.py`：`wait`、`wait_for_screen_stable`）
- 即時滑鼠鍵盤控制（`tools/input_tools.py`：`mouse_down`/`mouse_up`/
  `drag_mouse`/`scroll_mouse`/`press_key`/`key_down`/`key_up`/
  `release_all_held_inputs`）
- 全域緊急停止（`agent/emergency_stop.py`，快捷鍵預設 `ctrl+alt+shift+q`）
  ＋ `pyautogui.FailSafeException`（滑鼠甩到螢幕角落）也會真的中斷 agent
  （`agent/agent_tool_execution.py`），不會被通用例外處理吞掉
- 檔案搜尋（`tools/file_search.py`：`search_files_by_content` 內容搜尋、
  `find_files_by_name` 檔名搜尋，兩者都支援純關鍵字自動當子字串比對，
  預設 root_dir 是使用者家目錄不是 cwd）
- PowerShell/cmd 執行（`tools/shell_exec.py`，DANGEROUS 等級）
- 路徑導向的檔案上傳（`main.py` 的 `pick_files()`，跳原生檔案對話框，
  只傳路徑字串，不搬運內容、沒有大小限制——**不是** base64 上傳，那個
  設計已經被否決並移除了，如果你在舊 commit 歷史看到
  `tools/file_upload.py`/`save_uploaded_file` 相關的東西，那是被取代
  掉的舊設計，不要復原）
- 前端：VS Code console 合併（`src/lib/devConsoleBridge.ts`，只在
  `import.meta.env.DEV` 生效，前端 console 轉送到 `main.py` 的
  `log_from_frontend`）、剪貼簿修復（`::selection` CSS、Qt clipboard
  優先於 win32clipboard）、`ChatInput.tsx` 附加檔案按鈕
- 輕量思考步驟（`agent/agent_thinking.py`，`thinking_enabled`，預設
  **關閉**，Direct Mode 回覆前/Planner 規劃前先讓模型簡短想一次）
- 滑鼠鍵盤動作預覽 + 三段式閘門（`agent/agent_physical_input_preview.py`，
  `instant_input_enabled`，預設**關閉**＝預設會顯示預覽；`overlay.py` 新增
  `add_mouse_trajectory`/`add_typing_preview` 兩個真的用 QTimer 做動畫的
  方法——**這部分我沒辦法在沙盒裡實際看到畫面渲染結果，只驗證了邏輯層
  （閘門怎麼判斷、多久觸發），使用者說「我有空會測」，如果使用者回報
  預覽畫面有問題，從 `overlay.py` 的 `add_mouse_trajectory`/
  `add_typing_preview`/`paintEvent` 裡 `typing_preview` 分支開始查**）
- Task Tree 兩個真的很重要的 bug 修好了（截圖回報過的「任務樹一直拆」）：
  1. `agent_llm_client.py` 的 `_call_and_execute`（Task Tree 每個步驟
     執行都會走這裡）漏了 `_strip_routing_tag_for_display`，導致
     `<|direct|>` 標記外露成一堆重複文字。
  2. `agent_task_processor.py` 的 `_run_execute_and_verify_step` 組
     `step_prompt` 時完全沒有提到 `self.last_image_paths`，導致使用者
     先傳圖片、請求被升級成 Task Tree 之後，每個步驟都拿不到圖片，
     驗證一直失敗、越拆越多層卻怎麼拆都沒用。這是任務樹一直拆的**根因**，
     不是拆解邏輯本身有問題。
  詳見下面「踩過的坑」第 13 條。
- `webview_bootstrap.py` 的 `_EXPOSED_METHOD_NAMES` 這個坑踩了不只一次
  （見「踩過的坑」第 10、14 條）——**任何時候你在 `main.py` 加新的 JsApi
  方法，寫完方法本體的同一個改動裡，立刻去 `webview_bootstrap.py` 把
  名字加進 `_EXPOSED_METHOD_NAMES`，不要等全部做完再回頭補，非常容易忘記**。
- 統一的彩色/格式化 log 模組：新檔案 `logging_setup.py`（純 Python
  內建 `logging` + 自己手刻 ANSI color code，沒有引入 colorama/rich 這類
  新依賴），提供一個 `log(message, level="info", channel=None)` 函式。
  **已經**把 `agent/agent_core.py` 的 `AgentWorker.emit()` 接上：現在每次
  `emit("log", ...)` 送一則訊息給前端 LogPanel 顯示的同時，也會呼叫
  `logging_setup.log(...)` 印到 stdout（channel="agent"），這就是「把
  面板 log 併到 VS Code console」這個需求**已經完成的部分**。

後端目前 51 個測試檔（`ls tests/test_*.py | wc -l`）、400+ 案例；前端
50 個。全部綠燈，收尾前務必自己重新跑一次確認（見下面「開工前一定要做
的事」的指令）。

### 沒做完、明確是 backlog 的東西（照優先度／使用者原話列出）

1. **`logging_setup.py` 還沒掃過全專案**——目前只有 `AgentWorker.emit()`
   接上了，下面這些檔案裡的裸 `print()` 呼叫**還沒換成 `log(...)`**，
   使用者原話是「把專案log全部都用能格式化並且有顏色的輸出moduale格式化」，
   這件事只完成了一小部分：
   ```
   main.py:192, 202, 258
   webview_bootstrap.py:59, 95, 97, 105, 107, 135, 149, 204
   agent/task_system.py:161
   agent/llama_client.py:149, 155, 162, 164
   tools/screen_tools.py:122
   ```
   換法很單純：`from logging_setup import log`（注意這些檔案有的在
   `agent/`/`tools/` 子目錄下，import 路徑寫法比照這些檔案裡已經有的
   `from config import ...`），把 `print(f"...")` 換成
   `log(f"...", level=?, channel=?)`——level 用 `error`/`warning`/`info`
   依原本訊息語氣判斷（有 `[錯誤]`/`失敗` 字樣的通常是 error 或
   warning），channel 可以留空或用 `"webview"`（webview_bootstrap.py）。
   `agent/tool_docs.py` 裡有幾個 `print(` 是**文件字串裡的範例文字**，
   不是真的 print() 呼叫，不要誤改。`run_all_tests.py` 的 print() 是
   這支腳本本身的正式輸出（給人類直接看跑測試結果的），**故意**保持
   原樣，不要動。

2. **檔案屬性讀取工具**（使用者原話「增加讓agent可以讀file屬性」）——
   完全沒開始。合理設計：在 `tools/file_search.py` 或新開一個
   `tools/file_info.py`，加一個 `get_file_info(path)` 之類的函式，回傳
   檔案大小、建立/修改時間、是不是目錄、副檔名、可讀/可寫/可執行權限。
   應該分類成 SAFE（純讀取）。記得同步 `main.py` 的 `available_functions`、
   `config.py` 的工具清單（目前編到 56 號）、如果邏輯夠複雜要在
   `agent/tool_docs.py` 加 📖 文件、`agent/tool_permissions.py` 的
   `TOOL_RISK_LEVELS`。可以參考 `find_files_by_name`（同一個檔案裡）的
   現有風格：純函式、找不到/參數錯一律回傳說明性字串而不是拋例外。

3. **「細分權限系統」**——使用者原話很模糊，我沒有進一步追問就先擱置了。
   目前的權限系統只依「工具名稱」分 SAFE/MODERATE/DANGEROUS 三級，不看
   參數內容（`tool_permissions.py` 開頭有寫為什麼刻意不做參數層級的
   黑名單分析）。如果使用者接下來提到這個，**先問清楚**他想要的是：
   (a) 更多分級（例如四級、五級），還是
   (b) 某些工具現在的分類不合理想調整，還是
   (c) 想要參數層級的細分（前面已經有架構理由說明為什麼目前刻意不做），
   還是
   (d) 其他完全不同的意思（例如想要每個工具個別開關，而不是三個統一
   等級共用一套策略）。
   不要自己腦補方向直接開工，這個詞太模糊，之前已經因為誤解需求類似的
   模糊指示（權限系統剛推出時）炸過一次測試套件（見「踩過的坑」第 9 條），
   這次應該先問。

4. **TASKLIST / "plan for user"**——使用者原話：「還有agent的TASKLIST跟
   plan for user」，同樣沒有進一步展開，我也還沒動手，甚至還沒想清楚
   使用者具體想要什麼。我的猜測（**沒有跟使用者確認過，不要直接當成
   需求開工**）：
   - 可能是想要一個獨立於現有 Task Tree DSL（`agent/task_system.py`，
     那套是拿來給 agent 自己執行任務用的，有 need_confirm/信心值/驗證
     這些執行引擎才需要的欄位，UI 也是設計成「執行進度追蹤」）之外、
     更輕量的「待辦清單」，類似其他 coding agent（例如 Claude Code 的
     TodoWrite）那種：agent 開始做一件多步驟的事之前，先列一個純文字的
     checklist 給使用者看「我打算做這些事」，做完一項打勾一項，讓使用者
     有進度感、不用理解 Task Tree 那套比較複雜的 DSL 格式。
   - 也可能是「plan for user」單獨指：在 Task Tree 真的開始執行前，
     現有的 `ask_confirm` 事件（`agent_routing.py` 裡 `self.emit(
     "ask_confirm", self.engine.render_tree_markdown())`）已經會把整棵
     Task Tree 的 Markdown 呈現給使用者確認——如果使用者不滿意的是這個
     呈現方式（例如覺得太技術性、想要更口語化的「一句話講清楚等一下要
     做什麼」摘要），那是另一個方向：在 `ask_confirm` 之前，多呼叫一次
     LLM（可能可以重用 `agent_thinking.py` 那套 `generate_prethink`
     的呼叫模式）產生一段人話摘要，跟著 Task Tree Markdown 一起顯示。
   兩種猜測都要動到前端（新的訊息類型、新的 UI 元件，比照
   `PermissionRequestMessage.tsx`/`TaskTreeMessage.tsx` 的模式）+ 後端
   （新的 event 類型、可能新的 available_functions 工具）。**強烈建議
   下一輪先跟使用者確認到底是哪一種、或完全不同的第三種，再動工**，
   這個功能牽涉的改動面很廣，猜錯方向會浪費很多輪。

5. **`screen_tools.py` 的無障礙 API 強化**（"盲人用的 API" 那個需求）——
   這個很特別：**它其實已經被實作過一次，但因為某次 session 中斷，
   那份改動沒有真的被保留下來**（我在這個 session 中途發現
   `tools/screen_tools.py` 沒有 `_accessible_name`/`_describe_state`
   這兩個函式，代表那次的成果遺失了，git clone 下來的最新版本也沒有）。
   如果使用者又提到「螢幕讀取抓不到圖示按鈕」「read_screen_api 漏掉
   東西」這類問題，設計方向是：
   - `_accessible_name(elem, fallback_text)`：優先讀 UIA 的
     `elem.element_info.name`（螢幕報讀器唸的那個名字），抓不到才退回
     `elem.window_text()`——解決「圖示按鈕只有 icon、沒有可見文字，
     window_text() 是空字串」導致整個元件被漏掉的問題。
   - `_describe_state(elem)`：盡量抓 `is_enabled()`/`get_toggle_state()`
     （勾選狀態）/`is_selected()`/`has_keyboard_focus()`，每個都要
     個別包 try/except（不是每種控制項都支援每種查詢），抓不到就跳過
     那個欄位而不是整個元件都不回報。
   - `_should_report_element(text, accessible_name, state, elem_type)`：
     決定要不要把這個元件放進結果——原本的邏輯只看「window_text 是不是
     非空」，會漏掉圖示按鈕；改成「有文字/名稱，或有抓到任何狀態，或
     類型本身是常見互動控制項（button/checkbox/...）」三者任一成立
     就收。
   測試策略：這個沙盒沒有 pywinauto、沒有真的 Windows UI，測試要用
   duck-typing 的假 element 物件（不需要真的 pywinauto），並且要先
   `sys.modules` 塞假的 `pywinauto`/`pyautogui` 模組才能 import
   `tools/screen_tools.py`（因為它頂層 `from pywinauto import Desktop`）。
   如果你要重做這個，之前已經寫過的假模組安裝工具可以重用：
   `tests/_fake_pyautogui.py` 已經存在，你可能需要另外建一個
   `tests/_fake_pywinauto.py`（如果 git 版本裡沒有的話，用同樣的模式：
   一個 `ensure_fake_pywinauto()` 函式，塞一個有 `Desktop` 屬性的空殼
   模組進 `sys.modules`）。

### 這個 session 犯過、值得提醒下一個你的錯誤（不是程式碼坑，是流程坑）
- 曾經誤以為 `ask_user` 沒有被註冊成可呼叫的工具，因為沒有看完
  `agent_core.py` 的 `__init__` 全文就下結論——後來發現其實已經註冊了，
  白白修了一個不存在的 bug。**診斷任何「這個功能好像沒接上」之前，先用
  `grep`/`view` 把相關檔案完整看過一遍，不要看了一半就下定論**。
- 曾經一次把 46 個工具（尤其是測試裡常用的 `run_action`）都判成
  DANGEROUS，直接讓十幾個既有測試卡死（不是失敗，是真的 hang 住）——
  因為新加的權限系統預設策略是 ASK，而測試沒有人會去回應那個等待。
  **任何會改變「工具呼叫預設行為」的新機制，上線前一定要想清楚會不會讓
  現有測試 hang 住，不是只看會不會「失敗」**（hang 住比失敗更難排查，
  會一路卡到 pytest 逾時或你自己手動中斷）。這個專案已經裝了
  `pytest-timeout`，`pytest tests/ --timeout=250` 可以避免意外 hang 住
  拖垮整個 debug 過程。

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
   目前應該是全綠（51 個檔案、400+ 案例）。如果 pull 下來就有紅的，
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
| `agent_thinking.py` (`AgentThinkingMixin`) | 可開關的輕量思考步驟（`generate_prethink`），預設關閉 |
| `agent_physical_input_preview.py` (`AgentPhysicalInputPreviewMixin`) | 滑鼠/鍵盤動作預覽 + 三段式閘門（`_gate_physical_input`），預設顯示預覽 |

`agent/tool_permissions.py` 不是 Mixin，是獨立模組（風險分級表 +
`PermissionManager`），被 `agent_core.py` 組合進 `AgentWorker` 當一個
屬性（`self.permission_manager`），不是繼承進去的——它管的是「單一工具
呼叫」層級的安全邊界，跟上面那些管「對話/任務流程」的 Mixin 是不同性質
的關注點，混進 Mixin 繼承鏈裡反而會讓人搞混兩者的差異。

`agent/emergency_stop.py` 也不是 Mixin，是純函式模組（全域快捷鍵的
註冊/取消，`start_emergency_stop_listener`/`stop_emergency_stop_listener`），
`AgentWorker._init_emergency_stop()` 呼叫一次，把 callback 綁定成
`self.request_stop`。刻意設計成「怎麼觸發」（全域快捷鍵）完全不知道
「觸發了要做什麼」，方便獨立測試（`tests/test_emergency_stop.py` 用假的
`keyboard` 模組）。

`logging_setup.py`（跟 `config.py` 同一層，不在 `agent/` 底下）是整個
專案共用的彩色/格式化 log 模組，提供一個 `log(message, level="info",
channel=None)` 函式。`AgentWorker.emit()`（`agent_core.py`）對 "log"
事件類型會額外呼叫這裡的 `log()`，讓面板 log 也印到 stdout（VS Code
Debug Console 看得到）。**這個模組本身已經完成，但目前只有 `emit()`
接上了，專案裡其餘的裸 `print()` 呼叫還沒換過去**——完整清單見最上面
「交接筆記」的 backlog 第 1 項。

`agent/agent_protocol.py` 是給 pyright 用的型別 stub（`AgentWorkerBase`，
方法本體全是 `...`），**改了哪個 Mixin 的方法簽名，記得同步更新這裡**，
不然型別檢查會失準（但不影響 runtime，pytest 不會抓到這個）。

`agent/agent_execution_cycle.py` 現在只是相容 shim（組合
`AgentRoutingMixin` + `AgentTaskProcessorMixin` + `AgentReflectionMixin`），
新程式碼不需要再 import 它。

**`AgentWorker.__init__` 本身拆成好幾個私有階段方法**（
`_init_memory_subsystem` / `_register_available_functions` /
`_init_llm_client` / `_init_session_state` / `_init_permission_manager` /
`_init_emergency_stop` / `_init_thinking` / `_init_instant_input`——
這份清單會隨新功能持續變長，上面列的是這份文件寫的時候的完整清單，
如果你又加了新的 `_init_*` 方法，記得也回來更新這裡的清單），純粹是把
「建構順序」變成「有名字的步驟」，不影響任何屬性名稱或外部行為。
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

### 13. Task Tree 步驟執行（`_call_and_execute`）漏掉兩件事：標記濾除、附圖上下文
使用者拿截圖回報過一個案例：上傳圖片問「這個圖片的 OCR」，結果任務樹
一直拆解（1 個子任務拆成 4 個又拆成 8 個），而且同一則聊天泡泡裡出現
一堆 `<|direct|>` 字樣。追下去是兩個各自獨立、但表現出來很像同一個問題
的漏洞：

1. **標記沒被濾掉**：`agent_routing.py` 的 `_run_idle_routing` 跟
   `agent_direct_mode.py` 的工具迴圈，呼叫 `_call_llm_stream` 之後都會
   接著呼叫 `self._strip_routing_tag_for_display(content)` 把
   `<|direct|>`/`<|plan|>` 從畫面上濾掉——但 Task Tree 每個步驟執行走的
   `_call_and_execute`（`agent_llm_client.py`）漏了這一步。Task Tree
   重試同一個步驟時，每次呼叫都會再吐一次帶標記的內容，沒有任何一個
   路徑幫忙濾掉，疊在同一個泡泡裡看起來就是一堆標記字樣。
2. **附圖路徑沒有傳進去**：`self.last_image_paths`（暫存圖片路徑）已經
   在 `agent_routing.py`/`agent_direct_mode.py` 里被拿來提醒模型「上一輪
   有附圖，路徑在這裡，不要說沒收到」，但 Task Tree 的步驟執行完全是
   純文字 prompt（`_run_execute_and_verify_step` 組出來的 `step_prompt`），
   從來沒有提到過 `last_image_paths`。如果使用者先傳圖片、這個請求才被
   判定需要完整規劃，圖片本身在升級的那一刻就跟這個純文字流程斷開了，
   之後每個步驟都只能回答「沒有收到圖片」，驗證當然一直失敗——**這才是
   任務樹一直拆解的根本原因，不是拆解邏輯本身有問題，是拆出來的每個
   子任務一樣拿不到圖片，怎麼拆都沒用**。

兩個都已修好：`_call_and_execute` 補上 `_strip_routing_tag_for_display`；
`_run_execute_and_verify_step` 組 `step_prompt` 時，比照 agent_routing.py
的做法把 `last_image_paths` 寫進去。**這提醒一個更通用的原則**：任何新增
的「會呼叫 `_call_llm_stream`/`_call_llm` 產生要顯示給使用者看的內容」的
路徑，都要記得檢查是不是也需要標記濾除跟附圖上下文提醒——這兩件事目前
是分散在各自呼叫點手動加的，沒有一個統一的入口保證新路徑不會漏掉。

### 14. `webview_bootstrap.py` 的 `_EXPOSED_METHOD_NAMES` 是持續性的坑，不是一次性修好就沒事
第 10 條記錄過這個 allowlist 第一次讓我踩雷（`respond_permission`/
`set_permission_mode`/`pick_files`/`log_from_frontend` 全部忘記加）。
這次加 `set_thinking_enabled`/`set_instant_input_enabled` 時，即使已經
「知道」這個坑，還是得每一次都刻意檢查、手動加——這不是那種修一次就
永久解決的 bug，是**新增任何 JsApi 方法都會重新面臨一次的固定步驟**。
`tests/test_webview_bootstrap_exposure.py` 能防止「忘記加」被合併進去
都測試沒過，但沒辦法讓人「想起來要做這件事」——加新 JsApi 方法前，
先把這條筆記讀一遍可能比較有用：**寫 `main.py` 新方法的同一個改動裡，
就順手把名字加進 `webview_bootstrap.py` 的 `_EXPOSED_METHOD_NAMES`，
而不是寫完方法本體再回頭補**，順序反過來很容易忘記後半段。

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
  一次列出所有 56 個工具的一行摘要。
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
