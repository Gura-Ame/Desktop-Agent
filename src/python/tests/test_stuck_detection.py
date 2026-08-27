"""
針對「卡住偵測」升級的測試：think_count 到達上限時，不再無腦直接 ask_user，
而是先判斷信心值趨勢（還在進步就延長預算），真的停滯才依序試 replan → expand_memory，
都試過仍卡住才 ask_user。
"""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.agent_core import AgentState
from agent.agent_execution_cycle import AgentExecutionMixin
from agent.task_system import TaskNode, TaskStatus, ExecutionMode
from fake_llm import ECHO_REFLECT
from test_agent_core_helpers import make_agent, wait_until, DECOMPOSE_DSL


# ----------------------------------------------------------------------
# 1. 純邏輯單元測試：_diagnose_stuck_action 本身的判斷是否正確
# ----------------------------------------------------------------------

class _FakeAgent(AgentExecutionMixin):
    pass


def _task_with_history(history, escalation_level=0):
    t = TaskNode("TASK-1", "測試任務")
    t.confidence_history = list(history)
    t.confidence = history[-1] if history else 1.0
    t.stuck_escalation_level = escalation_level
    return t


def test_diagnose_extend_when_confidence_improving():
    task = _task_with_history([0.2, 0.3, 0.45, 0.55])  # 持續上升
    assert _FakeAgent()._diagnose_stuck_action(task) == "extend"


def test_diagnose_replan_when_flat_and_level_zero():
    task = _task_with_history([0.4, 0.4, 0.4], escalation_level=0)
    assert _FakeAgent()._diagnose_stuck_action(task) == "replan"


def test_diagnose_replan_when_declining():
    task = _task_with_history([0.6, 0.5, 0.4], escalation_level=0)  # 越想越沒信心
    assert _FakeAgent()._diagnose_stuck_action(task) == "replan"


def test_diagnose_expand_memory_after_replan_already_tried():
    task = _task_with_history([0.4, 0.4], escalation_level=1)
    assert _FakeAgent()._diagnose_stuck_action(task) == "expand_memory"


def test_diagnose_ask_user_as_last_resort():
    task = _task_with_history([0.4, 0.4], escalation_level=2)
    assert _FakeAgent()._diagnose_stuck_action(task) == "ask_user"
    # 就算 escalation_level 超過階梯長度，也不該 IndexError，一律視為已經到底了
    task2 = _task_with_history([0.4, 0.4], escalation_level=99)
    assert _FakeAgent()._diagnose_stuck_action(task2) == "ask_user"


def test_diagnose_no_history_defaults_to_ladder_not_extend():
    # 全新任務、還沒真的思考過（history 太短），不該被誤判成「正在進步」而放行
    task = _task_with_history([], escalation_level=0)
    assert _FakeAgent()._diagnose_stuck_action(task) == "replan"


# ----------------------------------------------------------------------
# 2. 端對端：信心值持續上升時，不該打擾使用者，應該自動延長思考預算
#
# 為了真的走到「think_count 到達上限」這個分岐，前面必須先讓執行驗證失敗個幾次
# （每次驗證失敗都會讓 needs_think 在下一輪重新成立，回到思考階段），
# 這跟系統實際運作的方式一致：think_count 只有在「思考→嘗試執行→驗證失敗」
# 反覆循環時才會累積，不是連續思考很多次才去執行一次。
#
# 信心值刻意都停在 <= 0.4：因為每次驗證失敗都會把信心值鉗制到
# min(目前信心值, 0.4)，如果思考時設得比 0.4 高，會在驗證失敗那一刻被打回 0.4，
# 反而看起來像沒有進步。只要維持在 <= 0.4 這個鉗制就不會生效，可以乾淨地驗證「趨勢上升」。
# ----------------------------------------------------------------------

def test_extend_path_does_not_ask_user_and_eventually_succeeds():
    scripts = {
        "thinking": [
            "分析: 第一次嘗試\n修正方法: v1\n修正注意: 無\n拆解: NO\n新信心值: 0.1\n",
            "分析: 有點進展\n修正方法: v2\n修正注意: 無\n拆解: NO\n新信心值: 0.2\n",
            "分析: 持續進步\n修正方法: v3\n修正注意: 無\n拆解: NO\n新信心值: 0.3\n",
            "分析: 這次應該可以了\n修正方法: v4\n修正注意: 無\n拆解: NO\n新信心值: 0.5\n",
        ],
        "system": [
            '<|tool_call|>call:run_action("attempt 1")<|tool_call|>',
            '<|tool_call|>call:run_action("attempt 2")<|tool_call|>',
            '<|tool_call|>call:run_action("attempt 3")<|tool_call|>',
            '<|tool_call|>call:run_action("attempt 4")<|tool_call|>',
        ],
        "verify": [
            "STATUS: FAIL\nREASON: 還沒到位 1",
            "STATUS: FAIL\nREASON: 還沒到位 2",
            "STATUS: FAIL\nREASON: 還沒到位 3",
            "STATUS: PASS\nREASON: 這次通過了",
        ],
        "reflect": [ECHO_REFLECT],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)

    task = TaskNode("TASK-1", "信心值持續上升的任務")
    task.method = "逐步嘗試"
    task.condition = "完成"
    task.note = "無"
    task.need_thinking = False  # 純靠信心值 < 0.6 驅動 needs_think，不用旗標卡死
    task.need_confirm = False
    task.confidence = 0.3
    agent.engine.tasks = [task]
    agent.state = AgentState.EXECUTING
    agent.start()

    wait_until(lambda: not agent.is_running(), timeout=3.0, message="沒有在時限內完成")

    assert not any(e[0] == "waiting_input" for e in events), "信心值一直在進步，不應該打擾使用者"
    assert any("多給 2 次思考機會" in str(d) for _, d in events if _ == "log"), \
        "應該要有偵測到進步、延長預算的訊息"
    assert not any("先嘗試拆解重新規劃" in str(d) for _, d in events if _ == "log"), \
        "信心值一直在進步，不該誤觸發 replan"
    assert task.status == TaskStatus.COMPLETED
    assert task.stuck_escalation_level == 0
    print("[PASS] test_extend_path_does_not_ask_user_and_eventually_succeeds")


# ----------------------------------------------------------------------
# 3. 端對端：信心值停滯不前，先試拆解重新規劃，拆解成功就直接執行子任務，不問使用者
# ----------------------------------------------------------------------

def test_replan_path_succeeds_without_asking_user():
    scripts = {
        "thinking": [
            "分析: 卡住了\n修正方法: v1\n修正注意: 無\n拆解: NO\n新信心值: 0.4\n",
            "分析: 還是卡住\n修正方法: v2\n修正注意: 無\n拆解: NO\n新信心值: 0.4\n",
            "分析: 依然卡住\n修正方法: v3\n修正注意: 無\n拆解: NO\n新信心值: 0.4\n",
            # 拆解後的第二個子任務（DECOMPOSE_DSL 裡信心值 0.5 < 0.6）也會需要思考一次
            "分析: 子任務信心值偏低，正常執行前思考\n修正方法: 搬移檔案\n修正注意: 無\n拆解: NO\n新信心值: 0.8\n",
        ],
        "decompose": [DECOMPOSE_DSL],
        "system": [
            '<|tool_call|>call:run_action("attempt 1")<|tool_call|>',
            '<|tool_call|>call:run_action("attempt 2")<|tool_call|>',
            '<|tool_call|>call:run_action("attempt 3")<|tool_call|>',
            "done step 1",
            "done step 2",
        ],
        "verify": [
            "STATUS: FAIL\nREASON: 還是不行 1",
            "STATUS: FAIL\nREASON: 還是不行 2",
            "STATUS: FAIL\nREASON: 還是不行 3",
            "STATUS: PASS\nREASON: ok",
            "STATUS: PASS\nREASON: ok",
        ],
        "reflect": [ECHO_REFLECT, ECHO_REFLECT],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)

    task = TaskNode("TASK-1", "信心值停滯不前的任務")
    task.method = "原本的方法"
    task.condition = "完成"
    task.note = "無"
    task.need_thinking = False
    task.need_confirm = False
    task.confidence = 0.4
    agent.engine.tasks = [task]
    agent.state = AgentState.EXECUTING
    agent.start()

    wait_until(lambda: not agent.is_running(), timeout=3.0, message="沒有在時限內完成")

    assert not any(e[0] == "waiting_input" for e in events), "應該靠拆解解決，不需要打擾使用者"
    assert any("先嘗試拆解重新規劃" in str(d) for _, d in events if _ == "log")
    assert task.stuck_escalation_level == 1
    children = [t for t in agent.engine.tasks if t.parent_id == "TASK-1"]
    assert len(children) == 2
    assert all(c.status == TaskStatus.COMPLETED for c in children)
    # 子任務都完成後，父任務會被 check_and_complete_parent 自動標記完成並填入摘要
    assert task.status == TaskStatus.COMPLETED
    assert task.result
    print("[PASS] test_replan_path_succeeds_without_asking_user")


# ----------------------------------------------------------------------
# 4. 端對端：拆解失敗後，思考卡住升級（stuck_escalation_level）跟驗證重試次數
#    (retry_count) 兩條獨立的卡住偵測會一起運作，最終仍收斂到 ask_user，
#    而且使用者回覆後，所有卡住狀態都要乾淨重置，不能汙染下一次。
# ----------------------------------------------------------------------

def test_ladder_falls_through_to_ask_user_then_resets_state():
    scripts = {
        "thinking": [
            "分析: 卡住1\n修正方法: v1\n修正注意: 無\n拆解: NO\n新信心值: 0.3\n",
            "分析: 卡住2\n修正方法: v2\n修正注意: 無\n拆解: NO\n新信心值: 0.3\n",
            "分析: 卡住3\n修正方法: v3\n修正注意: 無\n拆解: NO\n新信心值: 0.3\n",
            "分析: 卡住4\n修正方法: v4\n修正注意: 無\n拆解: NO\n新信心值: 0.3\n",
            # ask_user 的回覆不會自動把信心值拉高（跟思考卡住那條路徑的 ask_user 不同），
            # 所以使用者提供指示後，還是會先思考一次該怎麼運用這個新資訊，這是合理的行為。
            "分析: 使用者給了新指示，照著做\n修正方法: after user hint\n修正注意: 無\n拆解: NO\n新信心值: 0.8\n",
        ],
        # DECOMPOSE_SYSTEM_PROMPT 的重試機制（_call_dsl_with_repair）預設會重試一次，
        # 所以要準備兩份都解析不了的散文，才會讓拆解真的徹底失敗。
        "decompose": [
            "這是一段完全不照格式輸出的散文，拆解會失敗",
            "重試後依然是散文，還是失敗",
        ],
        "system": [
            '<|tool_call|>call:run_action("attempt 1")<|tool_call|>',
            '<|tool_call|>call:run_action("attempt 2")<|tool_call|>',
            '<|tool_call|>call:run_action("attempt 3")<|tool_call|>',
            '<|tool_call|>call:run_action("attempt 4")<|tool_call|>',
            '<|tool_call|>call:run_action("after user hint")<|tool_call|>',
        ],
        "verify": [
            "STATUS: FAIL\nREASON: 還是不行 1",
            "STATUS: FAIL\nREASON: 還是不行 2",
            "STATUS: FAIL\nREASON: 還是不行 3",
            "STATUS: FAIL\nREASON: 還是不行 4",
            "STATUS: PASS\nREASON: 使用者指點後成功",
        ],
        "reflect": [ECHO_REFLECT],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)

    task = TaskNode("TASK-1", "怎麼想都想不通的任務")
    task.method = "原本的方法"
    task.condition = "完成"
    task.note = "無"
    task.need_thinking = False
    task.need_confirm = False
    task.confidence = 0.3
    agent.engine.tasks = [task]
    agent.state = AgentState.EXECUTING
    agent.start()

    wait_until(lambda: agent.is_paused_for_input, timeout=3.0,
               message="拆解失敗、重試次數用盡後，最終應該觸發 ask_user")

    logs = [d for t, d in events if t == "log"]
    assert any("先嘗試拆解重新規劃" in str(l) for l in logs)
    assert any("拆解沒有成功" in str(l) for l in logs)
    assert task.stuck_escalation_level == 1, "思考卡住的升級階段應該停在『已試過拆解』"

    agent.resume_with_user_input("這樣試試看")
    wait_until(lambda: not agent.is_running(), timeout=3.0, message="使用者回覆後沒有在時限內完成")

    assert task.status == TaskStatus.COMPLETED
    # 卡住狀態要在使用者介入後乾淨重置，不能把舊的升級階段/信心值歷史帶進下一次
    # （注：note 內容後續思考步驟合理地覆寫掉了使用者指示的原始文字，這是預期行為，
    # 重點是流程真的走完並收斂到完成，而不是卡在原地或狀態污染到下一輪）
    assert task.stuck_escalation_level == 0
    assert task.think_limit_override is None
    assert task.confidence_history == [task.confidence]
    print("[PASS] test_ladder_falls_through_to_ask_user_then_resets_state")


if __name__ == "__main__":
    test_diagnose_extend_when_confidence_improving()
    print("[PASS] test_diagnose_extend_when_confidence_improving")
    test_diagnose_replan_when_flat_and_level_zero()
    print("[PASS] test_diagnose_replan_when_flat_and_level_zero")
    test_diagnose_replan_when_declining()
    print("[PASS] test_diagnose_replan_when_declining")
    test_diagnose_expand_memory_after_replan_already_tried()
    print("[PASS] test_diagnose_expand_memory_after_replan_already_tried")
    test_diagnose_ask_user_as_last_resort()
    print("[PASS] test_diagnose_ask_user_as_last_resort")
    test_diagnose_no_history_defaults_to_ladder_not_extend()
    print("[PASS] test_diagnose_no_history_defaults_to_ladder_not_extend")
    test_extend_path_does_not_ask_user_and_eventually_succeeds()
    test_replan_path_succeeds_without_asking_user()
    test_ladder_falls_through_to_ask_user_then_resets_state()
