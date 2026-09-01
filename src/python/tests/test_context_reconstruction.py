import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
"""
Context 應該在每個任務/每一輪對話開始時重新編譯，而不是讓 Working Memory
在整個 session 裡無限累積、只靠 LRU 上限硬頂著（設計文件第 8 點）。

驗證重點：working_memory.clear() 要在對的時機被呼叫——新的一輪對話開始前、
以及 EXECUTING 模式下每個任務開始前——但不能清得太勤（同一個任務內部的
思考/執行/驗證幾輪之間不該互相清掉彼此的 Context，那樣反而會讓同一個任務
內的連續性斷掉）。
"""

from agent.agent_core import AgentState
from agent.task_system import TaskNode, ExecutionMode, TaskStatus
from fake_llm import ECHO_REFLECT
from test_agent_core_helpers import make_agent, send_turn, wait_until, PLAN_DSL


def test_new_user_turn_clears_working_memory_before_reasoning():
    """新的一輪對話開始時，上一輪殘留在 Working Memory 裡的節點不該繼續佔著位置。"""
    scripts = {"system": [("好的，這是回答", "stop")]}
    agent, events, _ = make_agent(scripts, mode=ExecutionMode.AUTO)

    # 模擬「上一輪」留下來的活躍節點
    agent.remember("leftover_from_previous_turn", "Fact", "上一輪聊到的東西")
    assert "leftover_from_previous_turn" in agent.working_memory.active_ids()

    send_turn(agent, "這是完全不相關的新問題")

    assert "leftover_from_previous_turn" not in agent.working_memory.active_ids(), \
        "新的一輪對話開始前，working memory 應該先被清空重建，不該延續上一輪的活躍節點"


def test_each_task_in_executing_mode_gets_fresh_working_memory():
    """EXECUTING 模式下，任務 A 啟用的節點不該原封不動地留給任務 B 的 Context。"""
    scripts = {
        "system": [
            '<|tool_call|>call:run_action("task a")<|tool_call|>',
            '<|tool_call|>call:run_action("task b")<|tool_call|>',
        ],
        "verify": ["STATUS: PASS\nREASON: ok", "STATUS: PASS\nREASON: ok"],
        "reflect": [ECHO_REFLECT, ECHO_REFLECT],
    }
    agent, events, _ = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.remember("topic_a_only", "Fact", "牛排烤五分熟比較好吃")

    task_a = TaskNode("TASK-A", "牛排相關的步驟")
    task_a.method = "topic_a_only"
    task_a.condition = "完成"
    task_a.note = "無"
    task_a.need_confirm = False
    task_a.confidence = 0.9

    task_b = TaskNode("TASK-B", "整理財務報表")
    task_b.method = "打開試算表填數字"
    task_b.condition = "完成"
    task_b.note = "無"
    task_b.need_confirm = False
    task_b.confidence = 0.9

    agent.engine.tasks = [task_a, task_b]
    agent.state = AgentState.EXECUTING
    agent.start()
    wait_until(lambda: not agent.is_running(), timeout=3.0, message="沒有在時限內完成")

    # TASK-A 執行時會把 topic_a_only 拉進 working memory，但 TASK-B 開始時應該
    # 已經被清空重建過，不該讓 topic_a_only 因為 LRU 還沒滿而繼續賴著不走。
    final_active = agent.working_memory.active_ids()
    assert "topic_a_only" not in final_active, \
        f"TASK-B 開始執行前，working memory 應該已經重新清空，實際還留著: {final_active}"


def test_working_memory_not_cleared_mid_task_between_think_and_execute():
    """同一個任務內部的思考跟執行是連續的，不該因為清空 working memory
    而讓思考階段拉進來的相關節點，到了執行階段又突然不見。
    """
    scripts = {
        "thinking": [
            "分析: 需要參考一下相關資料\n修正方法: 用參考資料\n修正注意: 無\n拆解: NO\n新信心值: 0.8\n",
        ],
        "system": ['<|tool_call|>call:run_action("done")<|tool_call|>'],
        "verify": ["STATUS: PASS\nREASON: ok"],
        "reflect": [ECHO_REFLECT],
    }
    agent, events, _ = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.remember("reference_material", "Fact", "任務會用到的參考資料")

    task = TaskNode("TASK-1", "reference_material 相關的任務")
    task.method = "reference_material"
    task.condition = "完成"
    task.note = "無"
    task.need_thinking = False
    task.need_confirm = False
    task.confidence = 0.4  # < 0.6，會先思考一次
    agent.engine.tasks = [task]
    agent.state = AgentState.EXECUTING

    # 監控 build_context_block 在執行階段被呼叫時，working memory 裡還在不在
    original_build = agent.attention_manager.build_context_block
    seen_active_ids_at_execute = []

    call_count = {"n": 0}

    def spy(working_mem, task=None):
        call_count["n"] += 1
        if call_count["n"] == 2:  # 第二次呼叫是執行階段（第一次是思考階段）
            seen_active_ids_at_execute.append(list(working_mem.active_ids()))
        return original_build(working_mem, task=task)

    agent.attention_manager.build_context_block = spy

    agent.start()
    wait_until(lambda: not agent.is_running(), timeout=3.0, message="沒有在時限內完成")

    assert seen_active_ids_at_execute, "應該有攔截到執行階段的 build_context_block 呼叫"
    assert "reference_material" in seen_active_ids_at_execute[0], \
        "思考階段活化的節點，到了同一個任務的執行階段不該憑空消失"


def test_disk_data_survives_working_memory_clear():
    """working_memory.clear() 只是清掉『目前載入 Context 的子集合』，
    Disk 上的資料本身完全不受影響，之後 Retriever 一樣找得回來。
    """
    scripts = {"system": [("好的", "stop")]}
    agent, events, _ = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.remember("persistent_fact", "Fact", "這個事實應該永久存在")

    agent.working_memory.clear()
    assert "persistent_fact" not in agent.working_memory.active_ids()

    # Disk 上的節點完全沒有消失，重新用 recall 或 search 都找得到
    node = agent.memory_store.get_node("persistent_fact")
    assert node is not None
    assert node.summary == "這個事實應該永久存在"


if __name__ == "__main__":
    test_new_user_turn_clears_working_memory_before_reasoning()
    print("[PASS] test_new_user_turn_clears_working_memory_before_reasoning")
    test_each_task_in_executing_mode_gets_fresh_working_memory()
    print("[PASS] test_each_task_in_executing_mode_gets_fresh_working_memory")
    test_working_memory_not_cleared_mid_task_between_think_and_execute()
    print("[PASS] test_working_memory_not_cleared_mid_task_between_think_and_execute")
    test_disk_data_survives_working_memory_clear()
    print("[PASS] test_disk_data_survives_working_memory_clear")
