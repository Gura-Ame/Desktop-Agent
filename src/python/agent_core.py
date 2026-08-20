import re
import ast
import time
import json
import difflib
import threading
from enum import Enum
from openai import OpenAI

from config import (
    API_BASE_URL, API_KEY, MODEL_NAME, SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT, REFLECT_SYSTEM_PROMPT,
    THINKING_SYSTEM_PROMPT, VERIFY_SYSTEM_PROMPT, DECOMPOSE_SYSTEM_PROMPT,
    VALUE_JUDGMENT_PROMPT,
)
from task_system import TaskEngine, ExecutionMode, TaskStatus, TaskNode
from memory_store import MemoryStore
from working_memory import WorkingMemory
from context_compressor import ContextCompressor
from code_graph import CodeGraphBuilder
from code_impact import queue_impact_check_tasks
from relation_impact import queue_relation_impact_tasks

# 單一任務連續驗證失敗超過這個次數，就不再自己悶著頭重試，改為向使用者提問
MAX_RETRY_PER_TASK = 3

# 有些本地模型（尤其是量化過的小模型）在多輪對話格式沒套用好、或本身能力不夠時，
# 會自己把「使用者：」「助理：」這種角色標籤也一起生成出來，變成自問自答停不下來。
# 這裡不管哪個 prompt 類別都一律帶上，當作最後一道安全網——正常情況下不會被觸發，
# 一旦模型開始寫出這些標籤，立刻在那裡截斷，而不是讓它繼續失控生成下去。
STOP_SEQUENCES = ["\nUSER:", "USER:", "\nASSISTANT:", "ASSISTANT:", "\n使用者:", "\n使用者："]
# 同樣是防失控用的硬上限，不是正常操作的長度限制；正常回應遠遠用不到這麼多。
MAX_RESPONSE_TOKENS = 2048

# 混合記憶：self.history 只維持這麼多則訊息當作「常駐視窗」，維持當下對話的直接連續性；
# 超過的部分每一輪都會被主動濃縮進硬記憶，不是被動等 token 成長超過門檻才觸發。
# 設成 2（也就是只留最近一次來回）是刻意的：像人腦一樣，短期記憶只留「當下這一刻」，
# 其餘一律交給長期記憶負責，盡量把依賴壓在硬記憶這一邊，不是靠 context 硬撐。
HYBRID_WINDOW_MESSAGES = 2

# self.history 存進 MemoryStore 時固定用這個 id（開頭底線代表這是系統內部用的節點，
# 不是模型透過 remember 建立的一般記憶）。
HISTORY_NODE_ID = "_conversation_history"


class AgentState(Enum):
    IDLE = "IDLE"
    WAITING_CONFIRM = "WAITING_CONFIRM"
    EXECUTING = "EXECUTING"


class AgentWorker:
    def __init__(self, available_functions: dict, event_callback, default_mode=ExecutionMode.STEP_BY_STEP,
                 memory_path: str = "agent_memory.json", memory_max_nodes: int = 20):
        self.available_functions = available_functions
        self.available_functions["ask_user"] = self.ask_user

        # 長期記憶：Disk (MemoryStore，落地成 JSON) + Working Memory (in-memory，有上限)
        # 這四個工具是給 LLM 自己在對話/任務執行過程中主動呼叫的，不是背景自動做的事。
        self.memory_store = MemoryStore(memory_path)
        self.working_memory = WorkingMemory(self.memory_store, max_nodes=memory_max_nodes)
        self.context_compressor = ContextCompressor(self.memory_store)
        self.available_functions["remember"] = self.remember
        self.available_functions["recall"] = self.recall
        self.available_functions["relate"] = self.relate
        self.available_functions["recall_related"] = self.recall_related
        self.available_functions["search_memory"] = self.search_memory
        self.available_functions["record_observation"] = self.record_observation
        self.available_functions["recall_observation"] = self.recall_observation
        self.available_functions["recall_with_event"] = self.recall_with_event

        # 程式碼呼叫關係圖：跟 memory_store 共用同一份 Disk，
        # 這三個是給模型主動查詢用的；「改了 X，誰會受影響」的插入任務則是系統自動做的，
        # 見 _auto_queue_impact_checks，不依賴模型自己記得要講。
        self.code_graph = CodeGraphBuilder(self.memory_store)
        self.available_functions["build_code_graph"] = self.build_code_graph
        self.available_functions["build_code_graph_for_project"] = self.build_code_graph_for_project
        self.available_functions["find_callers"] = self.find_callers
        self.available_functions["find_callees"] = self.find_callees

        self.event_callback = event_callback

        self.base_url = API_BASE_URL
        self.api_key = API_KEY
        self.model_name = MODEL_NAME
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=90.0)
        self.engine = TaskEngine(mode=default_mode)
        self.state = AgentState.IDLE

        self.current_user_prompt = ""
        # 使用者本輪附上的圖片 data URL 列表（OpenAI vision 格式）
        self.current_images = []
        # 混合記憶：self.history 只是「當下對話的常駐視窗」，會主動維持在很小的大小，
        # 不再是預設一路長大的地方；超過視窗大小的部分，每一輪都會被濃縮進硬記憶
        # （MemoryStore，同一份 JSON 檔案），重開程式後會從那裡讀回來，不會憑空消失。
        self.history = self._load_history()
        self.is_paused_for_input = False
        self.user_reply_content = ""
        self.max_think_limit = 3
        self._thread = None
        self._stop_event = threading.Event()
        self._active_stream = None
        self._last_finish_reason = None

    # ------------------------------------------------------------------
    # 基礎設施：事件、使用者輸入、狀態控制
    # ------------------------------------------------------------------
    def emit(self, event_type: str, payload: any):
        if self.event_callback:
            self.event_callback(event_type, payload)

    def ask_user(self, question: str) -> str:
        self.is_paused_for_input = True
        self.emit("waiting_input", question)
        self.emit("log", f"❓ Agent 提問等待中: {question}")
        while self.is_paused_for_input:
            if self._stop_event.is_set():
                raise InterruptedError("Agent 已由使用者停止")
            time.sleep(0.1)
        return f"User replied: {self.user_reply_content}"

    def request_stop(self):
        """前端呼叫：要求盡快停止目前執行，並強制關閉正在進行的 LLM stream。"""
        self._stop_event.set()
        # 若卡在 ask_user，一併解除等待
        self.is_paused_for_input = False
        self.user_reply_content = "[系統] 使用者已停止 Agent"
        # 強制關掉 OpenAI stream，中斷 HTTP 讀取
        stream = self._active_stream
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
            try:
                # httpx / openai 有些版本把 response 掛在 .response
                resp = getattr(stream, "response", None)
                if resp is not None:
                    resp.close()
            except Exception:
                pass
        self.emit("log", "[系統] 收到停止請求，正在中止 LLM stream…")

    def _should_stop(self) -> bool:
        return self._stop_event.is_set()

    # ------------------------------------------------------------------
    # 長期記憶工具：給 LLM 自己在對話/任務執行過程中呼叫
    # ------------------------------------------------------------------
    def remember(self, id: str, type: str, summary: str = "", properties: dict = None) -> str:
        node = self.memory_store.upsert_node(id, type, properties=properties or {}, summary=summary)
        self.working_memory.activate(id)
        self.emit("log", f"🧠 記住了 [{node.type}] {id}: {summary}")
        return f"已記住 {id}（{type}）: {summary or '(無摘要)'}"

    def recall(self, id: str) -> str:
        node = self.working_memory.activate(id)
        if not node:
            return f"沒有找到 {id} 這個記憶，可能還沒被 remember 過。"
        props = self.memory_store.get_effective_properties(id)
        rel_text = ", ".join(f"{r['rel']}->{r['target']}" for r in node.relations) or "(無)"
        return (
            f"[{node.type}] {id}\n"
            f"摘要: {node.summary or '(無)'}\n"
            f"屬性: {json.dumps(props, ensure_ascii=False)}\n"
            f"關聯: {rel_text}"
        )

    def relate(self, source_id: str, rel: str, target_id: str) -> str:
        self.memory_store.add_relation(source_id, rel, target_id)
        return f"已建立關聯: {source_id} -{rel}-> {target_id}"

    def record_observation(self, id: str, about_id: str, conclusion: str, confidence: float = 0.8) -> str:
        """記錄一次分析的結論，並記下當時目標物件的版本，之後可以判斷這個結論還新不新鮮。
        跟 remember 的差別：remember 是記事實本身，record_observation 是記「你對某個事實
        分析出來的結論」，而且自動掛上 ABOUT 關聯指向被分析的對象，之後可以用
        recall_observation 讀回來，並且會自動檢查有沒有過期。
        """
        if not self.memory_store.get_node(about_id):
            return f"找不到 {about_id}，要先用 remember 記住它，才能對它記錄 Observation。"
        obs = self.memory_store.record_observation(id, about_id, conclusion, confidence)
        self.working_memory.activate(id)
        self.emit("log", f"🔎 記錄了一個結論 [{id}]（關於 {about_id}）: {conclusion}")
        return f"已記錄結論 {id}（關於 {about_id}，信心值 {confidence:.2f}）: {conclusion}"

    def recall_observation(self, id: str) -> str:
        """讀回之前記錄的結論，會先檢查目標物件的內容有沒有變過。
        變過的話結論可能已經過期了，會明確提醒你，而不是悄悄把舊結論當成還有效的拿給你用。
        """
        node = self.memory_store.get_node(id)
        if not node or node.type != "Observation":
            return f"沒有找到 {id} 這個 Observation，可能還沒被 record_observation 記錄過。"
        self.working_memory.activate(id)
        conclusion = node.summary
        if self.memory_store.is_observation_stale(id):
            return (
                f"⚠️ 結論 {id} 可能已經過期了（它分析的對象內容已經變過）："
                f"{conclusion}（信心值 {node.confidence:.2f}，建議重新分析後用 record_observation 更新）"
            )
        return f"{id}（信心值 {node.confidence:.2f}，仍然新鮮）: {conclusion}"

    def recall_with_event(self, id: str, event_id: str) -> str:
        """查某個物件在特定事件情境下的屬性——先取得繼承後的屬性，再套用該事件對它的局部覆寫。
        例如「牛排」平常的溫度是 hot，但某次事件把它 override 成 cold，
        查那次事件情境下的牛排屬性，看到的就會是 cold，不影響牛排本身的預設屬性。
        """
        if not self.memory_store.get_node(id):
            return f"沒有找到 {id}，可能還沒被 remember 過。"
        if not self.memory_store.get_node(event_id):
            return f"沒有找到事件 {event_id}，可能還沒被 remember 過。"
        self.working_memory.activate(id)
        self.working_memory.activate(event_id)
        props = self.memory_store.get_properties_with_event_override(id, event_id)
        return f"{id} 在 {event_id} 這個情境下的屬性: {json.dumps(props, ensure_ascii=False)}"

    def recall_related(self, id: str, rel: str = None) -> str:
        outgoing = self.memory_store.get_outgoing(id, rel)
        incoming = self.memory_store.get_incoming(id, rel)
        for nid in outgoing + incoming:
            self.working_memory.activate(nid)
        return (
            f"由 {id} 指出去: {outgoing if outgoing else '(無)'}\n"
            f"指向 {id} 的: {incoming if incoming else '(無)'}"
        )

    def search_memory(self, keyword: str) -> str:
        """聯想式搜尋：不需要知道精確的 id，靠關鍵字大概想一下「這跟什麼有關」就能找到。
        找到的結果會自動 activate 進 Working Memory，不用再另外呼叫 recall。
        """
        matches = self.memory_store.search(keyword)
        if not matches:
            return f"沒有找到跟「{keyword}」有關的記憶。"
        for node in matches:
            self.working_memory.activate(node.id)
        lines = [f"- [{n.type}] {n.id}: {n.summary}" for n in matches]
        return f"找到 {len(matches)} 筆跟「{keyword}」有關的記憶：\n" + "\n".join(lines)

    # ------------------------------------------------------------------
    # 程式碼關聯圖工具：給 LLM 主動查詢用
    # ------------------------------------------------------------------
    def build_code_graph(self, filepath: str, module_name: str = None) -> str:
        try:
            func_ids = self.code_graph.build_from_file(filepath, module_name)
        except Exception as e:
            return f"建立程式碼關聯圖失敗: {e}"
        if not func_ids:
            return f"{filepath} 裡沒有解析到任何函式。"
        return f"已建立/更新 {len(func_ids)} 個函式節點: {', '.join(func_ids)}"

    def build_code_graph_for_project(self, root_dir: str) -> str:
        """跟 build_code_graph 的差別：這個會遞迴掃整個資料夾底下所有 .py 檔案，
        並解析 import，把跨檔案的呼叫關係也記下來（例如 a.py 呼叫了 from b import foo 的 foo）。
        """
        try:
            result = self.code_graph.build_project(root_dir)
        except Exception as e:
            return f"建立專案程式碼關聯圖失敗: {e}"
        total_files = len(result)
        total_funcs = sum(len(v) for v in result.values())
        if total_funcs == 0:
            return f"{root_dir} 底下掃了 {total_files} 個檔案，沒有解析到任何函式。"
        return f"掃了 {total_files} 個檔案，共建立/更新 {total_funcs} 個函式節點，跨檔案的呼叫關係也已經解析。"

    def find_callers(self, func_id: str) -> str:
        callers = self.code_graph.find_callers(func_id)
        if not callers:
            return f"沒有找到呼叫 {func_id} 的函式（可能它沒有被任何函式呼叫，或這個檔案還沒用 build_code_graph 建立過）。"
        return f"呼叫了 {func_id} 的函式: {', '.join(callers)}"

    def find_callees(self, func_id: str) -> str:
        callees = self.code_graph.find_callees(func_id)
        if not callees:
            return f"{func_id} 沒有呼叫任何已知函式（或這個檔案還沒用 build_code_graph 建立過）。"
        return f"{func_id} 呼叫了: {', '.join(callees)}"

    # 這些類型是內部記帳用的節點，本身不是「世界裡的物件」，不該觸發影響檢查連鎖反應：
    # History 是對話常駐視窗的存檔，Observation 有自己的過期檢查機制，兩者都不適用
    # 「改了它、誰的關聯要重新確認」這種語意。
    _IMPACT_CHECK_EXCLUDED_TYPES = ("History", "Observation")

    def _auto_queue_impact_checks(self, task: TaskNode):
        """任務完成後，看看它的標題/方法裡有沒有提到已知的記憶物件（不限類型），
        有的話自動查詢跟它有關聯的其他物件、插入「檢查是否受影響」的任務——
        不依賴模型自己記得要講，是系統根據已經建立好的關聯機械式判斷的。

        這個原則最早只用在程式碼函式的呼叫關係上（CALLS），現在泛化成任何物件、
        任何關聯類型都適用：只要曾經用 remember() 記住過、用 relate() 建過關聯，
        改到它的時候一樣會自動被查出來，不侷限於程式碼場景。

        用短名稱（去掉句點前綴）做關鍵字比對，因為任務標題通常只會寫物件本身的名稱
        （例如「修改 handle_login」），不會完整寫出 "auth.handle_login" 這種合格 id。
        這只是關鍵字比對，會有誤判風險（例如名稱剛好是常見詞），
        但最壞情況只是多插入幾個沒必要的檢查任務，不是漏掉真正受影響的關聯物件。
        """
        haystack = f"{task.title} {task.method}"
        for node_id, node in list(self.memory_store.nodes.items()):
            if node.type in self._IMPACT_CHECK_EXCLUDED_TYPES:
                continue
            short_name = node_id.split(".")[-1]
            if not short_name or not re.search(rf'\b{re.escape(short_name)}\b', haystack):
                continue

            if node.type == "Function":
                # 程式碼函式：沿用專門的呼叫關係圖 (CALLS)，措辭針對原始碼比對更精準
                inserted = queue_impact_check_tasks(self.engine, self.memory_store, node_id, task.id)
                reason = "根據呼叫關係圖"
            else:
                # 其他任何類型的物件：不限定關聯類型的通用版本
                inserted = queue_relation_impact_tasks(self.engine, self.memory_store, node_id, task.id)
                reason = "根據記憶裡的關聯"

            if inserted:
                self.emit(
                    "log",
                    f"[系統] [{task.id}] 提到了已知的 {node.type} {node_id}，"
                    f"{reason}自動插入 {inserted} 個影響檢查任務。"
                )

    def resume_with_user_input(self, text: str):
        self.user_reply_content = text
        self.is_paused_for_input = False

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_user_prompt(self, user_prompt: str, images=None):
        self.current_user_prompt = user_prompt
        self.current_images = list(images or [])

    def _build_user_content(self, text: str, images=None):
        """組成 OpenAI / llama.cpp 相容的 user content；有圖時用 multimodal parts。

        Qwen2-VL / llama.cpp 對 data URL 較穩；若只有 raw base64 會自動補前綴。
        """
        imgs = images if images is not None else []
        if not imgs:
            return text
        parts = [{
            "type": "text",
            "text": text or "Please describe what you see in the image in detail.",
        }]
        for url in imgs:
            if not url:
                continue
            # 確保是 data URL
            if not str(url).startswith("data:"):
                url = f"data:image/jpeg;base64,{url}"
            parts.append({
                "type": "image_url",
                "image_url": {"url": url},
            })
        self.emit("log", f"[系統] 本輪附圖 {len(imgs)} 張（multimodal）")
        return parts

    def set_execution_mode(self, mode: ExecutionMode):
        self.engine.mode = mode

    def _maybe_compress_history(self):
        """建立/檢查對話歷史的壓縮基準，超過門檻就自動壓縮。
        _run_inner 的推理階段跟 _run_direct_mode 的迴圈都要呼叫這個，
        不然像「先推理判斷難度」這種新架構，第一輪會直接繞過壓縮檢查。

        估算基礎裡刻意把 SYSTEM_PROMPT 也算進去——它本來就是每次都會送出去的固定成本，
        如果只拿空的 self.history 當基準，對話一開始 baseline 會被訂在接近 0，
        隨便一點內容就會誤判成「成長超過 120%」。

        觸發條件有兩個，任一成立就壓縮——這是混合記憶的核心：
        - token 成長超過基準的門檻（原本就有的，防止少數幾則超長訊息把 context 塞爆）
        - 訊息「數量」超過常駐視窗大小（新加的，即使每則訊息都很短，只要輪數夠多，
          一樣要主動把舊的濃縮掉，不是放著讓它一路長大，等哪天 token 才剛好超過門檻）。
        """
        estimate_basis = [{"content": SYSTEM_PROMPT}] + self.history
        self.context_compressor.establish_baseline(
            self.context_compressor.estimate_tokens(estimate_basis)
        )
        current_tokens = self.context_compressor.estimate_tokens(estimate_basis)
        over_token_budget = self.context_compressor.should_compress(current_tokens)
        over_message_window = len(self.history) > HYBRID_WINDOW_MESSAGES

        if over_token_budget or over_message_window:
            trigger = (
                f"token 成長超過門檻（約 {current_tokens} tokens）" if over_token_budget
                else f"訊息數量超過常駐視窗大小（{len(self.history)} > {HYBRID_WINDOW_MESSAGES}）"
            )
            self.emit("log", f"[系統] 對話上下文{trigger}，自動濃縮成結構化事實...")
            try:
                self.history = self.context_compressor.compress(self._call_llm, self.history)
                self._save_history()
                self.emit("log", "[系統] 壓縮完成，繼續對話。")
            except Exception as e:
                # 壓縮失敗不該讓整輪對話跟著中斷——保留原本沒壓縮的歷史，這輪繼續正常進行，
                # 下一輪還會再檢查一次要不要壓縮。
                self.emit("log", f"[警告] 自動壓縮失敗，暫時保留原本的對話歷史，稍後會再嘗試: {e}")

    def _load_history(self) -> list:
        """從硬記憶（MemoryStore）讀回上次留下的對話常駐視窗；沒有的話就是全新對話。"""
        node = self.memory_store.get_node(HISTORY_NODE_ID)
        if not node:
            return []
        messages = node.properties.get("messages", [])
        return messages if isinstance(messages, list) else []

    def _save_history(self):
        """把目前的常駐視窗存進硬記憶，重開程式後可以讀回來。

        存之前把圖片內容換成占位文字——圖片在當輪用完就沒有重複利用的價值，
        原封不動存進長期記憶只會讓 JSON 檔案被 base64 塞得又大又慢，不值得。
        """
        compact = []
        for m in self.history:
            content = m.get("content")
            if isinstance(content, list):
                new_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        new_parts.append({"type": "text", "text": "[圖片內容已省略，不重複保存]"})
                    else:
                        new_parts.append(part)
                compact.append({**m, "content": new_parts})
            else:
                compact.append(m)
        self.memory_store.upsert_node(HISTORY_NODE_ID, "History", properties={"messages": compact})

    def clear_conversation_history(self):
        """清空對話——連同硬記憶裡存的那份一起清掉，不然重開程式後又會讀回被「清空」的內容。"""
        self.history = []
        if self.memory_store.get_node(HISTORY_NODE_ID):
            self.memory_store.delete_node(HISTORY_NODE_ID)
        self.context_compressor.reset_baseline()

    def _similar_to_previous_reply(self, new_content: str, threshold: float = 0.6) -> bool:
        """這輪的回答跟上一輪 assistant 的回答比起來，重複度是不是高到像在原地打轉。

        用在「連續正常結束、沒被截斷、也沒講出要切換規劃模式」的情況——即使每輪表面上都
        乾淨收尾，如果內容幾乎跟上一輪一樣，代表模型只是換句話說重講一次，沒有真的往前推進，
        這種情況一樣值得被當成「這個任務被低估難度了」的訊號。

        內容太短的話（例如簡短的招呼語）本來就容易剛好長得像，不判斷，避免誤判。
        """
        prev_assistant = next(
            (m.get("content") for m in reversed(self.history) if m.get("role") == "assistant"),
            None
        )
        if not prev_assistant or not isinstance(prev_assistant, str):
            return False
        if len(new_content) < 80 or len(prev_assistant) < 80:
            return False
        ratio = difflib.SequenceMatcher(None, prev_assistant, new_content).ratio()
        return ratio >= threshold

    def update_api_config(self, base_url: str, api_key: str, model_name: str):
        """前端可以動態切換連線的 LLM 端點/金鑰/模型名稱。"""
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=90.0)

    def confirm_and_start(self):
        self.state = AgentState.EXECUTING
        self.start()

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def _run(self):
        self.emit("started", None)
        try:
            self._run_inner()
        except InterruptedError:
            self.state = AgentState.IDLE
            self._save_history()
            self.emit("log", "[系統] Agent 已停止")
            self.emit("chunk", "\n\n*(已停止)*\n")
            self.emit("finished", "stopped")
        except Exception as e:
            self.state = AgentState.IDLE
            self._save_history()
            self.emit("log", f"[錯誤] Agent 異常結束: {e}")
            self.emit("finished", f"error: {e}")

    def _run_inner(self):
        # 1. 第一階段：先做一次「簡短推理 + 嘗試回答」，讓模型自己判斷要不要切換到完整規劃模式。
        #    不再需要額外的 Router 分類呼叫——這次呼叫本身就是串流顯示給使用者看的，
        #    就算之後判斷要切換到規劃模式，這段推理過程使用者也已經看到了，沒有浪費掉。
        if self.state == AgentState.IDLE:
            # 有附圖時直接走對話模式（vision），避免 planner 丟圖，也不需要推理判斷
            if self.current_images:
                self.emit("log", "[系統] 偵測到附圖，進入直接對話（Vision）模式。")
                self._run_direct_mode()
                return

            if self._should_stop():
                raise InterruptedError("Agent 已由使用者停止")

            self.emit("log", "[系統] 開始推理，判斷任務難度...")
            self._maybe_compress_history()
            attempt_user_content = self._build_user_content(self.current_user_prompt, self.current_images)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": self.working_memory.render_context()},
            ] + self.history + [{"role": "user", "content": attempt_user_content}]

            try:
                attempt_content = self._call_llm_stream(messages)
            except InterruptedError:
                raise
            except Exception as e:
                self.emit("log", f"[錯誤] 推理呼叫模型失敗: {e}")
                self.emit("finished", f"error: {e}")
                return

            if self._should_stop():
                raise InterruptedError("Agent 已由使用者停止")

            escalate_match = re.search(r'<\|plan\|>\s*(.*)', attempt_content)
            has_tool_call = bool(re.search(r'<\|tool_call\|>', attempt_content))
            truncated_without_conclusion = (
                self._last_finish_reason == "length" and not escalate_match and not has_tool_call
            )
            repeating_without_progress = (
                not escalate_match and not has_tool_call and not truncated_without_conclusion
                and self._similar_to_previous_reply(attempt_content)
            )

            if escalate_match:
                reason = escalate_match.group(1).strip() or "（模型沒有說明原因）"
                self.emit("log", f"[系統] 推理後判斷需要切換到完整規劃模式：{reason}")
            elif truncated_without_conclusion:
                reason = (
                    "回答在還沒有結論之前就用完了長度上限（並非模型自己判斷要切換，"
                    "而是系統觀察到寫了很多卻沒有收斂，判定這題被低估了難度）"
                )
                self.emit(
                    "log",
                    "[系統] 偵測到回答被長度上限截斷、還沒有結論，"
                    "視為模型低估了難度，自動切換到完整規劃模式（而不是讓它接著同樣沒方向的內容繼續寫）。"
                )
            elif repeating_without_progress:
                reason = (
                    "這輪回答跟上一輪高度重複，代表雖然每輪都正常收尾，但實際上在原地打轉、"
                    "沒有真的往前推進（並非模型自己判斷要切換，而是系統比對前後兩輪內容後判定的）"
                )
                self.emit(
                    "log",
                    "[系統] 偵測到這輪回答跟上一輪高度重複，判定為原地打轉，自動切換到完整規劃模式。"
                )

            if escalate_match or truncated_without_conclusion or repeating_without_progress:
                # 推理過程只在這一輪當草稿用，不寫進 self.history——
                # Planning 模式管自己的 Task Tree 狀態，不靠對話歷史。
                planner_user_prompt = (
                    f"{self.current_user_prompt}\n\n"
                    f"（先前已經嘗試過，判斷這個任務需要完整規劃，原因: {reason}）"
                )
                try:
                    dsl_plan = self._call_llm(PLANNER_SYSTEM_PROMPT, planner_user_prompt)
                except Exception as e:
                    self.emit("log", f"[錯誤] Planning 呼叫模型失敗: {e}，轉為直接模式重試。")
                    self._run_direct_mode()
                    return

                if self.engine.load_initial_plan(dsl_plan):
                    self.state = AgentState.WAITING_CONFIRM
                    # 整個計畫的第一次審視，不受執行模式影響，一律需要人工確認才會開始跑
                    self.emit("ask_confirm", self.engine.render_tree_markdown())
                    return
                else:
                    self.emit("log", "[錯誤] 生成 Task Tree 解析失敗，轉為直接模式。")
                    self._run_direct_mode()
                    return

            # 沒有要求切換：這次推理已經包含（或緊接著給出）答案/工具呼叫了，
            # 直接把這則已經串流出去的內容交給對話模式接手，不用再呼叫一次模型。
            self.history.append({"role": "user", "content": attempt_user_content})
            self.current_images = []
            self._run_direct_mode(initial_content=attempt_content)
            return

        # 2. 第二階段：任務樹執行 —— 每個任務都會跑 think/decompose/execute/verify/retry 迴圈
        if self.state == AgentState.EXECUTING:
            while True:
                if self._should_stop():
                    raise InterruptedError("Agent 已由使用者停止")
                task = self.engine.get_next_pending_task()
                if not task:
                    self.emit("log", "\n[系統] 所有任務執行完畢！")
                    self.state = AgentState.IDLE
                    self.emit("finished", "All tasks completed.")
                    break

                task.status = TaskStatus.RUNNING
                self.emit("log", f"\n>>> 準備執行 [{task.id}]: {task.title}")

                resolved = self._process_task(task)
                if not resolved:
                    # 只有底層系統性錯誤（例如模型連線本身掛掉）才會走到這裡，
                    # 任務本身「驗證失敗」不會、而是在 _process_task 內自己重試/拆解/提問。
                    task.status = TaskStatus.FAILED
                    self.state = AgentState.IDLE
                    self.emit("finished", f"Task {task.id} failed due to a system-level error.")
                    break

                # 決定要不要在下一步之前暫停，讓使用者確認
                next_task = self.engine.get_next_pending_task()
                if next_task:
                    should_pause = self._should_pause_before(next_task)
                    if should_pause:
                        reason = (
                            "逐步模式" if self.engine.mode == ExecutionMode.STEP_BY_STEP
                            else "智慧確認：此任務被標記為需要確認"
                        )
                        self.emit("log", f"[{reason}] 下一步 [{next_task.id}] 等待確認...")
                        self.state = AgentState.WAITING_CONFIRM
                        self.emit("ask_confirm", self.engine.render_tree_markdown())
                        break
                    # AUTO 模式，或 SMART 模式判定這一步不需要確認 -> 迴圈直接繼續處理下一個任務

    def _should_pause_before(self, next_task: TaskNode) -> bool:
        """依照目前的執行模式，決定跑下一個任務之前要不要暫停等使用者確認。"""
        if self.engine.mode == ExecutionMode.STEP_BY_STEP:
            return True  # 無視任務自己的判斷，一律暫停
        if self.engine.mode == ExecutionMode.AUTO:
            return False  # 無視任務自己的判斷，一律不暫停
        if self.engine.mode == ExecutionMode.SMART:
            return next_task.need_confirm  # 交給模型當初規劃這個任務時標的判斷
        return True  # 未知模式，保守起見預設暫停

    # ------------------------------------------------------------------
    # 單一任務的 Decompose / Think / Execute / Verify / Retry 狀態機
    # ------------------------------------------------------------------
    def _process_task(self, task: TaskNode) -> bool:
        """處理單一任務直到「驗證通過」或「被拆解成子任務交給主迴圈」為止。
        回傳 False 只代表底層系統性錯誤（模型連線失敗等），
        任務邏輯上的失敗一律在內部透過 thinking / retry / decompose / ask_user 自行收斂，
        絕不會悄悄放棄整條任務鏈。
        """
        last_fail_reason = ""

        while True:
            # --- 0. 是否需要先拆解成子任務，而不是直接嘗試執行 ---
            if task.need_decompose and not task.is_decomposed:
                decomposed = self._decompose_task(task)
                if decomposed:
                    # 把處理權交還給主迴圈：下一個 pending 任務就會是它的第一個子任務
                    return True
                # 拆解失敗（模型連線問題或格式解析失敗）就放棄拆解，改為直接嘗試執行這個任務
                task.need_decompose = False
                self.emit("log", f"[系統] [{task.id}] 拆解失敗，改為直接嘗試執行原任務。")

            needs_think = task.need_thinking or task.confidence < 0.6 or bool(last_fail_reason)

            if needs_think:
                if task.think_count >= self.max_think_limit:
                    self.emit(
                        "log",
                        f"[警告] [{task.id}] 已思考 {task.think_count} 次仍卡關，向使用者提問。"
                    )
                    question = f"我在執行 [{task.title}] 時卡關了（信心值: {task.confidence:.2f}）"
                    if last_fail_reason:
                        question += f"，上次失敗原因: {last_fail_reason}"
                    question += "，請指導該如何處理？"

                    user_ans = self.ask_user(question)
                    task.note += f"\n(使用者補充: {user_ans})"
                    task.think_count = 0
                    task.retry_count = 0
                    task.confidence = 0.85
                    last_fail_reason = ""
                else:
                    task.think_count += 1
                    self.emit(
                        "log",
                        f"[思考模組] [{task.id}] 第 {task.think_count}/{self.max_think_limit} 次思考"
                        f"（信心值 {task.confidence:.2f}）..."
                    )
                    think_prompt = THINKING_SYSTEM_PROMPT.format(
                        think_count=task.think_count,
                        max_think_limit=self.max_think_limit,
                        confidence=f"{task.confidence:.2f}",
                        last_fail_reason=last_fail_reason or "無"
                    )
                    think_context = (
                        f"當前任務: {task.title}\n"
                        f"目前方法: {task.method}\n"
                        f"目前注意事項: {task.note}\n"
                        f"{self.working_memory.render_context()}\n\n"
                        f"歷史樹:\n{self.engine.render_tree_markdown()}"
                    )
                    try:
                        think_res = self._call_llm(think_prompt, think_context)
                    except Exception as e:
                        self.emit("log", f"[錯誤] 思考階段呼叫模型失敗: {e}")
                        return False

                    fields = self._parse_structured_fields(
                        think_res, ["分析", "修正方法", "修正注意", "拆解", "新信心值"]
                    )
                    self.emit("log", f"💡 [{task.id}] 思考分析: {fields.get('分析', '')[:150]}")

                    # 思考後如果模型認為這個任務其實該拆解，就中斷這輪、改走拆解流程
                    if fields.get("拆解", "").upper().startswith("YES") and not task.is_decomposed:
                        task.need_decompose = True
                        decomposed = self._decompose_task(task)
                        if decomposed:
                            return True
                        task.need_decompose = False
                        self.emit("log", f"[系統] [{task.id}] 思考建議拆解但拆解失敗，改為繼續嘗試執行。")

                    if fields.get("修正方法"):
                        task.method = fields["修正方法"]
                    if fields.get("修正注意"):
                        task.note = fields["修正注意"]
                    try:
                        if fields.get("新信心值"):
                            task.confidence = float(fields["新信心值"])
                    except ValueError:
                        pass

            # --- 執行 ---
            step_prompt = (
                f"{self.working_memory.render_context()}\n\n"
                f"{self.engine.render_tree_markdown()}\n\n"
                f"【請執行步驟 [{task.id}]】\n"
                f"- 標題: {task.title}\n"
                f"- 方法: {task.method}\n"
                f"- 條件: {task.condition}\n"
                f"- 注意: {task.note}\n"
            )
            try:
                result_text = self._call_and_execute(step_prompt)
            except Exception as e:
                self.emit("log", f"[錯誤] 執行階段呼叫模型/工具失敗: {e}")
                return False

            # --- 驗證：獨立呼叫，實際比對「條件」跟「結果」，不是靠有沒有 exception ---
            try:
                verify_res = self._call_llm(
                    VERIFY_SYSTEM_PROMPT,
                    f"條件: {task.condition}\n執行結果:\n{result_text}"
                )
            except Exception as e:
                self.emit("log", f"[警告] 驗證階段呼叫模型失敗，暫時視為未通過: {e}")
                verify_res = "STATUS: FAIL\nREASON: 驗證呼叫本身失敗"

            vfields = self._parse_structured_fields(verify_res, ["STATUS", "REASON"])
            passed = vfields.get("STATUS", "").upper().startswith("PASS")
            reason = vfields.get("REASON", "")

            if passed:
                task.status = TaskStatus.COMPLETED
                task.result = result_text
                task.think_count = 0
                task.retry_count = 0
                self.emit("log", f"[✓ 完成 {task.id}]: {result_text}")

                # 如果這個任務是某個拆解出來的子任務，檢查兄弟姊妹是否也都完成了，
                # 完成的話父任務自動標記完成（並往上遞迴檢查，支援巢狀拆解）。
                self.engine.check_and_complete_parent(task.id)

                # 這個任務有沒有動到已知的函式？有的話自動插入「檢查呼叫者」的任務。
                self._auto_queue_impact_checks(task)

                self._reflect(task, result_text)
                return True

            task.retry_count += 1
            last_fail_reason = reason or "未說明理由"
            task.note += f"\n(上次嘗試失敗原因: {last_fail_reason})"
            task.confidence = min(task.confidence, 0.4)  # 強制下一輪進入思考
            self.emit(
                "log",
                f"[✗ 驗證未通過 {task.id}] 第 {task.retry_count} 次失敗: {last_fail_reason}"
            )

            if task.retry_count > MAX_RETRY_PER_TASK:
                self.emit("log", f"[警告] [{task.id}] 重試次數過多，向使用者提問。")
                user_ans = self.ask_user(
                    f"任務 [{task.title}] 已重試 {task.retry_count} 次仍失敗"
                    f"（原因: {last_fail_reason}），請指示下一步該怎麼做？"
                )
                task.note += f"\n(使用者指示: {user_ans})"
                task.retry_count = 0
                task.think_count = 0
            # 迴圈繼續：因為 confidence 已被壓低或 last_fail_reason 非空，
            # 下一輪會自動進入思考階段（也可能因此判定需要拆解），帶著失敗原因重新規劃方法。

    def _decompose_task(self, task: TaskNode) -> bool:
        """呼叫拆解 prompt，把過於複雜的任務展開成子任務，插入到它後面。"""
        self.emit("log", f"[系統] [{task.id}] 判斷過於複雜，嘗試拆解為子任務...")
        context = (
            f"父任務: {task.title}\n方法: {task.method}\n條件: {task.condition}\n注意: {task.note}\n"
            f"歷史樹:\n{self.engine.render_tree_markdown()}"
        )
        try:
            dsl = self._call_llm(DECOMPOSE_SYSTEM_PROMPT, context)
        except Exception as e:
            self.emit("log", f"[警告] 拆解呼叫模型失敗: {e}")
            return False

        ok, msg = self.engine.decompose_task(task.id, dsl)
        self.emit("log", f"[{'系統' if ok else '警告'}] {msg}")
        return ok

    def _reflect(self, task: TaskNode, result_text: str):
        """任務完成後，檢視最新資訊並動態調整後續 Task Tree，同時把值得長期記住的結論存進硬記憶。
        Task Tree 更新會經過 TaskEngine 的安全驗證，避免已完成/已拆解的任務被模型漏寫或打亂；
        MEMORY 部分是獨立處理的——就算樹更新被拒絕，值得記住的結論還是照樣會被存下來，
        這是兩件不該互相牽連的事：一個是「任務規劃有沒有跟上現況」，一個是「有沒有學到新東西」。
        """
        self.emit("log", "[系統] 檢視最新獲得資訊，動態調整後續 Task Tree...")
        reflect_prompt = (
            f"剛完成任務 [{task.id}]，結果為:\n{result_text}\n\n"
            f"當前完整任務樹:\n{self.engine.render_tree_markdown()}"
        )
        try:
            reflect_output = self._call_llm(REFLECT_SYSTEM_PROMPT, reflect_prompt)
        except Exception as e:
            self.emit("log", f"[警告] Reflect 呼叫模型失敗，保留原任務樹: {e}")
            return

        tree_dsl, memory_facts = self._split_reflect_output(reflect_output)

        ok, msg = self.engine.apply_reflected_dsl(tree_dsl)
        if ok:
            self.emit("log", f"[系統] {msg}")
        else:
            self.emit("log", f"[警告] Task Tree 更新被拒絕: {msg}")

        self._remember_facts(memory_facts, source="Reflect")

    def _split_reflect_output(self, text: str):
        """把 Reflect 的輸出拆成「Task Tree DSL」跟「MEMORY 區塊列出的結論」兩部分。
        沒有 MEMORY 區塊是正常情況（不是每個任務都有值得記住的東西），回傳空列表即可。
        """
        marker_start = "===MEMORY==="
        marker_end = "===END MEMORY==="
        start_idx = text.find(marker_start)
        if start_idx == -1:
            return text, []

        tree_dsl = text[:start_idx]
        rest = text[start_idx + len(marker_start):]
        end_idx = rest.find(marker_end)
        memory_text = rest if end_idx == -1 else rest[:end_idx]
        return tree_dsl, self._parse_memory_facts(memory_text)

    def _parse_memory_facts(self, text: str) -> list:
        """解析「- id: ...\\n- type: ...\\n- summary: ...」這種重複條列格式，
        供 Reflect 的 MEMORY 區塊跟 direct mode 的價值判斷共用。
        """
        facts = []
        blocks = re.split(r'\n(?=-\s*id\s*:)', text.strip())
        for block in blocks:
            if not block.strip():
                continue
            fact = {}
            for field in ("id", "type", "summary"):
                m = re.search(fr'-\s*{field}\s*:\s*(.*)', block)
                if m:
                    fact[field] = m.group(1).strip()
            if fact.get("id"):
                facts.append(fact)
        return facts

    def _remember_facts(self, facts: list, source: str = ""):
        """把解析出來的結論實際寫進硬記憶，供 Reflect 跟價值判斷共用。"""
        for fact in facts:
            fact_id = fact.get("id")
            if not fact_id:
                continue
            fact_type = fact.get("type") or "Fact"
            summary = fact.get("summary", "")
            self.memory_store.upsert_node(fact_id, fact_type, summary=summary)
            self.working_memory.activate(fact_id)
            prefix = f"🧠 [{source}]" if source else "🧠"
            self.emit("log", f"{prefix} 自動記住了 [{fact_type}] {fact_id}: {summary}")

    def _judge_and_remember_from_turn(self, user_text: str, assistant_text: str):
        """direct mode 每一輪對話結束後都會呼叫這個——不管 history 有沒有超過視窗大小，
        單純由模型判斷「這一輪交換的內容值不值得長期記住」。

        這是這個系統「用價值判斷取代靠上下文記住」的核心：context_compressor 的壓縮是
        被動的，只有 history 大小超過門檻才會觸發，如果對話一直沒超過視窗，
        再重要的內容也不會被判斷、不會被存下來。這裡是主動的，每一輪都問一次，
        不依賴「剛好塞滿視窗」這種跟內容價值毫無關係的觸發時機。
        """
        exchange_text = f"使用者: {user_text}\n助理: {assistant_text}"
        try:
            result = self._call_llm(VALUE_JUDGMENT_PROMPT, exchange_text, temperature=0.2)
        except Exception as e:
            self.emit("log", f"[警告] 價值判斷呼叫模型失敗，略過: {e}")
            return
        if result.strip().upper().startswith("NONE"):
            return
        facts = self._parse_memory_facts(result)
        self._remember_facts(facts, source="價值判斷")

    # ------------------------------------------------------------------
    # 直接對話模式（不經過 Task Tree）
    # ------------------------------------------------------------------
    def _run_direct_mode(self, initial_content: str = None):
        """一般對話/工具呼叫迴圈。

        initial_content: 如果呼叫端已經有第一輪的模型輸出（例如 _run_inner 的推理階段
        已經呼叫過模型、確認不需要切換到規劃模式），就傳進來直接處理，不要重打一次；
        呼叫端也要負責先把 user 訊息 append 進 self.history。
        傳 None（預設）代表要從頭開始：自己 append user 訊息、自己呼叫模型。
        """
        if initial_content is None:
            user_content = self._build_user_content(self.current_user_prompt, self.current_images)
            self.history.append({"role": "user", "content": user_content})
            # 圖片只在本輪用一次，避免之後 history 一直帶大 base64
            self.current_images = []
            # vision 模式或其他直接呼叫 _run_direct_mode() 的情況：這裡是第一次真的要
            # 呼叫模型之前，確保視窗大小合規。initial_content 已提供的情況（_run_inner
            # 的推理階段已經呼叫過模型）不需要在這裡多檢查一次——會跟 _run_inner 自己的
            # 檢查在同一輪內重複觸發，變成沒必要地壓縮兩次；晚一輪才被壓到，代價很小，
            # 不值得為了消除這個小小的時機差再多打一次模型。
            self._maybe_compress_history()

        content = initial_content
        final_assistant_text = None

        while True:
            if self._should_stop():
                raise InterruptedError("Agent 已由使用者停止")
            try:
                if content is None:
                    self._maybe_compress_history()

                    messages = [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "system", "content": self.working_memory.render_context()},
                    ] + self.history
                    content = self._call_llm_stream(messages)
                    if self._should_stop():
                        raise InterruptedError("Agent 已由使用者停止")

                self.history.append({"role": "assistant", "content": content})
                is_tool, combined_result, interleaved_content = self._execute_tools(content)
                raw_content = content
                content = None  # 下一輪要重新呼叫模型

                if is_tool:
                    # 用 chunk_patch 把剛剛串流出去的原始文字，就地換成「結果內嵌在各自呼叫後面」的版本，
                    # 不是全部工具都跑完才在整段文字最後面貼一大塊合併結果。
                    self.emit("chunk_patch", {"old": raw_content, "new": interleaved_content})
                    self.history.append({"role": "user", "content": f"[System: Tool Execution Result]\n{combined_result}"})
                else:
                    final_assistant_text = raw_content
                    break
            except InterruptedError:
                raise
            except Exception as e:
                # stream 被 close 時常見各種連線錯誤，視為使用者停止
                if self._should_stop():
                    raise InterruptedError("Agent 已由使用者停止")
                self.emit("chunk", f"\n<tool_error>{str(e)}</tool_error>\n")
                break

        # 只有正常結束、有實際回覆內容時才做價值判斷——出錯中斷的訊息不該被拿去判斷值不值得記。
        # 這一步不管 history 有沒有超過視窗大小都會做，是主動的價值判斷，不是被動的容量管理。
        if final_assistant_text is not None and isinstance(final_assistant_text, str):
            self._judge_and_remember_from_turn(self.current_user_prompt, final_assistant_text)

        self.state = AgentState.IDLE
        self._save_history()
        self.emit("finished", "")

    # ------------------------------------------------------------------
    # LLM / 工具呼叫的共用小工具
    # ------------------------------------------------------------------
    def _call_and_execute(self, prompt: str) -> str:
        """呼叫 LLM 產生回覆並執行其中的工具呼叫，回傳「拿去驗證用」的結果文字。
        會直接把底層例外往外丟，由呼叫端判斷這是系統性錯誤還是任務失敗。
        工具結果會用 chunk_patch 內嵌回原本呼叫的位置，前端才能正確結束「執行中」狀態。
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        content = self._call_llm_stream(messages)
        try:
            is_tool, combined_result, interleaved_content = self._execute_tools(content)
        except Exception as e:
            self.emit("chunk", f"\n<tool_error>\n{e}\n</tool_error>\n")
            raise

        if is_tool:
            self.emit("chunk_patch", {"old": content, "new": interleaved_content})
            return combined_result
        return content

    def _call_llm(self, system_prompt: str, user_prompt: str, temperature=0.2) -> str:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        response = self.client.chat.completions.create(
            model=self.model_name, messages=messages, temperature=temperature,
            stop=STOP_SEQUENCES, max_tokens=MAX_RESPONSE_TOKENS,
        )
        return response.choices[0].message.content or ""

    def _call_llm_stream(self, messages: list) -> str:
        if self._should_stop():
            raise InterruptedError("Agent 已由使用者停止")
        response = self.client.chat.completions.create(
            model=self.model_name, messages=messages, temperature=0.1, stream=True,
            stop=STOP_SEQUENCES, max_tokens=MAX_RESPONSE_TOKENS,
        )
        self._active_stream = response
        full_content = ""
        self._last_finish_reason = None
        try:
            for chunk in response:
                if self._should_stop():
                    raise InterruptedError("Agent 已由使用者停止")
                if chunk.choices:
                    if chunk.choices[0].delta.content:
                        text = chunk.choices[0].delta.content
                        full_content += text
                        self.emit("chunk", text)
                    if getattr(chunk.choices[0], "finish_reason", None):
                        self._last_finish_reason = chunk.choices[0].finish_reason
            return full_content
        except InterruptedError:
            raise
        except Exception:
            if self._should_stop():
                raise InterruptedError("Agent 已由使用者停止")
            raise
        finally:
            self._active_stream = None
            try:
                response.close()
            except Exception:
                pass

    def _parse_structured_fields(self, text: str, field_names: list) -> dict:
        """通用結構化欄位解析：用於 Thinking / Verify 這種要求模型輸出固定欄位的回覆。
        每個欄位對應 text 中第一個「欄位名: 內容」的出現位置。
        """
        result = {}
        for name in field_names:
            match = re.search(fr'{re.escape(name)}\s*:\s*(.*)', text)
            result[name] = match.group(1).strip() if match else ""
        return result

    def _execute_tools(self, content: str):
        """解析並執行 content 裡所有的 <|tool_call|>，每個呼叫只執行一次。

        回傳 (是否有執行到任何工具, 合併結果字串, 逐一內嵌結果後的完整文字)：
        - 合併結果：給模型下一輪或 Verify 使用，格式跟以前一樣（每個工具一行，換行接續）。
        - 逐一內嵌結果：把每個工具呼叫的結果直接接在該次呼叫後面，給畫面顯示用——
          這樣同一輪如果模型呼叫了兩個以上的工具，中間穿插文字說明，每個結果才會正確地
          跟著它自己的呼叫，而不是全部工具都跑完才在整段文字最後面貼一大塊合併結果。
        """
        pattern = r'<\|tool_call\|>call:(\w+)\(([\s\S]*?)\)\s*</?\|?tool_call\|?>'
        matches = list(re.finditer(pattern, content))
        if not matches:
            return False, content, content

        combined_parts = []

        def _execute_and_format(match):
            func_name, args_str = match.group(1), match.group(2)
            if func_name in self.available_functions:
                try:
                    args, kwargs = self._parse_tool_arguments(func_name, args_str)
                    res = self.available_functions[func_name](*args, **kwargs)
                    text = f"[{func_name}]: {res}"
                    tag = "tool_result"
                except Exception as e:
                    text = f"[{func_name} 錯誤]: {e}"
                    tag = "tool_error"
            else:
                text = f"未找到函式 '{func_name}'"
                tag = "tool_error"

            combined_parts.append(text)
            return text, tag

        def _replace(match):
            text, tag = _execute_and_format(match)
            return f"{match.group(0)}\n<{tag}>\n{text}\n</{tag}>\n"

        interleaved_content = re.sub(pattern, _replace, content)
        combined_result = "\n".join(combined_parts)
        return True, combined_result, interleaved_content

    def _parse_tool_arguments(self, func_name: str, args_str: str):
        args_str = args_str.strip()
        if not args_str:
            return [], {}

        # 1. execute_python：專用字串剝除邏輯
        if func_name == "execute_python":
            code_str = args_str
            for q in ('"""', "'''", '"', "'"):
                if code_str.startswith(q) and code_str.endswith(q) and len(code_str) >= len(q) * 2:
                    code_str = code_str[len(q):-len(q)]
                    break
            try:
                code_str = bytes(code_str, "utf-8").decode("unicode_escape")
            except Exception:
                pass
            return [code_str], {}

        # 2. 一般工具：補回括號供 ast.parse 解析
        try:
            expr = ast.parse(f"dummy({args_str})", mode="eval")
            if isinstance(expr.body, ast.Call):
                args = [ast.literal_eval(a) for a in expr.body.args]
                kwargs = {kw.arg: ast.literal_eval(kw.value) for kw in expr.body.keywords}
                return args, kwargs
        except Exception:
            pass

        return [], {}