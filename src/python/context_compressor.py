"""
自動上下文壓縮。

核心想法：不依賴模型自己記得呼叫 remember/recall——那是給模型「主動想存什麼」用的工具，
但模型很多時候根本不會想到要用。這裡做的是另一件事：由 *系統本身* 監控 context 大小，
超過門檻就強制把舊的部分濃縮成結構化事實寫進 MemoryStore，然後把送給模型的訊息砍短。
模型每一輪看到的東西，永遠只夠支撐「當下這一步」的判斷，不會無限累積下去。

這一層完全不管 inference 是走 HTTP 打 LM Studio 還是本地 GGUF——它只決定「這次要送多少
東西給模型」，跟後端無關。KV cache 怎麼被重用/捨棄是 server 端的事，不需要在這裡插手。
"""

import re
from typing import Callable, Dict, List, Optional

from memory_store import MemoryStore
from config import COMPRESS_SYSTEM_PROMPT


class ContextCompressor:
    def __init__(self, memory_store: MemoryStore, growth_ratio: float = 0.2):
        """
        growth_ratio: 相對於「這次對話/任務開頭」的 context 大小，成長超過這個比例就觸發壓縮。
        預設 0.2 代表成長超過 20%（變成原本的 1.2 倍以上）就壓縮。
        """
        self.memory_store = memory_store
        self.growth_ratio = growth_ratio
        self.baseline_tokens: Optional[int] = None

    def reset_baseline(self):
        """開始一段新的對話/任務時呼叫，清掉舊的基準值，避免跨任務互相影響。"""
        self.baseline_tokens = None

    def establish_baseline(self, token_count: int):
        if self.baseline_tokens is None:
            self.baseline_tokens = max(token_count, 1)

    def should_compress(self, current_tokens: int) -> bool:
        if self.baseline_tokens is None or self.baseline_tokens <= 0:
            return False
        return current_tokens > self.baseline_tokens * (1 + self.growth_ratio)

    @staticmethod
    def estimate_tokens(messages: List[Dict[str, str]]) -> int:
        """沒有真正 tokenizer 時的粗略估算（中英混合抓每 2.2 字元約 1 token）。
        這裡只拿來判斷「要不要壓縮」的相對門檻，baseline 跟 current 都用同一套估法，
        系統性誤差會互相抵銷，所以估算準不準沒那麼重要，重要的是前後一致。
        """
        total_chars = sum(len(m.get("content", "") or "") for m in messages)
        return max(1, int(total_chars / 2.2))

    def compress(self, call_llm_fn: Callable[[str, str], str],
                 history: List[Dict[str, str]], keep_last_turns: int = 2) -> List[Dict[str, str]]:
        """把 history 濃縮成結構化事實寫進 MemoryStore，回傳一份短很多的新 history。

        call_llm_fn: 簽名為 (system_prompt, user_prompt) -> str，通常直接傳 AgentWorker._call_llm。
        keep_last_turns: 最近幾輪原文保留不壓，維持當下對話的直接連續性。
        """
        if len(history) <= keep_last_turns:
            return history  # 太短，還不需要壓

        to_compress = history[:-keep_last_turns] if keep_last_turns > 0 else history
        keep_raw = history[-keep_last_turns:] if keep_last_turns > 0 else []

        transcript = "\n\n".join(
            f"[{m.get('role', '?')}]\n{m.get('content', '')}" for m in to_compress
        )
        response = call_llm_fn(COMPRESS_SYSTEM_PROMPT, transcript)
        facts = self._parse_facts(response)

        for i, fact in enumerate(facts, start=1):
            fact_id = fact.get("id") or f"compressed_fact_{i}"
            self.memory_store.upsert_node(
                fact_id, fact.get("type") or "Fact",
                properties={"detail": fact.get("detail", "")},
                summary=fact.get("summary", ""),
            )

        if facts:
            summary_lines = [f"- [{f.get('type') or 'Fact'}] {f.get('summary', '')}" for f in facts]
            primer = (
                "（先前的對話已經被自動濃縮，以下是保留下來的關鍵事實，"
                "完整細節已經寫進長期記憶，需要時可以用 recall 查回來）\n"
                + "\n".join(summary_lines)
            )
        else:
            primer = "（先前的對話已經被自動濃縮，但這次沒有抽出明確的結構化事實。）"

        new_history = [{"role": "system", "content": primer}] + keep_raw
        # 重新建立 baseline，避免壓完之後馬上又因為原本的門檻被觸發一次
        self.baseline_tokens = self.estimate_tokens(new_history)
        return new_history

    def _parse_facts(self, text: str) -> List[Dict[str, str]]:
        facts = []
        blocks = re.split(r'\n(?=-\s*id\s*:)', text.strip())
        for block in blocks:
            if not block.strip():
                continue
            fact = {}
            for field in ("id", "type", "summary", "detail"):
                m = re.search(fr'-\s*{field}\s*:\s*(.*)', block)
                if m:
                    fact[field] = m.group(1).strip()
            if fact.get("id") or fact.get("summary"):
                facts.append(fact)
        return facts
