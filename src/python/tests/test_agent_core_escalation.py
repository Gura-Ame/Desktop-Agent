import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from agent.agent_core import AgentState
from agent.task_system import ExecutionMode, TaskStatus
from fake_llm import ECHO_REFLECT
from test_agent_core_helpers import (
    make_agent, wait_until, send_turn,
    ESCALATE_RESPONSE, PLAN_DSL, DECOMPOSE_DSL, THINK_RESPONSE_1, THINK_RESPONSE_2
)

def test_reasoning_escalates_to_planning_with_decompose_and_smart_confirm():
    scripts = {
        "system": [
            ESCALATE_RESPONSE,
            '<|tool_call|>run_action("mkdir docs images")<|tool_call|>',
            '<|tool_call|>run_action("move files")<|tool_call|>',
            '<|tool_call|>run_action("move files carefully, retry")<|tool_call|>',
            '<|tool_call|>run_action("print report")<|tool_call|>',
        ],
        "planner": [PLAN_DSL],
        "decompose": [DECOMPOSE_DSL],
        "thinking": [THINK_RESPONSE_1, THINK_RESPONSE_2],
        "verify": [
            "STATUS: PASS\nREASON: 資料夾都已建立",
            "STATUS: FAIL\nREASON: 還有檔案沒搬移乾淨",
            "STATUS: PASS\nREASON: 檔案都搬移完成",
            "STATUS: PASS\nREASON: 報告已印出",
        ],
        "reflect": [ECHO_REFLECT, ECHO_REFLECT, ECHO_REFLECT],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.SMART)

    agent.set_user_prompt("整理桌面上的檔案並回報")
    agent.state = AgentState.IDLE
    agent.start()
    wait_until(lambda: not agent.is_running(), message="推理 + Planning 階段沒有在時限內結束")

    assert agent.state == AgentState.WAITING_CONFIRM
    assert any(e[0] == "ask_confirm" for e in events), "初版計畫一定要送出 ask_confirm，不受執行模式影響"
    chunk_texts = "".join(str(d) for t, d in events if t == "chunk")
    assert "需要拆解成多個步驟" in chunk_texts, "切換前的推理內容應該有串流顯示給使用者看"
    assert agent.history == [], "切換到 Planning 模式時，推理草稿不應該留在對話歷史裡"

    agent.confirm_and_start()
    wait_until(lambda: not agent.is_running(), timeout=3.0,
               message="第一批任務（含拆解、重試）沒有在時限內跑完")

    task1 = next(t for t in agent.engine.tasks if t.id == "TASK-1")
    assert task1.status == TaskStatus.COMPLETED, "兩個子任務都完成後，父任務應該自動標記完成"
    assert "TASK-1.1" in task1.result and "TASK-1.2" in task1.result

    child2 = next(t for t in agent.engine.tasks if t.id == "TASK-1.2")
    assert child2.retry_count == 0, "驗證通過後 retry_count 應該被重置"
    assert child2.think_count == 0

    assert agent.state == AgentState.WAITING_CONFIRM
    task2 = next(t for t in agent.engine.tasks if t.id == "TASK-2")
    assert task2.status == TaskStatus.PENDING, "TASK-2 應該還沒被執行，正在等待確認"

    agent.confirm_and_start()
    wait_until(lambda: not agent.is_running(), message="最後一步沒有在時限內完成")

    assert agent.state == AgentState.IDLE
    assert any(e[0] == "finished" for e in events)
    task2 = next(t for t in agent.engine.tasks if t.id == "TASK-2")
    assert task2.status == TaskStatus.COMPLETED

    assert len(tool_calls) == 4, f"應該總共呼叫了 4 次工具，實際: {tool_calls}"
    print("[PASS] test_reasoning_escalates_to_planning_with_decompose_and_smart_confirm")

def test_repeating_without_progress_auto_escalates_to_planning():
    verbose_reply = (
        "這個問題需要證明 (a^2+b^2)/(ab+1) 是完全平方數。讓我們考慮 a 和 b 滿足條件，"
        "首先我們可以嘗試代入具體數值來觀察規律，然後用代數變換來簡化這個表達式，"
        "考慮到 ab+1 整除 a^2+b^2，我們可以進一步分析這個關係式的性質。"
    )
    scripts = {
        "system": [verbose_reply, verbose_reply],
        "planner": [
            "- [ ] [TASK-1] 嘗試策略 A\n"
            "  - 方法: 用 Vieta jumping 建構最小反例\n"
            "  - 條件: 找出矛盾或證明成立\n"
            "  - 注意: 無\n"
            "  - 深度思考: YES\n"
            "  - 需要拆解: NO\n"
            "  - 需要確認: NO\n"
            "  - 信心值: 0.4\n"
        ],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.SMART)

    send_turn(agent, "幫我證明這個數論題")
    assert agent.state == AgentState.IDLE
    assert not any(e[0] == "ask_confirm" for e in events)

    send_turn(agent, "continue")

    assert agent.state == AgentState.WAITING_CONFIRM
    assert any(e[0] == "ask_confirm" for e in events)
    assert any("原地打轉" in str(d) for t, d in events if t == "log")
    print("[PASS] test_repeating_without_progress_auto_escalates_to_planning")

def test_short_similar_replies_not_falsely_flagged():
    scripts = {"system": ["好的", "好的"]}
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)

    send_turn(agent, "嗨")
    send_turn(agent, "嗨")

    assert not any(e[0] == "ask_confirm" for e in events), "內容太短，不該被判定為原地打轉"
    print("[PASS] test_short_similar_replies_not_falsely_flagged")

def test_truncated_without_conclusion_auto_escalates_to_planning():
    rambling_no_conclusion = (
        "這個問題需要證明...讓我們考慮 a 和 b 滿足條件...首先我們可以嘗試代入具體數值...\n"
        "然後我們可以用代數變換來簡化這個表達式，考慮到...我們可以進一步分析..."
    )
    scripts = {
        "system": [(rambling_no_conclusion, "length")],
        "planner": [
            "- [ ] [TASK-1] 嘗試策略 A：代數變換\n"
            "  - 方法: 從 ab+1 | a^2+b^2 出發，用 Vieta jumping 建構最小反例\n"
            "  - 條件: 找出矛盾或證明成立\n"
            "  - 注意: 無\n"
            "  - 深度思考: YES\n"
            "  - 需要拆解: NO\n"
            "  - 需要確認: NO\n"
            "  - 信心值: 0.4\n"
        ],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.SMART)

    agent.set_user_prompt("Let a and b be positive integers such that ab+1 divides a^2+b^2...")
    agent.state = AgentState.IDLE
    agent.start()
    wait_until(lambda: not agent.is_running(), message="沒有在時限內結束")

    assert agent.state == AgentState.WAITING_CONFIRM
    assert any(e[0] == "ask_confirm" for e in events), "被截斷又沒收斂，應該自動切換到規劃模式並送出 ask_confirm"
    assert any("被長度上限截斷" in str(d) for t, d in events if t == "log")
    assert agent.history == [], "自動切換到規劃模式時，這段沒結論的草稿不應該留在對話歷史裡"
    assert tool_calls == [], "不應該把這段沒收斂的內容當成正常回答讓它去呼叫工具"
    print("[PASS] test_truncated_without_conclusion_auto_escalates_to_planning")

def test_truncated_but_has_tool_call_does_not_force_escalate():
    scripts = {
        "system": [
            ('<|tool_call|>run_action("do something long")<|tool_call|>\n後面接了很長的說明文字...', "length"),
            "工具結果我看到了，這是最終回覆。",
        ],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)

    agent.set_user_prompt("幫我做一件事")
    agent.state = AgentState.IDLE
    agent.start()
    wait_until(lambda: not agent.is_running(), message="沒有在時限內結束")

    assert agent.state == AgentState.IDLE
    assert not any(e[0] == "ask_confirm" for e in events), "有呼叫工具就不該被誤判成需要規劃"
    assert tool_calls == ["do something long"]
    print("[PASS] test_truncated_but_has_tool_call_does_not_force_escalate")
