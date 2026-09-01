"""
把新資訊回饋進 Task Tree 的機制：Reflect（任務完成後或中途發現新資訊時，
重新檢視並調整整個計畫）跟 <|replan|> 標記偵測。

拆分自原本的 agent_execution_cycle.py（見 agent_routing.py 開頭的說明）。
"""
import re
from typing import TYPE_CHECKING
from config import REFLECT_SYSTEM_PROMPT
from agent.task_system import TaskNode, TaskStatus

if TYPE_CHECKING:
    from agent.agent_protocol import AgentWorkerBase as _Base
else:
    _Base = object


class AgentReflectionMixin(_Base):
    """提供 AgentWorker 的 Reflect 機制與 <|replan|> 標記偵測。"""

    _REPLAN_MARKER_RE = re.compile(r'<\|replan\|>\s*(.*)', re.DOTALL)

    def _reflect(self, task: TaskNode, result_text: str, in_progress: bool = False, reason: str = ""):
        """檢視新資訊、動態調整 Task Tree。

        in_progress=False（預設）：任務已經完整驗證通過，這是原本就有的「完成後檢視」流程。
        in_progress=True：任務都還沒執行完就發現了足以推翻現有規劃的新資訊（見
        _maybe_handle_replan_marker），此時這個任務本身還在 RUNNING，還沒有 result，
        prompt 的措辭要如實反映「還沒做完、是中途中斷」，不能講成「已經做完了」，
        不然會誤導模型以為這個任務已經有確定的執行結果。
        """
        if in_progress:
            self.emit("log", f"[系統] [{task.id}] 執行到一半發現新資訊，提前檢視並調整 Task Tree...")
            reflect_prompt = (
                f"任務 [{task.id}] 還沒執行完成，但過程中回報了需要重新規劃的原因: {reason}\n"
                f"目前為止得到的內容（尚未驗證，不代表任務已完成）:\n{result_text}\n\n"
                f"當前完整任務樹:\n{self.engine.render_tree_markdown()}\n\n"
                f"請注意：[{task.id}] 目前還沒有完成，不要把它標記為 [x]，"
                f"可以依照新資訊調整它的方法/注意事項/信心值，或視情況拆解它，"
                f"或調整它之後的任務——但它本身應保持未完成狀態，讓系統重新執行它。"
            )
        else:
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

    def _maybe_handle_replan_marker(self, task: TaskNode, text: str) -> bool:
        """檢查思考/執行階段的輸出裡有沒有 <|replan|>原因 這個標記。

        這是「邊做邊發現新資訊，需要重新規劃」的入口：跟一開始 Router 用的 <|plan|>
        是同一種機制、同一種語氣，差別只在於 <|plan|> 用在對話一開始（還沒有任務樹），
        <|replan|> 用在任務樹已經存在、任務執行到一半時（見 SYSTEM_PROMPT 說明）。

        回傳 True 代表偵測到標記、已經觸發重新規劃，呼叫端應該立刻結束對這個任務
        目前這一輪的處理、把控制權交還給最外層的 EXECUTING 迴圈——不要繼續拿著
        這個任務原本的（可能已經過時的）方法/條件繼續往下跑驗證，因為 Reflect
        可能已經整個改寫了這個任務、甚至改寫了它之後的所有任務。
        """
        m = self._REPLAN_MARKER_RE.search(text)
        if not m:
            return False

        reason = m.group(1).strip() or "（模型沒有說明原因）"
        preview = text[:m.start()].strip() or "（標記出現在回覆最開頭，尚無其他內容）"

        self._reflect(task, preview, in_progress=True, reason=reason)

        # Reflect 可能整個換掉了這個 id 對應的 TaskNode 物件（apply_reflected_dsl 對非
        # 保護狀態的任務一律採用新解析出來的內容），所以不能繼續沿用呼叫端手上那個
        # task 區域變數往下處理，只需要確保「這個 id 目前的狀態」是可以被重新撿起來執行的。
        updated = next((t for t in self.engine.tasks if t.id == task.id), None)
        if updated is not None and updated.status not in (TaskStatus.COMPLETED, TaskStatus.DECOMPOSED):
            updated.status = TaskStatus.PENDING
            updated.note = (updated.note or "") + f"\n(先前執行到一半時觸發重新規劃，原因: {reason})"

        return True
