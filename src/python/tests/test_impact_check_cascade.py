import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
"""
針對「_auto_queue_impact_checks 重複插入 / 無限連鎖」這兩個 bug 的回歸測試。

背景：_auto_queue_impact_checks 在同一個任務生命週期裡會被呼叫兩次
（開始前預掃一次、完成後再掃一次）。曾經發現兩個問題：

1. 兩次呼叫用的是同一份、純機械式（不含亂數/時間戳）產生的 id，
   如果不去重，同一個任務完成一次就會插入兩份內容一模一樣的重複任務。

2. 自動插入的「影響檢查」任務本身的描述文字必然會提到被改動的節點，
   如果讓它自己也去跑一次同樣的掃描，會再次命中同一個節點、再插入下一個
   影響檢查任務，如此無限循環。原本想用 TaskNode.is_auto_impact_check 這個
   屬性擋掉，但這個屬性不是 DSL 文字格式的一部分，Reflect 每次都會把
   還沒執行完的任務整個用重新解析出來的新物件取代掉（apply_reflected_dsl），
   屬性就這樣被悄悄重置回 False，保護形同虛設。改成看 id 命名規則
   （".impact數字" / ".rel_impact數字" 結尾）才是真正能存活下來的判斷依據。
"""

from agent.agent_core import AgentState
from agent.task_system import TaskNode, TaskStatus, ExecutionMode
from fake_llm import ECHO_REFLECT
from test_agent_core_helpers import make_agent, wait_until


def test_relation_impact_check_not_duplicated_within_one_task_lifecycle():
    """完成一個提到已知 Fact 的任務，只該插入一份 rel_impact 任務，不是兩份
    （_auto_queue_impact_checks 在任務開始前跟完成後各呼叫一次，兩次都會命中
    同一個節點，去重前會各插入一份、變成兩份重複的）。
    """
    scripts = {
        "system": [
            '<|tool_call|>call:run_action("main task")<|tool_call|>',
            '<|tool_call|>call:run_action("impact check")<|tool_call|>',
        ],
        "verify": ["STATUS: PASS\nREASON: ok", "STATUS: PASS\nREASON: ok"],
        "reflect": [ECHO_REFLECT, ECHO_REFLECT],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.remember("target_x", "Fact", "被關聯到的東西")
    agent.record_observation("obs1", "target_x", "背景資訊", 0.9, runtime_action="context")

    task = TaskNode("TASK-1", "target_x 相關的任務")
    task.method = "target_x"
    task.condition = "完成"
    task.note = "無"
    task.need_confirm = False
    task.confidence = 0.9
    agent.engine.tasks = [task]
    agent.state = AgentState.EXECUTING
    agent.start()

    wait_until(lambda: not agent.is_running(), timeout=3.0, message="沒有在時限內完成")

    rel_impact_tasks = [t for t in agent.engine.tasks if t.id.startswith("TASK-1.rel_impact")]
    assert len(rel_impact_tasks) == 1, \
        f"開始前跟完成後各掃一次都會命中同一個節點，去重後應該只有一份，實際: {[t.id for t in rel_impact_tasks]}"
    assert agent.client.call_log.count("system") == 2


def test_auto_impact_check_task_does_not_cascade_after_reflect_replaces_it():
    """關鍵回歸測試：插入的 rel_impact 任務在『被 Reflect 摸過一次』
    （因為前一個任務完成後觸發了 Reflect，把它整個換成新解析出來的物件）之後，
    is_auto_impact_check 這個屬性已經不可靠了；但它執行時仍然不該再往下
    連鎖插入下一個 rel_impact 任務——這必須靠 id 命名規則來判斷，而不是屬性。
    """
    scripts = {
        "system": [
            '<|tool_call|>call:run_action("main task")<|tool_call|>',
            '<|tool_call|>call:run_action("impact check")<|tool_call|>',
        ],
        "verify": ["STATUS: PASS\nREASON: ok", "STATUS: PASS\nREASON: ok"],
        "reflect": [ECHO_REFLECT, ECHO_REFLECT],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.remember("target_x", "Fact", "被關聯到的東西")
    agent.record_observation("obs1", "target_x", "背景資訊", 0.9, runtime_action="context")

    task = TaskNode("TASK-1", "target_x 相關的任務")
    task.method = "target_x"
    task.condition = "完成"
    task.note = "無"
    task.need_confirm = False
    task.confidence = 0.9
    agent.engine.tasks = [task]
    agent.state = AgentState.EXECUTING
    agent.start()

    wait_until(lambda: not agent.is_running(), timeout=3.0, message="沒有在時限內完成")

    # TASK-1 完成時觸發的 Reflect（第一次 ECHO_REFLECT）已經把 rel_impact1
    # 換成一份重新解析出來的新物件——驗證它此時的 is_auto_impact_check 屬性
    # 確實已經是 False（證明屬性真的不可靠，這是這個 bug 的根本原因）：
    rel_impact_task = next(t for t in agent.engine.tasks if t.id == "TASK-1.rel_impact1")
    assert rel_impact_task.is_auto_impact_check is False, \
        "這裡驗證的是問題的根源：屬性在 Reflect 換物件後確實會遺失，所以不能拿它當判斷依據"

    # 儘管屬性已經遺失，整個流程仍然正確在一層就停止，沒有連鎖出 rel_impact1.rel_impact1
    grandchild_tasks = [t for t in agent.engine.tasks if ".rel_impact" in t.id.split("TASK-1.rel_impact1")[-1]]
    nested = [t for t in agent.engine.tasks if t.id.count("rel_impact") >= 2]
    assert nested == [], f"不該連鎖出下一層的 rel_impact 任務，實際: {[t.id for t in nested]}"
    assert agent.client.call_log.count("system") == 2, \
        "應該正好兩次：TASK-1 本身，加上唯一一層 rel_impact 任務，沒有無限連鎖"


def test_is_auto_impact_check_task_recognizes_id_pattern_regardless_of_attribute():
    """直接測試 _is_auto_impact_check_task 這個判斷本身：就算屬性是 False，
    只要 id 符合命名規則就該被視為終點任務；反過來，一般任務不該被誤判。
    """
    scripts = {}
    agent, events, _ = make_agent(scripts, mode=ExecutionMode.AUTO)

    fake_but_id_matches = TaskNode("TASK-1.rel_impact1", "隨便的標題")
    fake_but_id_matches.is_auto_impact_check = False  # 模擬屬性已經遺失
    assert agent._is_auto_impact_check_task(fake_but_id_matches) is True

    code_impact_id = TaskNode("TASK-2.impact3", "隨便的標題")
    code_impact_id.is_auto_impact_check = False
    assert agent._is_auto_impact_check_task(code_impact_id) is True

    normal_task = TaskNode("TASK-3", "一般任務")
    assert agent._is_auto_impact_check_task(normal_task) is False

    # 不該誤判：一般任務的 id 剛好含有類似字樣但不是規則要求的「結尾是 .impact數字」格式
    almost_but_not_quite = TaskNode("TASK-4.impact_analysis", "一般任務")
    assert agent._is_auto_impact_check_task(almost_but_not_quite) is False


def test_code_impact_check_also_dedupes_and_terminates():
    """code_impact.py 的 CALLS 關聯版本跟 relation_impact.py 是同一套邏輯、
    同樣的兩個 bug，這裡用 Function 節點 + CALLS 關聯確認一樣修好了。
    """
    scripts = {
        "system": [
            '<|tool_call|>call:run_action("main task")<|tool_call|>',
            '<|tool_call|>call:run_action("impact check")<|tool_call|>',
        ],
        "verify": ["STATUS: PASS\nREASON: ok", "STATUS: PASS\nREASON: ok"],
        "reflect": [ECHO_REFLECT, ECHO_REFLECT],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.memory_store.upsert_node("mymod.changed_func", "Function", summary="被改動的函式")
    agent.memory_store.upsert_node("mymod.caller_func", "Function", summary="呼叫者",
                                    properties={"file": "mymod.py"})
    agent.memory_store.add_relation("mymod.caller_func", "CALLS", "mymod.changed_func")

    task = TaskNode("TASK-1", "changed_func 相關的任務")
    task.method = "changed_func"  # 用短名比對，符合 _auto_queue_impact_checks 的 word-boundary 規則
    task.condition = "完成"
    task.note = "無"
    task.need_confirm = False
    task.confidence = 0.9
    agent.engine.tasks = [task]
    agent.state = AgentState.EXECUTING
    agent.start()

    wait_until(lambda: not agent.is_running(), timeout=3.0, message="沒有在時限內完成")

    impact_tasks = [t for t in agent.engine.tasks if t.id.startswith("TASK-1.impact")]
    assert len(impact_tasks) == 1, f"應該只有一份，實際: {[t.id for t in impact_tasks]}"
    nested = [t for t in agent.engine.tasks if t.id.count("impact") >= 2]
    assert nested == [], f"不該連鎖出下一層，實際: {[t.id for t in nested]}"
    assert agent.client.call_log.count("system") == 2


if __name__ == "__main__":
    test_relation_impact_check_not_duplicated_within_one_task_lifecycle()
    print("[PASS] test_relation_impact_check_not_duplicated_within_one_task_lifecycle")
    test_auto_impact_check_task_does_not_cascade_after_reflect_replaces_it()
    print("[PASS] test_auto_impact_check_task_does_not_cascade_after_reflect_replaces_it")
    test_is_auto_impact_check_task_recognizes_id_pattern_regardless_of_attribute()
    print("[PASS] test_is_auto_impact_check_task_recognizes_id_pattern_regardless_of_attribute")
    test_code_impact_check_also_dedupes_and_terminates()
    print("[PASS] test_code_impact_check_also_dedupes_and_terminates")
