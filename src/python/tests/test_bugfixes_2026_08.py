"""
針對這次修的幾個問題的回歸測試：
1. Task Tree 解析失敗時，會把錯誤原因回饋給模型重試，而不是第一次沒格式對就整批放棄。
2. 重試用盡仍失敗時，會 emit "reset_message" 通知前端丟棄殘留內容，並正確降級到直接模式。
3. 串流過程中即時偵測到內容重複時，會提前中止，並用 "repetition_detected" 標記，
   使 escalate 判斷邏輯把它當成「需要完整規劃」處理（而不是預設的長度截斷判斷）。
"""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.agent_core import AgentState
from agent.task_system import ExecutionMode
from test_agent_core_helpers import make_agent, send_turn, PLAN_DSL

BAD_PROSE = (
    "這是模型不聽話直接寫的一大段散文推理，完全沒有照規定的任務清單格式輸出。"
    "就算內容本身很有道理，也沒辦法被拆解成結構化的任務項目。"
)

REPEATING_CONTENT = (
    "Let us use the given condition to derive a relationship between a and b "
    "and show it is a perfect square. "
) * 12


def test_task_tree_repair_retry_succeeds_on_second_attempt():
    """Planner 第一次輸出散文（解析失敗），把錯誤回饋後第二次輸出正確 DSL，應該成功進入待確認狀態，
    而不是直接放棄降級到直接模式。"""
    scripts = {
        "system": [("<|plan|>需要嘗試多種策略並驗算", "stop")],
        "planner": [BAD_PROSE, PLAN_DSL],
    }
    agent, events, _ = make_agent(scripts, mode=ExecutionMode.SMART)
    send_turn(agent, "證明某個數學命題")

    event_types = [t for t, _ in events]
    assert "ask_confirm" in event_types, f"應該成功解析出 Task Tree 並等待確認，實際事件: {event_types}"
    assert "reset_message" not in event_types, "重試成功的話不應該觸發 reset_message"
    assert agent.state == AgentState.WAITING_CONFIRM
    assert len(agent.engine.tasks) == 2
    # 確認 planner 真的被呼叫了兩次（第一次失敗 + 重試一次）
    assert agent.client.call_log.count("planner") == 2


def test_task_tree_repair_falls_back_after_exhausting_retries():
    """Planner 兩次都輸出散文（重試也救不回來），應該乾淨降級到直接模式，
    並且要先 emit reset_message 讓前端丟棄殘留的舊內容。"""
    scripts = {
        "system": [
            ("<|plan|>需要嘗試多種策略並驗算", "stop"),
            "好的，我直接回答你的問題。",  # 降級後 direct mode 的第二次呼叫
        ],
        "planner": [BAD_PROSE, BAD_PROSE],
    }
    agent, events, _ = make_agent(scripts, mode=ExecutionMode.SMART)
    send_turn(agent, "證明某個數學命題")

    event_types = [t for t, _ in events]
    assert "reset_message" in event_types, f"重試用盡後應該通知前端捨棄殘留內容，實際事件: {event_types}"
    assert "ask_confirm" not in event_types
    assert agent.engine.tasks == [], "解析從頭到尾都沒成功，不應該套用任何任務樹"
    assert agent.state == AgentState.IDLE
    assert agent.client.call_log.count("planner") == 2
    # reset_message 必須發生在直接模式重新生成內容「之前」，不能在它之後才補發
    reset_idx = event_types.index("reset_message")
    chunk_indices_after = [i for i, t in enumerate(event_types) if t == "chunk" and i > reset_idx]
    assert chunk_indices_after, "reset_message 之後應該還有新的 chunk 內容（降級後 direct mode 的回覆）"


def test_mid_stream_repetition_triggers_escalation_not_left_undetected():
    """模型在單次生成裡自己原地打轉（同一段話重複），系統應該即時偵測到並提前中止，
    標記為 repetition_detected，走跟『被截斷』一樣的自動切換到 Planning 的流程，
    而不是把這段重複內容原封不動當成正常回答收下。"""
    scripts = {
        "system": [(REPEATING_CONTENT, "stop")],  # 假裝模型自己收尾了，但內容其實在繞圈
        "planner": [PLAN_DSL],
    }
    agent, events, _ = make_agent(scripts, mode=ExecutionMode.SMART)
    send_turn(agent, "證明某個很難的數學題")

    event_types = [t for t, _ in events]
    logs = [d for t, d in events if t == "log"]
    assert any("即時偵測到生成內容重複" in str(l) for l in logs), (
        f"應該要有即時偵測到重複的系統訊息，實際 logs: {logs}"
    )
    assert "ask_confirm" in event_types, "偵測到重複後應該自動切換到完整規劃模式並成功生成 Task Tree"
    assert agent.client.call_log.count("planner") == 1


def test_lazy_tool_doc_injected_on_first_real_call_only():
    """第一次真的呼叫一個有文件的工具（例如 execute_python），系統應該自動把完整用法說明
    夾帶進『回饋給模型』的結果裡；同一個工具第二次呼叫就不該再重複夾帶，避免浪費 token。
    這份文件只該出現在餵給模型的 combined_result，不該混進使用者在畫面上看到的
    interleaved_content（不然每個工具第一次用都會在聊天視窗炸出一大段說明書）。
    """
    scripts = {"system": [("好的", "stop")]}
    agent, events, _ = make_agent(scripts, mode=ExecutionMode.SMART)
    agent.available_functions["execute_python"] = lambda code: "42"

    content1 = '<|tool_call|>execute_python("print(6*7)")<|tool_call|>'
    is_tool, combined1, interleaved1 = agent._execute_tools(content1)

    assert is_tool
    assert "execute_python" in agent._doc_shown_tools
    assert "這是你本次對話第一次呼叫 execute_python" in combined1
    assert "凡涉及幾何座標計算" in combined1  # 來自 tool_docs.py 的實際說明內容
    assert "[execute_python]: 42" in combined1
    # 文件不該混進使用者看到的畫面內容
    assert "這是你本次對話第一次呼叫" not in interleaved1
    assert "[execute_python]: 42" in interleaved1

    # 第二次呼叫同一個工具，不該再重複夾帶文件
    content2 = '<|tool_call|>execute_python("print(1+1)")<|tool_call|>'
    agent.available_functions["execute_python"] = lambda code: "2"
    is_tool2, combined2, interleaved2 = agent._execute_tools(content2)
    assert is_tool2
    assert "這是你本次對話第一次呼叫" not in combined2
    assert "[execute_python]: 2" in combined2


def test_read_tool_doc_marks_shown_so_first_real_call_does_not_duplicate():
    """模型主動呼叫 read_tool_doc 先查過用法之後，實際呼叫該工具時就不該再被動夾帶一次文件
    （不然等於白白重複貼兩次一樣的說明，浪費 token）。"""
    scripts = {"system": [("好的", "stop")]}
    agent, events, _ = make_agent(scripts, mode=ExecutionMode.SMART)
    agent.available_functions["draw_box"] = lambda *a, **k: "drawn"

    doc_text = agent.read_tool_doc("draw_box")
    assert "6 位數 Hex 色碼" in doc_text
    assert "draw_box" in agent._doc_shown_tools

    content = '<|tool_call|>draw_box(10, 20, 100, 100, "test", "#FF0000")<|tool_call|>'
    is_tool, combined, interleaved = agent._execute_tools(content)
    assert is_tool
    assert "這是你本次對話第一次呼叫" not in combined
    assert "[draw_box]: drawn" in combined


def test_tool_without_registered_doc_has_no_injection_overhead():
    """像 run_action 這種沒有登記文件的工具（本來就簡單直覺），完全不該被硬塞任何說明文字，
    確保懶加載機制不會反過來對「不需要文件的工具」也造成額外開銷。"""
    scripts = {"system": [("好的", "stop")]}
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.SMART)

    content = '<|tool_call|>run_action("do something")<|tool_call|>'
    is_tool, combined, interleaved = agent._execute_tools(content)
    assert is_tool
    assert tool_calls == ["do something"]
    assert combined.strip() == '[run_action]: executed: do something'
    assert "run_action" not in agent._doc_shown_tools


if __name__ == "__main__":
    test_task_tree_repair_retry_succeeds_on_second_attempt()
    print("[PASS] test_task_tree_repair_retry_succeeds_on_second_attempt")
    test_task_tree_repair_falls_back_after_exhausting_retries()
    print("[PASS] test_task_tree_repair_falls_back_after_exhausting_retries")
    test_mid_stream_repetition_triggers_escalation_not_left_undetected()
    print("[PASS] test_mid_stream_repetition_triggers_escalation_not_left_undetected")
    test_lazy_tool_doc_injected_on_first_real_call_only()
    print("[PASS] test_lazy_tool_doc_injected_on_first_real_call_only")
    test_read_tool_doc_marks_shown_so_first_real_call_does_not_duplicate()
    print("[PASS] test_read_tool_doc_marks_shown_so_first_real_call_does_not_duplicate")
    test_tool_without_registered_doc_has_no_injection_overhead()
    print("[PASS] test_tool_without_registered_doc_has_no_injection_overhead")
