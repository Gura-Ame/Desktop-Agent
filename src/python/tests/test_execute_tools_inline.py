import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
"""
測試 agent_core.py 的 _execute_tools：驗證多個 tool_call 在同一輪時，
每個結果會內嵌在自己那次呼叫後面，而不是全部執行完才在最後面貼一整塊合併結果；
同時驗證每個工具真的只被執行一次（不會因為算兩種輸出格式就被呼叫兩次）。

執行方式：
    python test_execute_tools_inline.py
"""

import os
import sys
import tempfile


from agent.agent_core import AgentWorker  # noqa: E402
from agent.task_system import ExecutionMode  # noqa: E402
from agent.tool_permissions import PermissionMode  # noqa: E402


def make_agent(memory_path):
    agent = AgentWorker({}, event_callback=lambda t, d: None,
                        default_mode=ExecutionMode.AUTO, memory_path=memory_path)
    # 這個檔案專門測 _execute_tools 本身的行為（有沒有重複執行、結果有沒有內嵌
    # 在正確位置），會動態註冊像 counted_action/step_a/boom 這種測試用的假工具名稱，
    # 這些名字當然不在 TOOL_RISK_LEVELS 裡，會被判定為預設的 DANGEROUS，
    # 在 ASK 模式下每一個都會卡住等使用者回應——這裡測的不是權限系統，切成
    # AUTO 讓它跳過確認。
    agent.permission_manager.set_mode(PermissionMode.AUTO)
    return agent


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


@with_temp_memory
def test_no_tool_call_returns_content_unchanged(memory_path):
    agent = make_agent(memory_path)
    content = "這裡完全沒有工具呼叫，純文字回答。"
    is_tool, combined, interleaved = agent._execute_tools(content)
    assert is_tool is False
    assert combined == content
    assert interleaved == content
    print("[PASS] test_no_tool_call_returns_content_unchanged")


@with_temp_memory
def test_single_tool_call_executes_exactly_once(memory_path):
    call_count = {"n": 0}

    def counted_action(x):
        call_count["n"] += 1
        return f"got {x}"

    agent = make_agent(memory_path)
    agent.available_functions["counted_action"] = counted_action

    content = '呼叫看看：\n<|tool_call|>counted_action("hi")<|tool_call|>\n呼叫完了。'
    is_tool, combined, interleaved = agent._execute_tools(content)

    assert is_tool is True
    assert call_count["n"] == 1, "同一個 tool call 只應該被執行一次"
    assert "[counted_action]: got hi" in combined
    # 結果應該緊接在呼叫後面，出現在「呼叫完了」這句話之前
    result_pos = interleaved.find("got hi")
    trailing_text_pos = interleaved.find("呼叫完了")
    assert result_pos != -1 and trailing_text_pos != -1
    assert result_pos < trailing_text_pos, "結果應該內嵌在呼叫後面，而不是被推到整段文字最後"
    print("[PASS] test_single_tool_call_executes_exactly_once")


@with_temp_memory
def test_multiple_tool_calls_each_result_stays_next_to_its_own_call(memory_path):
    agent = make_agent(memory_path)
    agent.available_functions["step_a"] = lambda: "RESULT_A"
    agent.available_functions["step_b"] = lambda: "RESULT_B"

    content = (
        "先做第一步：\n"
        "<|tool_call|>step_a()<|tool_call|>\n"
        "這中間夾了一段說明文字，模型正在解釋接下來要做什麼。\n"
        "再做第二步：\n"
        "<|tool_call|>step_b()<|tool_call|>\n"
        "最後總結。"
    )
    is_tool, combined, interleaved = agent._execute_tools(content)

    assert is_tool is True
    assert "RESULT_A" in combined and "RESULT_B" in combined

    pos_call_a = interleaved.find("step_a")
    pos_result_a = interleaved.find("RESULT_A")
    pos_middle_text = interleaved.find("這中間夾了一段說明文字")
    pos_call_b = interleaved.find("step_b")
    pos_result_b = interleaved.find("RESULT_B")
    pos_summary = interleaved.find("最後總結")

    # 順序必須是：呼叫A -> 結果A -> 中間說明文字 -> 呼叫B -> 結果B -> 總結
    # 舊版是「呼叫A -> 中間文字 -> 呼叫B -> 總結 -> 結果A + 結果B 全部貼在最後」，這裡要驗證不再是這樣
    assert pos_call_a < pos_result_a < pos_middle_text < pos_call_b < pos_result_b < pos_summary, (
        f"結果沒有正確內嵌在各自呼叫後面: {[pos_call_a, pos_result_a, pos_middle_text, pos_call_b, pos_result_b, pos_summary]}"
    )
    print("[PASS] test_multiple_tool_calls_each_result_stays_next_to_its_own_call")


@with_temp_memory
def test_failing_call_tagged_as_error_succeeding_call_tagged_as_result(memory_path):
    agent = make_agent(memory_path)

    def boom():
        raise RuntimeError("測試用的失敗")

    agent.available_functions["boom"] = boom
    agent.available_functions["ok_action"] = lambda: "fine"

    content = (
        "<|tool_call|>boom()<|tool_call|>\n"
        "<|tool_call|>ok_action()<|tool_call|>"
    )
    is_tool, combined, interleaved = agent._execute_tools(content)

    assert is_tool is True
    assert "測試用的失敗" in combined
    assert "fine" in combined

    # boom() 那次呼叫後面應該接 <tool_error>，ok_action() 後面應該接 <tool_result>
    boom_section = interleaved[interleaved.find("boom"):interleaved.find("ok_action")]
    ok_section = interleaved[interleaved.find("ok_action"):]
    assert "<tool_error>" in boom_section
    assert "<tool_result>" in ok_section
    print("[PASS] test_failing_call_tagged_as_error_succeeding_call_tagged_as_result")


@with_temp_memory
def test_unknown_function_reported_as_error(memory_path):
    agent = make_agent(memory_path)
    content = '<|tool_call|>does_not_exist("x")<|tool_call|>'
    is_tool, combined, interleaved = agent._execute_tools(content)

    assert is_tool is True
    assert "未找到函式" in combined
    assert "<tool_error>" in interleaved
    print("[PASS] test_unknown_function_reported_as_error")


@with_temp_memory
def test_pyautogui_failsafe_exception_stops_agent_instead_of_being_swallowed(memory_path):
    """使用者把滑鼠甩去螢幕角落觸發 pyautogui 內建的實體緊急停止手勢時，
    這代表使用者現在就要 agent 停下來——不能被 _execute_tools 的通用
    Exception 處理當成一般工具失敗吞掉、讓迴圈繼續跑下一步。

    這台測試機沒有真的裝 pyautogui，agent_tool_execution.py 在 import
    階段就已經把 FailSafeException 定死成 None 了（見它開頭的
    try/except ImportError），這裡直接 monkeypatch 那個模組屬性，
    繞過「需要真的環境才能測到這條路徑」的限制，專注測邏輯本身：
    真的是這個特定例外類型時，要呼叫 request_stop() 並且往外拋
    InterruptedError，而不是回傳一句 tool_error 文字。
    """
    import agent.agent_tool_execution as tool_execution_module

    class FakeFailSafeException(Exception):
        pass

    original = tool_execution_module.FailSafeException
    tool_execution_module.FailSafeException = FakeFailSafeException
    try:
        agent = make_agent(memory_path)
        stop_calls = {"n": 0}
        original_request_stop = agent.request_stop

        def spy_request_stop():
            stop_calls["n"] += 1
            original_request_stop()

        agent.request_stop = spy_request_stop

        def moves_to_corner():
            raise FakeFailSafeException("mouse moved to a corner of the screen")

        agent.available_functions["moves_to_corner"] = moves_to_corner

        raised = False
        try:
            agent._execute_tools('<|tool_call|>moves_to_corner()<|tool_call|>')
        except InterruptedError:
            raised = True

        assert raised, "FailSafeException 應該讓 _execute_tools 拋出 InterruptedError，不是回傳一句錯誤文字"
        assert stop_calls["n"] == 1, "應該要呼叫 request_stop() 讓整個 agent 真的停下來"
        print("[PASS] test_pyautogui_failsafe_exception_stops_agent_instead_of_being_swallowed")
    finally:
        tool_execution_module.FailSafeException = original


if __name__ == "__main__":
    tests = [
        test_no_tool_call_returns_content_unchanged,
        test_single_tool_call_executes_exactly_once,
        test_multiple_tool_calls_each_result_stays_next_to_its_own_call,
        test_failing_call_tagged_as_error_succeeding_call_tagged_as_result,
        test_unknown_function_reported_as_error,
        test_pyautogui_failsafe_exception_stops_agent_instead_of_being_swallowed,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
