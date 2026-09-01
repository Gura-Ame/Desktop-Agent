"""
把「改了 X，誰可能受影響」這個原則從 code_impact.py 的「函式呼叫關係 (CALLS)」
泛化到記憶裡的任何物件、任何關聯類型。

code_impact.py 的 queue_impact_check_tasks 是這個原則在「程式碼函式」這個特定場景下
的具體實作，寫死用 CALLS 關聯、措辭也專門針對原始碼。這裡是不限定的通用版本：
不管是函式、定理、設定、還是任何用 remember() 記住過、用 relate() 建過關聯的東西，
只要任務完成後動到了它，就機械式地檢查誰跟它有關聯、插入對應的檢查任務——
一樣不需要模型自己想到要問「這個改了誰會受影響」。
"""

from typing import Optional
from memory.memory_store import MemoryStore
from agent.task_system import TaskEngine, TaskNode


def queue_relation_impact_tasks(engine: TaskEngine, store: MemoryStore,
                                 changed_id: str, after_task_id: str, rel: Optional[str] = None) -> int:
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

    # _auto_queue_impact_checks 在同一個任務生命週期裡會被呼叫兩次（開始前預掃一次、
    # 完成後再掃一次），兩次掃到的是同一份 related_ids，id 又是純機械式產生
    # （f"{after_task_id}.rel_impact{i}"）、完全確定性、不含亂數或時間戳，
    # 如果不檢查就會插入兩份 id 一模一樣的重複任務。這裡用「id 是否已存在」擋掉，
    # 而不是用某種「這個任務有沒有被掃過」的旗標，這樣不管未來還有沒有其他呼叫點
    # 會重複觸發，只要 id 相同就一律視為已經插過，天然去重。
    existing_ids = {t.id for t in engine.tasks}

    new_tasks = []
    for i, related_id in enumerate(related_ids, start=1):
        candidate_id = f"{after_task_id}.rel_impact{i}"
        if candidate_id in existing_ids:
            continue
        related_node = store.get_node(related_id)
        related_summary = related_node.summary if related_node else ""
        related_type = related_node.type if related_node else "?"

        t = TaskNode(
            candidate_id,
            f"檢查 {related_id} 是否受 {changed_id} 的變更影響"
        )
        t.method = f"檢視 {related_id}（{related_type}: {related_summary}）跟 {changed_id} 之間的關聯是否還成立"
        t.condition = f"確認 {related_id} 跟 {changed_id} 的關聯內容仍然正確，或已經同步修正"
        t.note = "這個任務是根據記憶裡的關聯自動產生的，不是模型猜的"
        t.need_confirm = True  # 保守起見預設要人確認
        t.is_auto_impact_check = True  # 終點任務：不再對它自己觸發下一輪影響掃描
        # 驗證「這種任務的內容必然會提到被改動的節點」這個假設真的成立——這正是
        # is_auto_impact_check / id 命名規則需要存在的理由：如果 title/method 沒提到
        # changed_id 的短名稱，_auto_queue_impact_checks 的關鍵字掃描本來就不會命中它，
        # 也就不會有連鎖生成的風險，那麼 is_auto_impact_check 的保護就無關緊要；
        # 但只要這裡的字串範本被改動，這個假設就可能悄悄不成立，用 assert 攔住，
        # 而不是等到真的發生無限連鎖生成才發現。
        assert changed_id.split(".")[-1] in t.title or changed_id in t.title, (
            "產生的任務標題沒有提到被改動的節點，_auto_queue_impact_checks 的"
            "連鎖生成風險假設可能已經不成立，需要重新檢視 is_auto_impact_check 保護是否還有必要"
        )
        new_tasks.append(t)

    engine.tasks[insert_at:insert_at] = new_tasks
    return len(new_tasks)