"""
可開關的「先想清楚再說」步驟——跟 agent_task_processor.py 裡既有的
THINKING_SYSTEM_PROMPT（任務卡關/失敗後才觸發的深度診斷，有
think_count/confidence 這些任務專屬欄位）不是同一件事，這裡是更輕量、
更通用的一次性思考，用在兩個地方：
1. Direct Mode 生成正式回覆之前（agent_routing.py 的 _run_idle_routing）。
2. Planner 生成 Task Tree 之前（agent_routing.py 的 _call_planner_with_repair）。

存在的理由：Direct Mode 經常一有請求就立刻吐輸出，容易忽略掉上下文裡
已經有的關鍵資訊（例如稍早附的圖片路徑），或把簡單任務不必要地判斷成
需要拆解成 Task Tree；Planner 也常常沒有先想清楚使用者真正要什麼，就
直接硬套拆解格式，導致拆出一堆治標不治本的子任務（見 AGENT_NOTES.md
「使用者回報任務樹一直拆」那個案例的根因分析）。多一步簡短的思考，
讓模型在生成正式輸出之前先把這些想清楚，理論上能改善這類問題。

預設關閉：這是額外的一次完整 LLM 呼叫，對每一輪對話/每一次規劃都多了
明顯的延遲跟 token 成本，不該在使用者沒有主動開啟的情況下就悄悄套用。
跟 forgetting_enabled/activation_enabled/permission_mode 一樣透過
MemoryStore 持久化這個開關本身。
"""

from config import PRE_THINK_SYSTEM_PROMPT


class AgentThinkingMixin:
    """提供「輕量思考」步驟；不管有沒有開啟，這個 mixin 本身不影響其他
    任何行為——關閉時 generate_prethink 直接回傳 None，呼叫端據此判斷
    要不要把思考結果接進 prompt 裡。
    """

    def set_thinking_enabled(self, enabled: bool):
        """使用者決定要不要開啟這個輕量思考步驟。不透過 available_functions
        暴露給模型——這是使用者對「要不要多花一次 LLM 呼叫換取更好輸出」
        的取捨，模型不該有權限自己決定要不要多想一步（不然等於讓它自己
        決定要花使用者多少額外的時間/成本）。
        """
        self.thinking_enabled = enabled
        self.memory_store.set_thinking_enabled(enabled)
        self.emit(
            "log",
            f"[系統] 輕量思考步驟已{'開啟' if enabled else '關閉'}"
            + ("，Direct Mode 回覆與 Planner 規劃前都會先做一次簡短思考。" if enabled else "。")
        )

    def generate_prethink(self, context_prompt: str) -> "str | None":
        """關閉時直接回傳 None，開啟時呼叫 PRE_THINK_SYSTEM_PROMPT 取得一段
        簡短思考文字。這次額外的 LLM 呼叫本身失敗（例如模型暫時不穩定）
        不該讓整個流程跟著失敗——失敗時記一筆 log、回傳 None，呼叫端當作
        「這次沒有思考結果」處理，繼續往下走原本沒有思考步驟時的流程。
        """
        if not getattr(self, "thinking_enabled", False):
            return None
        try:
            return self._call_llm(PRE_THINK_SYSTEM_PROMPT, context_prompt)
        except Exception as e:
            self.emit("log", f"[警告] 輕量思考步驟呼叫失敗，略過這一步: {e}")
            return None
