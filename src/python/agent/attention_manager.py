"""
Attention Manager：Working Memory → Context 的閘道。

Working Memory 可能有 20 個節點，但真正能送給模型的 token 很有限
（8192 context window，扣掉 SYSTEM_PROMPT、Task Tree、history 後，
Working Memory 區塊大概只剩 600~700 tokens，約 1320~1540 字元）。

Attention Manager 的工作：
- 對 WorkingMemory 裡的節點打分排序
- 在 token_budget 以內：分數高的展開（properties + relations），分數低的只給 summary
- 完全放不下的不輸出（仍在 WorkingMemory，下次 retrieve 可能再拿到）

分數計算（各項相加）：
  +relevance : 節點 id 或 summary 含有 task 關鍵字 → 每個關鍵字命中 +0.3，最多 +0.9
  +confidence: 節點的 confidence 直接作為分數（0~1）
  +recency   : 最近 activate 的 → 線性插值 0~0.5（最新的 0.5，最舊的 0）
  +activation: 跨 session 累積的「常被想起」分數，套用時間衰減後 * 0.4（見 memory_store.py
               的 MemoryNode.get_effective_activation）。這一項預設幾乎不影響排序——
               只有使用者開啟 Activation 功能、節點被讀取過，activation 才會 > 0；
               關閉時所有節點的 activation 永遠是 0，這一項自然變成沒有作用的 no-op，
               不需要在這裡另外查一次「功能有沒有開」。
  -uncertainty: has_dynamic_call=True 或 ExternalRef 類型 → -0.2（靜態圖不確定，降展開優先度）
"""

import re
import time
from typing import TYPE_CHECKING

from agent.working_memory import WorkingMemory
from memory.memory_store import MemoryNode

if TYPE_CHECKING:
    from agent.task_system import TaskNode

# token_budget 保守上限，留夠空間給 system prompt / task tree / LLM output
# 8192 context - ~3000 system+task - ~2000 history - ~1500 LLM output ≈ 1700 剩餘
# Working Memory 只用其中約 650 tokens（避免邊界爆炸）
DEFAULT_TOKEN_BUDGET = 650

# 粗略估算：每個字元約 0.45 tokens（中英混合，比純英文低）
_CHARS_PER_TOKEN = 2.2

# activation 這項訊號的權重。跟 relevance（最高 0.9）、recency（最高 0.5）同量級，
# 給它足夠份量在關鍵字打平手時能真的影響排序，但又不會蓋過真正的關鍵字相關性。
ACTIVATION_WEIGHT = 0.4


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


class AttentionManager:
    def build_context_block(
        self,
        working_mem: WorkingMemory,
        task: "TaskNode | str | None" = None,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ) -> tuple[str, set[str]]:
        """從 WorkingMemory 組出 Context 區塊字串，同時回傳被展開的節點 id 集合。

        回傳值：(context_str, expanded_ids)
        """
        if not working_mem._active:
            return "### 【Working Memory】\n(目前沒有已啟用的節點)", set()

        keywords = self._task_keywords(task) if task else set()
        scored = self._score_nodes(working_mem, keywords)

        budget_chars = int(token_budget * _CHARS_PER_TOKEN)
        used_chars = 0
        lines: list[str] = ["### 【Working Memory】"]
        header_chars = _estimate_tokens("### 【Working Memory】\n") * _CHARS_PER_TOKEN
        used_chars += header_chars

        expanded_ids: set[str] = set()

        for node_id, score, node in scored:
            # --- summary 行（一定要有，即使 budget 快滿也盡量給一行 summary）---
            conf_str = f"{node.confidence:.2f}"
            summary_line = f"- [{node.type}] {node_id} (信心值 {conf_str})"
            if node.summary:
                summary_line += f"\n  摘要: {node.summary}"
            summary_chars = len(summary_line) + 1

            if used_chars + summary_chars > budget_chars:
                # budget 用盡，後面的節點都跳過
                break
            lines.append(summary_line)
            used_chars += summary_chars

            # --- 展開層（只對分數高的節點展開）---
            # 分數 > 0.8 或 budget 還有一半以上剩餘時展開
            remaining_ratio = 1 - (used_chars / budget_chars)
            should_expand = score > 0.8 or remaining_ratio > 0.5

            if should_expand and (node.properties or node.relations):
                expand_parts: list[str] = []

                if node.properties:
                    # 只展示非標準書記用屬性（file/lineno 等對模型沒意義的跳過）
                    skip_props = {"file", "lineno", "qualified_name"}
                    display_props = {k: v for k, v in node.properties.items() if k not in skip_props}
                    if display_props:
                        expand_parts.append(f"  屬性: {display_props}")

                if node.relations:
                    rel_text = ", ".join(
                        f"{r['rel']}→{r['target']}" for r in node.relations[:6]  # 最多顯示 6 條
                    )
                    if len(node.relations) > 6:
                        rel_text += f" …(共 {len(node.relations)} 條)"
                    expand_parts.append(f"  關聯: {rel_text}")

                if expand_parts:
                    expand_str = "\n".join(expand_parts)
                    expand_chars = len(expand_str) + 1
                    if used_chars + expand_chars <= budget_chars:
                        lines.append(expand_str)
                        used_chars += expand_chars
                        expanded_ids.add(node_id)

        if len(scored) > len(lines) - 1:
            omitted = len(scored) - (len(lines) - 1)
            lines.append(f"  …（另有 {omitted} 個節點因 token 預算不足暫不顯示）")

        return "\n".join(lines), expanded_ids

    # ------------------------------------------------------------------
    # 打分
    # ------------------------------------------------------------------
    def _score_nodes(
        self, working_mem: WorkingMemory, keywords: set[str]
    ) -> list[tuple[str, float, MemoryNode]]:
        """回傳 [(node_id, score, node), ...] 按 score 降序排列。

        使用 iter_by_recency() 取得按 activation_time 排序的節點列表，
        確保 recency score 與真實的最後啟用時間對齊（而不是 OrderedDict 的插入順序）。
        """
        items_by_recency = working_mem.iter_by_recency()  # 最新在前
        n = len(items_by_recency)
        scored: list[tuple[str, float, MemoryNode]] = []

        for rank, (node_id, node) in enumerate(items_by_recency):
            # recency score：rank=0 最新 → 0.5，rank=n-1 最舊 → 0
            recency = ((n - 1 - rank) / max(n - 1, 1)) * 0.5

            # relevance score：關鍵字命中（大小寫不敏感子字串比對）
            text = (node_id + " " + (node.summary or "")).lower()
            hits = sum(1 for kw in keywords if kw in text)
            relevance = min(hits * 0.3, 0.9)

            # confidence（節點自己帶的可信度）
            confidence = node.confidence

            # uncertainty penalty（靜態圖不確定的節點，降低展開優先度）
            uncertainty = 0.0
            if node.properties.get("has_dynamic_call") or node.type == "ExternalRef":
                uncertainty = 0.2

            # activation（跨 session 的「常被想起」訊號，關閉時恆為 0，見上方說明）
            activation = 0.0
            if hasattr(node, "get_effective_activation"):
                activation = node.get_effective_activation() * ACTIVATION_WEIGHT

            score = recency + relevance + confidence + activation - uncertainty
            scored.append((node_id, score, node))

        scored.sort(key=lambda x: -x[1])
        return scored

    @staticmethod
    def _task_keywords(task: "TaskNode | str | None") -> set[str]:
        if not task:
            return set()
        if isinstance(task, str):
            text = task
        else:
            text = " ".join(filter(None, [task.title, task.method, task.note]))
        tokens = re.findall(r"[A-Za-z0-9_\.]+|[\u4e00-\u9fff]{2,}", text)
        return {t.lower() for t in tokens if len(t) >= 2}

