"""
agent/agent_physical_input_preview.py 的測試：三種權限策略對應的三種
行為（ASK=詢問、ASK_DANGEROUS_ONLY=預覽+1秒、AUTO=立刻繼續），
「瞬間輸入」開啟時完全略過這一切，以及參數綁定/預覽呼叫本身的邏輯。
"""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.agent_core import AgentWorker
from agent.tool_permissions import PermissionMode
from agent.agent_physical_input_preview import (
    _bind_args,
    _extract_target_xy,
    _extract_typing_text,
)


def _make_agent():
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)
    calls = []

    def fake_trajectory(current, target):
        calls.append(("trajectory", current, target))
        return "ok"

    def fake_typing_preview(x, y, text):
        calls.append(("typing_preview", x, y, text))
        return "ok"

    def fake_get_mouse_position():
        return "Current mouse position is (10, 20)"

    agent = AgentWorker(
        {
            "_show_mouse_trajectory": fake_trajectory,
            "_show_typing_preview": fake_typing_preview,
            "get_mouse_position": fake_get_mouse_position,
        },
        event_callback=lambda *a: None,
        memory_path=memory_path,
    )
    return agent, memory_path, calls


# ---- 參數綁定/擷取邏輯 ----

def test_bind_args_merges_positional_and_keyword():
    bound = _bind_args("move_mouse", [100, 200], {"duration": 0.5})
    assert bound == {"x": 100, "y": 200, "duration": 0.5}


def test_extract_target_xy_from_move_mouse():
    assert _extract_target_xy("move_mouse", [100, 200], {}) == (100.0, 200.0)


def test_extract_target_xy_returns_none_when_missing():
    assert _extract_target_xy("click_mouse", [], {"button": "left"}) is None


def test_extract_target_xy_handles_invalid_values_gracefully():
    assert _extract_target_xy("move_mouse", ["not_a_number", 200], {}) is None


def test_extract_typing_text_from_type_text():
    assert _extract_typing_text("type_text", ["hello"], {}) == "hello"


def test_extract_typing_text_from_press_key():
    assert _extract_typing_text("press_key", [], {"key": "ctrl+c"}) == "ctrl+c"


def test_extract_typing_text_empty_for_non_typing_tool():
    assert _extract_typing_text("move_mouse", [1, 2], {}) == ""


# ---- 開關本身 ----

def test_instant_input_disabled_by_default():
    agent, memory_path, calls = _make_agent()
    try:
        assert agent.instant_input_enabled is False
        print("[PASS] test_instant_input_disabled_by_default")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_set_instant_input_enabled_persists_across_restart():
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)
    try:
        agent1 = AgentWorker({}, event_callback=lambda *a: None, memory_path=memory_path)
        agent1.set_instant_input_enabled(True)

        agent2 = AgentWorker({}, event_callback=lambda *a: None, memory_path=memory_path)
        assert agent2.instant_input_enabled is True
        print("[PASS] test_set_instant_input_enabled_persists_across_restart")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


# ---- 三種權限策略下的閘門行為 ----

def test_instant_input_enabled_skips_everything():
    agent, memory_path, calls = _make_agent()
    try:
        agent.set_instant_input_enabled(True)
        agent.permission_manager.set_mode(PermissionMode.ASK)
        start = time.time()
        allowed = agent._gate_physical_input("move_mouse", [100, 200], {}, "100, 200")
        elapsed = time.time() - start
        assert allowed is True
        assert elapsed < 0.05, "瞬間輸入開啟時不該有任何停留"
        assert calls == [], "瞬間輸入開啟時不該畫任何預覽"
        print("[PASS] test_instant_input_enabled_skips_everything")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_auto_mode_shows_preview_and_continues_immediately():
    agent, memory_path, calls = _make_agent()
    try:
        agent.permission_manager.set_mode(PermissionMode.AUTO)
        start = time.time()
        allowed = agent._gate_physical_input("move_mouse", [100, 200], {}, "100, 200")
        elapsed = time.time() - start
        assert allowed is True
        assert elapsed < 0.3, "AUTO 模式不該停留"
        assert ("trajectory", (10, 20), (100.0, 200.0)) in calls
        print("[PASS] test_auto_mode_shows_preview_and_continues_immediately")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_ask_dangerous_only_mode_waits_about_one_second_then_continues():
    agent, memory_path, calls = _make_agent()
    try:
        agent.permission_manager.set_mode(PermissionMode.ASK_DANGEROUS_ONLY)
        start = time.time()
        allowed = agent._gate_physical_input("type_text", ["hello"], {}, "'hello'")
        elapsed = time.time() - start
        assert allowed is True
        assert elapsed >= 0.9, "ASK_DANGEROUS_ONLY 應該要停留大約 1 秒"
        assert ("typing_preview", 10, 20, "hello") in calls
        print("[PASS] test_ask_dangerous_only_mode_waits_about_one_second_then_continues")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_ask_dangerous_only_wait_is_interruptible_by_stop():
    agent, memory_path, calls = _make_agent()
    try:
        agent.permission_manager.set_mode(PermissionMode.ASK_DANGEROUS_ONLY)

        def stop_soon():
            time.sleep(0.15)
            agent.request_stop()

        threading.Thread(target=stop_soon).start()
        start = time.time()
        allowed = agent._gate_physical_input("type_text", ["hello"], {}, "'hello'")
        elapsed = time.time() - start
        assert allowed is False, "使用者在等待期間按下停止，不該繼續執行"
        assert elapsed < 0.9, "應該提早結束等待，不用等滿 1 秒"
        print("[PASS] test_ask_dangerous_only_wait_is_interruptible_by_stop")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_ask_mode_goes_through_full_permission_dialog():
    agent, memory_path, calls = _make_agent()
    events = []
    agent.event_callback = lambda t, d: events.append((t, d))
    try:
        agent.permission_manager.set_mode(PermissionMode.ASK)

        def respond_allow():
            start = time.time()
            while not any(e[0] == "permission_request" for e in events):
                if time.time() - start > 5.0:
                    raise AssertionError("等不到 permission_request 事件")
                time.sleep(0.02)
            agent.resume_with_permission_decision("allow")

        t = threading.Thread(target=respond_allow)
        t.start()
        allowed = agent._gate_physical_input("move_mouse", [100, 200], {}, "100, 200")
        t.join(timeout=2.0)

        assert allowed is True
        assert ("trajectory", (10, 20), (100.0, 200.0)) in calls
        print("[PASS] test_ask_mode_goes_through_full_permission_dialog")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_preview_failure_does_not_block_execution():
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)
    try:
        def boom(current, target):
            raise RuntimeError("overlay unavailable")

        agent = AgentWorker(
            {"_show_mouse_trajectory": boom},
            event_callback=lambda *a: None,
            memory_path=memory_path,
        )
        agent.permission_manager.set_mode(PermissionMode.AUTO)
        allowed = agent._gate_physical_input("move_mouse", [100, 200], {}, "100, 200")
        assert allowed is True
        print("[PASS] test_preview_failure_does_not_block_execution")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


if __name__ == "__main__":
    tests = [
        test_bind_args_merges_positional_and_keyword,
        test_extract_target_xy_from_move_mouse,
        test_extract_target_xy_returns_none_when_missing,
        test_extract_target_xy_handles_invalid_values_gracefully,
        test_extract_typing_text_from_type_text,
        test_extract_typing_text_from_press_key,
        test_extract_typing_text_empty_for_non_typing_tool,
        test_instant_input_disabled_by_default,
        test_set_instant_input_enabled_persists_across_restart,
        test_instant_input_enabled_skips_everything,
        test_auto_mode_shows_preview_and_continues_immediately,
        test_ask_dangerous_only_mode_waits_about_one_second_then_continues,
        test_ask_dangerous_only_wait_is_interruptible_by_stop,
        test_ask_mode_goes_through_full_permission_dialog,
        test_preview_failure_does_not_block_execution,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
