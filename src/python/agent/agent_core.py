import os
import time
import threading
from typing import Any
from openai import OpenAI

import config
from config import API_BASE_URL, API_KEY, MODEL_NAME
from agent.llama_client import LlamaClient
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
from agent.agent_execution_cycle import AgentExecutionMixin
from agent.agent_direct_mode import AgentDirectModeMixin
from agent.retriever import Retriever
from agent.attention_manager import AttentionManager
from agent.forgetting import ForgettingManager


class AgentWorker(AgentMemoryMixin, AgentLLMClientMixin, AgentExecutionMixin, AgentDirectModeMixin):
    def __init__(self, available_functions: dict, event_callback, default_mode=ExecutionMode.STEP_BY_STEP,
                 memory_path: str = "agent_memory.json", memory_max_nodes: int = 20):
        self.available_functions = available_functions
        self.available_functions["ask_user"] = self.ask_user
        self.available_functions["read_tool_doc"] = self.read_tool_doc
        # 追蹤本次對話裡，哪些工具的詳細文件已經送給過模型了（不管是它自己主動查的，
        # 還是第一次實際呼叫時系統自動夾帶的），避免重複贈送浪費 token。
        self._doc_shown_tools = set()

        self.memory_store = MemoryStore(memory_path)
        self.working_memory = WorkingMemory(self.memory_store, max_nodes=memory_max_nodes)
        self.context_compressor = ContextCompressor(self.memory_store)
        # CCS 中間層：Retriever 和 AttentionManager
        self.retriever = Retriever(self.memory_store, self.working_memory)
        self.attention_manager = AttentionManager()
        # 漸進式遺忘：預設關閉，由使用者透過 set_forgetting_enabled 決定要不要打開
        self.forgetting_manager = ForgettingManager()
        self.available_functions["remember"] = self.remember
        self.available_functions["recall"] = self.recall
        self.available_functions["relate"] = self.relate
        self.available_functions["recall_related"] = self.recall_related
        self.available_functions["search_memory"] = self.search_memory
        self.available_functions["record_observation"] = self.record_observation
        self.available_functions["recall_observation"] = self.recall_observation
        self.available_functions["recall_with_event"] = self.recall_with_event

        self.code_graph = CodeGraphBuilder(self.memory_store)
        self.available_functions["build_code_graph"] = self.build_code_graph
        self.available_functions["build_code_graph_for_project"] = self.build_code_graph_for_project
        self.available_functions["find_callers"] = self.find_callers
        self.available_functions["find_callees"] = self.find_callees

        self.event_callback = event_callback

        self.base_url = API_BASE_URL
        self.api_key = API_KEY
        self.model_name = MODEL_NAME

        # 優先以 Llama-cpp 載入本地 GGUF 模型；若路徑不存在或未啟用則退回相容 API Client
        text_model_path = getattr(config, "TEXT_MODEL_PATH", "")
        if getattr(config, "USE_LOCAL_LLAMA", False) and text_model_path and os.path.exists(text_model_path):
            self.client = LlamaClient(
                model_path=text_model_path,
                n_ctx=getattr(config, "N_CTX", 8192),
                n_gpu_layers=getattr(config, "N_GPU_LAYERS", -1),
            )
            self.model_name = os.path.basename(text_model_path)
        else:
            self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=90.0)

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
        return f"User replied: {self.user_reply_content}"

    def request_stop(self):
        self._stop_event.set()
        self.is_paused_for_input = False
        self.user_reply_content = "[系統] 使用者已停止 Agent"
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
        """
        self.forgetting_manager.set_enabled(enabled)
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
        分數都會疊加、跨 session 持續存在，只有「要不要繼續累積」是每次啟動時的選擇。
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