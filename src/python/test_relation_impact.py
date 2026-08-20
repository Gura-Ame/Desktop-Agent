"""
測試「改了 X，誰可能受影響」這個原則泛化到任何物件、任何關聯類型
（不再侷限於程式碼函式的 CALLS 關聯）。

執行方式：
    python test_relation_impact.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory_store import MemoryStore  # noqa: E402
from task_system import TaskEngine, TaskNode, TaskStatus  # noqa: E402
from relation_impact import queue_relation_impact_tasks  # noqa: E402
from agent_core import AgentWorker  # noqa: E402
from task_system import ExecutionMode  # noqa: E402


def with_temp_store(fn):
    def wrapper():
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(path)
        try:
            store = MemoryStore(path)
            fn(store)
        finally:
            if os.path.exists(path):
                os.remove(path)
    return wrapper


@with_temp_store
def test_queue_relation_impact_tasks_any_relation_type(store: MemoryStore):
    store.upsert_node("lemma_a", "Lemma", summary="核心引理")
    store.upsert_node("proof_final", "Proof", summary="最終證明")
    store.add_relation("proof_final", "USED_BY", "lemma_a")  # 不是 CALLS，是別種關聯

    engine = TaskEngine()
    t1 = TaskNode("TASK-1", "修改 lemma_a 的敘述")
    t1.status = TaskStatus.COMPLETED
    engine.tasks = [t1]

    inserted = queue_relation_impact_tasks(engine, store, "lemma_a", "TASK-1")
    assert inserted == 1
    ids = [t.id for t in engine.tasks]
    assert "TASK-1.rel_impact1" in ids
    impact_task = next(t for t in engine.tasks if t.id == "TASK-1.rel_impact1")
    assert "proof_final" in impact_task.title
    print("[PASS] test_queue_relation_impact_tasks_any_relation_type")


@with_temp_store
def test_queue_relation_impact_tasks_no_incoming_relation_is_noop(store: MemoryStore):
    store.upsert_node("isolated_fact", "Fact", summary="沒有跟任何東西關聯")
    engine = TaskEngine()
    t1 = TaskNode("TASK-1", "修改 isolated_fact")
    t1.status = TaskStatus.COMPLETED
    engine.tasks = [t1]

    inserted = queue_relation_impact_tasks(engine, store, "isolated_fact", "TASK-1")
    assert inserted == 0
    assert len(engine.tasks) == 1
    print("[PASS] test_queue_relation_impact_tasks_no_incoming_relation_is_noop")


@with_temp_store
def test_rel_impact_id_does_not_collide_with_code_impact_id(store: MemoryStore):
    """同一個任務如果同時提到函式跟一般物件，兩種影響檢查任務的 id 不該撞在一起。"""
    from code_impact import queue_impact_check_tasks

    store.upsert_node("mod.func_a", "Function", summary="函式")
    store.upsert_node("mod.func_b", "Function", summary="呼叫 func_a 的函式")
    store.add_relation("mod.func_b", "CALLS", "mod.func_a")

    store.upsert_node("some_fact", "Fact", summary="一般事實")
    store.upsert_node("related_fact", "Fact", summary="跟 some_fact 有關的事實")
    store.add_relation("related_fact", "ABOUT", "some_fact")

    engine = TaskEngine()
    t1 = TaskNode("TASK-1", "同時動到 func_a 跟 some_fact")
    t1.status = TaskStatus.COMPLETED
    engine.tasks = [t1]

    n1 = queue_impact_check_tasks(engine, store, "mod.func_a", "TASK-1")
    n2 = queue_relation_impact_tasks(engine, store, "some_fact", "TASK-1")

    assert n1 == 1 and n2 == 1
    ids = [t.id for t in engine.tasks]
    assert "TASK-1.impact1" in ids
    assert "TASK-1.rel_impact1" in ids
    assert len(ids) == len(set(ids)), f"id 不該有重複: {ids}"
    print("[PASS] test_rel_impact_id_does_not_collide_with_code_impact_id")


def _make_agent(memory_path):
    return AgentWorker({}, event_callback=lambda t, d: None,
                        default_mode=ExecutionMode.AUTO, memory_path=memory_path)


def test_auto_queue_impact_checks_works_for_non_function_objects():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(path)
    try:
        agent = _make_agent(path)
        agent.remember("api_rate_limit", "Constraint", "這個 API 每分鐘最多 60 次")
        agent.remember("retry_logic", "Decision", "遇到限流就重試 3 次")
        agent.relate("retry_logic", "DEPENDS_ON", "api_rate_limit")

        task = TaskNode("TASK-1", "調整 api_rate_limit 的限制")
        task.method = "把限制從 60 次改成 30 次"
        agent.engine.tasks = [task]

        agent._auto_queue_impact_checks(task)

        ids = [t.id for t in agent.engine.tasks]
        assert "TASK-1.rel_impact1" in ids, f"實際: {ids}"
        impact_task = next(t for t in agent.engine.tasks if t.id == "TASK-1.rel_impact1")
        assert "retry_logic" in impact_task.title
        print("[PASS] test_auto_queue_impact_checks_works_for_non_function_objects")
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_history_and_observation_types_excluded_from_impact_checks():
    """History（對話存檔）、Observation（有自己的過期機制）不該觸發影響檢查連鎖反應。"""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(path)
    try:
        agent = _make_agent(path)
        agent.memory_store.upsert_node("_conversation_history", "History", summary="conversation")
        agent.remember("target_fn", "Function", "一個函式")
        agent.record_observation("obs_target_fn", "target_fn", "有個問題", 0.8)
        agent.remember("watcher", "Fact", "跟 obs_target_fn 有關")
        agent.relate("watcher", "ABOUT", "obs_target_fn")

        task = TaskNode("TASK-1", "動到 obs_target_fn 這個 Observation")
        task.method = "修改分析結論"
        agent.engine.tasks = [task]

        agent._auto_queue_impact_checks(task)

        ids = [t.id for t in agent.engine.tasks]
        assert ids == ["TASK-1"], (
            f"Observation 類型不該觸發影響檢查（有自己的過期機制），實際: {ids}"
        )
        print("[PASS] test_history_and_observation_types_excluded_from_impact_checks")
    finally:
        if os.path.exists(path):
            os.remove(path)


if __name__ == "__main__":
    tests = [
        test_queue_relation_impact_tasks_any_relation_type,
        test_queue_relation_impact_tasks_no_incoming_relation_is_noop,
        test_rel_impact_id_does_not_collide_with_code_impact_id,
        test_auto_queue_impact_checks_works_for_non_function_objects,
        test_history_and_observation_types_excluded_from_impact_checks,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
