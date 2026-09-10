"""
驗證輕量思考步驟（agent/agent_thinking.py）真的接進 Direct Mode 跟
Planner 的實際流程裡，不是只有單元測試層級測到 generate_prethink 本身。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.task_system import ExecutionMode
from test_agent_core_helpers import make_agent, send_turn, ESCALATE_RESPONSE, PLAN_DSL


def test_direct_mode_calls_prethink_before_main_reply_when_enabled():
    scripts = {
        "prethink": ["使用者只是打招呼，不需要用到任何工具，直接回覆就好。"],
        "system": ["<|direct|>\n你好！有什麼我可以幫忙的嗎？"],
        "value_judgment": ["NONE"],  # 每輪 Direct Mode 結束後都會自動跑一次記憶價值判斷
    }
    agent, events, tool_calls = make_agent(scripts)
    agent.set_thinking_enabled(True)

    send_turn(agent, "你好")

    assert agent.client.call_log == ["prethink", "system", "value_judgment"]
    assert any(e[0] == "log" and "內部思考" in str(e[1]) for e in events)
    print("[PASS] test_direct_mode_calls_prethink_before_main_reply_when_enabled")


def test_direct_mode_skips_prethink_when_disabled():
    scripts = {"system": ["<|direct|>\n你好！"], "value_judgment": ["NONE"]}
    agent, events, tool_calls = make_agent(scripts)
    # 預設就是關閉的，這裡刻意不呼叫 set_thinking_enabled，確認完全不影響呼叫序列。

    send_turn(agent, "你好")

    assert agent.client.call_log == ["system", "value_judgment"]
    print("[PASS] test_direct_mode_skips_prethink_when_disabled")


def test_planner_calls_prethink_before_planning_when_enabled():
    scripts = {
        "prethink": [
            "使用者要整理桌面檔案，這是個多步驟任務，需要規劃。",
            "應該先建立分類資料夾，再依副檔名搬移檔案，不需要過度拆解。",
        ],
        "system": [ESCALATE_RESPONSE],
        "planner": [PLAN_DSL],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.set_thinking_enabled(True)

    send_turn(agent, "幫我整理桌面資料夾")

    assert agent.client.call_log == ["prethink", "system", "prethink", "planner"]
    assert any(e[0] == "log" and "規劃前的思考" in str(e[1]) for e in events)
    print("[PASS] test_planner_calls_prethink_before_planning_when_enabled")


if __name__ == "__main__":
    tests = [
        test_direct_mode_calls_prethink_before_main_reply_when_enabled,
        test_direct_mode_skips_prethink_when_disabled,
        test_planner_calls_prethink_before_planning_when_enabled,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
