import re
import ast
import time
import threading
from enum import Enum
from openai import OpenAI

from config import (
    API_BASE_URL, API_KEY, MODEL_NAME, SYSTEM_PROMPT,
    ROUTER_PROMPT, PLANNER_SYSTEM_PROMPT, REFLECT_SYSTEM_PROMPT,
    THINKING_SYSTEM_PROMPT, VERIFY_SYSTEM_PROMPT, DECOMPOSE_SYSTEM_PROMPT
)
from task_system import TaskEngine, ExecutionMode, TaskStatus, TaskNode

# 單一任務連續驗證失敗超過這個次數，就不再自己悶著頭重試，改為向使用者提問
MAX_RETRY_PER_TASK = 3


class AgentState(Enum):
    IDLE = "IDLE"
    WAITING_CONFIRM = "WAITING_CONFIRM"
    EXECUTING = "EXECUTING"


class AgentWorker:
    def __init__(self, available_functions: dict, event_callback, default_mode=ExecutionMode.STEP_BY_STEP):
        self.available_functions = available_functions
        self.available_functions["ask_user"] = self.ask_user
        self.event_callback = event_callback

        self.base_url = API_BASE_URL
        self.api_key = API_KEY
        self.model_name = MODEL_NAME
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=90.0)
        self.engine = TaskEngine(mode=default_mode)
        self.state = AgentState.IDLE

        self.current_user_prompt = ""
        self.history = []
        self.is_paused_for_input = False
        self.user_reply_content = ""
        self.max_think_limit = 3
        self._thread = None

    # ------------------------------------------------------------------
    # 基礎設施：事件、使用者輸入、狀態控制
    # ------------------------------------------------------------------
    def emit(self, event_type: str, payload: any):
        if self.event_callback:
            self.event_callback(event_type, payload)

    def ask_user(self, question: str) -> str:
        self.is_paused_for_input = True
        self.emit("waiting_input", question)
        self.emit("log", f"❓ Agent 提問等待中: {question}")
        while self.is_paused_for_input:
            time.sleep(0.1)
        return f"User replied: {self.user_reply_content}"

    def resume_with_user_input(self, text: str):
        self.user_reply_content = text
        self.is_paused_for_input = False

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_user_prompt(self, user_prompt: str):
        self.current_user_prompt = user_prompt

    def set_execution_mode(self, mode: ExecutionMode):
        self.engine.mode = mode

    def update_api_config(self, base_url: str, api_key: str, model_name: str):
        """前端可以動態切換連線的 LLM 端點/金鑰/模型名稱。"""
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=90.0)

    def confirm_and_start(self):
        self.state = AgentState.EXECUTING
        self.start()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def _run(self):
        self.emit("started", None)

        # 1. 第一階段：路由判斷 (Router) —— 模型自己決定要不要 Planning
        if self.state == AgentState.IDLE:
            self.emit("log", "[系統] 正在分析任務複雜度 (Router)...")
            route_decision = self._route_intent(self.current_user_prompt)

            if route_decision == "DIRECT":
                self.emit("log", "[系統] 判斷為直接對話模式。")
                self._run_direct_mode()
                return

            self.emit("log", "[系統] 判斷為複雜任務，進入 Planning 模式生成 Task Tree...")
            try:
                dsl_plan = self._call_llm(PLANNER_SYSTEM_PROMPT, self.current_user_prompt)
            except Exception as e:
                self.emit("log", f"[錯誤] Planning 呼叫模型失敗: {e}，轉為直接模式。")
                self._run_direct_mode()
                return

            if self.engine.load_initial_plan(dsl_plan):
                self.state = AgentState.WAITING_CONFIRM
                # 整個計畫的第一次審視，不受執行模式影響，一律需要人工確認才會開始跑
                self.emit("ask_confirm", self.engine.render_tree_markdown())
                return
            else:
                self.emit("log", "[錯誤] 生成 Task Tree 解析失敗，轉為直接模式。")
                self._run_direct_mode()
                return

        # 2. 第二階段：任務樹執行 —— 每個任務都會跑 think/decompose/execute/verify/retry 迴圈
        if self.state == AgentState.EXECUTING:
            while True:
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
                    # 只有底層系統性錯誤（例如模型連線本身掛掉）才會走到這裡，
                    # 任務本身「驗證失敗」不會、而是在 _process_task 內自己重試/拆解/提問。
                    task.status = TaskStatus.FAILED
                    self.state = AgentState.IDLE
                    self.emit("finished", f"Task {task.id} failed due to a system-level error.")
                    break

                # 決定要不要在下一步之前暫停，讓使用者確認
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
                    # AUTO 模式，或 SMART 模式判定這一步不需要確認 -> 迴圈直接繼續處理下一個任務

    def _should_pause_before(self, next_task: TaskNode) -> bool:
        """依照目前的執行模式，決定跑下一個任務之前要不要暫停等使用者確認。"""
        if self.engine.mode == ExecutionMode.STEP_BY_STEP:
            return True  # 無視任務自己的判斷，一律暫停
        if self.engine.mode == ExecutionMode.AUTO:
            return False  # 無視任務自己的判斷，一律不暫停
        if self.engine.mode == ExecutionMode.SMART:
            return next_task.need_confirm  # 交給模型當初規劃這個任務時標的判斷
        return True  # 未知模式，保守起見預設暫停

    # ------------------------------------------------------------------
    # 單一任務的 Decompose / Think / Execute / Verify / Retry 狀態機
    # ------------------------------------------------------------------
    def _process_task(self, task: TaskNode) -> bool:
        """處理單一任務直到「驗證通過」或「被拆解成子任務交給主迴圈」為止。
        回傳 False 只代表底層系統性錯誤（模型連線失敗等），
        任務邏輯上的失敗一律在內部透過 thinking / retry / decompose / ask_user 自行收斂，
        絕不會悄悄放棄整條任務鏈。
        """
        last_fail_reason = ""

        while True:
            # --- 0. 是否需要先拆解成子任務，而不是直接嘗試執行 ---
            if task.need_decompose and not task.is_decomposed:
                decomposed = self._decompose_task(task)
                if decomposed:
                    # 把處理權交還給主迴圈：下一個 pending 任務就會是它的第一個子任務
                    return True
                # 拆解失敗（模型連線問題或格式解析失敗）就放棄拆解，改為直接嘗試執行這個任務
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
                    think_context = (
                        f"當前任務: {task.title}\n"
                        f"目前方法: {task.method}\n"
                        f"目前注意事項: {task.note}\n"
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

                    # 思考後如果模型認為這個任務其實該拆解，就中斷這輪、改走拆解流程
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

            # --- 執行 ---
            step_prompt = (
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

            # --- 驗證：獨立呼叫，實際比對「條件」跟「結果」，不是靠有沒有 exception ---
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

                # 如果這個任務是某個拆解出來的子任務，檢查兄弟姊妹是否也都完成了，
                # 完成的話父任務自動標記完成（並往上遞迴檢查，支援巢狀拆解）。
                self.engine.check_and_complete_parent(task.id)

                self._reflect(task, result_text)
                return True

            task.retry_count += 1
            last_fail_reason = reason or "未說明理由"
            task.note += f"\n(上次嘗試失敗原因: {last_fail_reason})"
            task.confidence = min(task.confidence, 0.4)  # 強制下一輪進入思考
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
            # 迴圈繼續：因為 confidence 已被壓低或 last_fail_reason 非空，
            # 下一輪會自動進入思考階段（也可能因此判定需要拆解），帶著失敗原因重新規劃方法。

    def _decompose_task(self, task: TaskNode) -> bool:
        """呼叫拆解 prompt，把過於複雜的任務展開成子任務，插入到它後面。"""
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
        """任務完成後，檢視最新資訊並動態調整後續 Task Tree。
        套用前會經過 TaskEngine 的安全驗證，避免已完成/已拆解的任務被模型漏寫或打亂。
        """
        self.emit("log", "[系統] 檢視最新獲得資訊，動態調整後續 Task Tree...")
        reflect_prompt = (
            f"剛完成任務 [{task.id}]，結果為:\n{result_text}\n\n"
            f"當前完整任務樹:\n{self.engine.render_tree_markdown()}"
        )
        try:
            updated_dsl = self._call_llm(REFLECT_SYSTEM_PROMPT, reflect_prompt)
        except Exception as e:
            self.emit("log", f"[警告] Reflect 呼叫模型失敗，保留原任務樹: {e}")
            return

        ok, msg = self.engine.apply_reflected_dsl(updated_dsl)
        if ok:
            self.emit("log", f"[系統] {msg}")
        else:
            self.emit("log", f"[警告] Task Tree 更新被拒絕: {msg}")

    # ------------------------------------------------------------------
    # 直接對話模式（不經過 Task Tree）
    # ------------------------------------------------------------------
    def _run_direct_mode(self):
        self.history.append({"role": "user", "content": self.current_user_prompt})

        while True:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self.history
            try:
                content = self._call_llm_stream(messages)
                self.history.append({"role": "assistant", "content": content})
                is_tool, tool_result = self._parse_and_execute_tool(content)

                if is_tool:
                    # 乾淨輸出結構化標籤，不混入任何 UI 樣式與 Emoji
                    self.emit("chunk", f"\n<tool_result>\n{tool_result}\n</tool_result>\n")
                    self.history.append({"role": "user", "content": f"[System: Tool Execution Result]\n{tool_result}"})
                else:
                    break
            except Exception as e:
                self.emit("chunk", f"\n<tool_error>{str(e)}</tool_error>\n")
                break

        self.state = AgentState.IDLE
        self.emit("finished", "")

    # ------------------------------------------------------------------
    # LLM / 工具呼叫的共用小工具
    # ------------------------------------------------------------------
    def _call_and_execute(self, prompt: str) -> str:
        """呼叫 LLM 產生回覆並執行其中的工具呼叫，回傳「拿去驗證用」的結果文字。
        會直接把底層例外往外丟，由呼叫端判斷這是系統性錯誤還是任務失敗。
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        content = self._call_llm_stream(messages)
        is_tool, tool_result = self._parse_and_execute_tool(content)
        return tool_result if is_tool else content

    def _route_intent(self, user_prompt: str) -> str:
        res = self._call_llm(ROUTER_PROMPT, user_prompt, temperature=0.0).strip().upper()
        return "PLANNING" if "PLANNING" in res else "DIRECT"

    def _call_llm(self, system_prompt: str, user_prompt: str, temperature=0.2) -> str:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        response = self.client.chat.completions.create(
            model=self.model_name, messages=messages, temperature=temperature
        )
        return response.choices[0].message.content or ""

    def _call_llm_stream(self, messages: list) -> str:
        response = self.client.chat.completions.create(
            model=self.model_name, messages=messages, temperature=0.1, stream=True
        )
        full_content = ""
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full_content += text
                self.emit("chunk", text)
        return full_content

    def _parse_structured_fields(self, text: str, field_names: list) -> dict:
        """通用結構化欄位解析：用於 Thinking / Verify 這種要求模型輸出固定欄位的回覆。
        每個欄位對應 text 中第一個「欄位名: 內容」的出現位置。
        """
        result = {}
        for name in field_names:
            match = re.search(fr'{re.escape(name)}\s*:\s*(.*)', text)
            result[name] = match.group(1).strip() if match else ""
        return result

    def _parse_and_execute_tool(self, content: str):
        # 使用非貪婪匹配，並確保比對到該 Tool Call 結尾的 )<|tool_call|>
        pattern = r'<\|tool_call\|>call:(\w+)\(([\s\S]*?)\)\s*</?\|?tool_call\|?>'
        matches = re.findall(pattern, content)
        if not matches:
            return False, content

        results = []
        for func_name, args_str in matches:
            if func_name in self.available_functions:
                try:
                    args, kwargs = self._parse_tool_arguments(func_name, args_str)
                    res = self.available_functions[func_name](*args, **kwargs)
                    results.append(f"[{func_name}]: {res}")
                except Exception as e:
                    results.append(f"[{func_name} 錯誤]: {e}")
            else:
                results.append(f"未找到函式 '{func_name}'")

        return True, "\n".join(results)

    def _parse_tool_arguments(self, func_name: str, args_str: str):
        args_str = args_str.strip()
        if not args_str:
            return [], {}

        # 1. execute_python：專用字串剝除邏輯
        if func_name == "execute_python":
            code_str = args_str
            for q in ('"""', "'''", '"', "'"):
                if code_str.startswith(q) and code_str.endswith(q) and len(code_str) >= len(q) * 2:
                    code_str = code_str[len(q):-len(q)]
                    break
            try:
                code_str = bytes(code_str, "utf-8").decode("unicode_escape")
            except Exception:
                pass
            return [code_str], {}

        # 2. 一般工具：補回括號供 ast.parse 解析
        try:
            expr = ast.parse(f"dummy({args_str})", mode="eval")
            if isinstance(expr.body, ast.Call):
                args = [ast.literal_eval(a) for a in expr.body.args]
                kwargs = {kw.arg: ast.literal_eval(kw.value) for kw in expr.body.keywords}
                return args, kwargs
        except Exception:
            pass

        return [], {}
