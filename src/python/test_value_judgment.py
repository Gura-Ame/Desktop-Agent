"""
測試 direct mode 每一輪對話結束後的「價值判斷」：不靠 history 有沒有超過視窗大小觸發，
每一輪都主動問一次「這個值不值得記」，模型判斷值得就寫進硬記憶。

執行方式：
    python test_value_judgment.py
"""

import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from agent_core import AgentWorker, AgentState  # noqa: E402
from task_system import ExecutionMode  # noqa: E402
from fake_llm import FakeOpenAIClient  # noqa: E402
from memory_store import MemoryStore  # noqa: E402


def wait_until(predicate, timeout=2.0, interval=0.01, message="等待逾時"):
    start = time.time()
    while not predicate():
        if time.time() - start > timeout:
            raise AssertionError(message)
        time.sleep(interval)


def send_turn(agent, prompt):
    agent.set_user_prompt(prompt)
    agent.state = AgentState.IDLE
    agent.start()
    wait_until(lambda: not agent.is_running(), message=f"「{prompt}」這輪沒有在時限內完成")


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


def make_agent(memory_path, scripts):
    agent = AgentWorker({}, event_callback=lambda t, d: None,
                         default_mode=ExecutionMode.AUTO, memory_path=memory_path)
    agent.client = FakeOpenAIClient(scripts)
    return agent


@with_temp_memory
def test_judged_valuable_gets_remembered_even_though_history_never_overflows(memory_path):
    """核心行為：對話只有 1 輪、history 遠遠沒超過視窗大小（HYBRID_WINDOW_MESSAGES=6），
    但只要模型判斷這輪值得記，還是要被存下來——不是靠視窗滿不滿觸發。"""
    scripts = {
        "system": ["好的，我記下了，你偏好用簡潔的條列式回答。"],
        "value_judgment": [
            "- id: pref_bullet_style\n- type: Preference\n- summary: 使用者偏好簡潔的條列式回答\n"
        ],
    }
    agent = make_agent(memory_path, scripts)
    send_turn(agent, "以後回答都用條列式，簡潔一點")

    assert len(agent.history) == 2, "只有 1 輪，遠遠沒超過視窗大小"
    node = agent.memory_store.get_node("pref_bullet_style")
    assert node is not None, "即使 history 沒超過視窗，值得記的東西還是該被存下來"
    assert node.type == "Preference"
    print("[PASS] test_judged_valuable_gets_remembered_even_though_history_never_overflows")


@with_temp_memory
def test_judged_not_valuable_writes_nothing(memory_path):
    scripts = {
        "system": ["現在下午三點。"],
        "value_judgment": ["NONE"],
    }
    agent = make_agent(memory_path, scripts)
    send_turn(agent, "現在幾點？")

    fact_nodes = [n for n in agent.memory_store.nodes.values() if n.id != "_conversation_history"]
    assert fact_nodes == [], "單純的寒暄/臨時問題不該被記下來"
    print("[PASS] test_judged_not_valuable_writes_nothing")


@with_temp_memory
def test_value_judgment_call_failure_does_not_break_the_turn(memory_path):
    """劇本沒準備 value_judgment 的回應，模擬呼叫失敗——這輪對話本身還是要正常結束，
    不能因為價值判斷這個附加動作失敗，就讓使用者收不到回覆。"""
    scripts = {"system": ["這是正常的回覆。"]}  # 故意不給 value_judgment
    agent = make_agent(memory_path, scripts)

    events = []
    agent.event_callback = lambda t, d: events.append((t, d))

    send_turn(agent, "隨便問個問題")

    assert agent.state == AgentState.IDLE
    assert any(e[0] == "finished" for e in events), "價值判斷失敗不該讓整輪對話卡住"
    assert any("價值判斷呼叫模型失敗" in str(d) for t, d in events if t == "log")
    print("[PASS] test_value_judgment_call_failure_does_not_break_the_turn")


@with_temp_memory
def test_multiple_facts_from_one_turn_all_saved(memory_path):
    scripts = {
        "system": ["好的，都記下了。"],
        "value_judgment": [
            "- id: fact_a\n- type: Fact\n- summary: 第一個結論\n"
            "- id: fact_b\n- type: Fact\n- summary: 第二個結論\n"
        ],
    }
    agent = make_agent(memory_path, scripts)
    send_turn(agent, "有兩件事要記")

    assert agent.memory_store.get_node("fact_a") is not None
    assert agent.memory_store.get_node("fact_b") is not None
    print("[PASS] test_multiple_facts_from_one_turn_all_saved")


@with_temp_memory
def test_value_judgment_uses_original_user_prompt_not_tool_result_message(memory_path):
    """對話這輪有經過工具呼叫，價值判斷應該拿原始的使用者問題去判斷，
    不是拿中間插入的 [System: Tool Execution Result] 訊息。"""
    captured_prompts = []

    def capture_and_respond(system_prompt, user_prompt):
        captured_prompts.append(user_prompt)
        return "NONE"

    scripts = {
        "system": [
            '<|tool_call|>call:run_action("do it")<|tool_call|>',
            "工具跑完了，這是結果。",
        ],
        "compress": [
            "- id: turn_note\n- type: Fact\n- summary: 使用者請求執行一個動作\n- detail: \n"
        ],
        "value_judgment": [capture_and_respond],
    }
    agent = AgentWorker({"run_action": lambda x: "ok"}, event_callback=lambda t, d: None,
                         default_mode=ExecutionMode.AUTO, memory_path=memory_path)
    agent.client = FakeOpenAIClient(scripts)
    send_turn(agent, "幫我執行一個動作")

    assert len(captured_prompts) == 1
    assert "幫我執行一個動作" in captured_prompts[0]
    assert "System: Tool Execution Result" not in captured_prompts[0]
    print("[PASS] test_value_judgment_uses_original_user_prompt_not_tool_result_message")


if __name__ == "__main__":
    tests = [
        test_judged_valuable_gets_remembered_even_though_history_never_overflows,
        test_judged_not_valuable_writes_nothing,
        test_value_judgment_call_failure_does_not_break_the_turn,
        test_multiple_facts_from_one_turn_all_saved,
        test_value_judgment_uses_original_user_prompt_not_tool_result_message,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
