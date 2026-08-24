import ast
import re
import difflib
import json
from openai import OpenAI

from config import (
    API_BASE_URL, API_KEY, MODEL_NAME, SYSTEM_PROMPT,
    VALUE_JUDGMENT_PROMPT
)
from agent.agent_state import (
    STOP_SEQUENCES, MAX_RESPONSE_TOKENS, HYBRID_WINDOW_MESSAGES, HISTORY_NODE_ID
)

class AgentLLMClientMixin:
    """提供 AgentWorker 與 OpenAI client 通訊、History 管理與工具呼叫解析。"""

    def _build_user_content(self, text: str, images=None):
        imgs = images if images is not None else []
        if not imgs:
            return text
        parts = [{
            "type": "text",
            "text": text or "Please describe what you see in the image in detail.",
        }]
        for url in imgs:
            if not url:
                continue
            if not str(url).startswith("data:"):
                url = f"data:image/jpeg;base64,{url}"
            parts.append({
                "type": "image_url",
                "image_url": {"url": url},
            })
        self.emit("log", f"[系統] 本輪附圖 {len(imgs)} 張（multimodal）")
        return parts

    def _maybe_compress_history(self):
        estimate_basis = [{"content": SYSTEM_PROMPT}] + self.history
        self.context_compressor.establish_baseline(
            self.context_compressor.estimate_tokens(estimate_basis)
        )
        current_tokens = self.context_compressor.estimate_tokens(estimate_basis)
        over_token_budget = self.context_compressor.should_compress(current_tokens)
        over_message_window = len(self.history) > HYBRID_WINDOW_MESSAGES

        if over_token_budget or over_message_window:
            trigger = (
                f"token 成長超過門檻（約 {current_tokens} tokens）" if over_token_budget
                else f"訊息數量超過常駐視窗大小（{len(self.history)} > {HYBRID_WINDOW_MESSAGES}）"
            )
            self.emit("log", f"[系統] 對話上下文{trigger}，自動濃縮成結構化事實...")
            try:
                self.history = self.context_compressor.compress(self._call_llm, self.history)
                self._save_history()
                self.emit("log", "[系統] 壓縮完成，繼續對話。")
            except Exception as e:
                self.emit("log", f"[警告] 自動壓縮失敗，暫時保留原本的對話歷史，稍後會再嘗試: {e}")

    def _load_history(self) -> list:
        node = self.memory_store.get_node(HISTORY_NODE_ID)
        if not node:
            return []
        messages = node.properties.get("messages", [])
        return messages if isinstance(messages, list) else []

    def _save_history(self):
        compact = []
        for m in self.history:
            content = m.get("content")
            if isinstance(content, list):
                new_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        new_parts.append({"type": "text", "text": "[圖片內容已省略，不重複保存]"})
                    else:
                        new_parts.append(part)
                compact.append({**m, "content": new_parts})
            else:
                compact.append(m)
        self.memory_store.upsert_node(HISTORY_NODE_ID, "History", properties={"messages": compact})

    def clear_conversation_history(self):
        self.history = []
        if self.memory_store.get_node(HISTORY_NODE_ID):
            self.memory_store.delete_node(HISTORY_NODE_ID)
        self.context_compressor.reset_baseline()

    def _similar_to_previous_reply(self, new_content: str, threshold: float = 0.6) -> bool:
        prev_assistant = next(
            (m.get("content") for m in reversed(self.history) if m.get("role") == "assistant"),
            None
        )
        if not prev_assistant or not isinstance(prev_assistant, str):
            return False
        if len(new_content) < 80 or len(prev_assistant) < 80:
            return False
        ratio = difflib.SequenceMatcher(None, prev_assistant, new_content).ratio()
        return ratio >= threshold

    def update_api_config(self, base_url: str, api_key: str, model_name: str):
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=90.0)

    def _call_and_execute(self, prompt: str) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        content = self._call_llm_stream(messages)
        try:
            is_tool, combined_result, interleaved_content = self._execute_tools(content)
        except Exception as e:
            self.emit("chunk", f"\n<tool_error>\n{e}\n</tool_error>\n")
            raise

        if is_tool:
            self.emit("chunk_patch", {"old": content, "new": interleaved_content})
            return combined_result
        return content

    def _call_llm(self, system_prompt: str, user_prompt: str, temperature=0.2) -> str:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        response = self.client.chat.completions.create(
            model=self.model_name, messages=messages, temperature=temperature,
            stop=STOP_SEQUENCES, max_tokens=MAX_RESPONSE_TOKENS,
        )
        return response.choices[0].message.content or ""

    def _call_llm_stream(self, messages: list) -> str:
        if self._should_stop():
            raise InterruptedError("Agent 已由使用者停止")
        response = self.client.chat.completions.create(
            model=self.model_name, messages=messages, temperature=0.1, stream=True,
            stop=STOP_SEQUENCES, max_tokens=MAX_RESPONSE_TOKENS,
        )
        self._active_stream = response
        full_content = ""
        self._last_finish_reason = None
        try:
            for chunk in response:
                if self._should_stop():
                    raise InterruptedError("Agent 已由使用者停止")
                if chunk.choices:
                    if chunk.choices[0].delta.content:
                        text = chunk.choices[0].delta.content
                        full_content += text
                        self.emit("chunk", text)
                    if getattr(chunk.choices[0], "finish_reason", None):
                        self._last_finish_reason = chunk.choices[0].finish_reason
            return full_content
        except InterruptedError:
            raise
        except Exception:
            if self._should_stop():
                raise InterruptedError("Agent 已由使用者停止")
            raise
        finally:
            self._active_stream = None
            try:
                response.close()
            except Exception:
                pass

    def _parse_structured_fields(self, text: str, field_names: list) -> dict:
        result = {}
        for name in field_names:
            match = re.search(fr'{re.escape(name)}\s*:\s*(.*)', text)
            result[name] = match.group(1).strip() if match else ""
        return result

    def _execute_tools(self, content: str):
        pattern = r'<\|tool_call\|>call:(\w+)\(([\s\S]*?)\)\s*</?\|?tool_call\|?>'
        matches = list(re.finditer(pattern, content))
        if not matches:
            return False, content, content

        combined_parts = []

        def _execute_and_format(match):
            func_name, args_str = match.group(1), match.group(2)
            if func_name in self.available_functions:
                try:
                    args, kwargs = self._parse_tool_arguments(func_name, args_str)
                    res = self.available_functions[func_name](*args, **kwargs)
                    text = f"[{func_name}]: {res}"
                    tag = "tool_result"
                except Exception as e:
                    text = f"[{func_name} 錯誤]: {e}"
                    tag = "tool_error"
            else:
                text = f"未找到函式 '{func_name}'"
                tag = "tool_error"

            combined_parts.append(text)
            return text, tag

        def _replace(match):
            text, tag = _execute_and_format(match)
            return f"{match.group(0)}\n<{tag}>\n{text}\n</{tag}>\n"

        interleaved_content = re.sub(pattern, _replace, content)
        combined_result = "\n".join(combined_parts)
        return True, combined_result, interleaved_content

    def _parse_tool_arguments(self, func_name: str, args_str: str):
        args_str = args_str.strip()
        if not args_str:
            return [], {}

        if func_name == "execute_python":
            # 優先用 ast.literal_eval 把 args_str 當成一個 Python 字串字面值來解析。
            # 這是唯一不會破壞非 ASCII 字元的做法——全程都是 Python str 在處理，
            # 沒有經過任何 bytes 編碼/解碼的轉換，模型如果照 Python 語法正確跳脫，
            # 這裡解析出來的中文字元完全不會被動到。
            try:
                parsed = ast.literal_eval(args_str)
                if isinstance(parsed, str):
                    return [parsed], {}
            except Exception:
                pass

            # ast.literal_eval 解析失敗（例如模型寫出來的字串裡有沒跳脫好的實際換行），
            # 退而求其次：只手動剝掉最外層引號，並且只替換「常見的跳脫序列本身」
            # （\n \t \" \' \\），不對整個字串做 unicode_escape 解碼——
            # 那個做法會把 UTF-8 編碼的中文字元誤判成 Latin-1 字元，變成亂碼，
            # 這正是之前「人生的意義」被印成亂碼的原因。
            code_str = args_str
            for q in ('"""', "'''", '"', "'"):
                if code_str.startswith(q) and code_str.endswith(q) and len(code_str) >= len(q) * 2:
                    code_str = code_str[len(q):-len(q)]
                    break
            code_str = (
                code_str.replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\'", "'")
                .replace("\\\\", "\\")
            )
            return [code_str], {}

        try:
            expr = ast.parse(f"dummy({args_str})", mode="eval")
            if isinstance(expr.body, ast.Call):
                args = [ast.literal_eval(a) for a in expr.body.args]
                kwargs = {kw.arg: ast.literal_eval(kw.value) for kw in expr.body.keywords}
                return args, kwargs
        except Exception:
            pass

        return [], {}

    def _judge_and_remember_from_turn(self, user_text: str, assistant_text: str):
        exchange_text = f"使用者: {user_text}\n助理: {assistant_text}"
        try:
            result = self._call_llm(VALUE_JUDGMENT_PROMPT, exchange_text, temperature=0.2)
        except Exception as e:
            self.emit("log", f"[警告] 價值判斷呼叫模型失敗，略過: {e}")
            return
        if result.strip().upper().startswith("NONE"):
            return
        facts = self._parse_memory_facts(result)
        self._remember_facts(facts, source="價值判斷")

    def _split_reflect_output(self, text: str):
        marker_start = "===MEMORY==="
        marker_end = "===END MEMORY==="
        start_idx = text.find(marker_start)
        if start_idx == -1:
            return text, []

        tree_dsl = text[:start_idx]
        rest = text[start_idx + len(marker_start):]
        end_idx = rest.find(marker_end)
        memory_text = rest if end_idx == -1 else rest[:end_idx]
        return tree_dsl, self._parse_memory_facts(memory_text)

    def _parse_memory_facts(self, text: str) -> list:
        facts = []
        blocks = re.split(r'\n(?=-\s*id\s*:)', text.strip())
        for block in blocks:
            if not block.strip():
                continue
            fact = {}
            for field in ("id", "type", "summary"):
                m = re.search(fr'-\s*{field}\s*:\s*(.*)', block)
                if m:
                    fact[field] = m.group(1).strip()
            if fact.get("id"):
                facts.append(fact)
        return facts

    def _remember_facts(self, facts: list, source: str = ""):
        for fact in facts:
            fact_id = fact.get("id")
            if not fact_id:
                continue
            fact_type = fact.get("type") or "Fact"
            summary = fact.get("summary", "")
            self.memory_store.upsert_node(fact_id, fact_type, summary=summary)
            self.working_memory.activate(fact_id)
            prefix = f"🧠 [{source}]" if source else "🧠"
            self.emit("log", f"{prefix} 自動記住了 [{fact_type}] {fact_id}: {summary}")