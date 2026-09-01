"""
AgentWorker 狀態機的最外層入口，跟「這一輪該走哪條路」的判斷。

拆分自原本的 agent_execution_cycle.py（太長，拆成三個各司其職的 mixin）：
- agent_routing.py（這個檔案）：_run 進入點、IDLE 狀態的 direct/plan 路由判斷、
  EXECUTING 狀態驅動迴圈。
- agent_task_processor.py：單一個任務從頭到尾的執行生命週期（思考、卡住偵測、
  執行、驗證、拆解）。
- agent_reflection.py：Reflect（檢視新資訊調整 Task Tree）跟 <|replan|> 標記偵測。

三個都是 Mixin，最後在 agent_core.py 的 AgentWorker 裡一起組合起來，
彼此之間單純透過 self.xxx() 互相呼叫，檔案怎麼拆完全不影響執行期行為。
"""
import re
from typing import TYPE_CHECKING
from config import SYSTEM_PROMPT
from agent.agent_state import AgentState
from agent.task_system import ExecutionMode, TaskStatus

if TYPE_CHECKING:
    from agent.agent_protocol import AgentWorkerBase as _Base
else:
    _Base = object


class AgentRoutingMixin(_Base):
    """提供 AgentWorker 最外層的狀態機進入點，以及 IDLE 狀態下的路由判斷。"""

    def _run(self):
        self.emit("started", None)
        # 每次開始新一輪都檢查一次（內部有節流，真正掃描的頻率遠低於每輪一次），
        # 放在最外層是因為這跟「這輪要做什麼任務」完全無關，是背景維護性質的動作。
        self.maybe_run_forgetting_pass()
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
            # 把錯誤明確寫進聊天泡泡本身，而不是只讓「忙碌」狀態悄悄解除——
            # 不然使用者只會看到暫停鍵消失，完全不知道發生了什麼事。
            self.emit("chunk", f"\n\n*(⚠️ 發生錯誤，Agent 已中止: {e})*\n")
            self.emit("finished", f"error: {e}")

    def _run_inner(self):
        if self.state == AgentState.IDLE:
            self._run_idle_routing()
            return

        if self.state == AgentState.EXECUTING:
            self._run_executing_loop()

    def _run_idle_routing(self):
        if self.current_images:
            self.emit("log", "[系統] 偵測到附圖，進入直接對話（Vision）模式。")
            self._run_direct_mode()
            return

        if self._should_stop():
            raise InterruptedError("Agent 已由使用者停止")

        self.emit("log", "[系統] 開始推理，判斷任務難度...")
        self._maybe_compress_history()
        # 每個全新的使用者請求都該是一次「重新編譯 Context」，而不是延續上一輪
        # 累積下來的 Working Memory——不然 Working Memory 會變成一個跨對話、
        # 跨主題的滾動快取，這一輪明明跟上一輪的主題完全無關，卻可能因為 LRU
        # 還沒把舊節點踢出去而混進這一輪的 Context 裡。清空之後，Retriever 會
        # 立刻依照這一輪的實際內容重新填入相關節點，真正相關的東西幾乎馬上就會
        # 被撈回來，不會真的「失憶」——Disk 上的資料完全不受影響，只是重新挑一次
        # 這一輪該看什麼。
        self.working_memory.clear()
        attempt_user_content = self._build_user_content(self.current_user_prompt, self.current_images)

        # 檢索與使用者輸入相關的跨 session 記憶與知識
        self.retriever.retrieve_for_text(self.current_user_prompt)
        attn_block, _ = self.attention_manager.build_context_block(
            self.working_memory, task=self.current_user_prompt
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": attn_block},
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

        escalate, reason = self._diagnose_escalation(attempt_content)

        if escalate:
            planner_user_prompt = (
                f"{self.current_user_prompt}\n\n"
                f"（先前已經嘗試過，判斷這個任務需要完整規劃，原因: {reason}）"
            )
            dsl_plan = self._call_planner_with_repair(planner_user_prompt)

            if dsl_plan is not None and self.engine.load_initial_plan(dsl_plan):
                self.state = AgentState.WAITING_CONFIRM
                self.emit("ask_confirm", self.engine.render_tree_markdown())
                return
            else:
                self.emit("log", "[錯誤] 生成 Task Tree 仍解析失敗（已重試過），轉為直接模式。")
                # 這則訊息裡已經有一輪被放棄的推理內容殘留在畫面上，
                # 通知前端捨棄它、開新的訊息泡泡，避免新一輪內容接在舊內容後面看起來像重複。
                self.emit("reset_message", None)
                self._run_direct_mode()
                return

        self.history.append({"role": "user", "content": attempt_user_content})
        self.current_images = []
        self._run_direct_mode(initial_content=attempt_content)

    def _diagnose_escalation(self, attempt_content: str):
        """判斷這輪推理的結果是不是該切換到完整規劃模式，回傳 (要不要切換, 原因說明)。

        三種觸發情況（任何一種成立就切換）：
        1. 模型自己判斷需要（輸出裡有 <|plan|> 標記）。
        2. 系統偵測到回答被截斷/重複而提前中止（finish_reason 是 length 或
           repetition_detected），且模型自己既沒有喊 <|plan|>、也沒有呼叫工具，
           代表寫了一堆卻沒收尾，視為低估了難度。
        3. 這輪回答跟上一輪高度重複，代表雖然形式上有收尾，但實際上在原地打轉。
        """
        escalate_match = re.search(r'<\|plan\|>\s*(.*)', attempt_content)
        has_tool_call = bool(re.search(r'<\|tool_call\|>', attempt_content))
        hit_length_limit = self._last_finish_reason in ("length", "repetition_detected")
        truncated_without_conclusion = (
            hit_length_limit and not escalate_match and not has_tool_call
        )
        repeating_without_progress = (
            not escalate_match and not has_tool_call and not truncated_without_conclusion
            and self._similar_to_previous_reply(attempt_content)
        )

        if escalate_match:
            reason = escalate_match.group(1).strip() or "（模型沒有說明原因）"
            self.emit("log", f"[系統] 推理後判斷需要切換到完整規劃模式：{reason}")
            return True, reason

        if truncated_without_conclusion:
            if self._last_finish_reason == "repetition_detected":
                reason = (
                    "系統在串流過程中即時偵測到內容疑似陷入重複、原地打轉，"
                    "已提前中止該次生成（並非模型自己判斷要切換）"
                )
                self.emit(
                    "log",
                    "[系統] 即時偵測到生成內容重複，已提前中止，自動切換到完整規劃模式。"
                )
            else:
                reason = (
                    "回答在還沒有結論之前就用完了長度上限（並非模型自己判斷要切換，"
                    "而是系統觀察到寫了很多卻沒有收攬，判定這題被低估了難度）"
                )
                self.emit(
                    "log",
                    "[系統] 偵測到回答被長度上限截斷、還沒有結論，"
                    "視為模型低估了難度，自動切換到完整規劃模式（而不是讓它接著同樣沒方向的內容繼續寫）。"
                )
            return True, reason

        if repeating_without_progress:
            reason = (
                "這輪回答跟上一輪高度重複，代表雖然每輪都正常收尾，但實際上在原地打轉、"
                "沒有真的往前推進（並非模型自己判斷要切換，而是系統比對前後兩輪內容後判定的）"
            )
            self.emit(
                "log",
                "[系統] 偵測到這輪回答跟上一輪高度重複，判定為原地打轉，自動切換到完整規劃模式。"
            )
            return True, reason

        return False, ""

    def _call_planner_with_repair(self, planner_user_prompt: str, max_retries: int = 1):
        """呼叫 Planner 產生 DSL，解析失敗時自動重試修正。回傳 None 代表徹底失敗。"""
        from config import PLANNER_SYSTEM_PROMPT
        return self._call_dsl_with_repair(PLANNER_SYSTEM_PROMPT, planner_user_prompt, max_retries)

    def _run_executing_loop(self):
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
                task.status = TaskStatus.FAILED
                self.state = AgentState.IDLE
                self.emit("finished", f"Task {task.id} failed due to a system-level error.")
                break

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

    def _should_pause_before(self, next_task) -> bool:
        if self.engine.mode == ExecutionMode.STEP_BY_STEP:
            return True
        if self.engine.mode == ExecutionMode.AUTO:
            return False
        if self.engine.mode == ExecutionMode.SMART:
            return next_task.need_confirm
        return True
