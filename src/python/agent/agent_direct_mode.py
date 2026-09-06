from typing import Optional, TYPE_CHECKING
from agent.agent_state import AgentState
from config import SYSTEM_PROMPT

if TYPE_CHECKING:
    from agent.agent_protocol import AgentWorkerBase as _Base
else:
    _Base = object

# 單一輪對話裡（使用者送出一次訊息之後）最多允許幾次工具呼叫來回。
# 這不是「正常操作」的限制——正常對話很少需要超過 2、3 次；這是最後一道安全網，
# 防止模型陷入「呼叫工具 -> 講幾句話 -> 又呼叫工具」的迴圈卻沒有真的往前推進。
MAX_DIRECT_MODE_ROUNDS = 6


class AgentDirectModeMixin(_Base):
    """提供 AgentWorker 直接對話/工具呼叫迴圈 (Direct Mode)。"""

    def _run_direct_mode(self, initial_content: Optional[str] = None, skip_user_append: bool = False):
        if initial_content is None:
            if not skip_user_append:
                # skip_user_append=True 是給 agent_routing.py 用的：那邊在決定要不要
                # 升級成完整規劃之前，已經把這輪使用者訊息記進 self.history 了
                # （不管有沒有升級都會記，見那邊的說明），這裡就不能再記一次，
                # 不然同一句話會在 self.history 裡出現兩次。
                user_content = self._build_user_content(self.current_user_prompt, self.current_images)
                self.history.append({"role": "user", "content": user_content})
                self.current_images = []
            self._maybe_compress_history()

        content = initial_content
        final_assistant_text = None
        round_count = 0

        if self.current_user_prompt:
            self.retriever.retrieve_for_text(self.current_user_prompt)

        while True:
            if self._should_stop():
                raise InterruptedError("Agent 已由使用者停止")

            round_count += 1
            if round_count > MAX_DIRECT_MODE_ROUNDS:
                # 這一輪已經呼叫工具/生成內容遠超過正常需要的次數了——不管每一次表面上
                # 看起來有沒有在做事，次數本身就是「亂跑」的訊號，直接問使用者，
                # 不能讓它憑自己判斷要不要停下來（已經證明不可靠）。
                self.emit(
                    "log",
                    f"[警告] 這一輪已經跑了 {round_count - 1} 個回合還沒有明確結論，"
                    f"可能卡住了或在做重複的事，向使用者提問。"
                )
                user_ans = self.ask_user(
                    f"我已經連續處理這個請求 {round_count - 1} 個回合還沒有明確結論，"
                    f"可能卡住了或在重複做同樣的事。要我繼續、換個做法，還是先停下來？"
                )
                self.history.append({"role": "user", "content": f"[System: 使用者介入]\n{user_ans}"})
                round_count = 0
                content = None
                continue

            try:
                if content is None:
                    self._maybe_compress_history()

                    attn_block, _ = self.attention_manager.build_context_block(
                        self.working_memory, task=self.current_user_prompt
                    )
                    messages = [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "system", "content": attn_block},
                    ] + self.history
                    content = self._call_llm_stream(messages)
                    # 這裡是 Direct Mode 工具呼叫迴圈的第 2 輪(以後)，模型偶爾還是會
                    # 習慣性地在這種延續回合重新吐一次 <|direct|>/<|plan|>... 標記
                    # （SYSTEM_PROMPT 的路由規則沒有特別區分「新請求」跟「同一輪的延續」），
                    # 一樣要濾掉，不然會出現圖三那種「路由標記本身被當成正式回覆」的畫面。
                    self._strip_routing_tag_for_display(content)
                    if self._should_stop():
                        raise InterruptedError("Agent 已由使用者停止")

                # 這一輪的內容跟上一輪比起來是不是幾乎一樣——不能只看「有沒有呼叫工具」，
                # 就算每一輪表面上都有呼叫工具、看起來像在做事，內容本身在原地打轉
                # 一樣要被抓出來。這裡沿用既有的 _similar_to_previous_reply，
                # 它比對的對象是 self.history 最後一則 assistant 訊息——
                # 因為每一輪都會把內容 append 進 history，所以在這裡呼叫，
                # 比對到的自然就是「上一輪」，不用另外再追蹤一個變數。
                if self._similar_to_previous_reply(content):
                    self.emit("log", "[警告] 這一輪的內容跟上一輪幾乎重複，判定為原地打轉，向使用者提問。")
                    user_ans = self.ask_user(
                        "我發現自己在重複講同樣的內容、沒有真的往前推進，要我換個做法，還是先停下來？"
                    )
                    self.history.append({"role": "user", "content": f"[System: 使用者介入]\n{user_ans}"})
                    round_count = 0
                    content = None
                    continue

                self.history.append({"role": "assistant", "content": content})
                is_tool, combined_result, interleaved_content = self._execute_tools(content)
                raw_content = content
                content = None

                if is_tool:
                    self.emit("chunk_patch", {"old": raw_content, "new": interleaved_content})
                    self.history.append({"role": "user", "content": f"[System: Tool Execution Result]\n{combined_result}"})
                else:
                    final_assistant_text = raw_content
                    break
            except InterruptedError:
                raise
            except Exception as e:
                if self._should_stop():
                    raise InterruptedError("Agent 已由使用者停止")
                self.emit("chunk", f"\n<tool_error>{str(e)}</tool_error>\n")
                break

        if final_assistant_text is not None and isinstance(final_assistant_text, str):
            self._judge_and_remember_from_turn(self.current_user_prompt, final_assistant_text)

        self.state = AgentState.IDLE
        self._save_history()
        self.emit("finished", "")