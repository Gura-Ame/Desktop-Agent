import os
from typing import Optional, List, Dict, Any, Generator


class _ChunkDelta:
    def __init__(self, content: str = ""):
        self.content = content


class _ChunkChoice:
    def __init__(self, delta: _ChunkDelta, finish_reason: Optional[str] = None):
        self.delta = delta
        self.finish_reason = finish_reason


class _StreamChunk:
    def __init__(self, content: str = "", finish_reason: Optional[str] = None):
        self.choices = [_ChunkChoice(_ChunkDelta(content), finish_reason)]


class _Message:
    def __init__(self, content: str = ""):
        self.content = content


class _Choice:
    def __init__(self, message: _Message, finish_reason: str = "stop"):
        self.message = message
        self.finish_reason = finish_reason


class _CompletionResponse:
    def __init__(self, content: str = "", finish_reason: str = "stop"):
        self.choices = [_Choice(_Message(content), finish_reason)]


class _LlamaCompletions:
    def __init__(self, llama_instance: Any):
        self.llama = llama_instance

    def create(
        self,
        model: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        stream: bool = False,
        stop: Optional[List[str]] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> Any:
        if self.llama is None:
            raise RuntimeError(
                "Llama 模型實例未載入成功。請確認 TEXT_MODEL_PATH 存在或使用 load_llama_model 載入模型。"
            )

        clean_messages = []
        for m in messages or []:
            content = m.get("content", "")
            if isinstance(content, list):
                # 處理 multimodal 或結構化 parts
                text_parts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                content = " ".join(text_parts) if text_parts else str(content)
            clean_messages.append({"role": m.get("role", "user"), "content": content})

        if stream:

            def _stream_gen() -> Generator[_StreamChunk, None, None]:
                raw_stream = self.llama.create_chat_completion(
                    messages=clean_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stop=stop,
                    stream=True,
                )
                for chunk in raw_stream:
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        finish_reason = choices[0].get("finish_reason")
                        yield _StreamChunk(content, finish_reason)

            class _StreamWrapper:
                def __init__(self, gen):
                    self._gen = gen

                def __iter__(self):
                    return self._gen

                def close(self):
                    pass

            return _StreamWrapper(_stream_gen())
        else:
            raw = self.llama.create_chat_completion(
                messages=clean_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop,
                stream=False,
            )
            choice = raw["choices"][0]
            content = choice["message"]["content"] or ""
            finish_reason = choice.get("finish_reason", "stop")
            return _CompletionResponse(content, finish_reason)


class _LlamaChat:
    def __init__(self, llama_instance: Any):
        self.completions = _LlamaCompletions(llama_instance)


class LlamaClient:
    """
    提供相容 OpenAI ChatCompletions 介面的本地 Llama (llama-cpp-python) Client。
    直接以 in-process 載入 GGUF 權重進行推理，不需依賴外部伺服器。
    """

    def __init__(
        self,
        model_path: str,
        n_ctx: int = 8192,
        n_gpu_layers: int = -1,
        verbose: bool = False,
    ):
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.verbose = verbose
        self.llama = None
        self._load_model()
        self.chat = _LlamaChat(self.llama)

    def _load_model(self):
        if not self.model_path or not os.path.exists(self.model_path):
            print(f"[提示] Llama 模型路徑目前不可用: {self.model_path}")
            return

        try:
            from llama_cpp import Llama

            print(f"\n[系統] 正在使用 Llama (llama-cpp-python) 載入本地 GGUF: {self.model_path}")
            self.llama = Llama(
                model_path=self.model_path,
                n_ctx=self.n_ctx,
                n_gpu_layers=self.n_gpu_layers,
                verbose=self.verbose,
            )
            print("[系統] Llama 本地模型載入成功！\n")
        except Exception as e:
            print(f"[錯誤] 載入 Llama 模型失敗: {e}")
            self.llama = None
