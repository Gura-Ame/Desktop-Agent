import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
"""
Activation（跨 session 的「常被想起」分數）測試。

執行方式：
    cd 到這個檔案所在的上一層資料夾，然後：
    python tests/test_activation.py
"""

import tempfile
import time

from memory.memory_store import MemoryStore, MemoryNode, ACTIVATION_HALF_LIFE_SECONDS
from agent.attention_manager import AttentionManager
from agent.working_memory import WorkingMemory


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


# ----------------------------------------------------------------------
# 開關本身：預設關閉、要能被使用者打開/關閉，關閉時完全不累積分數
# ----------------------------------------------------------------------

@with_temp_store
def test_disabled_by_default(store):
    assert store.activation_enabled is False, "應該預設關閉，讓使用者自己決定要不要打開"


@with_temp_store
def test_toggle_on_off(store):
    store.set_activation_enabled(True)
    assert store.activation_enabled is True
    store.set_activation_enabled(False)
    assert store.activation_enabled is False


@with_temp_store
def test_reads_do_not_boost_activation_when_disabled(store):
    store.upsert_node("rust", "Concept", summary="Rust 語言")
    for _ in range(5):
        store.get_node("rust")
        store.search("rust")

    node = store.nodes["rust"]
    assert node.activation == 0.0, "功能關閉時，不管讀取幾次都不該累積 activation"
    assert node.get_effective_activation() == 0.0


# ----------------------------------------------------------------------
# 開啟後：讀取會疊加分數，且會封頂在 1.0
# ----------------------------------------------------------------------

@with_temp_store
def test_get_node_boosts_activation_when_enabled(store):
    store.set_activation_enabled(True)
    store.upsert_node("rust", "Concept", summary="Rust 語言")

    assert store.nodes["rust"].activation == 0.0, "剛建立、還沒被讀取過，不該有分數"

    store.get_node("rust")
    first = store.nodes["rust"].activation
    assert first > 0.0, "讀取一次之後應該有分數"

    store.get_node("rust")
    second = store.nodes["rust"].activation
    assert second > first, "短時間內重複讀取應該持續疊加，而不是停在原地"


@with_temp_store
def test_search_hits_also_boost_activation(store):
    store.set_activation_enabled(True)
    store.upsert_node("rust_ownership", "Concept", summary="Rust 所有權機制")

    store.search("rust")
    assert store.nodes["rust_ownership"].activation > 0.0, "search 命中也該算一次被想起"


@with_temp_store
def test_activation_boost_caps_at_one(store):
    store.set_activation_enabled(True)
    store.upsert_node("rust", "Concept", summary="Rust 語言")

    for _ in range(50):
        store.get_node("rust")

    assert store.nodes["rust"].activation <= 1.0, "分數應該封頂在 1.0，不能無限疊加"


# ----------------------------------------------------------------------
# 衰減：套用時間衰減後才是「有效」分數，不是原始累積值
# ----------------------------------------------------------------------

def test_effective_activation_decays_over_time():
    node = MemoryNode("rust", "Concept", summary="Rust 語言")
    node.bump_activation(boost=0.8, now=1000.0)

    immediate = node.get_effective_activation(now=1000.0)
    one_half_life_later = node.get_effective_activation(now=1000.0 + ACTIVATION_HALF_LIFE_SECONDS)
    two_half_lives_later = node.get_effective_activation(now=1000.0 + 2 * ACTIVATION_HALF_LIFE_SECONDS)

    assert abs(immediate - 0.8) < 1e-9
    assert abs(one_half_life_later - 0.4) < 1e-9, "經過一個半衰期，分數應該剛好剩一半"
    assert abs(two_half_lives_later - 0.2) < 1e-9, "經過兩個半衰期，應該剩四分之一"


def test_effective_activation_never_negative_or_nan_far_in_future():
    node = MemoryNode("rust", "Concept", summary="Rust 語言")
    node.bump_activation(boost=0.5, now=1000.0)
    far_future = node.get_effective_activation(now=1000.0 + 1000 * ACTIVATION_HALF_LIFE_SECONDS)
    assert 0.0 <= far_future < 1e-6, "衰減夠久之後應該趨近 0，且不能變成負數"


def test_bump_uses_decayed_value_as_base_not_raw_accumulation():
    """疊加是「衰減後的真實分數」上再加 boost，不是原始累積值上再加——
    不然分數會失真地一直往上飄，即使中間隔了很久沒被想起。"""
    node = MemoryNode("rust", "Concept", summary="Rust 語言")
    node.bump_activation(boost=0.8, now=1000.0)
    # 過了一個半衰期才又被想起一次：這時候基礎應該是衰減後的 0.4，而不是原始的 0.8
    node.bump_activation(boost=0.1, now=1000.0 + ACTIVATION_HALF_LIFE_SECONDS)
    assert abs(node.activation - 0.5) < 1e-9


# ----------------------------------------------------------------------
# 持久化：跨 session（重新載入 MemoryStore）分數要保留
# ----------------------------------------------------------------------

def test_activation_persists_across_store_reload():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(path)
    try:
        store1 = MemoryStore(path)
        store1.set_activation_enabled(True)
        store1.upsert_node("rust", "Concept", summary="Rust 語言")
        store1.get_node("rust")
        store1.get_node("rust")
        activation_before = store1.nodes["rust"].activation
        assert activation_before > 0.0
        store1.save()

        # 模擬重啟：開新的 MemoryStore instance 讀同一個檔案
        store2 = MemoryStore(path)
        assert store2.activation_enabled is False, "開關本身不跨 session 保留，每次重啟預設關閉"
        assert store2.nodes["rust"].activation == activation_before, \
            "但已經累積的分數本身要跨 session 保留下來，不能重啟就歸零"
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_backward_compatible_with_old_saved_files_missing_activation_fields():
    """舊版存檔沒有 activation / activation_updated_at 欄位，讀進來不該爆炸，
    應該用安全的預設值（0 分、視為剛建立）補上。"""
    old_dict = {
        "id": "legacy_node", "type": "Fact", "properties": {}, "relations": [],
        "summary": "舊版資料", "confidence": 0.9, "version": "abc123",
        "updated_at": 12345.0,
    }
    node = MemoryNode.from_dict(old_dict)
    assert node.activation == 0.0
    assert node.activation_updated_at == 12345.0
    assert node.get_effective_activation(now=12345.0) == 0.0


# ----------------------------------------------------------------------
# 實際效果：AttentionManager 排序要真的受 activation 影響
# ----------------------------------------------------------------------

@with_temp_store
def test_attention_manager_prioritizes_highly_activated_node_on_tie(store):
    """activation 較高的節點，就算 recency 略舊、confidence 相同，
    只要差距在 activation 訊號能貢獻的範圍內，排序上還是應該追過去——
    這是「常被想起的東西更容易被優先想到」這個設計初衷真正落地的地方，
    不然分數只是存好看的，沒有任何行為上的效果。

    用 4 個節點是為了把 recency 每一階的間距縮小（0.5 / (n-1)），
    確保 rust 與 cpp 之間的 recency 差距小到能被 activation 蓋過去。
    """
    store.set_activation_enabled(True)
    store.upsert_node("rust", "Concept", summary="程式語言 A", confidence=0.7)
    store.upsert_node("cpp", "Concept", summary="程式語言 B", confidence=0.7)
    store.upsert_node("filler1", "Concept", summary="填充節點 1", confidence=0.7)
    store.upsert_node("filler2", "Concept", summary="填充節點 2", confidence=0.7)

    # 讓 rust 被想起很多次，其他三個完全沒被想起過
    for _ in range(10):
        store.get_node("rust")

    wm = WorkingMemory(store, max_nodes=10)
    # 依序啟用：rust 最舊，cpp 次舊，filler 兩個最新
    # （iter_by_recency 新的在前，所以 rust 的 recency 分數最低、cpp 只比它高一階）
    wm.activate("rust")
    wm.activate("cpp")
    wm.activate("filler1")
    wm.activate("filler2")

    am = AttentionManager()
    scored = am._score_nodes(wm, keywords=set())
    order = [node_id for node_id, _, _ in scored]

    assert order.index("rust") < order.index("cpp"), \
        "activation 較高的節點即使 recency 略舊，也該追過只差一階 recency 的節點"


@with_temp_store
def test_attention_manager_score_unaffected_when_activation_disabled(store):
    """功能關閉時，就算節點被讀取很多次，AttentionManager 的分數也不該受影響，
    確保這個功能真的是「選配」，不開就完全不改變原本的行為。
    """
    store.upsert_node("rust", "Concept", summary="程式語言 A", confidence=0.7)
    store.upsert_node("cpp", "Concept", summary="程式語言 B", confidence=0.7)
    for _ in range(10):
        store.get_node("rust")  # 開關是關的，這裡不該累積任何 activation

    wm = WorkingMemory(store, max_nodes=10)
    wm.activate("cpp")  # 先啟用 cpp
    wm.activate("rust")  # 再啟用 rust（rust 的 recency 較新，理論上分數該領先）

    am = AttentionManager()
    scored = am._score_nodes(wm, keywords=set())
    order = [node_id for node_id, _, _ in scored]

    # 這裡驗證的重點不是誰贏，而是 rust 的 activation 分量必須是 0（沒有被關閉之外的機制悄悄加分）
    rust_score = next(s for nid, s, _ in scored if nid == "rust")
    cpp_score = next(s for nid, s, _ in scored if nid == "cpp")
    # recency 領先幅度最多 0.5，confidence 相同會抵銷，activation 若沒關好會多貢獻到 0.4 的分量
    assert rust_score - cpp_score <= 0.5 + 1e-9, "分數差距不該超出 recency 本身能解釋的範圍"


if __name__ == "__main__":
    tests = [
        test_disabled_by_default,
        test_toggle_on_off,
        test_reads_do_not_boost_activation_when_disabled,
        test_get_node_boosts_activation_when_enabled,
        test_search_hits_also_boost_activation,
        test_activation_boost_caps_at_one,
        test_effective_activation_decays_over_time,
        test_effective_activation_never_negative_or_nan_far_in_future,
        test_bump_uses_decayed_value_as_base_not_raw_accumulation,
        test_activation_persists_across_store_reload,
        test_backward_compatible_with_old_saved_files_missing_activation_fields,
        test_attention_manager_prioritizes_highly_activated_node_on_tie,
        test_attention_manager_score_unaffected_when_activation_disabled,
    ]
    for t in tests:
        t()
        print(f"[PASS] {t.__name__}")
