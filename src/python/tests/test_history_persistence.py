import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
"""
測試混合記憶（hybrid memory）：對話常駐視窗會主動維持在很小的大小，
超過的部分濃縮進硬記憶；並且對話狀態會存進 MemoryStore，重開程式後讀得回來。

執行方式：
    python test_history_persistence.py
"""

import os
import sys
import time
import tempfile


from agent.agent_core import AgentWorker, AgentState, HYBRID_WINDOW_MESSAGES, HISTORY_NODE_ID  # noqa: E402
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


@with_temp_memory
def test_fresh_agent_has_empty_history(memory_path):
    agent = AgentWorker({}, event_callback=lambda t, d: None,
                         default_mode=ExecutionMode.AUTO, memory_path=memory_path)
    assert agent.history == []
    print("[PASS] test_fresh_agent_has_empty_history")


@with_temp_memory
def test_history_persists_across_restart(memory_path):
    scripts = {"system": ["好的，收到了。"]}
    agent1 = AgentWorker({}, event_callback=lambda t, d: None,
                          default_mode=ExecutionMode.AUTO, memory_path=memory_path)
    agent1.client = FakeOpenAIClient(scripts)
    send_turn(agent1, "你好，幫我記住我在寫一份報告")

    assert len(agent1.history) == 2  # user + assistant

    # 模擬「重開程式」：重新建立一個全新的 AgentWorker，指向同一個記憶檔案
    agent2 = AgentWorker({}, event_callback=lambda t, d: None,
                          default_mode=ExecutionMode.AUTO, memory_path=memory_path)

    assert agent2.history == agent1.history, "重開之後應該要讀回上次的對話"
    print("[PASS] test_history_persists_across_restart")


@with_temp_memory
def test_clear_history_also_clears_persisted_copy(memory_path):
    scripts = {"system": ["好的。"]}
    agent1 = AgentWorker({}, event_callback=lambda t, d: None,
                          default_mode=ExecutionMode.AUTO, memory_path=memory_path)
    agent1.client = FakeOpenAIClient(scripts)
    send_turn(agent1, "記住這件事")
    assert len(agent1.history) > 0

    agent1.clear_conversation_history()
    assert agent1.history == []

    store = MemoryStore(memory_path)
    assert store.get_node(HISTORY_NODE_ID) is None, "清空對話應該連硬記憶裡存的那份也一起清掉"

    # 重開一個新的 agent 指向同一個檔案，應該是全新對話，不會讀回被清空前的內容
    agent2 = AgentWorker({}, event_callback=lambda t, d: None,
                          default_mode=ExecutionMode.AUTO, memory_path=memory_path)
    assert agent2.history == []
    print("[PASS] test_clear_history_also_clears_persisted_copy")


@with_temp_memory
def test_history_window_stays_bounded_across_many_turns(memory_path):
    """混合記憶的核心行為：即使每輪都很短，輪數夠多還是要主動濃縮，
    不是放著讓它一路長大，等哪天 token 數才剛好超過門檻。"""
    n_turns = HYBRID_WINDOW_MESSAGES + 4  # 確定會跨過視窗大小好幾次
    scripts = {
        "system": [f"這是第 {i} 輪的簡短回覆。" for i in range(n_turns)],
        "compress": [
            f"- id: turn_fact_{i}\n- type: Fact\n- summary: 第 {i} 輪談到的重點\n- detail: \n"
            for i in range(n_turns)
        ],
    }
    agent = AgentWorker({}, event_callback=lambda t, d: None,
                         default_mode=ExecutionMode.AUTO, memory_path=memory_path)
    agent.client = FakeOpenAIClient(scripts)

    for i in range(n_turns):
        send_turn(agent, f"第 {i} 輪，內容普通")

    assert len(agent.history) <= HYBRID_WINDOW_MESSAGES + 3, (
        f"對話跑了 {n_turns} 輪，history 長度應該要被主動控制住，實際: {len(agent.history)}"
    )

    # 濃縮出來的事實應該真的被寫進硬記憶了，不是憑空消失
    reloaded = MemoryStore(memory_path)
    fact_nodes = [n for n in reloaded.nodes.values() if n.type == "Fact"]
    assert len(fact_nodes) > 0, "壓縮掉的內容應該以結構化事實的形式留在硬記憶裡"
    print("[PASS] test_history_window_stays_bounded_across_many_turns")


@with_temp_memory
def test_saved_history_strips_image_data(memory_path):
    """圖片內容存進硬記憶前應該被換成占位文字，不要讓 JSON 檔案被 base64 塞爆。"""
    agent = AgentWorker({}, event_callback=lambda t, d: None,
                         default_mode=ExecutionMode.AUTO, memory_path=memory_path)
    agent.history = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "這張圖是什麼？"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAAVERYLONGDATA...."}},
            ],
        },
        {"role": "assistant", "content": "這是一張截圖。"},
    ]
    agent._save_history()

    reloaded = MemoryStore(memory_path)
    node = reloaded.get_node(HISTORY_NODE_ID)
    assert node is not None
    saved_messages = node.properties["messages"]
    first_content = saved_messages[0]["content"]
    assert not any(
        part.get("type") == "image_url" for part in first_content if isinstance(part, dict)
    ), "存進硬記憶的版本不應該還留著圖片的 base64 資料"
    assert any(
        "圖片內容已省略" in part.get("text", "") for part in first_content if isinstance(part, dict)
    )
    print("[PASS] test_saved_history_strips_image_data")


if __name__ == "__main__":
    tests = [
        test_fresh_agent_has_empty_history,
        test_history_persists_across_restart,
        test_clear_history_also_clears_persisted_copy,
        test_history_window_stays_bounded_across_many_turns,
        test_saved_history_strips_image_data,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
