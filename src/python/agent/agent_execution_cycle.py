import re
from config import (
    SYSTEM_PROMPT, PLANNER_SYSTEM_PROMPT, THINKING_SYSTEM_PROMPT,
    VERIFY_SYSTEM_PROMPT, DECOMPOSE_SYSTEM_PROMPT, REFLECT_SYSTEM_PROMPT
)
from agent.agent_state import AgentState, MAX_RETRY_PER_TASK
from agent.task_system import ExecutionMode, TaskNode, TaskStatus

class AgentExecutionMixin:
    """提供 AgentWorker 狀態機執行流程（Reasoning, Planning, Task Cycle）。"""

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
            if self.current_images:
                self.emit("log", "[系統] 偵測到附圖，進入直接對話（Vision）模式。")
                self._run_direct_mode()
                return

            if self._should_stop():
                raise InterruptedError("Agent 已由使用者停止")

            self.emit("log", "[系統] 開始推理，判斷任務難度...")
            self._maybe_compress_history()
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
            elif truncated_without_conclusion:
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
            return

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

        ladder = ["replan", "expand_memory", "ask_user"]
        idx = min(task.stuck_escalation_level, len(ladder) - 1)
        return ladder[idx]

    def _call_planner_with_repair(self, planner_user_prompt: str, max_retries: int = 1):
        """呼叫 Planner 產生 DSL，解析失敗時自動重試修正。回傳 None 代表徹底失敗。"""
        return self._call_dsl_with_repair(PLANNER_SYSTEM_PROMPT, planner_user_prompt, max_retries)

    def _should_pause_before(self, next_task: TaskNode) -> bool:
        if self.engine.mode == ExecutionMode.STEP_BY_STEP:
            return True
        if self.engine.mode == ExecutionMode.AUTO:
            return False
        if self.engine.mode == ExecutionMode.SMART:
            return next_task.need_confirm
        return True

    def _apply_fresh_observation_decision(self, task: TaskNode) -> str:
        """Apply an explicit directive from fresh observations relevant to task."""
        observations = self.memory_store.get_fresh_observations(
            self.working_memory.active_ids()
        )
        actions = {obs.properties.get("runtime_action", "context") for obs in observations}

        if "replan" in actions:
            summaries = [obs.summary for obs in observations if obs.properties.get("runtime_action") == "replan"]
            result = "；".join(filter(None, summaries)) or "新鮮 Observation 要求重新規劃"
            self.emit("log", f"[Observation] [{task.id}] 觸發重新規劃: {result}")
            self._reflect(task, result, in_progress=True,
                          reason="fresh Observation runtime_action=replan")
            task.status = TaskStatus.PENDING
            return "replan"

        if "skip_task" in actions:
            summaries = [obs.summary for obs in observations if obs.properties.get("runtime_action") == "skip_task"]
            result = "；".join(filter(None, summaries)) or "新鮮 Observation 表示此步驟不需要執行"
            task.status = TaskStatus.COMPLETED
            task.result = f"由 Observation 跳過：{result}"
            self.engine.check_and_complete_parent(task.id)
            self.emit("log", f"[Observation] [✓ 跳過 {task.id}]: {result}")
            self._reflect(task, task.result)
            return "skip_task"

        return "context"

    def _process_task(self, task: TaskNode) -> bool:
        last_fail_reason = ""

        # ------------------------------------------------------------------
        # 任務開始前：Retrieve → Attend → 潛在影響預掃
        # ------------------------------------------------------------------
        # 1. 根據任務內容從 Disk 拉取相關節點進 Working Memory
        retrieved_ids = self.retriever.retrieve_for_task(task)
        if retrieved_ids:
            self.emit(
                "log",
                f"[Retriever] [{task.id}] 啟用了 {len(retrieved_ids)} 個相關節點: "
                + ", ".join(retrieved_ids[:5])
                + (" …" if len(retrieved_ids) > 5 else "")
            )

        observation_decision = self._apply_fresh_observation_decision(task)
        if observation_decision == "skip_task":
            return True
        if observation_decision == "replan":
            return True

        # 2. 潛在影響預掃（任務開始前）
        #    找出這個任務可能觸碰到的已知節點，提前插入影響檢查任務，
        #    讓模型在執行前就能注意到潛在的連帶影響。
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
                effective_think_limit = task.think_limit_override or self.max_think_limit

                if task.think_count >= effective_think_limit:
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
                        continue

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
                            return True
                        task.need_decompose = False
                        task.think_limit_override = task.think_count + 1
                        self.emit("log", f"[卡住偵測] [{task.id}] 拆解沒有成功，繼續嘗試下一種手段。")
                        continue

                    if action == "expand_memory":
                        task.stuck_escalation_level = 2
                        self.emit(
                            "log",
                            f"[卡住偵測] [{task.id}] 拆解也無濟於事，擴大記憶檢索範圍再試一次。"
                        )
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
                        continue

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
                    last_fail_reason = ""
                else:
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
                    # Attention Manager 組出 token-budget 以內的 Context 區塊
                    attn_block, _ = self.attention_manager.build_context_block(
                        self.working_memory, task=task
                    )
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
                        return False

                    fields = self._parse_structured_fields(
                        think_res, ["分析", "修正方法", "修正注意", "拆解", "新信心值"]
                    )
                    self.emit("log", f"💡 [{task.id}] 思考分析: {fields.get('分析', '')[:150]}")

                    if self._maybe_handle_replan_marker(task, think_res):
                        return True

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
                            task.set_confidence(float(fields["新信心值"]))
                    except ValueError:
                        pass

            # Attention Manager 組出 token-budget 以內的 Context 區塊（執行步驟用）
            attn_block, _ = self.attention_manager.build_context_block(
                self.working_memory, task=task
            )
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
                return False

            if self._maybe_handle_replan_marker(task, result_text):
                return True

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
                return True

            task.retry_count += 1
            last_fail_reason = reason or "未說明理由"
            task.note += f"\n(上次嘗試失敗原因: {last_fail_reason})"
            task.set_confidence(min(task.confidence, 0.4))
            self.emit(
                "log",
                f"[✗ 驗證未通過 {task.id}] 第 {task.retry_count} 次失敗: {last_fail_reason}"
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
                        return True
                    task.need_decompose = False
                    self.emit("log", f"[卡住偵測] [{task.id}] 拆解沒有成功，改為向使用者提問。")

                self.emit("log", f"[警告] [{task.id}] 重試次數過多，向使用者提問。")
                user_ans = self.ask_user(
                    f"任務 [{task.title}] 已重試 {task.retry_count} 次仍失敗"
                    f"（原因: {last_fail_reason}），請指示下一步該怎麼做？"
                )
                task.note += f"\n(使用者指示: {user_ans})"
                task.retry_count = 0
                task.think_count = 0
                task.reset_stuck_state()

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
        """跟 _call_planner_with_repair 邏輯相同，供拆解等其他也輸出 Task DSL 的呼叫共用。"""
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

    _REPLAN_MARKER_RE = re.compile(r'<\|replan\|>\s*(.*)', re.DOTALL)

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
