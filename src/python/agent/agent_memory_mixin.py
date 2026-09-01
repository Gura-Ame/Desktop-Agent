import json
import re
import difflib
from typing import Optional, TYPE_CHECKING
from agent.task_system import TaskNode

if TYPE_CHECKING:
    from agent.agent_protocol import AgentWorkerBase as _Base
else:
    _Base = object

# remember() 判斷「摘要跟既有節點很像，可能是重複」的相似度門檻（difflib ratio，0~1）。
# 設得偏高：只在「幾乎在講同一件事」時才提醒，避免摘要都被壓縮到 60 字內、
# 用詞略有重疊就一直跳出一堆假警報，反而讓模型學會忽略這個提醒。
_DUPLICATE_SUMMARY_SIMILARITY_THRESHOLD = 0.72

class AgentMemoryMixin(_Base):
    """提供 AgentWorker 長期記憶與程式碼關聯圖呼叫介面。"""

    _IMPACT_CHECK_EXCLUDED_TYPES = ("History", "Observation")

    def remember(self, id: str, type: str, summary: str = "", properties: Optional[dict] = None) -> str:
        is_new = id not in self.memory_store.nodes
        node = self.memory_store.upsert_node(id, type, properties=properties or {}, summary=summary)
        self.working_memory.activate(id)
        self.emit("log", f"🧠 記住了 [{node.type}] {id}: {summary}")

        warning = ""
        if is_new and summary:
            duplicate = self._find_likely_duplicate(id, type, summary)
            if duplicate is not None:
                warning = (
                    f"\n⚠️ 注意：這個摘要跟已經存在的 [{duplicate.type}] {duplicate.id}"
                    f"（摘要: {duplicate.summary}）看起來很相似，有可能是同一件事被存成了"
                    f"兩個不同的 id。如果真的是同一件事，建議之後改用 recall(\"{duplicate.id}\")"
                    f"或 relate() 把兩者關聯起來，不要讓同一個概念散落在多個 id 底下，"
                    f"不然之後查詢時反而容易漏掉一半。如果其實是不同的事，忽略這個提醒即可。"
                )
        return f"已記住 {id}（{type}）: {summary or '(無摘要)'}" + warning

    def _find_likely_duplicate(self, new_id: str, new_type: str, new_summary: str):
        """用摘要文字相似度找『很可能是同一件事、卻被存成不同 id』的既有節點。

        只做提示，不強制擋下——語意相近不代表真的重複（摘要被壓縮到 60 字內，
        用詞略有出入很正常，例如「Rust 所有權機制」跟「Rust 的所有權系統」講的是
        同一件事，但完全不相似的兩件事也可能剛好用詞接近）。呼應設計文件裡
        「只保存唯一事實」的想法：與其在儲存層強制去重（容易誤判、又需要語意
        embedding 這種目前系統沒有的能力），不如在寫入當下就提醒模型自己判斷，
        讓模型有機會用 relate() 把同一件事收斂成一個 id，而不是讓重複悄悄發生
        而沒有人注意到。

        只比對同一個 type 的節點：不同類型（例如一個 Function 跟一個 Fact）
        就算摘要文字剛好相似，也通常不是「同一件事被存成兩個 id」的情況。
        """
        best_match = None
        best_ratio = 0.0
        for node in self.memory_store.nodes.values():
            if node.id == new_id or node.type != new_type or not node.summary:
                continue
            ratio = difflib.SequenceMatcher(None, node.summary, new_summary).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = node
        if best_match is not None and best_ratio >= _DUPLICATE_SUMMARY_SIMILARITY_THRESHOLD:
            return best_match
        return None

    def recall(self, id: str) -> str:
        node = self.working_memory.activate(id)
        if not node:
            return f"沒有找到 {id} 這個記憶，可能還沒被 remember 過。"
        props = self.memory_store.get_effective_properties(id)
        rel_text = ", ".join(f"{r['rel']}->{r['target']}" for r in node.relations) or "(無)"
        return (
            f"[{node.type}] {id}\n"
            f"摘要: {node.summary or '(無)'}\n"
            f"屬性: {json.dumps(props, ensure_ascii=False)}\n"
            f"關聯: {rel_text}"
        )

    def relate(self, source_id: str, rel: str, target_id: str) -> str:
        self.memory_store.add_relation(source_id, rel, target_id)
        return f"已建立關聯: {source_id} -{rel}-> {target_id}"

    def record_observation(self, id: str, about_id: str, conclusion: str,
                           confidence: float = 0.8, runtime_action: str = "context") -> str:
        if not self.memory_store.get_node(about_id):
            return f"找不到 {about_id}，要先用 remember 記住它，才能對它記錄 Observation。"
        obs = self.memory_store.record_observation(
            id, about_id, conclusion, confidence, runtime_action
        )
        self.working_memory.activate(id)
        self.emit("log", f"🔎 記錄了一個結論 [{id}]（關於 {about_id}）: {conclusion}")
        return (
            f"已記錄結論 {id}（關於 {about_id}，信心值 {confidence:.2f}，"
            f"runtime_action={obs.properties.get('runtime_action', 'context')}）: {conclusion}"
        )

    def recall_observation(self, id: str) -> str:
        node = self.memory_store.get_node(id)
        if not node or node.type != "Observation":
            return f"沒有找到 {id} 這個 Observation，可能還沒被 record_observation 記錄過。"
        self.working_memory.activate(id)
        conclusion = node.summary
        if self.memory_store.is_observation_stale(id):
            return (
                f"⚠️ 結論 {id} 可能已經過期了（它分析的對象內容已經變過）："
                f"{conclusion}（信心值 {node.confidence:.2f}，建議重新分析後用 record_observation 更新）"
            )
        return f"{id}（信心值 {node.confidence:.2f}，仍然新鮮）: {conclusion}"

    def recall_with_event(self, id: str, event_id: str) -> str:
        if not self.memory_store.get_node(id):
            return f"沒有找到 {id}，可能還沒被 remember 過。"
        if not self.memory_store.get_node(event_id):
            return f"沒有找到事件 {event_id}，可能還沒被 remember 過。"
        self.working_memory.activate(id)
        self.working_memory.activate(event_id)
        props = self.memory_store.get_properties_with_event_override(id, event_id)
        return f"{id} 在 {event_id} 這個情境下的屬性: {json.dumps(props, ensure_ascii=False)}"

    def recall_related(self, id: str, rel: Optional[str] = None) -> str:
        outgoing = self.memory_store.get_outgoing(id, rel)
        incoming = self.memory_store.get_incoming(id, rel)
        related_ids = outgoing + incoming
        for nid in related_ids:
            self.working_memory.activate(nid)
        # 同時透過 Retriever 把相關節點的「關鍵字鄰居」也拉進 Working Memory，
        # 避免 recall_related 和 retrieve_for_task 的 activate 路徑不一致。
        if related_ids:
            self.retriever.retrieve_for_keywords(
                [nid.split(".")[-1] for nid in related_ids[:4]]
            )
        return (
            f"由 {id} 指出去: {outgoing if outgoing else '(無)'}\n"
            f"指向 {id} 的: {incoming if incoming else '(無)'}"
        )

    def search_memory(self, keyword: str) -> str:
        matches = self.memory_store.search(keyword)
        if not matches:
            return f"沒有找到跟「{keyword}」有關的記憶。"
        for node in matches:
            self.working_memory.activate(node.id)
        lines = [f"- [{n.type}] {n.id}: {n.summary}" for n in matches]
        return f"找到 {len(matches)} 筆跟「{keyword}」有關的記憶：\n" + "\n".join(lines)

    def build_code_graph(self, filepath: str, module_name: Optional[str] = None) -> str:
        try:
            func_ids = self.code_graph.build_from_file(filepath, module_name)
        except Exception as e:
            return f"建立程式碼關聯圖失敗: {e}"
        if not func_ids:
            return f"{filepath} 裡沒有解析到任何函式。"
        return f"已建立/更新 {len(func_ids)} 個函式節點: {', '.join(func_ids)}"

    def build_code_graph_for_project(self, root_dir: str) -> str:
        try:
            result = self.code_graph.build_project(root_dir)
        except Exception as e:
            return f"建立專案程式碼關聯圖失敗: {e}"
        total_files = len(result)
        total_funcs = sum(len(v) for v in result.values())
        if total_funcs == 0:
            return f"{root_dir} 底下掃了 {total_files} 個檔案，沒有解析到任何函式。"
        return f"掃了 {total_files} 個檔案，共建立/更新 {total_funcs} 個函式節點，跨檔案的呼叫關係也已經解析。"

    def find_callers(self, func_id: str) -> str:
        callers = self.code_graph.find_callers(func_id)
        if not callers:
            return f"沒有找到呼叫 {func_id} 的函式（可能它沒有被任何函式呼叫，或這個檔案還沒用 build_code_graph 建立過）。"
        return f"呼叫了 {func_id} 的函式: {', '.join(callers)}"

    def find_callees(self, func_id: str) -> str:
        callees = self.code_graph.find_callees(func_id)
        if not callees:
            return f"{func_id} 沒有呼叫任何已知函式（或這個檔案還沒用 build_code_graph 建立過）。"
        return f"{func_id} 呼叫了: {', '.join(callees)}"

    # 用來判斷一個任務 id 是不是「自動產生的影響檢查任務」——不能只看
    # TaskNode.is_auto_impact_check 這個 Python 屬性，因為 Reflect 每次都會把
    # 非 COMPLETED/DECOMPOSED 的任務整個用重新解析出來的新物件取代掉
    # （apply_reflected_dsl），而這個屬性根本不是 DSL 文字格式的一部分，
    # 换句話說：只要這個任務還沒執行完就先被 Reflect 摸過一次，屬性就會
    # 悄悄被重置回預設值 False，導致終點任務的保護形同虛設。id 本身的命名規則
    # （".impact數字" / ".rel_impact數字" 結尾）才是唯一保證會跨越這種
    # 物件替換存活下來的訊號，所以用 id pattern 當作判斷的真正依據。
    _AUTO_IMPACT_CHECK_ID_RE = re.compile(r'\.(?:impact|rel_impact)\d+$')

    def _is_auto_impact_check_task(self, task: TaskNode) -> bool:
        return bool(self._AUTO_IMPACT_CHECK_ID_RE.search(task.id)) or \
            getattr(task, "is_auto_impact_check", False)

    def _auto_queue_impact_checks(self, task: TaskNode):
        # 終點任務（本身就是自動產生的影響檢查任務）不再往下觸發新一輪掃描，
        # 否則它自己的描述文字必然會提到被改動的節點，導致無止盡地連鎖生成
        # 下一個、再下一個影響檢查任務（見上面 _is_auto_impact_check_task 的說明）。
        if self._is_auto_impact_check_task(task):
            return

        from tools.code_impact import queue_impact_check_tasks
        from tools.relation_impact import queue_relation_impact_tasks

        haystack = f"{task.title} {task.method}"
        for node_id, node in list(self.memory_store.nodes.items()):
            if node.type in self._IMPACT_CHECK_EXCLUDED_TYPES:
                continue
            short_name = node_id.split(".")[-1]
            if not short_name or not re.search(rf'\b{re.escape(short_name)}\b', haystack):
                continue

            if node.type == "Function":
                inserted = queue_impact_check_tasks(self.engine, self.memory_store, node_id, task.id)
                reason = "根據呼叫關係圖"
            else:
                inserted = queue_relation_impact_tasks(self.engine, self.memory_store, node_id, task.id)
                reason = "根據記憶裡的關聯"

            if inserted:
                self.emit(
                    "log",
                    f"[系統] [{task.id}] 提到了已知的 {node.type} {node_id}，"
                    f"{reason}自動插入 {inserted} 個影響檢查任務。"
                )