"""
agent_core.py 的整合測試：用假的 OpenAI client（fake_llm.py）+ 假的工具函式，
完整跑過 Router -> Planner -> Decompose -> Think -> Verify -> Retry -> SMART 暫停 -> ask_user
這整條狀態機，完全不需要真的 LLM、不需要 pyautogui/PyQt6/webview。

執行方式：
    python tests/test_agent_core.py

注意：這個測試需要 `openai` 套件在你的 Python 環境裡（跟 main.py 用的是同一個依賴），
但完全不會真的打網路，因為 client 會被替換成 FakeOpenAIClient。
"""

import os
import sys
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_core import AgentWorker, AgentState  # noqa: E402
from task_system import ExecutionMode, TaskNode, TaskStatus  # noqa: E402
from fake_llm import FakeOpenAIClient, ECHO_REFLECT  # noqa: E402


def wait_until(predicate, timeout=2.0, interval=0.01, message="等待逾時"):
    start = time.time()
    while not predicate():
        if time.time() - start > timeout:
            raise AssertionError(message)
        time.sleep(interval)


def make_agent(scripts: dict, mode=ExecutionMode.SMART):
    events = []

    def on_event(event_type, data):
        events.append((event_type, data))

    tool_calls = []

    def run_action(cmd):
        tool_calls.append(cmd)
        return f"executed: {cmd}"

    agent = AgentWorker({"run_action": run_action}, event_callback=on_event, default_mode=mode)
    agent.client = FakeOpenAIClient(scripts)  # 換掉真的 client，之後所有呼叫都吃劇本
    return agent, events, tool_calls


# ----------------------------------------------------------------------
# 情境一：完整跑一次 Planning -> Decompose -> Think/Retry -> 父任務自動完成
#         -> SMART 模式在「需要確認」的任務前暫停 -> 使用者確認 -> 完成
# ----------------------------------------------------------------------

PLAN_DSL = """
- [ ] [TASK-1] 整理桌面資料夾
  - 方法: 用 run_action 依序建立分類資料夾並搬移檔案
  - 條件: 資料夾都已分類完成
  - 注意: 不要刪除任何檔案
  - 深度思考: NO
  - 需要拆解: YES
  - 需要確認: NO
  - 信心值: 0.5
- [ ] [TASK-2] 回報整理結果
  - 方法: 用 run_action 印出整理後的清單
  - 條件: 有印出檔案清單
  - 注意: 結果要包含檔案數量
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: YES
  - 信心值: 0.9
"""

DECOMPOSE_DSL = """
- [ ] [TASK-1] 建立分類資料夾
  - 方法: run_action("mkdir docs images")
  - 條件: 資料夾都存在
  - 注意: 已存在就略過
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: NO
  - 信心值: 0.9
- [ ] [TASK-2] 搬移檔案
  - 方法: run_action("move files")
  - 條件: 桌面上不再有零散檔案
  - 注意: 保留資料夾結構
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: NO
  - 信心值: 0.5
"""

THINK_RESPONSE_1 = (
    "分析: 信心值偏低，先確認搬移邏輯是否正確\n"
    "修正方法: run_action(\"move files carefully\")\n"
    "修正注意: 保留資料夾結構，搬移前先確認副檔名\n"
    "拆解: NO\n"
    "新信心值: 0.85\n"
)

THINK_RESPONSE_2 = (
    "分析: 上次失敗是因為條件判斷太嚴格，調整驗證方式\n"
    "修正方法: run_action(\"move files carefully, retry\")\n"
    "修正注意: 保留資料夾結構\n"
    "拆解: NO\n"
    "新信心值: 0.9\n"
)


def test_full_planning_scenario_with_decompose_and_smart_confirm():
    scripts = {
        "router": ["PLANNING"],
        "planner": [PLAN_DSL],
        "decompose": [DECOMPOSE_DSL],
        "thinking": [THINK_RESPONSE_1, THINK_RESPONSE_2],
        "system": [
            '<|tool_call|>call:run_action("mkdir docs images")<|tool_call|>',
            '<|tool_call|>call:run_action("move files")<|tool_call|>',
            '<|tool_call|>call:run_action("move files carefully, retry")<|tool_call|>',
            '<|tool_call|>call:run_action("print report")<|tool_call|>',
        ],
        "verify": [
            "STATUS: PASS\nREASON: 資料夾都已建立",
            "STATUS: FAIL\nREASON: 還有檔案沒搬移乾淨",
            "STATUS: PASS\nREASON: 檔案都搬移完成",
            "STATUS: PASS\nREASON: 報告已印出",
        ],
        "reflect": [ECHO_REFLECT, ECHO_REFLECT, ECHO_REFLECT],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.SMART)

    # --- 第一階段：Router -> Planner，產生初版任務樹，一定要先暫停等人審過 ---
    agent.set_user_prompt("整理桌面上的檔案並回報")
    agent.state = AgentState.IDLE
    agent.start()
    wait_until(lambda: not agent.is_running(), message="Planning 階段沒有在時限內結束")

    assert agent.state == AgentState.WAITING_CONFIRM
    assert any(e[0] == "ask_confirm" for e in events), "初版計畫一定要送出 ask_confirm，不受執行模式影響"

    # --- 使用者確認整個計畫，開始執行 ---
    agent.confirm_and_start()
    wait_until(lambda: not agent.is_running(), timeout=3.0,
               message="第一批任務（含拆解、重試）沒有在時限內跑完")

    # TASK-1 應該已經因為兩個子任務都完成而自動標記完成
    task1 = next(t for t in agent.engine.tasks if t.id == "TASK-1")
    assert task1.status == TaskStatus.DECOMPOSED or task1.status == TaskStatus.COMPLETED
    assert task1.status == TaskStatus.COMPLETED, "兩個子任務都完成後，父任務應該自動標記完成"
    assert "TASK-1.1" in task1.result and "TASK-1.2" in task1.result

    child2 = next(t for t in agent.engine.tasks if t.id == "TASK-1.2")
    assert child2.retry_count == 0, "驗證通過後 retry_count 應該被重置"
    assert child2.think_count == 0

    # SMART 模式下，TASK-2 標了「需要確認: YES」，應該在執行它之前暫停
    assert agent.state == AgentState.WAITING_CONFIRM
    task2 = next(t for t in agent.engine.tasks if t.id == "TASK-2")
    assert task2.status == TaskStatus.PENDING, "TASK-2 應該還沒被執行，正在等待確認"

    # --- 使用者確認最後一步 ---
    agent.confirm_and_start()
    wait_until(lambda: not agent.is_running(), message="最後一步沒有在時限內完成")

    assert agent.state == AgentState.IDLE
    assert any(e[0] == "finished" for e in events)
    task2 = next(t for t in agent.engine.tasks if t.id == "TASK-2")
    assert task2.status == TaskStatus.COMPLETED

    assert len(tool_calls) == 4, f"應該總共呼叫了 4 次工具，實際: {tool_calls}"
    print("[PASS] test_full_planning_scenario_with_decompose_and_smart_confirm")


# ----------------------------------------------------------------------
# 情境二：同一個任務連續驗證失敗超過上限 -> 觸發 ask_user -> 使用者回覆後繼續 -> 成功
# ----------------------------------------------------------------------

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

    # 跳過 Planning，直接塞一個會一直失敗的任務進去，專心測 retry/ask_user 這條路徑
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

    # 等到 agent 卡在 ask_user 的阻塞迴圈裡
    wait_until(lambda: agent.is_paused_for_input, timeout=3.0,
               message="重試 4 次後應該要觸發 ask_user，但沒有等到")
    assert any(e[0] == "waiting_input" for e in events)
    waiting_question = next(d for t, d in events if t == "waiting_input")
    assert "反覆失敗的任務" in waiting_question
    assert task.retry_count == 4, "應該是第 4 次失敗才觸發 ask_user（retry_count 要等回覆後才會被重置）"

    # 模擬使用者回覆
    agent.resume_with_user_input("先忽略這個錯誤，放寬條件重新嘗試一次")

    wait_until(lambda: not agent.is_running(), timeout=3.0,
               message="使用者回覆後，任務沒有在時限內完成")

    assert task.status == TaskStatus.COMPLETED
    assert "使用者指示" in task.note
    assert any(e[0] == "finished" for e in events)
    assert len(tool_calls) == 5, f"應該總共嘗試了 5 次，實際: {tool_calls}"
    print("[PASS] test_ask_user_triggered_after_max_retries")


if __name__ == "__main__":
    tests = [
        test_full_planning_scenario_with_decompose_and_smart_confirm,
        test_ask_user_triggered_after_max_retries,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
