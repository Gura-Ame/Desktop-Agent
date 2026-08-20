"""
agent_core.py 的整合測試：用假的 OpenAI client（fake_llm.py）+ 假的工具函式，
完整跑過「推理後自行判斷要不要切換到規劃模式」-> Planner -> Decompose -> Think -> Verify
-> Retry -> SMART 暫停 -> ask_user 這整條狀態機，完全不需要真的 LLM、不需要 pyautogui/PyQt6/webview。

執行方式：
    python test_agent_core.py

注意：這個測試需要 `openai` 套件在你的 Python 環境裡（跟 main.py 用的是同一個依賴），
但完全不會真的打網路，因為 client 會被替換成 FakeOpenAIClient。
"""

import os
import sys
import time
import threading
import tempfile

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

    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)  # 讓 AgentWorker 自己建立全新的檔案，不要讀到其他測試留下的殘留資料
    agent = AgentWorker({"run_action": run_action}, event_callback=on_event, default_mode=mode,
                         memory_path=memory_path)
    agent.client = FakeOpenAIClient(scripts)  # 換掉真的 client，之後所有呼叫都吃劇本
    return agent, events, tool_calls


def send_turn(agent, prompt):
    """模擬使用者送出一則新訊息（例如按下 continue），等到這輪跑完為止。"""
    agent.set_user_prompt(prompt)
    agent.state = AgentState.IDLE
    agent.start()
    wait_until(lambda: not agent.is_running(), message=f"「{prompt}」這輪沒有在時限內完成")


# ----------------------------------------------------------------------
# 情境一：第一輪推理判斷「這個任務太複雜」-> 切換到 Planning -> Decompose
#         -> Think/Retry -> 父任務自動完成 -> SMART 模式在「需要確認」的任務前暫停
#         -> 使用者確認 -> 完成
# ----------------------------------------------------------------------

ESCALATE_RESPONSE = "<|plan|>需要拆解成多個步驟並逐一驗證是否完成"

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


def test_reasoning_escalates_to_planning_with_decompose_and_smart_confirm():
    scripts = {
        "system": [
            ESCALATE_RESPONSE,  # 第一輪推理：判斷太複雜，切換到規劃模式
            '<|tool_call|>call:run_action("mkdir docs images")<|tool_call|>',
            '<|tool_call|>call:run_action("move files")<|tool_call|>',
            '<|tool_call|>call:run_action("move files carefully, retry")<|tool_call|>',
            '<|tool_call|>call:run_action("print report")<|tool_call|>',
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

    # --- 第一階段：推理後自行判斷要切換到 Planning，產生初版任務樹，一定要先暫停等人審過 ---
    agent.set_user_prompt("整理桌面上的檔案並回報")
    agent.state = AgentState.IDLE
    agent.start()
    wait_until(lambda: not agent.is_running(), message="推理 + Planning 階段沒有在時限內結束")

    assert agent.state == AgentState.WAITING_CONFIRM
    assert any(e[0] == "ask_confirm" for e in events), "初版計畫一定要送出 ask_confirm，不受執行模式影響"
    # 推理過程本身有先串流給使用者看過（不是悄悄切換），且不該汙染對話歷史
    chunk_texts = "".join(str(d) for t, d in events if t == "chunk")
    assert "需要拆解成多個步驟" in chunk_texts, "切換前的推理內容應該有串流顯示給使用者看"
    assert agent.history == [], "切換到 Planning 模式時，推理草稿不應該留在對話歷史裡"

    # --- 使用者確認整個計畫，開始執行 ---
    agent.confirm_and_start()
    wait_until(lambda: not agent.is_running(), timeout=3.0,
               message="第一批任務（含拆解、重試）沒有在時限內跑完")

    # TASK-1 應該已經因為兩個子任務都完成而自動標記完成
    task1 = next(t for t in agent.engine.tasks if t.id == "TASK-1")
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
    print("[PASS] test_reasoning_escalates_to_planning_with_decompose_and_smart_confirm")


# ----------------------------------------------------------------------
# 情境一之二：推理後判斷「這個不難」-> 不切換，直接沿用第一輪的輸出繼續走對話/工具迴圈，
#            不應該為了同一輪內容再多打一次模型
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# 情境一之三：模型沒有講出 <|plan|>，也沒呼叫任何工具，就這樣被 max_tokens 截斷——
#            這種「寫了一堆卻沒有收斂」的行為本身就要被系統當成需要規劃的證據，
#            不能像 UI 上的 continue 按鈕一樣讓它接著同樣沒方向的內容繼續寫。
# ----------------------------------------------------------------------

def test_repeating_without_progress_auto_escalates_to_planning():
    # 兩輪的回答幾乎一模一樣（模擬使用者連續按 continue，但模型只是換句話說重講一次）
    verbose_reply = (
        "這個問題需要證明 (a^2+b^2)/(ab+1) 是完全平方數。讓我們考慮 a 和 b 滿足條件，"
        "首先我們可以嘗試代入具體數值來觀察規律，然後用代數變換來簡化這個表達式，"
        "考慮到 ab+1 整除 a^2+b^2，我們可以進一步分析這個關係式的性質。"
    )
    scripts = {
        "system": [verbose_reply, verbose_reply],  # 第二輪跟第一輪幾乎一樣
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

    # 第一輪：正常回答，不該觸發任何切換
    send_turn(agent, "幫我證明這個數論題")
    assert agent.state == AgentState.IDLE
    assert not any(e[0] == "ask_confirm" for e in events)

    # 第二輪：跟第一輪高度重複，應該被判定為原地打轉
    send_turn(agent, "continue")

    assert agent.state == AgentState.WAITING_CONFIRM
    assert any(e[0] == "ask_confirm" for e in events)
    assert any("原地打轉" in str(d) for t, d in events if t == "log")
    print("[PASS] test_repeating_without_progress_auto_escalates_to_planning")


def test_short_similar_replies_not_falsely_flagged():
    """太短的內容本來就容易剛好長得像（例如簡短的招呼語），不該被誤判成原地打轉。"""
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
        # 特意不包含 <|plan|>、也不包含 <|tool_call|>，模擬模型只顧著往下寫、忘了做難度判斷
    )
    scripts = {
        "system": [(rambling_no_conclusion, "length")],  # finish_reason="length" 代表被截斷
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
    """就算被截斷，只要這輪確實呼叫了工具，就不當成「沒收斂」，正常走對話模式繼續處理。"""
    scripts = {
        "system": [
            ('<|tool_call|>call:run_action("do something long")<|tool_call|>\n後面接了很長的說明文字...', "length"),
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


def test_reasoning_does_not_escalate_reuses_first_call():
    scripts = {
        "system": [
            '簡單問題，直接查詢時間就好。\n<|tool_call|>call:run_action("get_time")<|tool_call|>',
            "現在是下午三點。",
        ],
        # 視窗大小是 2，工具呼叫這輪中途 history 會累積到 3 則（user/assistant/tool結果），
        # 超過視窗，中間會觸發一次壓縮，才能繼續打第二次 system 呼叫拿到最終回覆。
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
    # 只應該打了 2 次「system」類別的模型呼叫（第一輪推理 + 看完工具結果後的回覆），
    # 第一輪不應該因為「推理」跟「直接回答」被算成兩次呼叫；中間的壓縮呼叫算在 compress 類別，不算 system。
    system_calls = [c for c in agent.client.call_log if c == "system"]
    assert len(system_calls) == 2, f"應該恰好 2 次，實際: {agent.client.call_log}"
    assert any(c == "compress" for c in agent.client.call_log), "視窗大小是 2，這輪中途應該要觸發過一次壓縮"
    print("[PASS] test_reasoning_does_not_escalate_reuses_first_call")


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
        test_reasoning_escalates_to_planning_with_decompose_and_smart_confirm,
        test_truncated_without_conclusion_auto_escalates_to_planning,
        test_truncated_but_has_tool_call_does_not_force_escalate,
        test_repeating_without_progress_auto_escalates_to_planning,
        test_short_similar_replies_not_falsely_flagged,
        test_reasoning_does_not_escalate_reuses_first_call,
        test_ask_user_triggered_after_max_retries,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
