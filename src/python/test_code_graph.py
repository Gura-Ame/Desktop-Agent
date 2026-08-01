"""
code_graph.py 與 code_impact.py 的測試。純 stdlib，不需要任何額外套件。

執行方式：
    python tests/test_code_graph.py
"""

import os
import sys
import tempfile
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory_store import MemoryStore  # noqa: E402
from code_graph import CodeGraphBuilder  # noqa: E402
from task_system import TaskEngine, TaskNode, TaskStatus  # noqa: E402
from code_impact import queue_impact_check_tasks  # noqa: E402


SAMPLE_SOURCE = textwrap.dedent("""
    def helper(x):
        return x + 1

    def a():
        return helper(1) + b()

    def b():
        return 42

    def unrelated():
        return "no calls here"
""")


def build_temp_module():
    fd, path = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(SAMPLE_SOURCE)
    return path


def with_temp_env(fn):
    def wrapper():
        store_fd, store_path = tempfile.mkstemp(suffix=".json")
        os.close(store_fd)
        os.remove(store_path)
        module_path = build_temp_module()
        try:
            store = MemoryStore(store_path)
            fn(store, module_path)
        finally:
            if os.path.exists(store_path):
                os.remove(store_path)
            if os.path.exists(module_path):
                os.remove(module_path)
    return wrapper


@with_temp_env
def test_build_from_file_creates_function_nodes(store: MemoryStore, module_path: str):
    builder = CodeGraphBuilder(store)
    func_ids = builder.build_from_file(module_path, module_name="sample")

    assert "sample.a" in func_ids
    assert "sample.b" in func_ids
    assert "sample.helper" in func_ids
    assert "sample.unrelated" in func_ids

    node = store.get_node("sample.a")
    assert node is not None
    assert "signature" in node.properties
    print("[PASS] test_build_from_file_creates_function_nodes")


@with_temp_env
def test_calls_relation_and_find_callers(store: MemoryStore, module_path: str):
    builder = CodeGraphBuilder(store)
    builder.build_from_file(module_path, module_name="sample")

    # a() 呼叫了 helper() 跟 b()
    callees_of_a = set(builder.find_callees("sample.a"))
    assert callees_of_a == {"sample.helper", "sample.b"}, f"實際: {callees_of_a}"

    # 反過來查：誰呼叫了 b()？—— 就是你原本說的「改 b() 要通知誰」
    callers_of_b = builder.find_callers("sample.b")
    assert callers_of_b == ["sample.a"], f"實際: {callers_of_b}"

    # unrelated() 沒有呼叫任何東西
    assert builder.find_callees("sample.unrelated") == []
    print("[PASS] test_calls_relation_and_find_callers")


@with_temp_env
def test_queue_impact_check_tasks_inserts_after_anchor(store: MemoryStore, module_path: str):
    builder = CodeGraphBuilder(store)
    builder.build_from_file(module_path, module_name="sample")

    engine = TaskEngine()
    t1 = TaskNode("TASK-1", "修改 b() 的行為")
    t1.status = TaskStatus.COMPLETED
    t2 = TaskNode("TASK-2", "跟改 b() 無關的任務")
    engine.tasks = [t1, t2]

    inserted = queue_impact_check_tasks(engine, store, changed_func_id="sample.b", after_task_id="TASK-1")

    assert inserted == 1, "只有 sample.a 呼叫了 sample.b，應該只插入 1 個"
    ids_in_order = [t.id for t in engine.tasks]
    assert ids_in_order == ["TASK-1", "TASK-1.impact1", "TASK-2"], f"實際順序: {ids_in_order}"

    impact_task = engine.tasks[1]
    assert "sample.a" in impact_task.title
    assert impact_task.need_confirm is True, "會動到別的檔案，預設要保守地要求確認"
    print("[PASS] test_queue_impact_check_tasks_inserts_after_anchor")


@with_temp_env
def test_queue_impact_check_tasks_noop_when_no_callers(store: MemoryStore, module_path: str):
    builder = CodeGraphBuilder(store)
    builder.build_from_file(module_path, module_name="sample")

    engine = TaskEngine()
    t1 = TaskNode("TASK-1", "修改 unrelated()")
    t1.status = TaskStatus.COMPLETED
    engine.tasks = [t1]

    inserted = queue_impact_check_tasks(engine, store, changed_func_id="sample.unrelated", after_task_id="TASK-1")
    assert inserted == 0
    assert len(engine.tasks) == 1, "沒有呼叫者就不應該插入任何任務"
    print("[PASS] test_queue_impact_check_tasks_noop_when_no_callers")


if __name__ == "__main__":
    tests = [
        test_build_from_file_creates_function_nodes,
        test_calls_relation_and_find_callers,
        test_queue_impact_check_tasks_inserts_after_anchor,
        test_queue_impact_check_tasks_noop_when_no_callers,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
