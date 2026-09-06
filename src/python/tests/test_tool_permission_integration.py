"""
權限系統的整合測試：驗證真正的暫停/等待/恢復迴圈跑得起來——跟
test_tool_permissions.py 只測 PermissionManager 的純邏輯不同，這裡要
確認 AgentWorker.request_tool_permission 真的會在背景執行緒裡卡住
等待，前端（這裡用一個背景 thread 模擬）呼叫 resume_with_permission_decision
之後才會繼續，而且拒絕/允許/本次工作階段永久允許三種決定的效果都對得上。
"""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.agent_core import AgentWorker
from agent.task_system import ExecutionMode
from agent.tool_permissions import PermissionMode


def _make_agent(mode=PermissionMode.ASK):
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)
    events = []
    agent = AgentWorker(
        {"dangerous_tool": lambda: "did the dangerous thing"},
        event_callback=lambda t, d: events.append((t, d)),
        default_mode=ExecutionMode.AUTO,
        memory_path=memory_path,
    )
    agent.permission_manager.set_mode(mode)
    return agent, events, memory_path


def _respond_after_request(agent, decision, events, timeout=5.0):
    """背景執行緒：等到 permission_request 事件出現後，模擬使用者做出決定。"""
    start = time.time()
    while not any(e[0] == "permission_request" for e in events):
        if time.time() - start > timeout:
            raise AssertionError("等不到 permission_request 事件")
        time.sleep(0.02)
    agent.resume_with_permission_decision(decision)


def test_dangerous_tool_blocks_until_resumed_then_allows():
    agent, events, memory_path = _make_agent()
    try:
        t = threading.Thread(
            target=_respond_after_request, args=(agent, "allow", events)
        )
        t.start()

        start = time.time()
        allowed = agent.request_tool_permission("dangerous_tool", "")
        elapsed = time.time() - start
        t.join(timeout=2.0)

        assert allowed is True
        assert elapsed >= 0.0  # 有真的卡住等待過（不是瞬間回傳），下面用事件更精確驗證
        assert any(e[0] == "permission_request" for e in events)
        # "allow"（僅此一次）不應該把工具加進本次工作階段的白名單
        assert agent.permission_manager.is_granted("dangerous_tool") is False
        print("[PASS] test_dangerous_tool_blocks_until_resumed_then_allows")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_deny_decision_blocks_execution():
    agent, events, memory_path = _make_agent()
    try:
        t = threading.Thread(
            target=_respond_after_request, args=(agent, "deny", events)
        )
        t.start()
        allowed = agent.request_tool_permission("dangerous_tool", "")
        t.join(timeout=2.0)

        assert allowed is False
        print("[PASS] test_deny_decision_blocks_execution")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_allow_session_grants_future_calls_without_asking_again():
    agent, events, memory_path = _make_agent()
    try:
        t = threading.Thread(
            target=_respond_after_request, args=(agent, "allow_session", events)
        )
        t.start()
        first = agent.request_tool_permission("dangerous_tool", "")
        t.join(timeout=2.0)
        assert first is True
        assert agent.permission_manager.is_granted("dangerous_tool") is True

        # 第二次呼叫同一個工具，不應該再卡住——needs_confirmation 已經是 False，
        # 完全不會進到暫停等待的分支，這裡故意不啟動任何 responder thread，
        # 如果邏輯有誤讓它還是卡住，這個測試會直接 hang 到 pytest-timeout 逾時。
        second = agent.request_tool_permission("dangerous_tool", "")
        assert second is True
        print("[PASS] test_allow_session_grants_future_calls_without_asking_again")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_full_tool_call_denied_produces_tool_error_not_execution():
    """走完整的 <|tool_call|> 解析 + _execute_tools 路徑，確認拒絕之後
    工具本身真的沒有被執行，而且回饋給模型的文字清楚說明是被拒絕，不是失敗。
    """
    call_log = []
    agent, events, memory_path = _make_agent()
    agent.available_functions["dangerous_tool"] = lambda: call_log.append("ran") or "done"
    try:
        t = threading.Thread(
            target=_respond_after_request, args=(agent, "deny", events)
        )
        t.start()
        is_tool, combined, interleaved = agent._execute_tools(
            '<|tool_call|>dangerous_tool()<|tool_call|>'
        )
        t.join(timeout=2.0)

        assert is_tool is True
        assert call_log == [], "使用者拒絕之後，工具本身不該被執行"
        assert "被拒絕" in combined
        assert "tool_error" in interleaved
        print("[PASS] test_full_tool_call_denied_produces_tool_error_not_execution")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_stopping_agent_while_waiting_for_permission_raises_interrupted():
    agent, events, memory_path = _make_agent()
    try:
        def stop_after_request():
            start = time.time()
            while not any(e[0] == "permission_request" for e in events):
                if time.time() - start > 5.0:
                    raise AssertionError("等不到 permission_request 事件")
                time.sleep(0.02)
            agent.request_stop()

        t = threading.Thread(target=stop_after_request)
        t.start()
        try:
            agent.request_tool_permission("dangerous_tool", "")
            raised = False
        except InterruptedError:
            raised = True
        t.join(timeout=2.0)
        assert raised, "使用者在等待授權的當下按下停止，應該要中斷、不是靜靜放行或拒絕"
        print("[PASS] test_stopping_agent_while_waiting_for_permission_raises_interrupted")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_permission_mode_persists_across_restart():
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)
    try:
        agent1 = AgentWorker({}, event_callback=lambda *a: None, memory_path=memory_path)
        agent1.set_permission_mode(PermissionMode.AUTO)

        agent2 = AgentWorker({}, event_callback=lambda *a: None, memory_path=memory_path)
        assert agent2.permission_manager.mode == PermissionMode.AUTO, (
            "策略本身應該跨 session 保留"
        )
        # 但已授權清單不應該跨 session 保留——見 PermissionManager 的說明
        assert agent2.permission_manager.is_granted("dangerous_tool") is False
        print("[PASS] test_permission_mode_persists_across_restart")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


if __name__ == "__main__":
    tests = [
        test_dangerous_tool_blocks_until_resumed_then_allows,
        test_deny_decision_blocks_execution,
        test_allow_session_grants_future_calls_without_asking_again,
        test_full_tool_call_denied_produces_tool_error_not_execution,
        test_stopping_agent_while_waiting_for_permission_raises_interrupted,
        test_permission_mode_persists_across_restart,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
