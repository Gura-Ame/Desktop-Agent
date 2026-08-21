import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
"""
驗證自動上下文壓縮真的接進 agent_core.py 的對話迴圈了——包含「先推理判斷難度」這個新架構
第一輪就會呼叫模型的路徑，不是只有 _run_direct_mode 內部的後續輪次。整段對話裡模型完全沒有
呼叫 remember/recall 任何一次，純粹因為 history 長度超過門檻，系統自己觸發壓縮、
把結構化事實寫進 MemoryStore、並且送給模型的訊息真的變短了。

執行方式：
    python test_auto_compression_integration.py
"""

import os
import sys
import time
import tempfile


from agent.agent_core import AgentWorker, AgentState  # noqa: E402
from agent.task_system import ExecutionMode  # noqa: E402
from fake_llm import FakeOpenAIClient  # noqa: E402
from memory.memory_store import MemoryStore  # noqa: E402


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


def test_compression_triggers_without_any_memory_tool_call():
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)

    try:
        scripts = {
            "system": [
                "好的，收到，有什麼我可以幫忙的嗎？",         # 第一輪回覆
                "了解，我會記住這件事。",                     # 第二輪回覆
                "根據前面壓縮下來的重點，這是第三輪的正式回覆。",  # 壓縮後、第三輪的正式回覆
            ],
            "compress": [
                "- id: pref1\n"
                "- type: Fact\n"
                "- summary: 使用者提到了一個很長的細節\n"
                "- detail: \n"
            ],
        }
        events = []

        def on_event(t, d):
            events.append((t, d))

        agent = AgentWorker({}, event_callback=on_event, default_mode=ExecutionMode.AUTO,
                             memory_path=memory_path)
        agent.client = FakeOpenAIClient(scripts)

        # --- 前兩輪：純粹是為了讓 history 累積到超過 keep_last_turns，才有東西可壓 ---
        send_turn(agent, "你好")
        send_turn(agent, "我要告訴你一件比較長的事情")
        assert len(agent.history) == 4  # user1, assistant1, user2, assistant2

        # 強制把 baseline 壓到很小，確保下一輪一定會觸發（不用真的堆一大段文字才能測）
        agent.context_compressor.baseline_tokens = 5

        # --- 第三輪：壓縮檢查發生在 _run_inner 的推理階段，不是只有 _run_direct_mode 內部 ---
        send_turn(agent, "那接下來呢？")

        # 1. 有真的觸發壓縮的 log，而且過程中沒有任何 remember/recall 工具呼叫
        assert any("自動濃縮" in str(d) for t, d in events if t == "log")
        assert not any(t == "chunk" and "<tool_result>" in str(d) for t, d in events), (
            "AgentWorker 這裡沒註冊任何工具、劇本裡也沒寫 <|tool_call|>，"
            "壓縮完全是系統自己做的，不是模型呼叫工具做的"
        )

        # 2. 結構化事實真的被寫進 Disk 了（不是模型自己選擇要不要存，是系統強制做的）
        reloaded = MemoryStore(memory_path)
        node = reloaded.get_node("pref1")
        assert node is not None, "壓縮出來的事實應該要被寫進 MemoryStore"
        assert node.type == "Fact"

        # 3. history 裡有一則壓縮摘要（system role），且整體長度受控，不是無限累積
        assert any(m["role"] == "system" and "已經被自動濃縮" in m["content"] for m in agent.history)
        from agent.agent_core import HYBRID_WINDOW_MESSAGES
        # 一輪最多再疊加 user+assistant 兩則，才會在下一輪開頭被壓下去；上限抓「視窗 + 這輪還沒被檢查到的 2 則」
        assert len(agent.history) <= HYBRID_WINDOW_MESSAGES + 3, (
            f"壓縮後 history 應該受控，實際: {len(agent.history)} 則"
        )

        print("[PASS] test_compression_triggers_without_any_memory_tool_call")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


if __name__ == "__main__":
    test_compression_triggers_without_any_memory_tool_call()
    print("\n全部 1 個測試通過。")
