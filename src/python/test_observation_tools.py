"""
測試 agent_core.py 新接上的三個 Observation / Event 工具：
record_observation / recall_observation / recall_with_event。

執行方式：
    python test_observation_tools.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from agent_core import AgentWorker  # noqa: E402
from task_system import ExecutionMode  # noqa: E402


def with_temp_memory(fn):
    def wrapper():
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(path)
        try:
            fn(path)
        finally:
            if os.path.exists(path):
                os.remove(path)
    return wrapper


def make_agent(memory_path):
    return AgentWorker({}, event_callback=lambda t, d: None,
                        default_mode=ExecutionMode.AUTO, memory_path=memory_path)


@with_temp_memory
def test_record_observation_requires_target_to_exist_first(memory_path):
    agent = make_agent(memory_path)
    result = agent.record_observation("obs1", "not_remembered_yet", "一些結論")
    assert "要先用 remember" in result
    assert agent.memory_store.get_node("obs1") is None, "目標不存在時不該真的寫進 Disk"
    print("[PASS] test_record_observation_requires_target_to_exist_first")


@with_temp_memory
def test_record_and_recall_observation_when_fresh(memory_path):
    agent = make_agent(memory_path)
    agent.remember("parser.parse_expr", "Function", "解析運算式的核心函式")
    agent.record_observation("obs1", "parser.parse_expr", "沒有處理空字串輸入", 0.85)

    result = agent.recall_observation("obs1")
    assert "沒有處理空字串輸入" in result
    assert "過期" not in result, "目標物件內容沒變過，不該被判定過期"
    assert "0.85" in result
    print("[PASS] test_record_and_recall_observation_when_fresh")


@with_temp_memory
def test_recall_observation_warns_when_stale(memory_path):
    agent = make_agent(memory_path)
    agent.remember("parser.parse_expr", "Function", "解析運算式的核心函式",
                    properties={"signature": "parse_expr(tokens)"})
    agent.record_observation("obs1", "parser.parse_expr", "沒有處理空字串輸入", 0.85)

    # 目標物件的內容變了（例如程式碼被改過）
    agent.remember("parser.parse_expr", "Function", "解析運算式的核心函式",
                    properties={"signature": "parse_expr(tokens, strict=False)"})

    result = agent.recall_observation("obs1")
    assert "過期" in result, "目標已經變了，應該要提醒可能過期"
    assert "沒有處理空字串輸入" in result, "就算過期，還是要把舊結論給使用者參考"
    print("[PASS] test_recall_observation_warns_when_stale")


@with_temp_memory
def test_recall_observation_not_found(memory_path):
    agent = make_agent(memory_path)
    result = agent.recall_observation("does_not_exist")
    assert "沒有找到" in result
    print("[PASS] test_recall_observation_not_found")


@with_temp_memory
def test_recall_with_event_applies_override(memory_path):
    agent = make_agent(memory_path)
    agent.remember("steak", "Food", "高蛋白食物", properties={"temperature": "hot", "protein": "high"})
    agent.remember("event_001", "Event", "某次用餐紀錄",
                    properties={"override": {"temperature": "cold"}})

    result = agent.recall_with_event("steak", "event_001")
    assert '"temperature": "cold"' in result, "應該套用 event 的 override"
    assert '"protein": "high"' in result, "沒被 override 的屬性應該維持原樣"
    print("[PASS] test_recall_with_event_applies_override")


@with_temp_memory
def test_recall_with_event_missing_target_or_event(memory_path):
    agent = make_agent(memory_path)
    agent.remember("steak", "Food", "高蛋白食物")

    result1 = agent.recall_with_event("steak", "no_such_event")
    assert "沒有找到事件" in result1

    result2 = agent.recall_with_event("no_such_thing", "event_001")
    assert "沒有找到" in result2
    print("[PASS] test_recall_with_event_missing_target_or_event")


@with_temp_memory
def test_tools_registered_and_callable_via_tool_call_syntax(memory_path):
    """確認這三個工具真的被註冊進 available_functions，且能透過 <|tool_call|> 語法呼叫到。"""
    agent = make_agent(memory_path)
    for name in ("record_observation", "recall_observation", "recall_with_event"):
        assert name in agent.available_functions, f"{name} 應該要被註冊成可呼叫的工具"

    agent.remember("x", "Fact", "一個事實")
    content = '<|tool_call|>call:record_observation("obs_x", "x", "一個結論", 0.7)<|tool_call|>'
    is_tool, combined, interleaved = agent._execute_tools(content)
    assert is_tool is True
    assert "已記錄結論" in combined
    assert agent.memory_store.get_node("obs_x") is not None
    print("[PASS] test_tools_registered_and_callable_via_tool_call_syntax")


if __name__ == "__main__":
    tests = [
        test_record_observation_requires_target_to_exist_first,
        test_record_and_recall_observation_when_fresh,
        test_recall_observation_warns_when_stale,
        test_recall_observation_not_found,
        test_recall_with_event_applies_override,
        test_recall_with_event_missing_target_or_event,
        test_tools_registered_and_callable_via_tool_call_syntax,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
