"""
自動記憶寫入：從一輪對話（價值判斷）或 Reflect 輸出裡萃取值得長期記住的事實，
不需要模型主動呼叫 remember()。

從 agent_llm_client.py 拆出來——這部分是「從文字裡萃取出結構化事實、寫進
Disk」，跟怎麼呼叫 LLM API 本身是不同層次的事。
"""
import re
from typing import TYPE_CHECKING
from config import VALUE_JUDGMENT_PROMPT

if TYPE_CHECKING:
    from agent.agent_protocol import AgentWorkerBase as _Base
else:
    _Base = object


class AgentMemoryExtractionMixin(_Base):
    """提供 AgentWorker 從對話/Reflect 輸出自動萃取並寫入長期記憶的能力。"""

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
