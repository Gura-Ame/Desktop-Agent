"""
Working Memory：本次任務的暫存區，不是永久記憶。

只放「目前任務需要」的少數 Object，超過上限就用 LRU 把最少用到的丟掉——
丟掉只是不再放進 Context，Disk 上的資料本身完全不受影響，要用隨時可以再 activate 回來。

Lazy Expansion：render_context 預設每個節點只給 summary（一行摘要），
只有明確要求展開的節點，才會把完整 properties / relations 塞進去，
避免「先讀了 a() 相關聯」就把整包資料一次全倒進 Context。
"""

import time
from collections import OrderedDict
from typing import Optional, Iterable

from memory.memory_store import MemoryStore, MemoryNode


class WorkingMemory:
    def __init__(self, store: MemoryStore, max_nodes: int = 20):
        self.store = store
        self.max_nodes = max_nodes
        self._active: "OrderedDict[str, MemoryNode]" = OrderedDict()
        # activation_time[node_id] = monotonic timestamp，供 AttentionManager 計算 recency
        self._activation_time: dict[str, float] = {}

    def activate(self, node_id: str) -> Optional[MemoryNode]:
        """把某個節點從 Disk 拉進 Working Memory（如果已經在裡面，只是刷新它的使用順序）。"""
        node = self.store.get_node(node_id)
        if node is None:
            return None
        now = time.monotonic()
        if node_id in self._active:
            self._active.move_to_end(node_id)
        else:
            self._active[node_id] = node
            if len(self._active) > self.max_nodes:
                evicted_id, _ = self._active.popitem(last=False)  # 丟掉最久沒被用到的
                self._activation_time.pop(evicted_id, None)
        self._activation_time[node_id] = now
        return node

    def activate_many(self, node_ids: Iterable[str]):
        for nid in node_ids:
            self.activate(nid)

    def deactivate(self, node_id: str):
        self._active.pop(node_id, None)
        self._activation_time.pop(node_id, None)

    def clear(self):
        self._active.clear()
        self._activation_time.clear()

    def active_ids(self) -> list[str]:
        return list(self._active.keys())

    def iter_by_recency(self):
        """按 activation_time 由新到舊排序，回傳 (node_id, node) 迭代器。
        提供給 AttentionManager 使用，讓最近剛被 retrieve 到的節點優先進 Context。
        """
        return sorted(
            self._active.items(),
            key=lambda item: self._activation_time.get(item[0], 0.0),
            reverse=True,  # 最新的在前
        )

    def render_context(self, expand_ids: Optional[Iterable[str]] = None) -> str:
        expand_ids = set(expand_ids or [])
        if not self._active:
            return "### 【Working Memory】\n(目前沒有已啟用的節點)"

        lines = ["### 【Working Memory】"]
        for nid, node in self._active.items():
            lines.append(f"- [{node.type}] {nid} (信心值 {node.confidence:.2f})")
            if node.summary:
                lines.append(f"  摘要: {node.summary}")
            if nid in expand_ids:
                if node.properties:
                    lines.append(f"  屬性: {node.properties}")
                if node.relations:
                    rel_text = ", ".join(f"{r['rel']}->{r['target']}" for r in node.relations)
                    lines.append(f"  關聯: {rel_text}")
        return "\n".join(lines)
