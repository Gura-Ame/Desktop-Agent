"""
working_memory.py 的單元測試。純 stdlib。

執行方式：
    python tests/test_working_memory.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory_store import MemoryStore  # noqa: E402
from working_memory import WorkingMemory  # noqa: E402


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
def test_activate_and_render(store: MemoryStore):
    store.upsert_node("steak", "Food", properties={"protein": "high"}, summary="高蛋白食物")
    wm = WorkingMemory(store, max_nodes=5)
    wm.activate("steak")

    text = wm.render_context()
    assert "steak" in text
    assert "高蛋白食物" in text
    assert "protein" not in text, "預設不展開 properties，只給 summary（Lazy Expansion）"
    print("[PASS] test_activate_and_render")


@with_temp_store
def test_expand_shows_full_properties(store: MemoryStore):
    store.upsert_node("steak", "Food", properties={"protein": "high"}, summary="高蛋白食物")
    wm = WorkingMemory(store, max_nodes=5)
    wm.activate("steak")

    text = wm.render_context(expand_ids=["steak"])
    assert "protein" in text, "明確要求展開的節點應該要看得到完整屬性"
    print("[PASS] test_expand_shows_full_properties")


@with_temp_store
def test_lru_eviction(store: MemoryStore):
    for i in range(5):
        store.upsert_node(f"n{i}", "Thing")

    wm = WorkingMemory(store, max_nodes=3)
    for i in range(5):
        wm.activate(f"n{i}")

    active = wm.active_ids()
    assert len(active) == 3, f"超過上限應該被淘汰，實際還有 {len(active)} 個"
    assert active == ["n2", "n3", "n4"], f"應該留下最近使用的 3 個，實際: {active}"
    print("[PASS] test_lru_eviction")


@with_temp_store
def test_reactivate_refreshes_lru_order(store: MemoryStore):
    for i in range(3):
        store.upsert_node(f"n{i}", "Thing")

    wm = WorkingMemory(store, max_nodes=2)
    wm.activate("n0")
    wm.activate("n1")
    wm.activate("n0")  # 重新啟用 n0，應該讓它變成「最近使用」
    wm.activate("n2")  # 這時應該淘汰 n1，而不是 n0

    active = wm.active_ids()
    assert "n1" not in active, "n1 最久沒被用到，應該被淘汰"
    assert "n0" in active, "n0 剛剛被重新啟用過，不應該被淘汰"
    print("[PASS] test_reactivate_refreshes_lru_order")


@with_temp_store
def test_activate_missing_node_returns_none(store: MemoryStore):
    wm = WorkingMemory(store, max_nodes=5)
    result = wm.activate("does_not_exist")
    assert result is None
    assert "does_not_exist" not in wm.active_ids()
    print("[PASS] test_activate_missing_node_returns_none")


if __name__ == "__main__":
    tests = [
        test_activate_and_render,
        test_expand_shows_full_properties,
        test_lru_eviction,
        test_reactivate_refreshes_lru_order,
        test_activate_missing_node_returns_none,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
