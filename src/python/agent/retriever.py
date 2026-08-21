"""
Retriever：Disk → Working Memory 的閘道。

不讓模型靠自己記得呼叫 recall——那是「主動記憶」工具，適合模型想要手動存取的情境。
Retriever 做的是另一件事：在每個任務**執行前**，系統自動根據任務內容把
Disk 裡相關的節點拉進 WorkingMemory，確保模型開始執行時 Context 裡已有必要背景。

設計原則：
- 只負責「拉進 WorkingMemory」，不直接構建 Context 字串（那是 AttentionManager 的事）
- 關聯擴展只走**一層**（CALLS / INSTANCE_OF），避免圖遍歷爆炸
- 節點已在 WorkingMemory 只刷新 LRU，不重複讀 Disk
"""

import re
from typing import TYPE_CHECKING

from memory.memory_store import MemoryStore
from agent.working_memory import WorkingMemory

if TYPE_CHECKING:
    from agent.task_system import TaskNode

# 圖遍歷時展開的關聯類型（只往外走一層）
_EXPAND_RELS = {"CALLS", "INSTANCE_OF", "ABOUT", "MENTIONS"}

# 關鍵字提取時要去掉的停用詞（避免 "的"、"是" 這種毫無辨識力的詞干擾搜尋）
_STOP_WORDS = {
    "的", "是", "在", "有", "和", "與", "或", "了", "把", "被", "讓", "這", "那",
    "它", "其", "我", "你", "他", "她", "們", "一個", "一些", "以及", "可以",
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "for",
    "and", "or", "not", "with", "from", "that", "this", "be", "do",
}


class Retriever:
    def __init__(self, store: MemoryStore, working_memory: WorkingMemory):
        self.store = store
        self.working_memory = working_memory

    def retrieve_for_text(self, text: str, top_k: int = 8) -> list[str]:
        """根據任意文字（使用者對話、任務描述等），從 Disk 拉取相關節點進 WorkingMemory。

        分三步：
        1. 從文字抽關鍵字
        2. 對每個關鍵字查 MemoryStore.search()，收集候選種子節點
        3. 對候選節點沿關聯走一層（Lazy Graph Expansion），拿到鄰居
        4. activate 進 WorkingMemory（受 max_nodes LRU 控制），回傳已啟用的 id 列表
        """
        keywords = self._extract_keywords_from_text(text)
        if not keywords:
            return []

        # 第一步：關鍵字搜尋，收集種子節點
        seeds: dict[str, int] = {}  # node_id -> 命中次數（命中越多次越相關）
        for kw in keywords:
            for node in self.store.search(kw, limit=top_k):
                seeds[node.id] = seeds.get(node.id, 0) + 1

        if not seeds:
            return []

        # 按命中次數排序，取 top_k 個種子
        sorted_seeds = sorted(seeds, key=lambda nid: -seeds[nid])[:top_k]

        # 第二步：關聯擴展一層
        to_activate: list[str] = []
        seen: set[str] = set()
        for seed_id in sorted_seeds:
            if seed_id not in seen:
                to_activate.append(seed_id)
                seen.add(seed_id)
            node = self.store.get_node(seed_id)
            if node:
                for rel in node.relations:
                    if rel["rel"] in _EXPAND_RELS and rel["target"] not in seen:
                        to_activate.append(rel["target"])
                        seen.add(rel["target"])
                # 反向：誰指向這個種子（例如哪些函式 CALL 了它）
                for incoming_id in self.store.get_incoming(seed_id):
                    if incoming_id not in seen:
                        to_activate.append(incoming_id)
                        seen.add(incoming_id)

        # 第三步：activate（WorkingMemory 的 LRU 會自動控制總量）
        activated: list[str] = []
        for nid in to_activate:
            if self.working_memory.activate(nid):
                activated.append(nid)

        return activated

    def retrieve_for_task(self, task: "TaskNode", top_k: int = 8) -> list[str]:
        """根據任務的 title + method + note，從 Disk 拉取相關節點進 WorkingMemory。"""
        text = " ".join(filter(None, [task.title, task.method, task.note]))
        return self.retrieve_for_text(text, top_k=top_k)

    def retrieve_for_keywords(self, keywords: list[str], top_k: int = 5) -> list[str]:
        """給 recall_related 等工具使用的輕量版本，直接傳入關鍵字列表。"""
        seen: set[str] = set()
        activated: list[str] = []
        for kw in keywords:
            for node in self.store.search(kw, limit=top_k):
                if node.id not in seen:
                    seen.add(node.id)
                    if self.working_memory.activate(node.id):
                        activated.append(node.id)
        return activated

    # ------------------------------------------------------------------
    # 關鍵字提取（不依賴外部 NLP，只做簡單的詞切割 + 停用詞過濾）
    # ------------------------------------------------------------------
    def _extract_keywords_from_text(self, text: str) -> list[str]:
        if not text:
            return []
        # 先用空白/標點切開，再用中文字元邊界切（英數字段保持完整）
        tokens = re.findall(r"[A-Za-z0-9_\.]+|[\u4e00-\u9fff]+", text)
        # 中文段再逐字或二元組展開（單字容易誤判，取 2~4 字片段）
        expanded: list[str] = []
        for tok in tokens:
            if re.match(r"[\u4e00-\u9fff]+", tok):
                # 中文：原始片語 + 每個 2~3 字的子串
                if len(tok) >= 2:
                    expanded.append(tok)
                for n in (2, 3):
                    expanded.extend(tok[i:i+n] for i in range(len(tok) - n + 1))
            else:
                # 英數：直接用，長度 >= 3 才有辨識意義
                if len(tok) >= 3:
                    expanded.append(tok.lower())

        # 過濾停用詞，去重
        seen: set[str] = set()
        result: list[str] = []
        for kw in expanded:
            kw_l = kw.lower()
            if kw_l not in _STOP_WORDS and kw_l not in seen:
                seen.add(kw_l)
                result.append(kw)
        return result

    def _extract_keywords(self, task: "TaskNode") -> list[str]:
        text = " ".join(filter(None, [task.title, task.method, task.note]))
        return self._extract_keywords_from_text(text)

