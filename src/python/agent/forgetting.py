"""
漸進式遺忘（Progressive Forgetting）。

對應設計裡「記憶不是 Delete，而是逐漸降低解析度」的想法：
    完整細節 (resolution_level=0)
        ↓ 太久沒人碰、也沒人存取過 → 回收 Override、退回 Parent 預設值
    已摘要 (resolution_level=1)
        ↓ 又過了更久、依然沒人碰 → 用一次 LLM 呼叫把它精煉成更抽象的摘要
    已抽象化 (resolution_level=2)（目前的終點；不做自動刪除，見下方說明）

這個模組本身只負責「決定該不該遺忘、以及怎麼遺忘」，完全不管什麼時候該被觸發——
觸發時機（多久跑一次）由呼叫端決定（見 agent_core.py 的 maybe_run_forgetting_pass）。

安全閥：
- 整個機制預設關閉（enabled=False），由使用者自己決定要不要打開（對應這次的需求）。
- pinned=True 的節點永遠跳過，這是使用者/呼叫端唯一該依賴的明確保護方式。
- protect_confidence 預設是 1.01（形同停用）：confidence 這個欄位在這個專案裡代表的是
  「這筆資料本身有多可信」，不是「這件事有多重要、值不值得留」——而且像 remember()
  這種最常見的寫入路徑根本不會讓呼叫端指定 confidence，一律預設 1.0。如果拿
  confidence>=0.95 當保護門檻，等於大多數記憶預設就永遠不會被遺忘，整個機制形同虛設。
  真的想用信心值當額外保護訊號的人，可以自行調低 protect_confidence 的門檻來啟用；
  預設情況下該由 pinned 或「多久沒被想起」自然決定，而不是被一個容易誤觸的預設值架空。
- 目前不會真的刪除節點——只降低解析度。物理刪除牽涉到不可逆的資料遺失，
  留給未來如果真的需要再做更保守的獨立機制，這裡先不碰。
"""

import time
from typing import Callable, List, Optional

from memory.memory_store import MemoryStore, MemoryNode, _compact_summary

# 預設的靜置門檻（秒）。可以在建構 ForgettingManager 時覆寫。
DEFAULT_IDLE_SECONDS_LEVEL_1 = 7 * 24 * 3600   # 7 天沒動、沒被存取 → 進入「已摘要」
DEFAULT_IDLE_SECONDS_LEVEL_2 = 30 * 24 * 3600  # 30 天 → 進入「已抽象化」

# 兩次完整 decay pass 之間至少間隔多久，避免每次對話都重新掃一次整個 Disk。
MIN_PASS_INTERVAL_SECONDS = 6 * 3600  # 6 小時

DEFAULT_PROTECT_CONFIDENCE = 1.01  # 預設「不用信心值當保護訊號」（見下方說明）

_ABSTRACT_SYSTEM_PROMPT = """你是一個記憶精煉器。下面是一個很久沒人存取過的知識節點，
請把它的描述壓縮成更抽象、更簡短的版本，只保留最核心的意涵，不需要細節。
直接輸出精煉後的一句話摘要，不要有任何其他文字、不要加引號。"""


class ForgettingManager:
    def __init__(
        self,
        idle_seconds_level_1: int = DEFAULT_IDLE_SECONDS_LEVEL_1,
        idle_seconds_level_2: int = DEFAULT_IDLE_SECONDS_LEVEL_2,
        protect_confidence: float = DEFAULT_PROTECT_CONFIDENCE,
        min_pass_interval: int = MIN_PASS_INTERVAL_SECONDS,
    ):
        self.enabled = False  # 預設關閉，由使用者決定要不要打開
        self.idle_seconds_level_1 = idle_seconds_level_1
        self.idle_seconds_level_2 = idle_seconds_level_2
        self.protect_confidence = protect_confidence
        self.min_pass_interval = min_pass_interval
        self._last_pass_at: float = 0.0

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)

    def _is_protected(self, node: MemoryNode) -> bool:
        return node.pinned or node.confidence >= self.protect_confidence

    def _idle_seconds(self, node: MemoryNode, now: float) -> float:
        # 用「最後一次被改動」跟「最後一次被存取/想起」兩者較新的那個當基準——
        # 只要有任何一種形式的「被想起」，就不該被當成遺忘的對象。
        last_touch = max(node.updated_at, node.last_accessed_at)
        return now - last_touch

    def should_run_pass(self, now: Optional[float] = None) -> bool:
        if not self.enabled:
            return False
        now = now if now is not None else time.time()
        return (now - self._last_pass_at) >= self.min_pass_interval

    def run_decay_pass(self, store: MemoryStore, call_llm: Optional[Callable] = None,
                        now: Optional[float] = None) -> List[str]:
        """跑一次完整的漸進式遺忘掃描。回傳有被改動過的節點 id 列表（方便 log/測試用）。
        call_llm(system_prompt, user_prompt) -> str：level 1→2 才會用到，不提供的話那一階就跳過。
        """
        if not self.enabled:
            return []

        now = now if now is not None else time.time()
        self._last_pass_at = now
        changed_ids: List[str] = []

        # 用 list() 先取快照，因為過程中可能會修改 store.nodes 的內容（不會增刪節點，
        # 但保險起見不要一邊疊代一邊改同一個活的 view）
        for node in list(store.nodes.values()):
            if self._is_protected(node):
                continue

            idle = self._idle_seconds(node, now)

            if node.resolution_level == 0 and idle >= self.idle_seconds_level_1:
                if self._decay_level_0_to_1(node):
                    changed_ids.append(node.id)

            elif node.resolution_level == 1 and idle >= self.idle_seconds_level_2:
                if call_llm is not None and self._decay_level_1_to_2(node, call_llm):
                    changed_ids.append(node.id)

        if changed_ids:
            store.save()
        return changed_ids

    def _decay_level_0_to_1(self, node: MemoryNode) -> bool:
        """完整 → 摘要：回收 override（回到 Parent 預設值），標記為 level 1。
        這步是純規則、不需要 LLM，所以就算沒接 LLM 也一定可以正常運作。
        """
        changed = False
        if isinstance(node.properties.get("override"), dict) and node.properties["override"]:
            del node.properties["override"]
            node.touch_version()
            changed = True
        # 遺忘只會往上升、不會還原（見 MemoryNode.resolution_level 的註解），
        # 這裡明確斷言而不是只在註解裡講——呼叫這個方法的兩個判斷條件
        # (node.resolution_level == 0) 理論上已經保證了這點，但這是那個保證
        # 唯一真正被落實的地方，之後改動判斷條件時如果不小心破壞了它，
        # 應該要立刻讓測試爆炸，而不是安靜地產生一個解析度不增反減的節點。
        assert node.resolution_level < 1, (
            f"resolution_level 只該往上升，node.resolution_level="
            f"{node.resolution_level} 不該小於 1 都還沒成立就想升到 1"
        )
        node.resolution_level = 1
        return True  # 就算沒有 override 可以回收，光是標記進入下一階本身就算一次變動

    def _decay_level_1_to_2(self, node: MemoryNode, call_llm: Callable) -> bool:
        """摘要 → 已抽象化：呼叫一次 LLM，把 summary 精煉成更抽象、更短的版本。
        呼叫失敗就放棄這一輪，維持在 level 1，下次 decay pass 再試一次，不強求一次成功。
        """
        try:
            context = f"類型: {node.type}\n目前摘要: {node.summary or '(無摘要)'}\n屬性: {node.properties}"
            new_summary = call_llm(_ABSTRACT_SYSTEM_PROMPT, context)
            new_summary = (new_summary or "").strip()
            if not new_summary:
                return False
            node.summary = _compact_summary(new_summary)
            assert node.resolution_level < 2, (
                f"resolution_level 只該往上升，node.resolution_level="
                f"{node.resolution_level} 不該小於 2 都還沒成立就想升到 2"
            )
            node.resolution_level = 2
            node.touch_version()
            return True
        except Exception:
            return False
