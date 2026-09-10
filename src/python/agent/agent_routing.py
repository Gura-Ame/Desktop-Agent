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
        ]

        # 如果這輪沒有新附圖，但上一輪有存暫存圖片，就在 system message 裡輕輕提醒模型圖在哪。
        # 這樣下一輪用戶說「這張圖片的 OCR」時，模型才能知道圖片在哪而不是誎稱「我需要您提供圖片」。
        if not self.current_images and getattr(self, "last_image_paths", []):
            existing = self.last_image_paths
            img_hint = (
                f"[系統：上一輪對話有 {len(existing)} 張圖片，暫存路徑如下：\n"
                + "\n".join(f"- {p}" for p in existing)
                + "\n如果用戶現在的討問跟圖片有關，請呼叫 analyze_image_visuals 或 analyze_image_ocr"
                  " 來完成任務，不要以「沒有圖片」为由拒絕回答。]"
            )
            messages.append({"role": "system", "content": img_hint})

        messages += self.history + [{"role": "user", "content": attempt_user_content}]

        # 輕量思考步驟（預設關閉，見 agent/agent_thinking.py）：開啟時，先讓
        # 模型針對這輪內容簡短想一次，再把想法接進 system message 裡，
        # 目標是讓接下來的正式生成不要漏看上下文裡已經有的關鍵資訊
        # （附圖路徑、檔案路徑），也不要動不動就把簡單任務判斷成需要拆解成
        # Task Tree。關閉時 generate_prethink 直接回傳 None，這段完全不會
        # 執行，不影響任何行為或延遲。
        image_note = (
            f"（上一輪對話留有 {len(self.last_image_paths)} 張圖片的暫存路徑可用）"
            if not self.current_images and getattr(self, "last_image_paths", [])
            else ""
        )
        prethink = self.generate_prethink(
            f"使用者這一輪的內容：\n{attempt_user_content}\n{image_note}"
        )
        if prethink:
            messages.append({
                "role": "system",
                "content": f"[內部思考，不是要給使用者看的內容]\n{prethink}",
            })
            self.emit("log", f"🧠 內部思考: {prethink}")

        # 不管接下來這輪會走 Direct Mode 還是升級成完整規劃，這輪使用者真正說了什麼
        # 都要先進 self.history——這是給「一般對話」用的記憶（跟 Task Tree/WorkingMemory
        # 是兩回事），之前只有走到後面第 126 行「沒有升級」那條路才會補這一筆，
        # 一旦這輪被判斷需要升級成完整規劃（escalate=True），使用者這句話就完全不會
        # 進到 self.history 裡——後面幾輪只要不是又跑一次 Task Tree，router 呼叫時
        # 帶的 self.history 完全看不到這句話說過，使用者事後隨口問「還記得我剛剛
        # 說要幹嘛嗎」，模型手上的 messages 真的就是沒有，不是它瞎掰、也不是
        # Working Memory 的鍋。搬到這裡、兩條路都先記下來，才是真的「該記得的有記住」。
        self.history.append({"role": "user", "content": attempt_user_content})
        self.current_images = []

        try:
            attempt_content = self._call_llm_stream(messages)
        except InterruptedError:
            raise
        except Exception as e:
            self.emit("log", f"[錯誤] 推理呼叫模型失敗: {e}")
            self.emit("finished", f"error: {e}")
            return

        self._strip_routing_tag_for_display(attempt_content)

        if self._should_stop():
            raise InterruptedError("Agent 已由使用者停止")

        escalate, reason = self._diagnose_escalation(attempt_content)

        if escalate:
            planner_user_prompt = (
                f"{self.current_user_prompt}\n\n"
                f"（先前已經嘗試過，判斷這個任務需要完整規劃，原因: {reason}）"
            )
            # 同樣是輕量思考步驟：Planner 常常沒想清楚使用者真正要什麼就直接
            # 硬套拆解格式，容易拆出一堆治標不治本的子任務（見 AGENT_NOTES.md
            # 「任務樹一直拆」案例的根因分析）。開啟時讓它先想一次再規劃。
            planner_prethink = self.generate_prethink(
                f"接下來要幫這個需求規劃 Task Tree：\n{planner_user_prompt}\n"
                f"想清楚使用者真正要達成的目標是什麼、有沒有更簡單的做法，"
                f"不要為了拆解而拆解。"
            )
            if planner_prethink:
                planner_user_prompt += f"\n\n（規劃前的思考：{planner_prethink}）"
                self.emit("log", f"🧠 規劃前的思考: {planner_prethink}")
            dsl_plan = self._call_planner_with_repair(planner_user_prompt)

            if dsl_plan is not None and self.engine.load_initial_plan(dsl_plan):
                self.state = AgentState.WAITING_CONFIRM
                # 讓後續的一般對話至少知道「這輪被規劃成了一棵 Task Tree」，
                # 而不是完全一片空白——實際執行結果會在整棵樹跑完時
                # 由 _record_plan_completion_to_history 補上更完整的摘要。
                self.history.append({
                    "role": "assistant",
                    "content": f"（這個請求被規劃成一份待確認的 Task Tree，原因: {reason}）",
                })
                self.emit("ask_confirm", self.engine.render_tree_markdown())
                return
            else:
                self.emit("log", "[錯誤] 生成 Task Tree 仍解析失敗（已重試過），轉為直接模式。")
                # 這則訊息裡已經有一輪被放棄的推理內容殘留在畫面上，
                # 通知前端捨棄它、開新的訊息泡泡，避免新一輪內容接在舊內容後面看起來像重複。
                self.emit("reset_message", None)
                self._run_direct_mode(skip_user_append=True)
                return

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
                self._record_plan_completion_to_history()
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

    def _record_plan_completion_to_history(self):
        """整棵 Task Tree 跑完之後，把結果摘要補進 self.history。

        Task Tree 執行過程中的 retrieve/think/verify 全都是走 _call_llm（不帶
        self.history 的獨立呼叫），跟一般對話用的 self.history 是兩條平行線；
        沒有這一步的話，這整輪「使用者請求 -> 規劃 -> 執行」在一般對話記憶裡
        會是完全空白的一段，之後使用者隨口問「剛剛那個任務做得怎樣了」，
        router 呼叫時帶的 self.history 根本沒有任何線索。只取頂層任務（沒有
        parent_id 的），避免拆解出來的子任務把摘要灌得又臭又長。
        """
        top_level = [t for t in self.engine.tasks if t.parent_id is None]
        if not top_level:
            return
        lines = []
        for t in top_level:
            status_label = t.status.value if hasattr(t.status, "value") else str(t.status)
            result_snippet = (t.result or "").strip()
            if len(result_snippet) > 200:
                result_snippet = result_snippet[:200] + "…"
            lines.append(f"- [{t.id}] {t.title} ({status_label}): {result_snippet or '（無結果內容）'}")
        summary = "（這棵 Task Tree 已執行完畢，各頂層步驟結果：）\n" + "\n".join(lines)
        self.history.append({"role": "assistant", "content": summary})
