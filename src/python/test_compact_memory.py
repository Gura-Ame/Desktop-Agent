"""
測試「強迫精簡」：不管哪個路徑寫進 MemoryStore 的 summary，都要在儲存層被截斷，
不能只靠拜託模型自律——這是 memory_store.py 的 upsert_node（唯一寫入入口）強制做的。

執行方式：
    python test_compact_memory.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory_store import MemoryStore, MAX_SUMMARY_LENGTH  # noqa: E402


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
def test_long_summary_truncated_on_new_node(store: MemoryStore):
    long_text = "這是一段非常長的摘要文字，" * 20  # 遠遠超過上限
    node = store.upsert_node("x", "Fact", summary=long_text)
    assert len(node.summary) <= MAX_SUMMARY_LENGTH
    assert node.summary.endswith("…")
    print("[PASS] test_long_summary_truncated_on_new_node")


@with_temp_store
def test_long_summary_truncated_on_update(store: MemoryStore):
    store.upsert_node("x", "Fact", summary="短摘要")
    long_text = "更新後的一段非常長的摘要文字，" * 20
    node = store.upsert_node("x", "Fact", summary=long_text)
    assert len(node.summary) <= MAX_SUMMARY_LENGTH
    assert node.summary.endswith("…")
    print("[PASS] test_long_summary_truncated_on_update")


@with_temp_store
def test_short_summary_not_altered(store: MemoryStore):
    node = store.upsert_node("x", "Fact", summary="很短的摘要")
    assert node.summary == "很短的摘要", "沒超過上限的摘要不該被動過"
    print("[PASS] test_short_summary_not_altered")


@with_temp_store
def test_record_observation_conclusion_is_compacted(store: MemoryStore):
    store.upsert_node("target", "Function")
    long_conclusion = "這個函式在處理邊界條件的時候會出現非預期的行為，" * 10
    store.record_observation("obs1", "target", long_conclusion, 0.8)

    node = store.get_node("obs1")
    assert len(node.summary) <= MAX_SUMMARY_LENGTH
    # properties 裡不該再偷偷存一份沒被精簡過的完整版本，不然等於繞過了強制精簡
    assert "conclusion" not in node.properties, (
        "record_observation 不該在 properties 裡另外存一份未精簡的結論，"
        "summary 才是唯一真實來源"
    )
    print("[PASS] test_record_observation_conclusion_is_compacted")


@with_temp_store
def test_properties_are_not_truncated(store: MemoryStore):
    """精簡只針對 summary（給人看的一句話），properties 是放結構化細節的地方，不該被砍。"""
    long_detail = "詳細的內部資訊，" * 30
    node = store.upsert_node("x", "Fact", summary="短摘要", properties={"detail": long_detail})
    assert node.properties["detail"] == long_detail, "properties 是放細節用的，不該被精簡邏輯動到"
    print("[PASS] test_properties_are_not_truncated")


@with_temp_store
def test_reload_from_disk_keeps_compacted_summary(store: MemoryStore):
    long_text = "一段很長的文字內容，" * 20
    store.upsert_node("x", "Fact", summary=long_text)
    path = store.path

    reloaded = MemoryStore(path)
    node = reloaded.get_node("x")
    assert len(node.summary) <= MAX_SUMMARY_LENGTH
    print("[PASS] test_reload_from_disk_keeps_compacted_summary")


if __name__ == "__main__":
    tests = [
        test_long_summary_truncated_on_new_node,
        test_long_summary_truncated_on_update,
        test_short_summary_not_altered,
        test_record_observation_conclusion_is_compacted,
        test_properties_are_not_truncated,
        test_reload_from_disk_keeps_compacted_summary,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
