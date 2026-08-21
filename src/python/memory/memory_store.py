"""
Disk Memory：長期知識庫。

設計原則（對應討論裡的想法）：
- 每件事都是一個 Object（MemoryNode）：id / type / properties / relations / summary / confidence / version
- 關聯 (Relation) 是一等公民：CALLS、INSTANCE_OF、ABOUT... 都用同一種機制表示
- 抽象屬性只存一次：靠 INSTANCE_OF 關聯往上查，不重複寫進每個實例
- Event 可以對它引用的 Object 做局部覆寫 (override)，不用整份複製
- Observation 是一種特殊節點：存放「上次分析的結論」，並記錄當時目標物件的 version，
  之後可以快速判斷「這個結論還新不新鮮」而不用每次都重新分析
"""

import json
import os
import time
import hashlib
from typing import Optional, List, Dict, Any

# 摘要長度上限（以字元數計）。這是「強迫精簡」的關鍵：不管呼叫端（remember、
# record_observation、Reflect 的 MEMORY 區塊、價值判斷、context_compressor...）
# 有沒有照 prompt 的要求寫得精簡，寫進 Disk 之前一律在這裡被截斷。
# 只靠 prompt 拜託模型「summary 精簡一點」不可靠——這顆模型已經證明不會每次都聽話，
# 真正的強制只能發生在儲存層，讓所有寫入路徑都逃不掉，而不是每個呼叫端各自小心。
MAX_SUMMARY_LENGTH = 60


def _compact_summary(summary: str) -> str:
    """把摘要截斷到 MAX_SUMMARY_LENGTH 字元以內，超過的部分用省略號取代結尾。"""
    if not summary:
        return summary
    summary = summary.strip()
    if len(summary) <= MAX_SUMMARY_LENGTH:
        return summary
    return summary[:MAX_SUMMARY_LENGTH - 1].rstrip() + "…"


class MemoryNode:
    def __init__(self, id: str, type: str, properties: dict = None,
                 summary: str = "", confidence: float = 1.0, version: str = None):
        self.id = id
        self.type = type
        self.properties: Dict[str, Any] = properties or {}
        self.relations: List[Dict[str, str]] = []  # [{"rel": "CALLS", "target": "..."}]
        self.summary = _compact_summary(summary)
        self.confidence = confidence
        self.version = version if version is not None else self._compute_version()
        self.updated_at = time.time()

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
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryNode":
        node = cls(d["id"], d["type"], d.get("properties", {}),
                   d.get("summary", ""), d.get("confidence", 1.0), d.get("version"))
        node.relations = d.get("relations", [])
        node.updated_at = d.get("updated_at", time.time())
        return node


class MemoryStore:
    """整個 Disk Memory 的存取層。目前用單一 JSON 檔案落地，
    圖的規模大了之後（幾萬個節點）建議換成 sqlite，但介面可以維持不變。
    """

    def __init__(self, path: str = "agent_memory.json"):
        self.path = path
        self.nodes: Dict[str, MemoryNode] = {}
        # 反向索引：target_id -> [{"rel":..., "source":...}, ...]，讓 get_incoming 不用
        # 每次都全表掃描所有節點的所有關聯。這是純執行期的衍生資料，跟 self.nodes 的
        # relations 保持同步（在 add_relation / delete_node 裡維護），不會落地存進 JSON——
        # 存了也沒意義，只要有 nodes 的 relations 在，隨時可以重建。
        self._reverse_index: Dict[str, List[Dict[str, str]]] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.nodes = {nid: MemoryNode.from_dict(nd) for nid, nd in raw.items()}
        self._rebuild_reverse_index()

    def _rebuild_reverse_index(self):
        """從目前所有節點的 relations（正向）重新算出反向索引。
        載入既有檔案、或任何懷疑索引跟實際資料對不上的情況都可以呼叫這個重新校正。
        """
        self._reverse_index = {}
        for source_id, node in self.nodes.items():
            for r in node.relations:
                self._reverse_index.setdefault(r["target"], []).append(
                    {"rel": r["rel"], "source": source_id}
                )

    def save(self):
        raw = {nid: n.to_dict() for nid, n in self.nodes.items()}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # 基本 CRUD
    # ------------------------------------------------------------------
    def upsert_node(self, id: str, type: str, properties: dict = None,
                     summary: str = "", confidence: float = 1.0) -> MemoryNode:
        node = self.nodes.get(id)
        if node is None:
            node = MemoryNode(id, type, properties, summary, confidence)
            self.nodes[id] = node
        else:
            if properties:
                node.properties.update(properties)
            if summary:
                node.summary = _compact_summary(summary)
            node.confidence = confidence
            node.touch_version()
        self.save()
        return node

    def get_node(self, id: str) -> Optional[MemoryNode]:
        return self.nodes.get(id)

    def delete_node(self, id: str):
        if id in self.nodes:
            removed_node = self.nodes.pop(id)
            # 這個節點自己的出邊，要從它們各自目標的反向索引裡移除
            for r in removed_node.relations:
                entries = self._reverse_index.get(r["target"])
                if entries:
                    self._reverse_index[r["target"]] = [
                        e for e in entries if not (e["source"] == id and e["rel"] == r["rel"])
                    ]
                    if not self._reverse_index[r["target"]]:
                        del self._reverse_index[r["target"]]
            # 順手清掉指向它的關聯，避免留下斷鏈
            for n in self.nodes.values():
                n.relations = [r for r in n.relations if r["target"] != id]
            # 這個節點作為 target 的反向索引項目整個消失（上面那個迴圈已經把來源端的
            # relations 清乾淨了，這裡把反向索引也一起清掉，兩邊才會保持一致）
            self._reverse_index.pop(id, None)
            self.save()

    # ------------------------------------------------------------------
    # 關聯
    # ------------------------------------------------------------------
    def add_relation(self, source_id: str, rel: str, target_id: str):
        node = self.nodes.get(source_id)
        if node is None:
            raise KeyError(f"找不到來源節點 {source_id}")
        if target_id not in self.nodes:
            raise KeyError(f"找不到目標節點 {target_id}")
        if not any(r["rel"] == rel and r["target"] == target_id for r in node.relations):
            node.relations.append({"rel": rel, "target": target_id})
            self._reverse_index.setdefault(target_id, []).append(
                {"rel": rel, "source": source_id}
            )
        self.save()

    def get_outgoing(self, id: str, rel: str = None) -> List[str]:
        node = self.nodes.get(id)
        if not node:
            return []
        return [r["target"] for r in node.relations if rel is None or r["rel"] == rel]

    def get_incoming(self, id: str, rel: str = None) -> List[str]:
        """誰指向這個節點？—— 直接查反向索引，O(命中筆數)，不用每次都全表掃描。
        索引在 add_relation / delete_node 裡同步維護，_load 時從 nodes 重建一次。
        """
        entries = self._reverse_index.get(id, [])
        return [e["source"] for e in entries if rel is None or e["rel"] == rel]

    def search(self, keyword: str, limit: int = 10) -> List["MemoryNode"]:
        """聯想式搜尋：靠關鍵字比對 id / type / summary，不需要事先知道精確的 id。

        recall(id) 要求呼叫端已經知道確切的 key，但實際使用上模型自己某一輪隨手取的
        id，換一輪之後很可能想不起來自己當初怎麼命名——這就是純粹 key-value 查詢的
        根本限制。人腦回想一件事靠的是「這跟什麼有關」，不是精確的鑰匙，所以這裡改成
        關鍵字比對，讓「大概記得是什麼」也能找得到，而不是非得「精確記得叫什麼」不可。

        比對方式很單純（大小寫不敏感的子字串比對），排序上讓「id 或 type 命中」優先於
        「只有 summary 命中」——命中欄位愈精確的，通常愈可能是真正要找的東西。
        """
        keyword_lower = keyword.strip().lower()
        if not keyword_lower:
            return []

        strong_matches = []
        weak_matches = []
        for node in self.nodes.values():
            if keyword_lower in node.id.lower() or keyword_lower in node.type.lower():
                strong_matches.append(node)
            elif keyword_lower in (node.summary or "").lower():
                weak_matches.append(node)

        return (strong_matches + weak_matches)[:limit]

    # ------------------------------------------------------------------
    # 抽象繼承 + Event Override（牛排/高蛋白 那個例子）
    # ------------------------------------------------------------------
    def get_effective_properties(self, id: str) -> Dict[str, Any]:
        """沿著 INSTANCE_OF 往上查，把抽象層屬性合併下來。
        越具體的節點優先權越高（會覆寫掉繼承來的同名屬性）。
        """
        node = self.nodes.get(id)
        if not node:
            return {}

        chain = []
        current = node
        seen = set()
        while current:
            chain.append(current)
            parents = self.get_outgoing(current.id, rel="INSTANCE_OF")
            if not parents or parents[0] in seen:
                break
            seen.add(parents[0])
            current = self.nodes.get(parents[0])

        merged: Dict[str, Any] = {}
        for n in reversed(chain):  # 從最抽象的先疊上去，最具體的最後蓋上去
            merged.update(n.properties)
        return merged

    def get_properties_with_event_override(self, id: str, event_id: str) -> Dict[str, Any]:
        """在「effective properties」的基礎上，再套用某個 Event 節點對它做的局部覆寫。
        Event 節點的 properties 裡放一個 "override": {...} 就會被套用。
        """
        base = self.get_effective_properties(id)
        event = self.nodes.get(event_id)
        if event:
            override = event.properties.get("override", {})
            base.update(override)
        return base

    # ------------------------------------------------------------------
    # Observation：快取「上次分析的結論」，並能判斷是否過期
    # ------------------------------------------------------------------
    def record_observation(self, obs_id: str, about_id: str, conclusion: str, confidence: float = 0.8) -> MemoryNode:
        about_node = self.nodes.get(about_id)
        based_on_version = about_node.version if about_node else None

        obs = self.upsert_node(
            obs_id, "Observation",
            properties={"based_on_version": based_on_version},
            summary=conclusion, confidence=confidence,
        )
        if about_id in self.nodes:
            self.add_relation(obs_id, "ABOUT", about_id)
        return obs

    def is_observation_stale(self, observation_id: str) -> bool:
        """目標物件的內容自從這個 Observation 產生之後有沒有變過？"""
        obs = self.nodes.get(observation_id)
        if not obs:
            return True
        about = self.get_outgoing(obs.id, rel="ABOUT")
        if not about:
            return True
        target = self.nodes.get(about[0])
        if not target:
            return True
        return obs.properties.get("based_on_version") != target.version
