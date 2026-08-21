from agent.agent_state import AgentState
from config import SYSTEM_PROMPT

class AgentDirectModeMixin:
    """提供 AgentWorker 直接對話/工具呼叫迴圈 (Direct Mode)。"""

    def _run_direct_mode(self, initial_content: str = None):
        if initial_content is None:
            user_content = self._build_user_content(self.current_user_prompt, self.current_images)
            self.history.append({"role": "user", "content": user_content})
            self.current_images = []
            self._maybe_compress_history()

        content = initial_content
        final_assistant_text = None

        if self.current_user_prompt:
            self.retriever.retrieve_for_text(self.current_user_prompt)

        while True:
            if self._should_stop():
                raise InterruptedError("Agent 已由使用者停止")
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
                    if self._should_stop():
                        raise InterruptedError("Agent 已由使用者停止")


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
