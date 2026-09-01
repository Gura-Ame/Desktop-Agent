"""
MemoryNode：Disk Memory 圖裡的單一節點資料模型。

從 memory_store.py 拆出來（那個檔案原本同時裝了節點資料模型跟整個
儲存/查詢引擎，太長）。這裡只管「一個節點自己的欄位、狀態轉換規則」；
跨節點的查詢、關聯、遺忘掃描邏輯留在 memory_store.py 的 MemoryStore。
"""
import json
import time
import hashlib
from typing import Optional, List, Dict, Any

# 摘要長度上限（以字元數計）。這是「強迫精簡」的關鍵：不管呼叫端（remember、
# record_observation、Reflect 的 MEMORY 區塊、價值判斷、context_compressor...）
# 有沒有照 prompt 的要求寫得精簡，寫進 Disk 之前一律在這裡被截斷。
# 只靠 prompt 拜託模型「summary 精簡一點」不可靠——這顆模型已經證明不會每次都聽話，
# 真正的強制只能發生在儲存層，讓所有寫入路徑都逃不掉，而不是每個呼叫端各自小心。
MAX_SUMMARY_LENGTH = 60

# --- Activation 用的參數 ---
# 半衰期：距離上次被想起（讀取/被 bump）多久之後，activation 分數衰減到剩一半。
# 3 天：讓「這幾天一直在用的東西」明顯比「上週用過一次就沒再碰」的東西更容易被想起，
# 但也不會永遠佔著高分——放著不管幾週後就會自然淡回接近 0。
ACTIVATION_HALF_LIFE_SECONDS = 3 * 24 * 3600
# 每次被讀取（get_node / search 命中）時，在目前衰減後的基礎上疊加的增量。
# 疊加而不是直接設成固定值：短時間內反覆被想起的東西，分數會持續墊高（封頂 1.0），
# 這樣才符合「越常想到的東西，第一個被想到的機率越高」的設計初衷。
ACTIVATION_BOOST = 0.35


def _compact_summary(summary: str) -> str:
    """把摘要截斷到 MAX_SUMMARY_LENGTH 字元以內，超過的部分用省略號取代結尾。"""
    if not summary:
        return summary
    summary = summary.strip()
    if len(summary) <= MAX_SUMMARY_LENGTH:
        return summary
    return summary[:MAX_SUMMARY_LENGTH - 1].rstrip() + "…"


class MemoryNode:
    def __init__(self, id: str, type: str, properties: Optional[dict] = None,
                 summary: str = "", confidence: float = 1.0, version: Optional[str] = None):
        self.id = id
        self.type = type
        self.properties: Dict[str, Any] = properties or {}
        self.relations: List[Dict[str, str]] = []  # [{"rel": "CALLS", "target": "..."}]
        self.summary = _compact_summary(summary)
        self.confidence = confidence
        self.version = version if version is not None else self._compute_version()
        self.updated_at = time.time()

        # --- 漸進式遺忘用的欄位 ---
        # resolution_level: 0=完整細節 1=已摘要（override 已被回收） 2=已抽象化（LLM 重新精煉過摘要）
        # 只會往上升，遺忘是單向的降低解析度，不是還原（還原的話跟沒遺忘一樣，失去意義）。
        self.resolution_level: int = 0
        # last_accessed_at：跟 updated_at 不同——updated_at 只在「內容被寫入/修改」時更新，
        # last_accessed_at 在「被讀取/被想起」時也會更新（見 MemoryStore.get_node / search）。
        # 遺忘該看的是「多久沒人理它」，一個常被查詢但內容穩定不變的節點不該被誤判成該遺忘。
        self.last_accessed_at: float = self.updated_at
        # pinned：使用者或呼叫端可以標記「這個永遠不要被自動遺忘」，作為安全閥。
        self.pinned: bool = False

        # --- Activation 用的欄位（跨 session 持續存在，會存進 Disk） ---
        # activation：目前的啟用分數（尚未套用衰減的「基準值」，實際使用時一律透過
        # get_effective_activation() 取得套用衰減後的即時值，不要直接讀這個原始欄位）。
        self.activation: float = 0.0
        # activation_updated_at：上一次 bump_activation() 的時間點，用來計算衰減經過了多久。
        self.activation_updated_at: float = self.updated_at

    def get_effective_activation(self, now: Optional[float] = None) -> float:
        """算出套用衰減後的即時 activation 分數，純讀取不修改狀態。
        就算 Activation 功能被使用者關閉，這個函式本身仍然可以正常呼叫——
        只是因為從來沒有 bump 過，activation 永遠是 0，效果自然等於沒有這個機制，
        不需要另外用開關去攔截這個函式本身。
        """
        if self.activation <= 0:
            return 0.0
        now = now if now is not None else time.time()
        elapsed = max(0.0, now - self.activation_updated_at)
        decay = 0.5 ** (elapsed / ACTIVATION_HALF_LIFE_SECONDS)
        return self.activation * decay

    def bump_activation(self, boost: float = ACTIVATION_BOOST, now: Optional[float] = None):
        """這個節點被想起了一次（被讀取到）：先套用衰減算出目前的真實分數，
        再疊加一次 boost，並把時間基準重設成現在。只有在 MemoryStore.activation_enabled
        為 True 時才會被呼叫到，關閉時這個方法完全不會被觸發，activation 就會一直停在 0。
        """
        now = now if now is not None else time.time()
        current = self.get_effective_activation(now)
        self.activation = min(1.0, current + boost)
        self.activation_updated_at = now

    def touch_access(self):
        self.last_accessed_at = time.time()

    def _compute_version(self) -> str:
        """properties 的內容指紋。properties 一變，version 就變，
        Observation 就可以用這個判斷自己的結論是不是根據舊資料下的。"""
        raw = json.dumps(self.properties, sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]

    def touch_version(self):
        self.version = self._compute_version()
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "properties": self.properties,
            "relations": self.relations, "summary": self.summary,
            "confidence": self.confidence, "version": self.version,
            "updated_at": self.updated_at,
            "resolution_level": self.resolution_level,
            "last_accessed_at": self.last_accessed_at,
            "pinned": self.pinned,
            "activation": self.activation,
            "activation_updated_at": self.activation_updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryNode":
        node = cls(d["id"], d["type"], d.get("properties", {}),
                   d.get("summary", ""), d.get("confidence", 1.0), d.get("version"))
        node.relations = d.get("relations", [])
        node.updated_at = d.get("updated_at", time.time())
        node.resolution_level = d.get("resolution_level", 0)
        node.last_accessed_at = d.get("last_accessed_at", node.updated_at)
        node.pinned = d.get("pinned", False)
        node.activation = d.get("activation", 0.0)
        node.activation_updated_at = d.get("activation_updated_at", node.updated_at)
        return node
