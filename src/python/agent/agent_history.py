"""
對話歷史（self.history）的持久化、自動壓縮觸發、重複偵測。

從 agent_llm_client.py 拆出來——這部分管的是「self.history 這個列表本身
的生命週期」，跟怎麼真的呼叫 LLM API 是兩件事，拆開後各自的職責更清楚。
"""
import difflib
from typing import TYPE_CHECKING
from config import SYSTEM_PROMPT
from agent.agent_state import HYBRID_WINDOW_MESSAGES, HISTORY_NODE_ID

if TYPE_CHECKING:
    from agent.agent_protocol import AgentWorkerBase as _Base
else:
    _Base = object


class AgentHistoryMixin(_Base):
    """提供 AgentWorker 的對話歷史管理（壓縮、持久化）與重複內容偵測。"""

    def _maybe_compress_history(self):
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
                self.emit("log", f"[警告] 自動壓縮失敗，暫時保留原本的對話歷史，稍後會再嘗試: {e}")

    def _load_history(self) -> list:
        node = self.memory_store.get_node(HISTORY_NODE_ID)
        if not node:
            return []
        messages = node.properties.get("messages", [])
        return messages if isinstance(messages, list) else []

    def _save_history(self):
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
        self.history = []
        if self.memory_store.get_node(HISTORY_NODE_ID):
            self.memory_store.delete_node(HISTORY_NODE_ID)
        self.context_compressor.reset_baseline()

    def _similar_to_previous_reply(self, new_content: str, threshold: float = 0.6) -> bool:
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

    def _is_repeating_tail(self, text: str, window: int = 260, threshold: float = 0.72) -> bool:
        """比對『這段文字最新的一段』跟『再往前一段』有多相似，用來抓模型在單一次
        生成裡自己原地打轉的情況（例如反覆寫同一段推導）。這跟 _similar_to_previous_reply
        不同：那個是比對「整則已完成的訊息」跟「上一整則」，這裡是在同一次串流生成
        「進行中」就即時比對，不用等它把 token 額度燒完才發現。
        """
        if len(text) < window * 3:
            return False
        tail = text[-window:]
        before_tail = text[-window * 2:-window]
        ratio = difflib.SequenceMatcher(None, before_tail, tail).ratio()
        return ratio >= threshold
