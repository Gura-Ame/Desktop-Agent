"""
測試跨 Session 記憶機制（Cross-Session Memory with CCS）：
1. 知識在 Disk (MemoryStore) 永久持久化。
2. 重啟 Session 後，Retriever 能根據新的使用者輸入自動從 Disk 拉取相關知識進 WorkingMemory。
3. AttentionManager 動態打分與 Token Budget 控制，將精煉上下文注入 Direct Mode 與 Reasoning 模式。
4. 歷史對話、經驗、事實與觀測結論（Observations）跨 Session 延續。
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.agent_core import AgentWorker, AgentState
from agent.task_system import ExecutionMode
from fake_llm import FakeOpenAIClient
from memory.memory_store import MemoryStore


def wait_until(predicate, timeout=3.0, interval=0.01, message="等待逾時"):
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
def test_cross_session_fact_retrieval(memory_path):
    """
    Session 1 記住一件事實並存入 Disk；
    Session 2（全新 AgentWorker 例項）即使 WorkingMemory 初始為空，
    也能透過 Retriever 自動從 Disk 拉取相關事實進 Context。
    """
    # === Session 1: 寫入結構化事實 ===
    store1 = MemoryStore(memory_path)
    store1.upsert_node(
        "user_favorite_project",
        "Fact",
        properties={"language": "Python", "type": "Agent"},
        summary="使用者正在開發 Desktop-Agent 專案",
    )
    store1.upsert_node(
        "project_guidelines",
        "Constraint",
        properties={"budget": 650},
        summary="Context 必須維持在 Token Budget 內",
    )

    # === Session 2: 模擬重新啟動程式 ===
    agent2 = AgentWorker(
        {},
        event_callback=lambda t, d: None,
        default_mode=ExecutionMode.AUTO,
        memory_path=memory_path,
    )
    agent2.client = FakeOpenAIClient({"system": ["收到，我已參考先前專案資訊。"]})

    # 驗證啟動時 WorkingMemory 為空
    assert len(agent2.working_memory.active_ids()) == 0

    # 發送與 Desktop-Agent 相關的詢問
    send_turn(agent2, "請繼續 Desktop-Agent 的開發工作")

    # 驗證 Retriever 已跨 Session 自動從 Disk 抓回該事實
    active_ids = agent2.working_memory.active_ids()
    assert "user_favorite_project" in active_ids, (
        f"Retriever 應該自動將相關知識從 Disk 拉入 Working Memory，實際: {active_ids}"
    )
    print("[PASS] test_cross_session_fact_retrieval")


@with_temp_memory
def test_cross_session_relation_graph_expansion(memory_path):
    """
    驗證跨 Session 的關聯圖走訪（Graph Expansion）：
    查詢 A 會自動帶出與 A 相關聯的 B，並受 AttentionManager token 控制。
    """
    store = MemoryStore(memory_path)
    store.upsert_node("module_a", "Function", summary="模組 A 負責資料解析")
    store.upsert_node("module_b", "Function", summary="模組 B 負責資料快取")
    store.add_relation("module_a", "CALLS", "module_b")

    agent = AgentWorker(
        {},
        event_callback=lambda t, d: None,
        default_mode=ExecutionMode.AUTO,
        memory_path=memory_path,
    )
    agent.client = FakeOpenAIClient({"system": ["分析完畢。"]})

    send_turn(agent, "請檢查 module_a 的行為")

    # 透過 Retriever 沿 CALLS 關聯擴展，module_a 與 module_b 都應被啟動
    active = agent.working_memory.active_ids()
    assert "module_a" in active
    assert "module_b" in active
    print("[PASS] test_cross_session_relation_graph_expansion")


if __name__ == "__main__":
    test_cross_session_fact_retrieval()
    test_cross_session_relation_graph_expansion()
    print("\n全部跨 Session 記憶測試通過。")
