"""
測試 Reflect 步驟裡新加的「值得長期記住的結論」：
1. _split_reflect_output 正確拆開 Task Tree DSL 跟 MEMORY 區塊
2. _reflect 真的把解析出來的結論寫進 MemoryStore，不靠模型自己想到要呼叫 remember
3. Task Tree 更新被拒絕，不影響 MEMORY 部分照樣被存下來（兩件事互相獨立）

執行方式：
    python test_reflect_memory.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from agent_core import AgentWorker, AgentState  # noqa: E402
from task_system import ExecutionMode, TaskNode, TaskStatus  # noqa: E402
from fake_llm import FakeOpenAIClient  # noqa: E402
from memory_store import MemoryStore  # noqa: E402


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


def make_agent(memory_path, scripts=None):
    agent = AgentWorker({}, event_callback=lambda t, d: None,
                         default_mode=ExecutionMode.AUTO, memory_path=memory_path)
    if scripts:
        agent.client = FakeOpenAIClient(scripts)
    return agent


TREE_ONLY = """
- [x] [TASK-1] 完成的任務
  - 結果: 做完了
"""

TREE_WITH_MEMORY = TREE_ONLY + """
===MEMORY===
- id: parser_nullcheck
- type: Fact
- summary: parser.parse_expr 沒有處理空字串輸入
- id: rate_limit
- type: Constraint
- summary: 這個 API 每分鐘最多呼叫 60 次
===END MEMORY===
"""


@with_temp_memory
def test_split_reflect_output_without_memory_block(memory_path):
    agent = make_agent(memory_path)
    tree_dsl, facts = agent._split_reflect_output(TREE_ONLY)
    assert facts == [], "沒有 MEMORY 區塊時應該回傳空列表，這是正常情況"
    assert "[TASK-1]" in tree_dsl
    print("[PASS] test_split_reflect_output_without_memory_block")


@with_temp_memory
def test_split_reflect_output_with_memory_block(memory_path):
    agent = make_agent(memory_path)
    tree_dsl, facts = agent._split_reflect_output(TREE_WITH_MEMORY)

    assert "===MEMORY===" not in tree_dsl, "MEMORY 區塊不該混進要拿去解析 Task Tree 的文字裡"
    assert "[TASK-1]" in tree_dsl

    assert len(facts) == 2
    assert facts[0]["id"] == "parser_nullcheck"
    assert facts[0]["type"] == "Fact"
    assert "空字串" in facts[0]["summary"]
    assert facts[1]["id"] == "rate_limit"
    assert facts[1]["type"] == "Constraint"
    print("[PASS] test_split_reflect_output_with_memory_block")


@with_temp_memory
def test_reflect_writes_memory_facts_without_model_calling_remember_tool(memory_path):
    scripts = {"reflect": [TREE_WITH_MEMORY]}
    agent = make_agent(memory_path, scripts)

    task = TaskNode("TASK-1", "完成的任務")
    task.status = TaskStatus.COMPLETED
    agent.engine.tasks = [task]

    agent._reflect(task, "做完了")

    node1 = agent.memory_store.get_node("parser_nullcheck")
    node2 = agent.memory_store.get_node("rate_limit")
    assert node1 is not None, "應該自動寫進硬記憶，不需要模型自己呼叫 remember 工具"
    assert node1.type == "Fact"
    assert "空字串" in node1.summary
    assert node2 is not None
    assert node2.type == "Constraint"

    # 也應該被 activate 進 Working Memory，之後的 prompt 才看得到
    assert "parser_nullcheck" in agent.working_memory.active_ids()
    print("[PASS] test_reflect_writes_memory_facts_without_model_calling_remember_tool")


@with_temp_memory
def test_memory_facts_saved_even_when_tree_update_rejected(memory_path):
    """Task Tree 更新被拒絕（例如漏寫了已完成的任務），不該連帶讓值得記住的結論也一起消失。"""
    scripts = {
        "reflect": [
            # 故意漏掉已完成的 TASK-1，會被 apply_reflected_dsl 拒絕
            "- [ ] [TASK-2] 新任務\n"
            "  - 方法: 做點什麼\n"
            "  - 條件: 做完了\n"
            "  - 注意: 無\n"
            "  - 深度思考: NO\n"
            "  - 需要拆解: NO\n"
            "  - 需要確認: NO\n"
            "  - 信心值: 0.8\n"
            "===MEMORY===\n"
            "- id: important_fact\n"
            "- type: Fact\n"
            "- summary: 這個結論不該因為樹更新被拒絕就跟著消失\n"
            "===END MEMORY===\n"
        ]
    }
    agent = make_agent(memory_path, scripts)

    task = TaskNode("TASK-1", "完成的任務")
    task.status = TaskStatus.COMPLETED
    agent.engine.tasks = [task]
    original_tasks = list(agent.engine.tasks)

    agent._reflect(task, "做完了")

    # 樹應該維持原狀（更新被拒絕）
    assert agent.engine.tasks == original_tasks, "樹更新應該被拒絕、保留原狀"
    # 但記憶結論還是要照樣被存下來
    node = agent.memory_store.get_node("important_fact")
    assert node is not None, "MEMORY 部分應該獨立於 Task Tree 驗證結果，照樣被存下來"
    print("[PASS] test_memory_facts_saved_even_when_tree_update_rejected")


@with_temp_memory
def test_fact_without_id_is_skipped(memory_path):
    scripts = {
        "reflect": [
            TREE_ONLY + "===MEMORY===\n- type: Fact\n- summary: 沒有 id 的結論\n===END MEMORY===\n"
        ]
    }
    agent = make_agent(memory_path, scripts)
    task = TaskNode("TASK-1", "完成的任務")
    task.status = TaskStatus.COMPLETED
    agent.engine.tasks = [task]

    agent._reflect(task, "做完了")
    fact_nodes = [n for n in agent.memory_store.nodes.values() if n.type == "Fact" and n.id != "TASK-1"]
    assert fact_nodes == [], "沒有 id 的結論沒辦法存，應該被跳過而不是報錯"
    print("[PASS] test_fact_without_id_is_skipped")


if __name__ == "__main__":
    tests = [
        test_split_reflect_output_without_memory_block,
        test_split_reflect_output_with_memory_block,
        test_reflect_writes_memory_facts_without_model_calling_remember_tool,
        test_memory_facts_saved_even_when_tree_update_rejected,
        test_fact_without_id_is_skipped,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
