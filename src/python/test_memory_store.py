"""
memory_store.py 的單元測試。純 stdlib，不需要真的 LLM、不需要裝任何套件。

執行方式：
    cd 到這個檔案所在的上一層資料夾（跟 memory_store.py 同一層），然後：
    python tests/test_memory_store.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory_store import MemoryStore  # noqa: E402


def with_temp_store(fn):
    """每個測試都用一個全新的暫存 JSON 檔案，測試之間互不干擾。"""
    def wrapper():
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(path)  # MemoryStore 遇到檔案不存在會視為空圖，這樣才是乾淨的起點
        try:
            store = MemoryStore(path)
            fn(store)
        finally:
            if os.path.exists(path):
                os.remove(path)
    return wrapper


@with_temp_store
def test_upsert_and_get(store: MemoryStore):
    store.upsert_node("steak", "Food", properties={"protein": "high", "temperature": "hot"})
    node = store.get_node("steak")
    assert node is not None
    assert node.type == "Food"
    assert node.properties["protein"] == "high"
    print("[PASS] test_upsert_and_get")


@with_temp_store
def test_upsert_updates_version(store: MemoryStore):
    store.upsert_node("steak", "Food", properties={"protein": "high"})
    v1 = store.get_node("steak").version
    store.upsert_node("steak", "Food", properties={"protein": "very high"})
    v2 = store.get_node("steak").version
    assert v1 != v2, "屬性變了，version 應該要跟著變"
    print("[PASS] test_upsert_updates_version")


@with_temp_store
def test_relations_in_and_out(store: MemoryStore):
    store.upsert_node("a", "Function")
    store.upsert_node("b", "Function")
    store.upsert_node("c", "Function")
    store.add_relation("a", "CALLS", "b")
    store.add_relation("c", "CALLS", "b")

    assert store.get_outgoing("a", rel="CALLS") == ["b"]
    callers_of_b = set(store.get_incoming("b", rel="CALLS"))
    assert callers_of_b == {"a", "c"}, f"預期 a 和 c 都呼叫了 b，實際: {callers_of_b}"
    print("[PASS] test_relations_in_and_out")


@with_temp_store
def test_relation_requires_existing_nodes(store: MemoryStore):
    store.upsert_node("a", "Function")
    try:
        store.add_relation("a", "CALLS", "not_exist")
        assert False, "目標節點不存在應該要丟例外"
    except KeyError:
        pass
    print("[PASS] test_relation_requires_existing_nodes")


@with_temp_store
def test_effective_properties_inheritance(store: MemoryStore):
    # 對應討論裡的牛排例子：Food 是抽象層，Steak 是實例，繼承 Food 的屬性
    store.upsert_node("Food", "Type", properties={"category": "食物"})
    store.upsert_node("ProteinHigh", "Type", properties={"protein": "high"})
    store.upsert_node("steak", "Food", properties={"temperature": "hot"})
    store.add_relation("steak", "INSTANCE_OF", "Food")

    # 讓 Food 本身也繼承自 ProteinHigh，測試多層繼承會不會疊起來
    store.add_relation("Food", "INSTANCE_OF", "ProteinHigh")

    effective = store.get_effective_properties("steak")
    assert effective["category"] == "食物", "應該繼承到 Food 的屬性"
    assert effective["protein"] == "high", "應該沿鏈繼承到 ProteinHigh 的屬性"
    assert effective["temperature"] == "hot", "自己的屬性要保留"
    print("[PASS] test_effective_properties_inheritance")


@with_temp_store
def test_event_override(store: MemoryStore):
    store.upsert_node("steak", "Food", properties={"temperature": "hot", "protein": "high"})
    store.upsert_node("event_001", "Event", properties={
        "type": "Eat", "time": "2026-07-30",
        "override": {"temperature": "cold"}
    })

    result = store.get_properties_with_event_override("steak", "event_001")
    assert result["temperature"] == "cold", "Event 的 override 應該要蓋掉原本的值"
    assert result["protein"] == "high", "沒被 override 的屬性應該維持原樣"
    print("[PASS] test_event_override")


@with_temp_store
def test_observation_staleness(store: MemoryStore):
    store.upsert_node("parser.parse", "Function", properties={"signature": "parse(tokens)"})
    store.record_observation("obs_001", "parser.parse", "可能造成 NullPointer", confidence=0.91)

    assert store.is_observation_stale("obs_001") is False, "剛記錄完，不應該被視為過期"

    # 目標物件的內容變了（例如程式碼被改過），version 會跟著變
    store.upsert_node("parser.parse", "Function", properties={"signature": "parse(tokens, strict=False)"})
    assert store.is_observation_stale("obs_001") is True, "目標已經變了，舊的 Observation 應該視為過期"
    print("[PASS] test_observation_staleness")


@with_temp_store
def test_delete_node_cleans_relations(store: MemoryStore):
    store.upsert_node("a", "Function")
    store.upsert_node("b", "Function")
    store.add_relation("a", "CALLS", "b")
    store.delete_node("b")

    assert store.get_node("b") is None
    assert store.get_outgoing("a", rel="CALLS") == [], "指向已刪除節點的關聯應該一併清掉"
    print("[PASS] test_delete_node_cleans_relations")


@with_temp_store
def test_persistence_across_reload(store: MemoryStore):
    store.upsert_node("steak", "Food", properties={"protein": "high"})
    path = store.path
    reloaded = MemoryStore(path)
    node = reloaded.get_node("steak")
    assert node is not None and node.properties["protein"] == "high"
    print("[PASS] test_persistence_across_reload")


if __name__ == "__main__":
    tests = [
        test_upsert_and_get,
        test_upsert_updates_version,
        test_relations_in_and_out,
        test_relation_requires_existing_nodes,
        test_effective_properties_inheritance,
        test_event_override,
        test_observation_staleness,
        test_delete_node_cleans_relations,
        test_persistence_across_reload,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
