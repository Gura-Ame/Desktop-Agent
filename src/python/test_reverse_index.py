"""
測試 get_incoming 的反向索引：正確性（結果要跟原本全表掃描一樣）、
索引在 add_relation / delete_node / 重新載入時有沒有正確維護、以及效能有沒有真的變好。

執行方式：
    python test_reverse_index.py
"""

import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory_store import MemoryStore  # noqa: E402


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


def _full_scan_incoming(store: MemoryStore, id: str, rel: str = None):
    """照抄舊版全表掃描的邏輯，當作正確性的 ground truth 拿來對照。"""
    result = []
    for nid, n in store.nodes.items():
        for r in n.relations:
            if r["target"] == id and (rel is None or r["rel"] == rel):
                result.append(nid)
    return result


@with_temp_store
def test_get_incoming_matches_full_scan_basic(store: MemoryStore):
    store.upsert_node("a", "Function")
    store.upsert_node("b", "Function")
    store.upsert_node("c", "Function")
    store.add_relation("a", "CALLS", "b")
    store.add_relation("c", "CALLS", "b")

    assert set(store.get_incoming("b", rel="CALLS")) == set(_full_scan_incoming(store, "b", "CALLS"))
    assert set(store.get_incoming("b", rel="CALLS")) == {"a", "c"}
    print("[PASS] test_get_incoming_matches_full_scan_basic")


@with_temp_store
def test_get_incoming_filters_by_rel_type(store: MemoryStore):
    store.upsert_node("a", "Fact")
    store.upsert_node("b", "Fact")
    store.add_relation("a", "USED_BY", "b")
    store.add_relation("a", "ABOUT", "b")  # 同一對節點，兩種不同關聯類型

    assert store.get_incoming("b", rel="USED_BY") == ["a"]
    assert store.get_incoming("b", rel="ABOUT") == ["a"]
    assert store.get_incoming("b", rel="NOT_EXIST") == []
    assert set(store.get_incoming("b")) == {"a"}  # 不指定 rel 就是不限定類型都算
    print("[PASS] test_get_incoming_filters_by_rel_type")


@with_temp_store
def test_index_updated_after_add_relation(store: MemoryStore):
    store.upsert_node("a", "Fact")
    store.upsert_node("b", "Fact")
    assert store.get_incoming("b") == []
    store.add_relation("a", "REL", "b")
    assert store.get_incoming("b") == ["a"]
    print("[PASS] test_index_updated_after_add_relation")


@with_temp_store
def test_index_updated_after_delete_node_as_target(store: MemoryStore):
    """刪掉被指向的節點（target），指向它的關聯要消失，反向索引項目也要一起清掉。"""
    store.upsert_node("a", "Fact")
    store.upsert_node("b", "Fact")
    store.add_relation("a", "REL", "b")
    assert store.get_incoming("b") == ["a"]

    store.delete_node("b")
    assert store.get_outgoing("a") == [], "指向已刪除節點的關聯應該一併清掉"
    # b 已經不存在了，查它的反向索引應該是空的（不是報錯）
    assert store.get_incoming("b") == []
    print("[PASS] test_index_updated_after_delete_node_as_target")


@with_temp_store
def test_index_updated_after_delete_node_as_source(store: MemoryStore):
    """刪掉發出關聯的節點（source），它指向別人的那些反向索引項目也要跟著消失。"""
    store.upsert_node("a", "Fact")
    store.upsert_node("b", "Fact")
    store.upsert_node("c", "Fact")
    store.add_relation("a", "REL", "b")
    store.add_relation("c", "REL", "b")
    assert set(store.get_incoming("b")) == {"a", "c"}

    store.delete_node("a")
    assert store.get_incoming("b") == ["c"], "a 被刪除了，b 的反向索引不該再看到 a"
    print("[PASS] test_index_updated_after_delete_node_as_source")


@with_temp_store
def test_index_rebuilt_correctly_after_reload(store: MemoryStore):
    """索引本身不落地存進 JSON，重新載入要能從 relations 正確重建。"""
    store.upsert_node("a", "Fact")
    store.upsert_node("b", "Fact")
    store.upsert_node("c", "Fact")
    store.add_relation("a", "REL", "b")
    store.add_relation("c", "REL", "b")
    path = store.path

    reloaded = MemoryStore(path)
    assert set(reloaded.get_incoming("b")) == {"a", "c"}
    print("[PASS] test_index_rebuilt_correctly_after_reload")


@with_temp_store
def test_get_incoming_on_node_with_no_incoming_relations(store: MemoryStore):
    store.upsert_node("isolated", "Fact")
    assert store.get_incoming("isolated") == []
    print("[PASS] test_get_incoming_on_node_with_no_incoming_relations")


@with_temp_store
def test_get_incoming_on_nonexistent_id_returns_empty(store: MemoryStore):
    assert store.get_incoming("does_not_exist") == []
    print("[PASS] test_get_incoming_on_nonexistent_id_returns_empty")


@with_temp_store
def test_reverse_index_avoids_full_scan_at_scale(store: MemoryStore):
    """效能檢查：建一個有一定規模的圖，確認 get_incoming 的查詢時間不會隨節點數線性增長
    到「掃過所有東西」的程度——用查詢時間遠小於一輪全表掃描來間接驗證有在用索引，
    而不是斷言絕對秒數（環境效能不一，抓比例比較穩）。
    """
    n = 3000
    for i in range(n):
        store.upsert_node(f"n{i}", "Fact")
    # 讓 n0 被大量節點指向，模擬一個熱門節點
    for i in range(1, n):
        store.add_relation(f"n{i}", "REL", "n0")

    start = time.perf_counter()
    for _ in range(200):
        store.get_incoming("n0")
    indexed_time = time.perf_counter() - start

    start = time.perf_counter()
    for _ in range(200):
        _full_scan_incoming(store, "n0")
    scan_time = time.perf_counter() - start

    assert indexed_time < scan_time / 3, (
        f"查詢應該要明顯比全表掃描快，實際 indexed={indexed_time:.4f}s scan={scan_time:.4f}s"
    )
    print(f"[PASS] test_reverse_index_avoids_full_scan_at_scale "
          f"(indexed={indexed_time:.4f}s, full_scan={scan_time:.4f}s)")


if __name__ == "__main__":
    tests = [
        test_get_incoming_matches_full_scan_basic,
        test_get_incoming_filters_by_rel_type,
        test_index_updated_after_add_relation,
        test_index_updated_after_delete_node_as_target,
        test_index_updated_after_delete_node_as_source,
        test_index_rebuilt_correctly_after_reload,
        test_get_incoming_on_node_with_no_incoming_relations,
        test_get_incoming_on_nonexistent_id_returns_empty,
        test_reverse_index_avoids_full_scan_at_scale,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
