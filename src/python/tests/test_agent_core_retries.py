import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from agent.agent_core import AgentState
from agent.task_system import ExecutionMode, TaskNode, TaskStatus
from fake_llm import ECHO_REFLECT
from test_agent_core_helpers import make_agent, wait_until

def test_reasoning_does_not_escalate_reuses_first_call():
    scripts = {
        "system": [
            '簡單問題，直接查詢時間就好。\n<|tool_call|>call:run_action("get_time")<|tool_call|>',
            "現在是下午三點。",
        ],
        "compress": [
            "- id: turn_note\n- type: Fact\n- summary: 使用者問了現在幾點\n- detail: \n"
        ],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)

    agent.set_user_prompt("現在幾點？")
    agent.state = AgentState.IDLE
    agent.start()
    wait_until(lambda: not agent.is_running(), message="沒有在時限內結束")

    assert agent.state == AgentState.IDLE
    assert any(e[0] == "finished" for e in events)
    assert tool_calls == ["get_time"]
    system_calls = [c for c in agent.client.call_log if c == "system"]
    assert len(system_calls) == 2, f"應該恰好 2 次，實際: {agent.client.call_log}"
    assert any(c == "compress" for c in agent.client.call_log), "視窗大小是 2，這輪中途應該要觸發過一次壓縮"
    print("[PASS] test_reasoning_does_not_escalate_reuses_first_call")

def test_ask_user_triggered_after_max_retries():
    fail_then_pass_verify = ["STATUS: FAIL\nREASON: 條件還沒滿足"] * 4 + ["STATUS: PASS\nREASON: 這次成功了"]
    scripts = {
        "thinking": [
            "分析: 第一次卡關\n修正方法: retry v1\n修正注意: 小心一點\n拆解: NO\n新信心值: 0.5\n",
            "分析: 還是卡關\n修正方法: retry v2\n修正注意: 小心一點\n拆解: NO\n新信心值: 0.5\n",
            "分析: 持續卡關\n修正方法: retry v3\n修正注意: 小心一點\n拆解: NO\n新信心值: 0.5\n",
            "分析: 使用者回覆後再試一次\n修正方法: retry v4 with user hint\n修正注意: 照使用者指示做\n拆解: NO\n新信心值: 0.9\n",
        ],
        "system": [f'<|tool_call|>call:run_action("attempt {i}")<|tool_call|>' for i in range(1, 6)],
        "verify": fail_then_pass_verify,
        "reflect": [ECHO_REFLECT],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)

    task = TaskNode("TASK-1", "反覆失敗的任務")
    task.method = "run_action(...)"
    task.condition = "動作要確實完成"
    task.note = "無"
    task.need_thinking = False
    task.need_confirm = False
    task.confidence = 0.9
    agent.engine.tasks = [task]
    agent.state = AgentState.EXECUTING

    agent.start()

    wait_until(lambda: agent.is_paused_for_input, timeout=3.0,
               message="重試 4 次後應該要觸發 ask_user，但沒有等到")
    assert any(e[0] == "waiting_input" for e in events)
    waiting_question = next(d for t, d in events if t == "waiting_input")
    assert "反覆失敗的任務" in waiting_question
    assert task.retry_count == 4, "應該是第 4 次失敗才觸發 ask_user（retry_count 要等回覆後才會被重置）"

    agent.resume_with_user_input("先忽略這個錯誤，放寬條件重新嘗試一次")

    wait_until(lambda: not agent.is_running(), timeout=3.0,
               message="使用者回覆後，任務沒有在時限內完成")

    assert task.status == TaskStatus.COMPLETED
    assert "使用者指示" in task.note
    assert any(e[0] == "finished" for e in events)
    assert len(tool_calls) == 5, f"應該總共嘗試了 5 次，實際: {tool_calls}"
    print("[PASS] test_ask_user_triggered_after_max_retries")
