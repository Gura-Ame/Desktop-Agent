import time
import threading
from typing import Any
from openai import OpenAI

from config import API_BASE_URL, API_KEY, MODEL_NAME
from agent.task_system import TaskEngine, ExecutionMode
from memory.memory_store import MemoryStore
from agent.working_memory import WorkingMemory
from agent.context_compressor import ContextCompressor
from tools.code_graph import CodeGraphBuilder

from agent.agent_state import (
    AgentState, MAX_RETRY_PER_TASK, STOP_SEQUENCES, MAX_RESPONSE_TOKENS,
    HYBRID_WINDOW_MESSAGES, HISTORY_NODE_ID
)
from agent.agent_memory_mixin import AgentMemoryMixin
from agent.agent_llm_client import AgentLLMClientMixin
from agent.agent_history import AgentHistoryMixin
from agent.agent_tool_execution import AgentToolExecutionMixin
from agent.agent_memory_extraction import AgentMemoryExtractionMixin
from agent.agent_routing import AgentRoutingMixin
from agent.agent_task_processor import AgentTaskProcessorMixin
from agent.agent_reflection import AgentReflectionMixin
from agent.agent_direct_mode import AgentDirectModeMixin
from agent.retriever import Retriever
from agent.attention_manager import AttentionManager
from agent.forgetting import ForgettingManager
from agent.tool_permissions import PermissionManager, PermissionMode, risk_of
from agent.emergency_stop import start_emergency_stop_listener, DEFAULT_HOTKEY


class AgentWorker(
    AgentMemoryMixin, AgentLLMClientMixin,
    AgentHistoryMixin, AgentToolExecutionMixin, AgentMemoryExtractionMixin,
    AgentRoutingMixin, AgentTaskProcessorMixin, AgentReflectionMixin,
    AgentDirectModeMixin,
):
    """Agent 執行核心。這個類別本身透過上面一長串 mixin 組合出完整行為
    （記憶、LLM 呼叫、history、工具執行、路由、任務處理、反思、Direct Mode），
    但 __init__ 是所有 mixin 共用狀態真正「被生出來」的地方，這裡很容易變成
    什麼都攪在一起的建構子。

    拆法：__init__ 本身只留 4 行高階步驟，每一步驟對應到下面一個私有方法——
    記憶子系統、可呼叫工具表、LLM client、跑一次對話所需的執行期狀態。
    這樣拆完全不影響任何外部行為：所有屬性名稱（self.memory_store、
    self.retriever…）都維持原樣，其他 mixin 完全不用跟著改，純粹是把
    「建構的順序」變成「有名字、可以個別讀懂在做什麼的步驟」。
    """

    def __init__(self, available_functions: dict, event_callback, default_mode=ExecutionMode.STEP_BY_STEP,
                 memory_path: str = "agent_memory.json", memory_max_nodes: int = 20):
        self.available_functions = available_functions
        self.event_callback = event_callback
        # 追蹤本次對話裡，哪些工具的詳細文件已經送給過模型了（不管是它自己主動查的，
        # 還是第一次實際呼叫時系統自動夾帶的），避免重複贈送浪費 token。
        self._doc_shown_tools = set()

        self._init_memory_subsystem(memory_path, memory_max_nodes)
        self._register_available_functions()
        self._init_llm_client()
        self._init_session_state(default_mode)
        self._init_permission_manager()
        self._init_emergency_stop()

    def _init_memory_subsystem(self, memory_path: str, memory_max_nodes: int):
        """建構「Context-centric Cognitive Memory」那一整套彼此相依的物件：
        MemoryStore 是最底層的持久化倉庫，其餘幾個（WorkingMemory、
        ContextCompressor、Retriever、AttentionManager、CodeGraphBuilder）
        都直接或間接依賴它。ForgettingManager 比較特殊——它自己不碰磁碟，
        「要不要開」這個開關的持久化狀態委託給 MemoryStore（見
        MemoryStore.set_forgetting_enabled），這裡負責在開機時把上次存的
        狀態同步回來，不然 MemoryStore 讀到的值只是存在那邊、沒人真的套用。
        """
        self.memory_store = MemoryStore(memory_path)
        self.working_memory = WorkingMemory(self.memory_store, max_nodes=memory_max_nodes)
        self.context_compressor = ContextCompressor(self.memory_store)
        # CCS 中間層：Retriever 和 AttentionManager
        self.retriever = Retriever(self.memory_store, self.working_memory)
        self.attention_manager = AttentionManager()
        self.forgetting_manager = ForgettingManager()
        self.forgetting_manager.set_enabled(self.memory_store.forgetting_enabled)
        self.code_graph = CodeGraphBuilder(self.memory_store)

    def _register_available_functions(self):
        """把 self 上（來自各個 mixin 的）方法登記進 available_functions 這張
        「模型可以呼叫什麼」的分派表。刻意跟上面的子系統建構分開成獨立步驟——
        這裡只做「登記」，不做「建構」，兩件事混在一起是原本最容易讀不懂
        __init__ 在幹嘛的地方：明明在看一個工具登記清單，卻要在中間穿插
        `self.code_graph = CodeGraphBuilder(...)` 這種建構語句。
        """
        self.available_functions["ask_user"] = self.ask_user
        self.available_functions["read_tool_doc"] = self.read_tool_doc

        self.available_functions["remember"] = self.remember
        self.available_functions["recall"] = self.recall
        self.available_functions["relate"] = self.relate
        self.available_functions["recall_related"] = self.recall_related
        self.available_functions["search_memory"] = self.search_memory
        self.available_functions["record_observation"] = self.record_observation
        self.available_functions["recall_observation"] = self.recall_observation
        self.available_functions["recall_with_event"] = self.recall_with_event

        self.available_functions["build_code_graph"] = self.build_code_graph
        self.available_functions["build_code_graph_for_project"] = self.build_code_graph_for_project
        self.available_functions["find_callers"] = self.find_callers
        self.available_functions["find_callees"] = self.find_callees

    def _init_llm_client(self):
        self.base_url = API_BASE_URL
        self.api_key = API_KEY
        self.model_name = MODEL_NAME

        # 一律先用相容 API Client 開機——建構這個物件本身不會真的發送請求、
        # 不會載入任何模型，很輕量。要不要改用本地 Llama 直接載入 GGUF，
        # 交給使用者透過 UI 呼叫 load_llama_model() 自己決定，不在啟動時自動載入。
        # （曾經預設在這裡根據 config.USE_LOCAL_LLAMA / TEXT_MODEL_PATH 自動載入，
        # 但這代表使用者連介面都還沒看到，程式就已經在背景默默把幾 GB 的模型
        # 讀進記憶體/顯存了，使用者完全沒有置喙餘地，所以拿掉了。）
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=90.0)

    def _init_session_state(self, default_mode: ExecutionMode):
        """跑一次對話所需要的執行期狀態——跟「記憶」是完全不同層次的東西：
        記憶要跨 session 存活，這裡的東西（目前是不是在跑、跑到哪個任務、
        目前這輪的 prompt/圖片）本質上只在這個 process 活著的期間有意義。
        """
        self.engine = TaskEngine(mode=default_mode)
        self.state = AgentState.IDLE

        self.current_user_prompt = ""
        self.current_images = []
        self.history = self._load_history()
        self.is_paused_for_input = False
        self.user_reply_content = ""
        self.max_think_limit = 3
        self._thread = None
        self._stop_event = threading.Event()
        self._active_stream = None
        self._last_finish_reason = None

    def _init_permission_manager(self):
        """安全 / 權限系統：跟「記憶要不要持久化」是不同的初始化步驟，
        獨立成一個階段，理由見 agent/tool_permissions.py 開頭的說明——
        這是系統層級、跟模型自我判斷的 need_confirm 完全獨立的一道防線。
        授權策略（要問到什麼程度）從 MemoryStore 讀回上次存的偏好；
        「這個工作階段已經允許了哪些工具」永遠從空的開始，不做持久化。
        """
        try:
            mode = PermissionMode(self.memory_store.permission_mode)
        except ValueError:
            mode = PermissionMode.ASK
        self.permission_manager = PermissionManager(mode=mode)
        self.is_paused_for_permission = False
        self.pending_permission_decision = None

    def _init_emergency_stop(self):
        """全域緊急停止：不管使用者目前在哪個視窗，按下快捷鍵（預設
        ctrl+alt+shift+q）就能立刻呼叫 request_stop()，不需要先點回這個
        App 的視窗——agent 執行期間可能正在操作其他應用程式，使用者不見得
        點得到「停止」按鈕。註冊失敗（套件沒裝、或權限不足，這在沒有用
        系統管理員權限啟動的一般使用情境很常見）只會記一筆 log，不影響
        agent 正常運作，退回用視窗裡原本的「停止」按鈕即可。見
        agent/emergency_stop.py 開頭的完整說明。
        """
        registered = start_emergency_stop_listener(self.request_stop)
        if registered:
            self.emit("log", f"[系統] 全域緊急停止快捷鍵已啟用：{DEFAULT_HOTKEY}")
        else:
            self.emit(
                "log",
                "[系統] 全域緊急停止快捷鍵未能啟用（可能是缺少 keyboard 套件或"
                "權限不足），仍可使用視窗裡的「停止」按鈕。",
            )

    def emit(self, event_type: str, payload: Any):
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
        # 迴圈也可能是被 request_stop() 直接把 is_paused_for_input 設回 False
        # 而結束的（不是使用者真的回覆了問題）——那種情況下 while 條件本身就
        # 已經是 False，迴圈裡的 _stop_event 檢查完全不會被跑到，上面那個
        # raise 形同沒用。這裡在迴圈外再補一次同樣的檢查，確保不管迴圈是怎麼
        # 結束的，只要是因為使用者按了停止，就一定會是 InterruptedError，
        # 不會把「使用者已停止」這句系統訊息偽裝成一句正常的使用者回覆繼續往下跑。
        if self._stop_event.is_set():
            raise InterruptedError("Agent 已由使用者停止")
        return f"User replied: {self.user_reply_content}"

    def request_stop(self):
        self._stop_event.set()
        self.is_paused_for_input = False
        self.user_reply_content = "[系統] 使用者已停止 Agent"
        self.is_paused_for_permission = False
        self.pending_permission_decision = "deny"
        # 如果 agent 剛好卡在 mouse_down/key_down 之後、還沒呼叫對應的
        # mouse_up/key_up 就被停止，這裡順便釋放掉，不然使用者的滑鼠鍵盤
        # 會維持在按住的狀態，繼續影響停止之後的操作。用 available_functions
        # 查表呼叫（不直接 import tools.input_tools）——agent_core 不該
        # 直接依賴任何具體工具模組，跟其他工具的呼叫方式維持一致。
        release_fn = self.available_functions.get("release_all_held_inputs")
        if release_fn:
            try:
                release_fn()
            except Exception:
                pass
        stream = self._active_stream
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
            try:
                resp = getattr(stream, "response", None)
                if resp is not None:
                    resp.close()
            except Exception:
                pass
        self.emit("log", "[系統] 收到停止請求，正在中止 LLM stream…")

    def _should_stop(self) -> bool:
        return self._stop_event.is_set()

    def resume_with_user_input(self, text: str):
        self.user_reply_content = text
        self.is_paused_for_input = False

    def request_tool_permission(self, func_name: str, args_str: str) -> bool:
        """在真的執行一個工具之前呼叫。回傳 True 代表可以放行，False 代表
        使用者拒絕（或已停止），呼叫端應該把這次呼叫當成失敗處理，不要執行。

        SAFE 工具、已經被授權過的工具、或目前策略是 AUTO/ASK_DANGEROUS_ONLY
        底下不需要問的等級，都會直接回傳 True，完全不會暫停——只有真的需要
        使用者當場做決定時才會走進下面的暫停等待迴圈，機制跟 ask_user 完全
        一樣（emit 一個事件、輪詢一個「還在等嗎」的旗標、由前端呼叫對應的
        resume_* 方法解除暫停）。
        """
        if not self.permission_manager.needs_confirmation(func_name):
            return True

        self.is_paused_for_permission = True
        self.pending_permission_decision = None
        risk = risk_of(func_name)
        self.emit("permission_request", {
            "tool": func_name,
            "args": args_str,
            "risk": risk.value,
        })
        self.emit(
            "log",
            f"🔒 Agent 請求授權呼叫 {func_name}（風險等級: {risk.value}），等待使用者回應…",
        )
        while self.is_paused_for_permission:
            if self._stop_event.is_set():
                raise InterruptedError("Agent 已由使用者停止")
            time.sleep(0.1)
        # 同樣的道理見 ask_user() 裡的說明：迴圈可能是被 request_stop() 直接
        # 把 is_paused_for_permission 設回 False 而結束的，不是真的等到使用者
        # 做出決定，這裡要在迴圈外再補一次檢查，不能只靠迴圈內那個檢查。
        if self._stop_event.is_set():
            raise InterruptedError("Agent 已由使用者停止")

        decision = self.pending_permission_decision or "deny"
        if decision == "allow_session":
            self.permission_manager.grant(func_name)
            self.emit("log", f"✅ 已允許 {func_name} 在本次工作階段持續使用，不會再重複詢問。")
            return True
        if decision == "allow":
            self.emit("log", f"✅ 已允許這一次呼叫 {func_name}。")
            return True
        self.emit("log", f"🚫 使用者拒絕了這次 {func_name} 呼叫。")
        return False

    def resume_with_permission_decision(self, decision: str):
        """decision 必須是 'allow' | 'allow_session' | 'deny' 之一，
        由前端的授權對話框呼叫。傳其他值一律視為 'deny'（安全的失敗方向：
        看不懂的指令不要當作允許）。
        """
        self.pending_permission_decision = decision if decision in (
            "allow", "allow_session", "deny"
        ) else "deny"
        self.is_paused_for_permission = False

    def set_permission_mode(self, mode: PermissionMode):
        """使用者決定要被問到什麼程度。不透過 available_functions 暴露給
        模型——這是使用者對「自己願意承擔多少風險」的設定，模型不該有
        調整自己被監督程度的權力。策略本身會持久化（跟 forgetting/activation
        一樣），但改變策略不會回頭影響「這個工作階段已經允許過的工具」，
        也不會自動 revoke 既有的授權。
        """
        self.permission_manager.set_mode(mode)
        self.memory_store.set_permission_mode(mode.value)
        self.emit("log", f"[系統] 工具授權策略已切換為: {mode.value}")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_user_prompt(self, user_prompt: str, images=None):
        self.current_user_prompt = user_prompt
        self.current_images = list(images or [])

    def set_execution_mode(self, mode: ExecutionMode):
        self.engine.mode = mode

    def set_forgetting_enabled(self, enabled: bool):
        """使用者決定要不要打開漸進式遺忘。這是這個功能唯一的開關入口，
        不透過 available_functions 暴露給模型——這是使用者的設定，不是 agent 的工具。
        開關本身現在會跟著 memory_store 一起存進磁碟（見 MemoryStore.save()），
        重開程式會恢復成上次關掉之前的狀態，不會每次都被迫重新打開一次。
        """
        self.forgetting_manager.set_enabled(enabled)
        self.memory_store.set_forgetting_enabled(enabled)
        self.emit(
            "log",
            f"[系統] 漸進式遺忘已{'開啟' if enabled else '關閉'}"
            + ("，長期沒被存取的記憶之後會自動降低解析度。" if enabled else "。")
        )

    def set_activation_enabled(self, enabled: bool):
        """使用者決定要不要打開 Activation（跨 session 的「常被想起」分數）。
        同樣不透過 available_functions 暴露給模型，純粹是使用者的偏好設定。
        關閉時 activation 永遠停在 0，AttentionManager 的排序就完全不受影響，
        等於功能不存在；開啟後每次 remember/recall/search_memory 命中，
        分數都會疊加、跨 session 持續存在。開關本身現在也會持久化
        （見 MemoryStore.set_activation_enabled），重開程式會恢復成上次的狀態。
        """
        self.memory_store.set_activation_enabled(enabled)
        self.emit(
            "log",
            f"[系統] Activation 已{'開啟' if enabled else '關閉'}"
            + ("，之後常被想起的記憶會在排序中更容易被優先看到。" if enabled else "。")
        )

    def maybe_run_forgetting_pass(self):
        """在每一輪新的使用者請求開始時檢查一次是否該跑 decay pass。
        頻率由 ForgettingManager 內部的 min_pass_interval 控制，不是每次呼叫都真的掃描，
        避免使用者聊得很頻繁時，每一輪都重新掃一次整個 Disk。
        """
        if not self.forgetting_manager.should_run_pass():
            return
        try:
            changed = self.forgetting_manager.run_decay_pass(self.memory_store, call_llm=self._call_llm)
            if changed:
                self.emit(
                    "log",
                    f"[系統] 漸進式遺忘：{len(changed)} 個長期沒被存取的記憶節點已降低解析度。"
                )
        except Exception as e:
            self.emit("log", f"[警告] 漸進式遺忘掃描失敗（不影響本輪對話）: {e}")

    def confirm_and_start(self):
        self.state = AgentState.EXECUTING
        self.start()

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()


__all__ = [
    "AgentState",
    "AgentWorker",
    "MAX_RETRY_PER_TASK",
    "STOP_SEQUENCES",
    "MAX_RESPONSE_TOKENS",
    "HYBRID_WINDOW_MESSAGES",
    "HISTORY_NODE_ID",
]