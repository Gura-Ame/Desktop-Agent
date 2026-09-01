"""
單一個任務從被撿起來執行、到完成/失敗為止的完整生命週期。

拆分自原本的 agent_execution_cycle.py（見 agent_routing.py 開頭的說明）。
這個檔案負責的是「一個任務內部發生的事」：Retrieve 相關記憶、套用 Observation
的即時指令、思考、卡住偵測升級、執行、驗證、拆解——凡是圍繞著單一 TaskNode
打轉的邏輯都在這裡；跨任務的狀態機驅動（誰先誰後、什麼時候該暫停確認）
在 agent_routing.py；把新資訊回饋進 Task Tree 的 Reflect 在 agent_reflection.py。
"""
from typing import TYPE_CHECKING, List
from config import (
    THINKING_SYSTEM_PROMPT, VERIFY_SYSTEM_PROMPT, DECOMPOSE_SYSTEM_PROMPT
)
from agent.agent_state import MAX_RETRY_PER_TASK
from agent.task_system import TaskNode, TaskStatus

if TYPE_CHECKING:
    from agent.agent_protocol import AgentWorkerBase as _Base
else:
    _Base = object

# 卡住偵測升級的階梯，索引即「目前升級到第幾階」（見 _diagnose_stuck_action）。
_STUCK_ESCALATION_LADDER = ["replan", "expand_memory", "ask_user"]


class AgentTaskProcessorMixin(_Base):
    """提供 AgentWorker 處理單一任務的完整生命週期。"""

    def _apply_fresh_observation_decision(self, task: TaskNode, retrieved_ids: List[str]) -> str:
        """Apply an explicit directive from fresh observations relevant to task.

        用這個任務「這一輪 Retriever 實際撈到的節點」(retrieved_ids) 當關聯範圍，
        而不是整個 WorkingMemory.active_ids()——後者是跨任務滾動的 LRU 快取，
        還留著前幾個任務的舊活躍節點，用它來判斷會導致一個跟目前任務完全無關、
        只是「剛好還沒被踢出快取」的舊 Observation 誤觸發 skip_task/replan。
        """
        observations = self.memory_store.get_fresh_observations(retrieved_ids)
        actions = {obs.properties.get("runtime_action", "context") for obs in observations}

        # 兩種都出現時 replan 優先：replan 會重新檢視整個任務樹（含這個任務本身該不該做），
        # 涵蓋範圍比單純 skip_task 更完整、更安全，不會漏掉 skip_task 沒考慮到的連帶影響。
        if "replan" in actions:
            triggering = [obs for obs in observations if obs.properties.get("runtime_action") == "replan"]
            summaries = [obs.summary for obs in triggering]
            result = "；".join(filter(None, summaries)) or "新鮮 Observation 要求重新規劃"
            self.emit("log", f"[Observation] [{task.id}] 觸發重新規劃: {result}")
            for obs in triggering:
                self.memory_store.mark_observation_applied(obs.id)
            self._reflect(task, result, in_progress=True,
                          reason="fresh Observation runtime_action=replan")
            # _reflect -> apply_reflected_dsl 對非 COMPLETED/DECOMPOSED 的任務一律採用
            # 新解析出來的 TaskNode 實例取代原本這個 id 的物件，所以這裡的區域變數 task
            # 之後可能已經不是 self.engine.tasks 裡真正存在的那個物件了——
            # 必須重新用 id 撈一次，狀態才會設定在「真的活著」的那個物件上。
            updated = next((t for t in self.engine.tasks if t.id == task.id), None)
            if updated is not None and updated.status not in (TaskStatus.COMPLETED, TaskStatus.DECOMPOSED):
                updated.status = TaskStatus.PENDING
            return "replan"

        if "skip_task" in actions:
            triggering = [obs for obs in observations if obs.properties.get("runtime_action") == "skip_task"]
            summaries = [obs.summary for obs in triggering]
            result = "；".join(filter(None, summaries)) or "新鮮 Observation 表示此步驟不需要執行"
            for obs in triggering:
                self.memory_store.mark_observation_applied(obs.id)
            task.status = TaskStatus.COMPLETED
            task.result = f"由 Observation 跳過：{result}"
            self.engine.check_and_complete_parent(task.id)
            self.emit("log", f"[Observation] [✓ 跳過 {task.id}]: {result}")
            self._reflect(task, task.result)
            return "skip_task"

        return "context"

    def _diagnose_stuck_action(self, task: TaskNode) -> str:
        """think_count 已經到達目前允許上限時，判斷接下來該做什麼，而不是無腦一律 ask_user。

        判斷邏輯（對應設計裡「Thinking 很多但 Confidence 沒起色才算真的卡住」的想法）：
        - 如果信心值最近其實一直在上升，代表思考本身是有效的、只是還沒收斂，
          不算真正卡住，多給一點預算讓它繼續走（"extend"）。
        - 如果信心值停滯或下降，才算真的卡住，這時依序嘗試代價較低、較不打擾使用者的手段：
          先試著拆解成更小的子任務重新規劃（"replan"），如果已經試過，
          再嘗試擴大記憶檢索範圍、看有沒有漏掉的相關知識（"expand_memory"），
          兩者都試過仍然卡住，才真的去打擾使用者（"ask_user"）。
        """
        hist = task.confidence_history[-4:]
        improving = len(hist) >= 2 and (hist[-1] - hist[0]) > 0.05

        if improving and task.stuck_escalation_level == 0:
            return "extend"

        idx = min(task.stuck_escalation_level, len(_STUCK_ESCALATION_LADDER) - 1)
        return _STUCK_ESCALATION_LADDER[idx]

    def _decompose_task(self, task: TaskNode) -> bool:
        self.emit("log", f"[系統] [{task.id}] 判斷過於複雜，嘗試拆解為子任務...")
        context = (
            f"父任務: {task.title}\n方法: {task.method}\n條件: {task.condition}\n注意: {task.note}\n"
            f"歷史樹:\n{self.engine.render_tree_markdown()}"
        )
        dsl = self._call_dsl_with_repair(DECOMPOSE_SYSTEM_PROMPT, context)
        if dsl is None:
            self.emit("log", f"[警告] [{task.id}] 拆解失敗（含重試）。")
            return False

        ok, msg = self.engine.decompose_task(task.id, dsl)
        self.emit("log", f"[{'系統' if ok else '警告'}] {msg}")
        return ok

    def _call_dsl_with_repair(self, system_prompt: str, user_prompt: str, max_retries: int = 1):
        """呼叫任何一種輸出 Task DSL 的 prompt（Planner、Decompose...），解析失敗時
        把具體錯誤原因跟原始輸出回饋給模型重試，而不是第一次沒格式對就整批放棄。
        回傳 None 代表重試用盡仍然失敗。
        """
        prompt = user_prompt
        for attempt in range(max_retries + 1):
            try:
                output = self._call_llm(system_prompt, prompt)
            except Exception as e:
                self.emit("log", f"[錯誤] 呼叫模型失敗: {e}")
                return None

            if self.engine.parse_markdown_dsl(output) is not None:
                return output

            error_reason = self.engine.last_parse_error or "格式不符合 DSL 規則"
            if attempt < max_retries:
                self.emit(
                    "log",
                    f"[系統] Task Tree 格式不符（{error_reason}），"
                    f"把錯誤回饋給模型重試第 {attempt + 1}/{max_retries} 次..."
                )
                prompt = (
                    f"{user_prompt}\n\n"
                    f"（上一次你的輸出格式不對，無法解析，原因: {error_reason}\n"
                    f"上一次你輸出的原始內容:\n{output}\n\n"
                    f"請重新輸出，務必嚴格照著規定的 DSL 格式。）"
                )
        return None

    def _process_task(self, task: TaskNode) -> bool:
        last_fail_reason = ""

        # ------------------------------------------------------------------
        # 任務開始前：重建 Context → Retrieve → Attend → 潛在影響預掃
        # ------------------------------------------------------------------
        # 每個任務都是一次獨立的「retrieve -> think -> result -> store -> 丟掉暫存
        # context -> 下一個任務」循環，不是讓 Working Memory 在整個任務樹執行過程中
        # 無限累積、只靠 LRU 上限硬頂著。清空之後 Retriever 馬上就會依照這個任務
        # 自己的內容重新載入相關節點——真正相關的東西幾乎立刻就會回來，不會真的
        # 遺失（Disk 上的資料完全不受影響），但不會讓上一個任務、甚至上上個任務
        # 留下的節點繼續佔著這個任務的 Context 空間，也不會有搭配 _apply_
        # fresh_observation_decision 時，被無關的舊活躍節點污染判斷的風險。
        self.working_memory.clear()

        retrieved_ids = self.retriever.retrieve_for_task(task)
        if retrieved_ids:
            self.emit(
                "log",
                f"[Retriever] [{task.id}] 啟用了 {len(retrieved_ids)} 個相關節點: "
                + ", ".join(retrieved_ids[:5])
                + (" …" if len(retrieved_ids) > 5 else "")
            )

        observation_decision = self._apply_fresh_observation_decision(task, retrieved_ids)
        if observation_decision in ("skip_task", "replan"):
            return True

        self._auto_queue_impact_checks(task)

        while True:
            if task.need_decompose and not task.is_decomposed:
                decomposed = self._decompose_task(task)
                if decomposed:
                    return True
                task.need_decompose = False
                self.emit("log", f"[系統] [{task.id}] 拆解失敗，改為直接嘗試執行原任務。")

            needs_think = task.need_thinking or task.confidence < 0.6 or bool(last_fail_reason)

            if needs_think:
                handled = self._run_thinking_step(task, last_fail_reason)
                assert handled in ("decomposed", "replanned", "system_error", "extended", "ask_user_resolved", "thought"), \
                    f"_run_thinking_step 回傳了未知的訊號字串: {handled!r}，呼叫端的分支沒有涵蓋到"
                if handled in ("decomposed", "replanned"):
                    return True
                if handled == "system_error":
                    return False
                if handled == "extended":
                    # 卡住偵測升級（延長預算/拆解失敗改下一階/擴大檢索）都只是調整了
                    # 狀態、還沒有真的嘗試執行這個任務，必須直接跳回迴圈開頭重新判斷
                    # need_decompose / needs_think，不能落到下面去嘗試執行——原本這幾種
                    # 情況在合併前都各自寫了 continue，拆開後這裡要顯式補回同樣的效果。
                    continue
                if handled == "ask_user_resolved":
                    last_fail_reason = ""
                # handled == "thought" 或 "ask_user_resolved"：往下走到執行階段
                # （ask_user 重置了信心值跟卡住狀態，用新的狀態直接嘗試一次執行）

            outcome = self._run_execute_and_verify_step(task, last_fail_reason)
            assert outcome["status"] in ("passed", "replanned", "system_error", "retry", "ask_user_resolved"), \
                f"_run_execute_and_verify_step 回傳了未知的 status: {outcome['status']!r}"
            if outcome["status"] in ("replanned", "passed"):
                return True
            if outcome["status"] == "system_error":
                return False
            if outcome["status"] == "ask_user_resolved":
                last_fail_reason = ""
                continue
            # outcome["status"] == "retry"：帶著新的失敗原因繼續下一輪
            last_fail_reason = outcome["last_fail_reason"]

    def _run_thinking_step(self, task: TaskNode, last_fail_reason: str) -> str:
        """處理 needs_think 分支：卡住升級判斷 or 真的做一次思考。

        回傳值是給 _process_task 用的訊號字串：
        - "decomposed"：思考建議拆解且拆解成功，任務已經變成子任務，外層該直接 return True
        - "replanned"：卡住升級觸發了 replan 或思考中出現 <|replan|> 標記
        - "system_error"：思考階段呼叫模型失敗，外層該直接 return False
        - "ask_user_resolved"：卡住升級到 ask_user 並且已經處理完
        - "extended"：判斷還在有效進步，延長了思考預算，這輪不做任何思考/執行嘗試
        - "thought"：正常做了一次思考，可以往下走到執行階段
        """
        effective_think_limit = task.think_limit_override or self.max_think_limit

        if task.think_count >= effective_think_limit:
            return self._escalate_stuck_task(task, last_fail_reason)

        task.think_count += 1
        self.emit(
            "log",
            f"[思考模組] [{task.id}] 第 {task.think_count}/{effective_think_limit} 次思考"
            f"（信心值 {task.confidence:.2f}）..."
        )
        think_prompt = THINKING_SYSTEM_PROMPT.format(
            think_count=task.think_count,
            max_think_limit=effective_think_limit,
            confidence=f"{task.confidence:.2f}",
            last_fail_reason=last_fail_reason or "無"
        )
        attn_block, _ = self.attention_manager.build_context_block(self.working_memory, task=task)
        think_context = (
            f"當前任務: {task.title}\n"
            f"目前方法: {task.method}\n"
            f"目前注意事項: {task.note}\n"
            f"{attn_block}\n\n"
            f"歷史樹:\n{self.engine.render_tree_markdown()}"
        )
        try:
            think_res = self._call_llm(think_prompt, think_context)
        except Exception as e:
            self.emit("log", f"[錯誤] 思考階段呼叫模型失敗: {e}")
            return "system_error"

        fields = self._parse_structured_fields(
            think_res, ["分析", "修正方法", "修正注意", "拆解", "新信心值"]
        )
        self.emit("log", f"💡 [{task.id}] 思考分析: {fields.get('分析', '')[:150]}")

        if self._maybe_handle_replan_marker(task, think_res):
            return "replanned"

        if fields.get("拆解", "").upper().startswith("YES") and not task.is_decomposed:
            task.need_decompose = True
            decomposed = self._decompose_task(task)
            if decomposed:
                return "decomposed"
            task.need_decompose = False
            self.emit("log", f"[系統] [{task.id}] 思考建議拆解但拆解失敗，改為繼續嘗試執行。")

        if fields.get("修正方法"):
            task.method = fields["修正方法"]
        if fields.get("修正注意"):
            task.note = fields["修正注意"]
        try:
            if fields.get("新信心值"):
                task.set_confidence(float(fields["新信心值"]))
        except ValueError:
            pass

        return "thought"

    def _escalate_stuck_task(self, task: TaskNode, last_fail_reason: str) -> str:
        """think_count 已經到頂，走卡住偵測升級階梯（見 _diagnose_stuck_action）。"""
        action = self._diagnose_stuck_action(task)

        if action == "extend":
            # 信心值還在持續往上、代表思考是有效的，不是原地打轉——
            # 多給一點預算讓它繼續走，不要因為單純「次數到了」就打斷或打擾使用者。
            task.think_limit_override = task.think_count + 2
            recent = [round(c, 2) for c in task.confidence_history[-3:]]
            self.emit(
                "log",
                f"[卡住偵測] [{task.id}] 信心值持續上升（近期: {recent}），"
                f"判斷仍在有效推進，多給 2 次思考機會，暫不打擾使用者。"
            )
            return "extended"

        if action == "replan":
            task.stuck_escalation_level = 1
            self.emit(
                "log",
                f"[卡住偵測] [{task.id}] 思考 {task.think_count} 次後信心值仍停滯在 "
                f"{task.confidence:.2f} 附近，先嘗試拆解重新規劃，而不是直接打擾使用者。"
            )
            task.need_decompose = True
            decomposed = self._decompose_task(task)
            if decomposed:
                return "decomposed"
            task.need_decompose = False
            task.think_limit_override = task.think_count + 1
            self.emit("log", f"[卡住偵測] [{task.id}] 拆解沒有成功，繼續嘗試下一種手段。")
            return "extended"  # 拆解失敗，回到思考迴圈繼續下一輪（下一階會是 expand_memory）

        if action == "expand_memory":
            task.stuck_escalation_level = 2
            self.emit("log", f"[卡住偵測] [{task.id}] 拆解也無濟於事，擴大記憶檢索範圍再試一次。")
            widened = self.retriever.retrieve_for_text(
                " ".join(filter(None, [task.title, task.note, last_fail_reason])),
                top_k=20
            )
            self.emit(
                "log",
                f"[卡住偵測] [{task.id}] 擴大檢索後新增啟用 {len(widened)} 個節點。"
                if widened else
                f"[卡住偵測] [{task.id}] 擴大檢索沒有找到新的相關節點，可用手段已用盡。"
            )
            task.think_limit_override = task.think_count + 1
            return "extended"

        # action == "ask_user"：延長預算、拆解、擴大檢索都試過了，才真的打擾使用者
        self.emit(
            "log",
            f"[警告] [{task.id}] 已思考 {task.think_count} 次、"
            f"嘗試拆解與擴大記憶檢索仍卡關，向使用者提問。"
        )
        question = f"我在執行 [{task.title}] 時卡關了（信心值: {task.confidence:.2f}）"
        if last_fail_reason:
            question += f"，上次失敗原因: {last_fail_reason}"
        question += "，請指導該如何處理？"

        user_ans = self.ask_user(question)
        task.note += f"\n(使用者補充: {user_ans})"
        task.think_count = 0
        task.retry_count = 0
        task.set_confidence(0.85)
        task.reset_stuck_state()
        return "ask_user_resolved"

    def _run_execute_and_verify_step(self, task: TaskNode, last_fail_reason: str) -> dict:
        """執行一輪「送出步驟 prompt → 執行 → 驗證」，回傳一個描述結果的 dict：
        {"status": "passed" | "replanned" | "system_error" | "retry" | "ask_user_resolved",
         "last_fail_reason": str}（只有 status == "retry" 時 last_fail_reason 才有意義）
        """
        attn_block, _ = self.attention_manager.build_context_block(self.working_memory, task=task)
        step_prompt = (
            f"{attn_block}\n\n"
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
            return {"status": "system_error", "last_fail_reason": last_fail_reason}

        if self._maybe_handle_replan_marker(task, result_text):
            return {"status": "replanned", "last_fail_reason": last_fail_reason}

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
            task.reset_stuck_state()
            self.emit("log", f"[✓ 完成 {task.id}]: {result_text}")

            self.engine.check_and_complete_parent(task.id)
            # 任務完成後再做一次影響掃描（此時結果已知，可能觸碰到更多節點）
            self._auto_queue_impact_checks(task)
            self._reflect(task, result_text)
            return {"status": "passed", "last_fail_reason": last_fail_reason}

        task.retry_count += 1
        new_fail_reason = reason or "未說明理由"
        task.note += f"\n(上次嘗試失敗原因: {new_fail_reason})"
        task.set_confidence(min(task.confidence, 0.4))
        self.emit(
            "log",
            f"[✗ 驗證未通過 {task.id}] 第 {task.retry_count} 次失敗: {new_fail_reason}"
        )

        if task.retry_count > MAX_RETRY_PER_TASK:
            # 跟思考卡住偵測同一個原則：反覆執行失敗，先試著拆解成更小的步驟重新來過，
            # 而不是次數一到就無腦去問使用者。只在還沒試過拆解時才嘗試一次，
            # 避免跟思考階段的拆解邏輯搶著拆同一個任務、無限循環。
            if not task.is_decomposed and task.stuck_escalation_level < 1:
                task.stuck_escalation_level = 1
                self.emit(
                    "log",
                    f"[卡住偵測] [{task.id}] 執行驗證已連續失敗 {task.retry_count} 次，"
                    f"先嘗試拆解重新規劃，而不是直接打擾使用者。"
                )
                task.need_decompose = True
                decomposed = self._decompose_task(task)
                if decomposed:
                    return {"status": "passed", "last_fail_reason": new_fail_reason}  # 已變成子任務
                task.need_decompose = False
                self.emit("log", f"[卡住偵測] [{task.id}] 拆解沒有成功，改為向使用者提問。")

            self.emit("log", f"[警告] [{task.id}] 重試次數過多，向使用者提問。")
            user_ans = self.ask_user(
                f"任務 [{task.title}] 已重試 {task.retry_count} 次仍失敗"
                f"（原因: {new_fail_reason}），請指示下一步該怎麼做？"
            )
            task.note += f"\n(使用者指示: {user_ans})"
            task.retry_count = 0
            task.think_count = 0
            task.reset_stuck_state()
            return {"status": "ask_user_resolved", "last_fail_reason": ""}

        return {"status": "retry", "last_fail_reason": new_fail_reason}
