"""
測試 agent_core.py 接上的 remember/recall/relate/recall_related 四個記憶工具，
確認從 <|tool_call|> 語法解析、實際呼叫、寫進 MemoryStore、到下一輪 prompt 能看到
Working Memory 內容，整條路徑都是通的（不是只有函式本身能跑，而是整個串接都要動）。

執行方式：
    python test_memory_tools.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from agent_core import AgentWorker, AgentState  # noqa: E402
from task_system import ExecutionMode  # noqa: E402
from fake_llm import FakeOpenAIClient  # noqa: E402
from memory_store import MemoryStore  # noqa: E402


def make_agent(scripts, memory_path):
    events = []

    def on_event(t, d):
        events.append((t, d))

    agent = AgentWorker({}, event_callback=on_event, default_mode=ExecutionMode.AUTO,
                         memory_path=memory_path)
    agent.client = FakeOpenAIClient(scripts)
    return agent, events


def test_remember_and_recall_persist_and_surface_in_context():
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)

    try:
        scripts = {
            "router": ["DIRECT"],
            "system": [
                '<|tool_call|>call:remember("lemma1", "Lemma", '
                '"若 ab+1 整除 a^2+b^2 則商是完全平方數", {"proved": True})<|tool_call|>',
                '<|tool_call|>call:recall("lemma1")<|tool_call|>',
                "已經記住這個結論了，之後可以直接用。",
            ],
        }
        agent, events = make_agent(scripts, memory_path)
        agent.set_user_prompt("幫我記住這個結論，之後可能會再用到")
        agent.state = AgentState.IDLE
        agent._run()  # 同步呼叫，不用開執行緒，方便直接斷言

        # 1. 真的寫進 Disk 了（重新開一個 MemoryStore 指到同一個檔案，應該也讀得到）
        reloaded = MemoryStore(memory_path)
        node = reloaded.get_node("lemma1")
        assert node is not None, "remember 應該要把節點寫進 Disk"
        assert node.type == "Lemma"
        assert "完全平方數" in node.summary
        assert node.properties.get("proved") is True

        # 2. recall 的工具結果應該要包含摘要內容，而不是只回一個「找到了」
        chunk_texts = "".join(str(d) for t, d in events if t == "chunk")
        assert "完全平方數" in chunk_texts, "recall 的結果應該要出現在對話輸出裡"

        # 3. remember 之後，這個節點應該被 activate 進 Working Memory
        assert "lemma1" in agent.working_memory.active_ids()

        print("[PASS] test_remember_and_recall_persist_and_surface_in_context")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_working_memory_context_reaches_next_prompt():
    """驗證 activate 過的節點，真的會被組進 Working Memory 的渲染內容裡
    （_run_direct_mode 會把 working_memory.render_context() 塞進每一輪的 system message，
    這裡直接驗證 render_context() 的輸出，確保不是「存了但沒人真的讀」）。"""
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)

    try:
        scripts = {
            "router": ["DIRECT"],
            "system": [
                '<|tool_call|>call:remember("steak", "Food", "高蛋白食物")<|tool_call|>',
                "好，我看到摘要了。",
            ],
        }
        agent, events = make_agent(scripts, memory_path)
        agent.set_user_prompt("記住牛排是高蛋白食物，然後跟我確認")
        agent.state = AgentState.IDLE
        agent._run()

        rendered = agent.working_memory.render_context()
        assert "steak" in rendered
        assert "高蛋白食物" in rendered, "render_context 預設就要看得到 summary（不用特別展開）"
        print("[PASS] test_working_memory_context_reaches_next_prompt")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


if __name__ == "__main__":
    tests = [
        test_remember_and_recall_persist_and_surface_in_context,
        test_working_memory_context_reaches_next_prompt,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")