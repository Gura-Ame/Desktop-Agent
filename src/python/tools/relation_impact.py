"""
把「改了 X，誰可能受影響」這個原則從 code_impact.py 的「函式呼叫關係 (CALLS)」
泛化到記憶裡的任何物件、任何關聯類型。

code_impact.py 的 queue_impact_check_tasks 是這個原則在「程式碼函式」這個特定場景下
的具體實作，寫死用 CALLS 關聯、措辭也專門針對原始碼。這裡是不限定的通用版本：
不管是函式、定理、設定、還是任何用 remember() 記住過、用 relate() 建過關聯的東西，
只要任務完成後動到了它，就機械式地檢查誰跟它有關聯、插入對應的檢查任務——
一樣不需要模型自己想到要問「這個改了誰會受影響」。
"""

from memory.memory_store import MemoryStore
from agent.task_system import TaskEngine, TaskNode


def queue_relation_impact_tasks(engine: TaskEngine, store: MemoryStore,
                                 changed_id: str, after_task_id: str, rel: str = None) -> int:
    """在 after_task_id 這個任務後面，幫每個「指向 changed_id」的物件插入一個
    「檢查是否受影響」的子任務。rel 不填代表不限定關聯類型，任何關聯都算；
    要只看特定類型的關聯（例如只看 "USED_BY"）可以指定 rel。回傳插入了幾個。

    id 用 ".rel_impact" 當前綴（跟 code_impact.py 的 ".impact" 前綴不同），
    避免同一個任務如果同時觸發了函式關聯檢查跟這個通用版本，兩邊產生的子任務 id 撞在一起。
    """
    related_ids = store.get_incoming(changed_id, rel=rel)
    if not related_ids:
        return 0

    anchor_idx = next((i for i, t in enumerate(engine.tasks) if t.id == after_task_id), None)
    insert_at = anchor_idx + 1 if anchor_idx is not None else len(engine.tasks)

    new_tasks = []
    for i, related_id in enumerate(related_ids, start=1):
        related_node = store.get_node(related_id)
        related_summary = related_node.summary if related_node else ""
        related_type = related_node.type if related_node else "?"

        t = TaskNode(
            f"{after_task_id}.rel_impact{i}",
            f"檢查 {related_id} 是否受 {changed_id} 的變更影響"
        )
        t.method = f"檢視 {related_id}（{related_type}: {related_summary}）跟 {changed_id} 之間的關聯是否還成立"
        t.condition = f"確認 {related_id} 跟 {changed_id} 的關聯內容仍然正確，或已經同步修正"
        t.note = "這個任務是根據記憶裡的關聯自動產生的，不是模型猜的"
        t.need_confirm = True  # 保守起見預設要人確認
        new_tasks.append(t)

    engine.tasks[insert_at:insert_at] = new_tasks
    return len(new_tasks)
