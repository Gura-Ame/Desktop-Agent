"""
agent/agent_thinking.py 的測試：預設關閉時完全不影響任何行為，開啟時
會呼叫 PRE_THINK_SYSTEM_PROMPT 拿到一段思考文字，該失敗的時候要能安全
降級（回傳 None），不能讓這個額外的步驟本身失敗就搞垮整個流程。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.agent_core import AgentWorker
from fake_llm import FakeOpenAIClient
from agent.tool_permissions import PermissionMode


def _make_agent():
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)
    agent = AgentWorker({}, event_callback=lambda *a: None, memory_path=memory_path)
    agent.permission_manager.set_mode(PermissionMode.AUTO)
    return agent, memory_path


def test_thinking_disabled_by_default():
    agent, memory_path = _make_agent()
    try:
        assert agent.thinking_enabled is False
        print("[PASS] test_thinking_disabled_by_default")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_generate_prethink_returns_none_when_disabled():
    agent, memory_path = _make_agent()
    try:
        # 沒有設定 agent.client，如果 generate_prethink 真的嘗試呼叫 LLM
        # 會直接炸掉——這裡確保關閉狀態下連呼叫都不會發生。
        result = agent.generate_prethink("隨便一個 context")
        assert result is None
        print("[PASS] test_generate_prethink_returns_none_when_disabled")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_generate_prethink_calls_llm_when_enabled():
    agent, memory_path = _make_agent()
    try:
        agent.set_thinking_enabled(True)
        agent.client = FakeOpenAIClient({"prethink": ["這是一段思考內容"]})
        result = agent.generate_prethink("使用者想幹嘛？")
        assert result == "這是一段思考內容"
        print("[PASS] test_generate_prethink_calls_llm_when_enabled")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_generate_prethink_fails_gracefully_and_returns_none():
    agent, memory_path = _make_agent()
    try:
        agent.set_thinking_enabled(True)

        def boom(*a, **k):
            raise RuntimeError("model unavailable")

        agent.client = type("C", (), {"chat": type("Chat", (), {
            "completions": type("Comp", (), {"create": staticmethod(boom)})()
        })()})()
        result = agent.generate_prethink("context")
        assert result is None
        print("[PASS] test_generate_prethink_fails_gracefully_and_returns_none")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_set_thinking_enabled_persists_across_restart():
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)
    try:
        agent1 = AgentWorker({}, event_callback=lambda *a: None, memory_path=memory_path)
        agent1.set_thinking_enabled(True)

        agent2 = AgentWorker({}, event_callback=lambda *a: None, memory_path=memory_path)
        assert agent2.thinking_enabled is True
        print("[PASS] test_set_thinking_enabled_persists_across_restart")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


if __name__ == "__main__":
    tests = [
        test_thinking_disabled_by_default,
        test_generate_prethink_returns_none_when_disabled,
        test_generate_prethink_calls_llm_when_enabled,
        test_generate_prethink_fails_gracefully_and_returns_none,
        test_set_thinking_enabled_persists_across_restart,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
