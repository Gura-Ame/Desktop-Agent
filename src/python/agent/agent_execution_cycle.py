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
                try:
                    dsl_plan = self._call_llm(PLANNER_SYSTEM_PROMPT, planner_user_prompt)
                except Exception as e:
                    self.emit("log", f"[錯誤] Planning 呼叫模型失敗: {e}，轉為直接模式重試。")
                    self._run_direct_mode()
                    return

                if self.engine.load_initial_plan(dsl_plan):
                    self.state = AgentState.WAITING_CONFIRM
                    self.emit("ask_confirm", self.engine.render_tree_markdown())
                    return
                else:
                    self.emit("log", "[錯誤] 生成 Task Tree 解析失敗，轉為直接模式。")
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

    def _should_pause_before(self, next_task: TaskNode) -> bool:
        if self.engine.mode == ExecutionMode.STEP_BY_STEP:
            return True
        if self.engine.mode == ExecutionMode.AUTO:
            return False
        if self.engine.mode == ExecutionMode.SMART:
            return next_task.need_confirm
        return True

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

                self.engine.check_and_complete_parent(task.id)
                # 任務完成後再做一次影響掃描（此時結果已知，可能觸碰到更多節點）
                self._auto_queue_impact_checks(task)
                self._reflect(task, result_text)
                return True

            task.retry_count += 1
            last_fail_reason = reason or "未說明理由"
            task.note += f"\n(上次嘗試失敗原因: {last_fail_reason})"
            task.confidence = min(task.confidence, 0.4)
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

    def _decompose_task(self, task: TaskNode) -> bool:
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
