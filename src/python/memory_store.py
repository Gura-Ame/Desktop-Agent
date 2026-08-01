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


class MemoryNode:
    def __init__(self, id: str, type: str, properties: dict = None,
                 summary: str = "", confidence: float = 1.0, version: str = None):
        self.id = id
        self.type = type
        self.properties: Dict[str, Any] = properties or {}
        self.relations: List[Dict[str, str]] = []  # [{"rel": "CALLS", "target": "..."}]
        self.summary = summary
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
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.nodes = {nid: MemoryNode.from_dict(nd) for nid, nd in raw.items()}

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
                node.summary = summary
            node.confidence = confidence
            node.touch_version()
        self.save()
        return node

    def get_node(self, id: str) -> Optional[MemoryNode]:
        return self.nodes.get(id)

    def delete_node(self, id: str):
        if id in self.nodes:
            del self.nodes[id]
            # 順手清掉指向它的關聯，避免留下斷鏈
            for n in self.nodes.values():
                n.relations = [r for r in n.relations if r["target"] != id]
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
        self.save()

    def get_outgoing(self, id: str, rel: str = None) -> List[str]:
        node = self.nodes.get(id)
        if not node:
            return []
        return [r["target"] for r in node.relations if rel is None or r["rel"] == rel]

    def get_incoming(self, id: str, rel: str = None) -> List[str]:
        """誰指向這個節點？—— 全表掃描，圖不大時夠用；
        真的變大了再加反向索引快取，介面不用改。"""
        result = []
        for nid, n in self.nodes.items():
            for r in n.relations:
                if r["target"] == id and (rel is None or r["rel"] == rel):
                    result.append(nid)
        return result

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
            properties={"conclusion": conclusion, "based_on_version": based_on_version},
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
