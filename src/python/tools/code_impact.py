"""
把 Code Graph 接回 Task Tree 的整合範例。

重點：函式改完之後，「誰可能受影響」不需要模型自己猜、也不需要把所有呼叫者的
原始碼都塞進 Context —— 直接對 Disk 做關聯查詢，機械式地插入檢查任務。
這就是討論裡「不全部加入 Context，而是新增 Background Task，真正需要時才載入」
那條原則的具體落地，而且比讓 LLM 自己猜可靠。
"""

from memory.memory_store import MemoryStore
from agent.task_system import TaskEngine, TaskNode


def queue_impact_check_tasks(engine: TaskEngine, store: MemoryStore,
                              changed_func_id: str, after_task_id: str) -> int:
    """在 after_task_id 這個任務後面，幫每個呼叫了 changed_func_id 的函式
    插入一個「檢查是否受影響」的子任務。回傳插入了幾個。

    這些新任務會被正常的驗證/思考/確認機制接手（因為它們就是普通的 TaskNode），
    只是「要不要檢查、檢查誰」這一步是靠圖查出來的，不是靠模型猜的。
    """
    callers = store.get_incoming(changed_func_id, rel="CALLS")
    if not callers:
        return 0

    anchor_idx = next((i for i, t in enumerate(engine.tasks) if t.id == after_task_id), None)
    insert_at = anchor_idx + 1 if anchor_idx is not None else len(engine.tasks)

    # 同一個原因：_auto_queue_impact_checks 一個任務生命週期內會被呼叫兩次
    # （開始前、完成後），id 又是純機械式產生、確定性的，不擋會插入兩份一樣的任務。
    existing_ids = {t.id for t in engine.tasks}

    new_tasks = []
    for i, caller_id in enumerate(callers, start=1):
        candidate_id = f"{after_task_id}.impact{i}"
        if candidate_id in existing_ids:
            continue
        caller_node = store.get_node(caller_id)
        caller_file = caller_node.properties.get("file", "") if caller_node else ""

        t = TaskNode(
            candidate_id,
            f"檢查 {caller_id} 是否受 {changed_func_id} 的修改影響"
        )
        t.method = f"讀取 {caller_id}（{caller_file}）的原始碼，比對 {changed_func_id} 新的簽名/行為是否仍相容"
        t.condition = f"確認 {caller_id} 呼叫 {changed_func_id} 的地方仍然正確，或已經同步修正"
        t.note = "這個任務是根據 Code Graph 的 CALLS 關聯自動產生的，不是模型猜的"
        t.need_confirm = True  # 會改到別的檔案，保守起見預設要人確認
        t.is_auto_impact_check = True  # 終點任務：不再對它自己觸發下一輪影響掃描
        # 同 relation_impact.py：驗證「內容必然提到被改動的節點」這個假設真的成立，
        # 這正是需要 is_auto_impact_check 保護、避免無限連鎖生成的理由所在。
        assert changed_func_id.split(".")[-1] in t.title or changed_func_id in t.title, (
            "產生的任務標題沒有提到被改動的函式，_auto_queue_impact_checks 的"
            "連鎖生成風險假設可能已經不成立，需要重新檢視 is_auto_impact_check 保護是否還有必要"
        )
        new_tasks.append(t)

    engine.tasks[insert_at:insert_at] = new_tasks
    return len(new_tasks)