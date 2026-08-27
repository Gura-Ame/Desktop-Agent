import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
"""
漸進式遺忘（ForgettingManager）的單元測試。

執行方式：
    cd 到這個檔案所在的上一層資料夾，然後：
    python tests/test_forgetting.py
"""

import tempfile

from memory.memory_store import MemoryStore
from agent.forgetting import ForgettingManager


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
# 開關本身：預設關閉、要能被使用者打開/關閉
# ----------------------------------------------------------------------

def test_disabled_by_default_and_toggleable():
    mgr = ForgettingManager()
    assert mgr.enabled is False, "應該預設關閉，讓使用者自己決定要不要打開"
    mgr.set_enabled(True)
    assert mgr.enabled is True
    mgr.set_enabled(False)
    assert mgr.enabled is False
    print("[PASS] test_disabled_by_default_and_toggleable")


@with_temp_store
def test_disabled_manager_never_touches_anything(store: MemoryStore):
    store.upsert_node("old_fact", "Fact", properties={"a": 1}, confidence=0.3)
    node = store.get_node("old_fact")
    node.updated_at -= 999 * 24 * 3600  # 假裝已經放了 999 天
    node.last_accessed_at = node.updated_at

    mgr = ForgettingManager()  # 沒有呼叫 set_enabled(True)，維持關閉
    changed = mgr.run_decay_pass(store, now=None)
    assert changed == [], "關閉狀態下，不管多舊都不該被動到"
    assert store.get_node("old_fact").resolution_level == 0
    print("[PASS] test_disabled_manager_never_touches_anything")


# ----------------------------------------------------------------------
# Level 0 → 1：回收 override、標記為已摘要
# ----------------------------------------------------------------------

@with_temp_store
def test_level_0_to_1_recycles_override(store: MemoryStore):
    store.upsert_node("steak", "Food", properties={"temperature": "hot", "protein": "high"})
    store.upsert_node("event_001", "Event", properties={
        "type": "Eat", "override": {"temperature": "cold"}
    }, confidence=0.6)  # 明確給一般信心值，避免預設 confidence=1.0 干擾判斷
    node = store.get_node("event_001")
    node.updated_at -= 10 * 24 * 3600  # 假裝已經 10 天沒動過
    node.last_accessed_at = node.updated_at

    mgr = ForgettingManager(idle_seconds_level_1=7 * 24 * 3600)
    mgr.set_enabled(True)
    changed = mgr.run_decay_pass(store)

    assert "event_001" in changed
    updated = store.get_node("event_001")
    assert "override" not in updated.properties, "太久沒被存取，override 應該被回收、退回 parent 預設值"
    assert updated.resolution_level == 1
    print("[PASS] test_level_0_to_1_recycles_override")


@with_temp_store
def test_recently_touched_node_is_not_decayed(store: MemoryStore):
    store.upsert_node("event_002", "Event", properties={"override": {"temperature": "cold"}})
    # 剛建立、剛存取過，updated_at/last_accessed_at 都是現在

    mgr = ForgettingManager(idle_seconds_level_1=7 * 24 * 3600)
    mgr.set_enabled(True)
    changed = mgr.run_decay_pass(store)

    assert changed == [], "才剛動過的節點不該被遺忘"
    assert store.get_node("event_002").properties.get("override") == {"temperature": "cold"}
    print("[PASS] test_recently_touched_node_is_not_decayed")


@with_temp_store
def test_being_accessed_counts_as_not_idle_even_without_content_change(store: MemoryStore):
    """就算內容（updated_at）很久沒變，只要一直有人在查它（last_accessed_at 持續更新），
    也不該被當成沒人理的記憶而遺忘——這正是分開追蹤 updated_at / last_accessed_at 的意義。
    """
    store.upsert_node("popular_fact", "Fact", properties={"x": 1})
    node = store.get_node("popular_fact")
    node.updated_at -= 999 * 24 * 3600  # 內容本身 999 天沒變過

    mgr = ForgettingManager(idle_seconds_level_1=7 * 24 * 3600)
    mgr.set_enabled(True)

    # 但持續有人用 search / get_node 查它，last_accessed_at 會一直被刷新
    store.search("popular")
    changed = mgr.run_decay_pass(store)
    assert changed == [], "一直被查詢、被想起的節點不該被判定為閒置"
    print("[PASS] test_being_accessed_counts_as_not_idle_even_without_content_change")


# ----------------------------------------------------------------------
# Level 1 → 2：需要 LLM 才會發生；沒接 LLM 就先停在 level 1，不會出錯
# ----------------------------------------------------------------------

@with_temp_store
def test_level_1_to_2_needs_llm_and_skips_gracefully_without_one(store: MemoryStore):
    store.upsert_node("old_summary_node", "Fact", summary="很久以前的一個小細節")
    node = store.get_node("old_summary_node")
    node.resolution_level = 1
    node.updated_at -= 40 * 24 * 3600
    node.last_accessed_at = node.updated_at

    mgr = ForgettingManager(idle_seconds_level_2=30 * 24 * 3600)
    mgr.set_enabled(True)

    # 不提供 call_llm，應該優雅跳過，不報錯、也不會誤標成 level 2
    changed = mgr.run_decay_pass(store, call_llm=None)
    assert changed == []
    assert store.get_node("old_summary_node").resolution_level == 1
    print("[PASS] test_level_1_to_2_needs_llm_and_skips_gracefully_without_one")


@with_temp_store
def test_level_1_to_2_abstracts_summary_via_llm(store: MemoryStore):
    store.upsert_node("dinner_event", "Event", summary="跟朋友在某餐廳吃牛排，五分熟，靠窗座位",
                       confidence=0.6)
    node = store.get_node("dinner_event")
    node.resolution_level = 1
    node.updated_at -= 40 * 24 * 3600
    node.last_accessed_at = node.updated_at

    def fake_llm(system_prompt, user_prompt):
        return "一次聚餐"

    mgr = ForgettingManager(idle_seconds_level_2=30 * 24 * 3600)
    mgr.set_enabled(True)
    changed = mgr.run_decay_pass(store, call_llm=fake_llm)

    assert "dinner_event" in changed
    updated = store.get_node("dinner_event")
    assert updated.summary == "一次聚餐"
    assert updated.resolution_level == 2
    print("[PASS] test_level_1_to_2_abstracts_summary_via_llm")


@with_temp_store
def test_level_1_to_2_llm_failure_keeps_level_1(store: MemoryStore):
    store.upsert_node("flaky_node", "Fact", summary="細節")
    node = store.get_node("flaky_node")
    node.resolution_level = 1
    node.updated_at -= 40 * 24 * 3600
    node.last_accessed_at = node.updated_at

    def broken_llm(system_prompt, user_prompt):
        raise RuntimeError("LLM 掛了")

    mgr = ForgettingManager(idle_seconds_level_2=30 * 24 * 3600)
    mgr.set_enabled(True)
    changed = mgr.run_decay_pass(store, call_llm=broken_llm)

    assert changed == [], "LLM 呼叫失敗不該讓整個 pass 掛掉，也不該誤標成功"
    assert store.get_node("flaky_node").resolution_level == 1
    print("[PASS] test_level_1_to_2_llm_failure_keeps_level_1")


# ----------------------------------------------------------------------
# 安全閥：pinned / 高 confidence 節點永遠不遺忘
# ----------------------------------------------------------------------

@with_temp_store
def test_pinned_node_is_never_decayed(store: MemoryStore):
    store.upsert_node("important", "Lemma", properties={"override": {"x": 1}})
    node = store.get_node("important")
    node.updated_at -= 999 * 24 * 3600
    node.last_accessed_at = node.updated_at
    store.pin_node("important", True)

    mgr = ForgettingManager(idle_seconds_level_1=1)
    mgr.set_enabled(True)
    changed = mgr.run_decay_pass(store)

    assert changed == [], "pinned 的節點不管多舊都不該被遺忘"
    assert store.get_node("important").properties.get("override") == {"x": 1}
    print("[PASS] test_pinned_node_is_never_decayed")


@with_temp_store
def test_high_confidence_node_is_protected_when_threshold_enabled(store: MemoryStore):
    """預設 protect_confidence 形同停用（見模組頂端說明），這裡示範：
    使用者如果真的想讓信心值也當作保護訊號，可以自行調低門檻來啟用。
    """
    store.upsert_node("critical_fact", "Fact",
                       properties={"override": {"x": 1}},
                       confidence=0.97)
    node = store.get_node("critical_fact")
    node.updated_at -= 999 * 24 * 3600
    node.last_accessed_at = node.updated_at

    mgr = ForgettingManager(idle_seconds_level_1=1, protect_confidence=0.95)
    mgr.set_enabled(True)
    changed = mgr.run_decay_pass(store)

    assert changed == [], "手動調低 protect_confidence 之後，高信心值節點應該被保護"
    print("[PASS] test_high_confidence_node_is_protected_when_threshold_enabled")


@with_temp_store
def test_default_settings_do_not_auto_protect_by_confidence(store: MemoryStore):
    """這是這次修正的重點回歸測試：remember() 這種最常見的寫入路徑完全不會指定
    confidence，一律預設 1.0——如果預設設定就拿信心值當保護門檻，等於大多數記憶
    永遠不會被遺忘，整個機制形同虛設。確保預設情況下，就算 confidence=1.0
    （也就是完全沒特別設定過的一般記憶），該遺忘的時候還是會正常遺忘。
    """
    store.upsert_node("ordinary_fact", "Fact", properties={"override": {"x": 1}})
    node = store.get_node("ordinary_fact")
    assert node.confidence == 1.0, "upsert_node 沒指定 confidence 時預設就是 1.0"
    node.updated_at -= 999 * 24 * 3600
    node.last_accessed_at = node.updated_at

    mgr = ForgettingManager(idle_seconds_level_1=1)  # 用預設 protect_confidence
    mgr.set_enabled(True)
    changed = mgr.run_decay_pass(store)

    assert "ordinary_fact" in changed, (
        "預設設定下，一般記憶（confidence=1.0）也該正常進入遺忘流程，"
        "不能被預設值意外保護住"
    )
    print("[PASS] test_default_settings_do_not_auto_protect_by_confidence")


@with_temp_store
def test_low_confidence_node_is_not_protected(store: MemoryStore):
    store.upsert_node("minor_fact", "Fact",
                       properties={"override": {"x": 1}},
                       confidence=0.5)
    node = store.get_node("minor_fact")
    node.updated_at -= 999 * 24 * 3600
    node.last_accessed_at = node.updated_at

    mgr = ForgettingManager(idle_seconds_level_1=1)
    mgr.set_enabled(True)
    changed = mgr.run_decay_pass(store)

    assert "minor_fact" in changed, "信心值不高的一般知識該正常進入遺忘流程"
    print("[PASS] test_low_confidence_node_is_not_protected")


# ----------------------------------------------------------------------
# 節流：should_run_pass 避免每次呼叫都真的掃描整個 Disk
# ----------------------------------------------------------------------

def test_should_run_pass_respects_min_interval():
    mgr = ForgettingManager(min_pass_interval=3600)
    mgr.set_enabled(True)
    now = 1_000_000.0
    assert mgr.should_run_pass(now) is True, "從沒跑過，第一次應該允許執行"

    mgr._last_pass_at = now
    assert mgr.should_run_pass(now + 60) is False, "距離上次才 60 秒，還沒到門檻"
    assert mgr.should_run_pass(now + 3601) is True, "超過門檻後應該允許再跑一次"
    print("[PASS] test_should_run_pass_respects_min_interval")


def test_should_run_pass_false_when_disabled():
    mgr = ForgettingManager(min_pass_interval=0)
    assert mgr.should_run_pass() is False, "關閉狀態下，不管間隔多久都不該執行"
    print("[PASS] test_should_run_pass_false_when_disabled")


# ----------------------------------------------------------------------
# MemoryStore 新增欄位的基本行為（resolution_level / last_accessed_at / pinned 序列化）
# ----------------------------------------------------------------------

@with_temp_store
def test_new_fields_persist_across_reload(store: MemoryStore):
    store.upsert_node("a", "Fact", properties={"x": 1})
    node = store.get_node("a")
    node.resolution_level = 2
    node.pinned = True
    store.save()

    reloaded = MemoryStore(store.path)
    r = reloaded.get_node("a")
    assert r.resolution_level == 2
    assert r.pinned is True
    print("[PASS] test_new_fields_persist_across_reload")


@with_temp_store
def test_get_node_bumps_last_accessed_at(store: MemoryStore):
    store.upsert_node("a", "Fact")
    node = store.get_node("a")
    node.last_accessed_at -= 1000
    old = node.last_accessed_at

    store.get_node("a")  # 再讀一次
    assert store.get_node("a").last_accessed_at > old, "讀取應該要刷新 last_accessed_at"
    print("[PASS] test_get_node_bumps_last_accessed_at")


# ----------------------------------------------------------------------
# AgentWorker 端對端整合：開關預設關閉、set_forgetting_enabled 能真的打開、
# 打開後在一輪對話開始時會自動跑一次 decay pass。
# ----------------------------------------------------------------------

def test_agent_forgetting_disabled_by_default():
    from agent.agent_core import AgentWorker
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)
    agent = AgentWorker({}, event_callback=lambda *a: None, memory_path=memory_path)
    assert agent.forgetting_manager.enabled is False
    print("[PASS] test_agent_forgetting_disabled_by_default")


def test_agent_set_forgetting_enabled_toggles_and_logs():
    from agent.agent_core import AgentWorker
    events = []
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)
    agent = AgentWorker({}, event_callback=lambda t, d: events.append((t, d)), memory_path=memory_path)

    agent.set_forgetting_enabled(True)
    assert agent.forgetting_manager.enabled is True
    assert any("漸進式遺忘已開啟" in str(d) for t, d in events if t == "log")

    agent.set_forgetting_enabled(False)
    assert agent.forgetting_manager.enabled is False
    assert any("漸進式遺忘已關閉" in str(d) for t, d in events if t == "log")
    print("[PASS] test_agent_set_forgetting_enabled_toggles_and_logs")


def test_agent_maybe_run_forgetting_pass_noop_when_disabled():
    from agent.agent_core import AgentWorker
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)
    agent = AgentWorker({}, event_callback=lambda *a: None, memory_path=memory_path)

    agent.memory_store.upsert_node("old", "Fact", properties={"override": {"x": 1}})
    node = agent.memory_store.get_node("old")
    node.updated_at -= 999 * 24 * 3600
    node.last_accessed_at = node.updated_at

    agent.maybe_run_forgetting_pass()  # 沒開啟，應該完全不動任何東西
    assert agent.memory_store.get_node("old").resolution_level == 0
    print("[PASS] test_agent_maybe_run_forgetting_pass_noop_when_disabled")


def test_agent_maybe_run_forgetting_pass_runs_once_enabled():
    from agent.agent_core import AgentWorker
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)
    agent = AgentWorker({}, event_callback=lambda *a: None, memory_path=memory_path)
    agent.set_forgetting_enabled(True)
    agent.forgetting_manager.idle_seconds_level_1 = 1  # 測試用，門檻放到幾乎沒有

    agent.memory_store.upsert_node(
        "old", "Fact", properties={"override": {"x": 1}}, confidence=0.6
    )
    node = agent.memory_store.get_node("old")
    node.updated_at -= 999 * 24 * 3600
    node.last_accessed_at = node.updated_at

    agent.maybe_run_forgetting_pass()
    assert agent.memory_store.get_node("old").resolution_level == 1, \
        "開啟之後、門檻放低，應該真的跑了一次 decay pass"

    # 節流：緊接著再呼叫一次，因為還沒過 min_pass_interval，不該真的重新掃描
    agent.memory_store.upsert_node(
        "another_old", "Fact", properties={"override": {"y": 2}}, confidence=0.6
    )
    node2 = agent.memory_store.get_node("another_old")
    node2.updated_at -= 999 * 24 * 3600
    node2.last_accessed_at = node2.updated_at

    agent.maybe_run_forgetting_pass()
    assert agent.memory_store.get_node("another_old").resolution_level == 0, \
        "距離上次掃描還沒過節流間隔，這次不該真的執行"
    print("[PASS] test_agent_maybe_run_forgetting_pass_runs_once_enabled")


if __name__ == "__main__":
    tests = [
        test_disabled_by_default_and_toggleable,
        test_disabled_manager_never_touches_anything,
        test_level_0_to_1_recycles_override,
        test_recently_touched_node_is_not_decayed,
        test_being_accessed_counts_as_not_idle_even_without_content_change,
        test_level_1_to_2_needs_llm_and_skips_gracefully_without_one,
        test_level_1_to_2_abstracts_summary_via_llm,
        test_level_1_to_2_llm_failure_keeps_level_1,
        test_pinned_node_is_never_decayed,
        test_high_confidence_node_is_protected_when_threshold_enabled,
        test_default_settings_do_not_auto_protect_by_confidence,
        test_low_confidence_node_is_not_protected,
        test_should_run_pass_respects_min_interval,
        test_should_run_pass_false_when_disabled,
        test_new_fields_persist_across_reload,
        test_get_node_bumps_last_accessed_at,
        test_agent_forgetting_disabled_by_default,
        test_agent_set_forgetting_enabled_toggles_and_logs,
        test_agent_maybe_run_forgetting_pass_noop_when_disabled,
        test_agent_maybe_run_forgetting_pass_runs_once_enabled,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
