"""
跟 LLM API 實際通訊的核心邏輯：組使用者訊息內容、非串流/串流呼叫、
切換 client 設定。

原本這個檔案還裝了對話歷史管理（見 agent_history.py）、工具呼叫解析
（見 agent_tool_execution.py）、自動記憶萃取（見 agent_memory_extraction.py），
太長，已經拆開；這裡只保留「怎麼跟 LLM 對話」本身。
"""
import os
import re
from typing import TYPE_CHECKING, Any, List, Dict
from openai import OpenAI

from config import SYSTEM_PROMPT
from agent.agent_state import STOP_SEQUENCES, MAX_RESPONSE_TOKENS
from agent.image_utils import save_data_url_to_temp

if TYPE_CHECKING:
    from agent.agent_protocol import AgentWorkerBase as _Base
else:
    _Base = object

class AgentLLMClientMixin(_Base):
    """提供 AgentWorker 與 LLM client（OpenAI SDK 相容介面）通訊的核心方法。"""

    def _build_user_content(self, text: str, images=None):
        imgs = images if images is not None else []
        if not imgs:
            return text
        parts: List[Dict[str, Any]] = [{
            "type": "text",
            "text": text or "Please describe what you see in the image in detail.",
        }]
        saved_paths = []
        for url in imgs:
            if not url:
                continue
            if not str(url).startswith("data:"):
                url = f"data:image/jpeg;base64,{url}"
            parts.append({
                "type": "image_url",
                "image_url": {"url": url},
            })
            saved_path = save_data_url_to_temp(url)
            if saved_path:
                saved_paths.append(saved_path)

        # 這則附圖不管接下來走哪個 client 都會經過這裡，所以在這裡統一補一段文字說明，
        # 而不是分別在各個 client adapter（例如 llama_client.py）裡各做各的：
        # - 如果真的是多模態模型，它會直接從上面的 image_url parts 看到圖片本身，
        #   這段文字只是錦上添花的補充資訊，不影響它原本就能看到圖片這件事。
        # - 如果背後其實是純文字模型（不管是本地 Llama 直接載入，還是 remote_api
        #   指到一個文字模型），image_url parts 會被那個 client 的 adapter 忽略/丟掉，
        #   但這段文字是 type: text，一定會被送到，讓模型知道「有圖、路徑在這、
        #   想看內容自己呼叫視覺工具」，而不是完全不知道使用者其實有附圖。
        if saved_paths:
            note = (
                f"[系統：這則訊息附上了 {len(saved_paths)} 張圖片，已存成暫存檔：\n"
                + "\n".join(f"- {p}" for p in saved_paths)
                + "\n如果你目前看得到圖片本身（多模態模型），可以直接忽略這段話。"
                  "如果你看不到圖片內容，請先判斷這則訊息是否需要理解圖片才能回答："
                  "需要的話呼叫 analyze_image_visuals(image_path=...) 做整體畫面分析，"
                  "或 analyze_image_ocr(image_path=...) 做精準文字/座標辨識；"
                  "如果視覺工具本身失敗或不可用，才如實告知使用者你目前無法直接查看圖片內容，"
                  "並請使用者用文字描述，不要憑空猜測或編造圖片裡有什麼。]"
            )
            parts.append({"type": "text", "text": note})

        self.emit("log", f"[系統] 本輪附圖 {len(imgs)} 張（multimodal）")
        return parts

    def update_api_config(self, base_url: str, api_key: str, model_name: str):
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=90.0)

    def load_llama_model(self, model_path: str, n_ctx: int = 8192, n_gpu_layers: int = -1):
        from agent.llama_client import LlamaClient
        self.client = LlamaClient(model_path=model_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers)
        self.model_name = os.path.basename(model_path)

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
        if self.client is None:
            raise RuntimeError("LLM Client 尚未初始化")
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        response = self.client.chat.completions.create(
            model=self.model_name, messages=messages, temperature=temperature,  # type: ignore[arg-type]
            stop=STOP_SEQUENCES, max_tokens=MAX_RESPONSE_TOKENS,
        )
        return response.choices[0].message.content or ""

    def _call_llm_stream(self, messages: list) -> str:
        if self._should_stop():
            raise InterruptedError("Agent 已由使用者停止")
        if self.client is None:
            raise RuntimeError("LLM Client 尚未初始化")
        response = self.client.chat.completions.create(
            model=self.model_name, messages=messages, temperature=0.1, stream=True,  # type: ignore[arg-type]
            stop=STOP_SEQUENCES, max_tokens=MAX_RESPONSE_TOKENS,
        )
        self._active_stream = response
        full_content = ""
        self._last_finish_reason = None
        next_repeat_check_at = 780  # window*3，累積到這個長度才第一次檢查，避免對短內容誤判
        try:
            for chunk in response:
                if self._should_stop():
                    raise InterruptedError("Agent 已由使用者停止")
                if chunk.choices:
                    if chunk.choices[0].delta.content:
                        text = chunk.choices[0].delta.content
                        full_content += text
                        self.emit("chunk", text)

                        if len(full_content) >= next_repeat_check_at:
                            next_repeat_check_at = len(full_content) + 150
                            if self._is_repeating_tail(full_content):
                                self.emit(
                                    "log",
                                    "[系統] 即時偵測到生成內容重複、原地打轉，提前中止本次生成。"
                                )
                                self._last_finish_reason = "repetition_detected"
                                return full_content
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
