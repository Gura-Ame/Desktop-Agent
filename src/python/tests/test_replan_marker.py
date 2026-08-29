"""
針對「邊做邊發現新資訊，中途觸發重新規劃」（<|replan|> 標記）的測試。

涵蓋：
1. 執行階段（_call_and_execute 的輸出）裡出現標記，應該暫停驗證、觸發 Reflect、
   把任務重置回 PENDING，交還給最外層 EXECUTING 迴圈重新撿起來執行。
2. 思考階段（thinking 的輸出）裡出現標記，一樣要能觸發，而不是只有執行階段才認得。
3. 一般情況下（沒有出現標記）完全不受影響，行為跟原本一樣。
4. Reflect 被觸發時，prompt 措辭要如實反映「任務還沒做完」，不能講成「已經完成」。
"""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.agent_core import AgentState
from agent.task_system import TaskNode, TaskStatus, ExecutionMode
from fake_llm import ECHO_REFLECT
from test_agent_core_helpers import make_agent, wait_until


def test_replan_marker_in_execute_stage_defers_verify_and_resumes_after_reflect():
    scripts = {
        "system": [
            "<|replan|>發現原本的假設整個方向錯了，需要重新規劃",
            '<|tool_call|>run_action("redo with new plan")<|tool_call|>',
        ],
        "reflect": [ECHO_REFLECT, ECHO_REFLECT],
        "verify": ["STATUS: PASS\nREASON: 重新規劃後成功"],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)

    task = TaskNode("TASK-1", "原本方向有誤的任務")
    task.method = "原本的方法"
    task.condition = "完成"
    task.note = "無"
    task.need_thinking = False
    task.need_confirm = False
    task.confidence = 0.9  # 夠高，不觸發思考階段，直接進執行階段
    agent.engine.tasks = [task]
    agent.state = AgentState.EXECUTING
    agent.start()

    wait_until(lambda: not agent.is_running(), timeout=3.0, message="沒有在時限內完成")

    logs = [d for t, d in events if t == "log"]
    assert any("執行到一半發現新資訊" in str(l) for l in logs), \
        f"應該要有觸發中途重新規劃的訊息，實際 logs: {logs}"
    # 第一次的 <|replan|> 那次生成不該被送去 verify（那不是一個可驗證的執行結果）
    assert agent.client.call_log.count("verify") == 1, \
        f"觸發 replan 那一輪不該呼叫 verify，實際呼叫記錄: {agent.client.call_log}"
    assert agent.client.call_log.count("system") == 2, "應該重試了一次，總共呼叫兩次執行階段"
    assert agent.client.call_log.count("reflect") == 2, \
        "一次是中途觸發的 Reflect，一次是任務最終完成後的正常 Reflect"
    # 注意：apply_reflected_dsl 會用新解析出來的 TaskNode 取代原本這個 id 的物件，
    # 所以要重新從 engine.tasks 撈一次目前的物件，不能繼續檢查一開始那個舊的 task 參照。
    final_task = next(t for t in agent.engine.tasks if t.id == "TASK-1")
    assert final_task.status == TaskStatus.COMPLETED
    assert final_task.result == '[run_action]: executed: redo with new plan'
    print("[PASS] test_replan_marker_in_execute_stage_defers_verify_and_resumes_after_reflect")


def test_replan_marker_in_thinking_stage_also_triggers():
    scripts = {
        "thinking": [
            "分析: 發現原本假設整個錯了<|replan|>方法的大方向錯了，需要重新規劃\n"
            "修正方法: 待重新規劃\n修正注意: 無\n拆解: NO\n新信心值: 0.3\n",
            "分析: 重新想過，這樣做應該可以了\n修正方法: v2\n修正注意: 無\n拆解: NO\n新信心值: 0.8\n",
        ],
        "reflect": [ECHO_REFLECT, ECHO_REFLECT],
        "system": ['<|tool_call|>run_action("redo")<|tool_call|>'],
        "verify": ["STATUS: PASS\nREASON: ok"],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)

    task = TaskNode("TASK-1", "思考中發現方向錯誤的任務")
    task.method = "原本的方法"
    task.condition = "完成"
    task.note = "無"
    task.need_thinking = False
    task.need_confirm = False
    task.confidence = 0.4  # < 0.6，會先進思考階段
    agent.engine.tasks = [task]
    agent.state = AgentState.EXECUTING
    agent.start()

    wait_until(lambda: not agent.is_running(), timeout=3.0, message="沒有在時限內完成")

    logs = [d for t, d in events if t == "log"]
    assert any("執行到一半發現新資訊" in str(l) for l in logs)
    # 第一次思考觸發 replan 後不該真的往下跑到執行階段
    assert agent.client.call_log.count("thinking") == 2
    assert agent.client.call_log.count("system") == 1, \
        "第一次思考就觸發 replan、被打斷重來，不該對第一次思考的結果做任何執行嘗試"
    final_task = next(t for t in agent.engine.tasks if t.id == "TASK-1")
    assert final_task.status == TaskStatus.COMPLETED
    print("[PASS] test_replan_marker_in_thinking_stage_also_triggers")


def test_no_replan_marker_behaves_exactly_as_before():
    """完全沒有出現標記的一般情況，行為應該跟原本一模一樣（一次執行、一次驗證、一次 reflect）。"""
    scripts = {
        "system": ['<|tool_call|>run_action("normal task")<|tool_call|>'],
        "verify": ["STATUS: PASS\nREASON: ok"],
        "reflect": [ECHO_REFLECT],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)

    task = TaskNode("TASK-1", "普通任務")
    task.method = "普通方法"
    task.condition = "完成"
    task.note = "無"
    task.need_thinking = False
    task.need_confirm = False
    task.confidence = 0.9
    agent.engine.tasks = [task]
    agent.state = AgentState.EXECUTING
    agent.start()

    wait_until(lambda: not agent.is_running(), timeout=3.0, message="沒有在時限內完成")

    logs = [d for t, d in events if t == "log"]
    assert not any("執行到一半發現新資訊" in str(l) for l in logs)
    assert agent.client.call_log == ["system", "verify", "reflect"]
    assert task.status == TaskStatus.COMPLETED
    print("[PASS] test_no_replan_marker_behaves_exactly_as_before")


def test_reflect_prompt_says_in_progress_not_completed():
    """直接檢查 _reflect(in_progress=True) 組出來的 prompt 措辭，
    確保不會誤導模型以為這個任務已經做完了（這是這個功能最容易出錯、也最重要的地方：
    如果措辭沒改，模型可能會把還沒驗證過的內容當成「確定結果」寫進任務樹）。
    """
    captured = {}

    scripts = {"reflect": [ECHO_REFLECT]}
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)

    original_call_llm = agent._call_llm

    def spy(system_prompt, user_prompt, *a, **kw):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return original_call_llm(system_prompt, user_prompt, *a, **kw)

    agent._call_llm = spy

    task = TaskNode("TASK-1", "測試措辭的任務")
    task.method = "方法"
    task.condition = "條件"
    task.note = "無"
    agent.engine.tasks = [task]

    agent._reflect(task, "目前為止得到的部分內容", in_progress=True, reason="發現假設錯誤")

    assert "還沒執行完成" in captured["user_prompt"]
    assert "不要把它標記為 [x]" in captured["user_prompt"]
    assert "剛完成任務" not in captured["user_prompt"], \
        "in_progress=True 時絕對不能用『剛完成』這種會誤導模型的措辭"
    print("[PASS] test_reflect_prompt_says_in_progress_not_completed")


if __name__ == "__main__":
    test_replan_marker_in_execute_stage_defers_verify_and_resumes_after_reflect()
    test_replan_marker_in_thinking_stage_also_triggers()
    test_no_replan_marker_behaves_exactly_as_before()
    test_reflect_prompt_says_in_progress_not_completed()
