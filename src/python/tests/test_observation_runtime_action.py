import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
"""
針對 Observation runtime_action（context / skip_task / replan）的測試。

背景：這個功能讓 record_observation 存下的結論不只是給模型參考的文字，還能直接
指示 Runtime「這個相關的任務不用做了 (skip_task)」或「這整個計畫要重新想過 (replan)」，
呼應設計文件第 15 點「Observation 要能影響 Runtime 決策，不只是文字」。

執行方式：
    python tests/test_observation_runtime_action.py
"""

from agent.agent_core import AgentState
from agent.task_system import TaskNode, TaskStatus, ExecutionMode
from fake_llm import ECHO_REFLECT
from test_agent_core_helpers import make_agent, wait_until


# ----------------------------------------------------------------------
# 1. memory_store 層：record_observation / get_fresh_observations 本身
# ----------------------------------------------------------------------

def test_runtime_action_defaults_to_context():
    scripts = {}
    agent, events, _ = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.remember("x", "Fact", "一個事實")
    agent.record_observation("obs_x", "x", "一個結論", 0.7)

    node = agent.memory_store.get_node("obs_x")
    assert node.properties.get("runtime_action") == "context"


def test_invalid_runtime_action_fails_closed_to_context():
    scripts = {}
    agent, events, _ = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.remember("x", "Fact", "一個事實")
    agent.memory_store.record_observation("obs_x", "x", "結論", 0.7, runtime_action="delete_everything")

    node = agent.memory_store.get_node("obs_x")
    assert node.properties.get("runtime_action") == "context", \
        "不認得的 runtime_action 應該安全地退回 context，而不是被當成有效指令執行"


def test_record_observation_return_text_shows_runtime_action():
    scripts = {}
    agent, events, _ = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.remember("x", "Fact", "一個事實")
    result = agent.record_observation("obs_x", "x", "一個結論", 0.7, runtime_action="skip_task")
    assert "runtime_action=skip_task" in result


def test_get_fresh_observations_only_returns_fresh_and_related():
    scripts = {}
    agent, events, _ = make_agent(scripts, mode=ExecutionMode.AUTO)
    store = agent.memory_store

    store.upsert_node("x", "Fact", summary="目標 A")
    store.upsert_node("y", "Fact", summary="目標 B（不相關）")
    store.record_observation("obs_fresh", "x", "新鮮的結論", 0.8, runtime_action="skip_task")
    store.record_observation("obs_unrelated", "y", "跟這次任務無關的結論", 0.8, runtime_action="skip_task")

    # x 的內容後來變了（version 是 properties 的內容指紋，改 summary 不會變，要改 properties）
    # -> obs_fresh 應該變成過期
    store.upsert_node("x", "Fact", properties={"note": "更新過"})
    store.record_observation("obs_still_fresh", "x", "更新後的新結論", 0.9, runtime_action="replan")

    fresh = store.get_fresh_observations(["x"])
    fresh_ids = {n.id for n in fresh}

    assert "obs_still_fresh" in fresh_ids, "沒過期、且關聯到 x 的應該要出現"
    assert "obs_fresh" not in fresh_ids, "關於 x 的舊 Observation 已經過期，不該被視為新鮮"
    assert "obs_unrelated" not in fresh_ids, "關於 y 的 Observation 跟這次查的 x 無關，不該混進來"


def test_get_fresh_observations_empty_related_ids_returns_nothing():
    scripts = {}
    agent, events, _ = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.remember("x", "Fact", "一個事實")
    agent.record_observation("obs_x", "x", "結論", 0.8, runtime_action="replan")
    assert agent.memory_store.get_fresh_observations([]) == []


# ----------------------------------------------------------------------
# 2. agent 層：_apply_fresh_observation_decision 在真正執行任務前的攔截效果
# ----------------------------------------------------------------------

def test_skip_task_completes_task_without_executing_it():
    """runtime_action=skip_task：任務應該被直接標記完成，完全不呼叫 system/verify。"""
    scripts = {
        "reflect": [ECHO_REFLECT],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.remember("target_x", "Fact", "任務會關聯到的東西")
    agent.record_observation("obs1", "target_x", "這個步驟其實不需要做了", 0.9, runtime_action="skip_task")

    task = TaskNode("TASK-1", "target_x 相關的任務")
    task.method = "target_x"  # 讓 Retriever 能透過關鍵字比對關聯到 target_x
    task.condition = "完成"
    task.note = "無"
    task.need_confirm = False
    agent.engine.tasks = [task]
    agent.state = AgentState.EXECUTING
    agent.start()

    wait_until(lambda: not agent.is_running(), timeout=3.0, message="沒有在時限內完成")

    assert agent.client.call_log == ["reflect"], \
        f"應該完全不呼叫 system/verify，只呼叫一次 reflect，實際: {agent.client.call_log}"
    final_task = next(t for t in agent.engine.tasks if t.id == "TASK-1")
    assert final_task.status == TaskStatus.COMPLETED
    assert "由 Observation 跳過" in final_task.result
    assert any("[Observation]" in str(d) and "跳過" in str(d) for t, d in events if t == "log")


def test_replan_reroutes_task_without_executing_it():
    """runtime_action=replan：任務應該被重置回 PENDING、觸發 Reflect，一樣不呼叫 system/verify。

    （同 test_context_action：完成後 _auto_queue_impact_checks 會因為 obs1 的 ABOUT
    關聯而自動插入一個已去重的 rel_impact 任務，多準備一輪腳本給它。）
    """
    scripts = {
        "reflect": [ECHO_REFLECT, ECHO_REFLECT, ECHO_REFLECT],
        "system": [
            '<|tool_call|>call:run_action("after replan")<|tool_call|>',
            '<|tool_call|>call:run_action("rel impact check")<|tool_call|>',
        ],
        "verify": ["STATUS: PASS\nREASON: ok", "STATUS: PASS\nREASON: ok"],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.remember("target_x", "Fact", "任務會關聯到的東西")
    agent.record_observation("obs1", "target_x", "整個方向需要重新規劃", 0.9, runtime_action="replan")

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

    # 第一輪：因為 replan 被攔截，不該呼叫 system/verify；重新撿起來之後才會有第二輪
    logs = [d for t, d in events if t == "log"]
    assert any("[Observation]" in str(l) and "觸發重新規劃" in str(l) for l in logs)
    assert agent.client.call_log.count("system") == 2, \
        f"一次是 replan 後重新執行 TASK-1，一次是完成後自動插入的 rel_impact 任務，實際: {agent.client.call_log}"
    final_task = next(t for t in agent.engine.tasks if t.id == "TASK-1")
    assert final_task.status == TaskStatus.COMPLETED, "重新規劃後任務應該還是能正常被執行完成"


def test_context_action_does_not_interrupt_normal_execution():
    """runtime_action=context（預設值）：不該攔截任何東西，任務照原本流程正常跑完。

    注意：record_observation 本身會對目標建立一條 ABOUT 關聯，所以任務完成後
    _auto_queue_impact_checks 會偵測到「target_x 有東西指向它」而自動插入一個
    rel_impact 檢查任務——這是既有、正確的行為（而且這裡順便證實了它真的有在跑：
    04a6791 曾經因為縮排錯誤讓這行變成永遠不會執行的死碼）。所以要多準備一輪
    system/verify/reflect 給這個自動插入的任務用。
    （_auto_queue_impact_checks 在任務開始前跟完成後各呼叫一次，兩次都會掃到同一個
    target_x，但已經用 id 去重擋掉，所以只會真的插入一個 rel_impact 任務，不是兩個。）
    """
    scripts = {
        "system": [
            '<|tool_call|>call:run_action("normal task")<|tool_call|>',
            '<|tool_call|>call:run_action("rel impact check")<|tool_call|>',
        ],
        "verify": ["STATUS: PASS\nREASON: ok", "STATUS: PASS\nREASON: ok"],
        "reflect": [ECHO_REFLECT, ECHO_REFLECT],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.remember("target_x", "Fact", "任務會關聯到的東西")
    agent.record_observation("obs1", "target_x", "只是提供背景資訊", 0.9, runtime_action="context")

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

    assert agent.client.call_log.count("system") == 2, \
        f"一次是 TASK-1 本身，一次是自動插入且去重過的 rel_impact 任務，實際: {agent.client.call_log}"
    rel_impact_tasks = [t for t in agent.engine.tasks if t.id.startswith("TASK-1.rel_impact")]
    assert len(rel_impact_tasks) == 1, \
        f"開始前跟完成後各掃一次都會命中同一個 target_x，去重後應該只有一個，實際: {[t.id for t in rel_impact_tasks]}"
    final_task = next(t for t in agent.engine.tasks if t.id == "TASK-1")
    assert final_task.status == TaskStatus.COMPLETED
    assert any("自動插入" in str(d) for t, d in events if t == "log"), \
        "應該要看到 _auto_queue_impact_checks 真的觸發了自動插入（確認它不再是死碼）"


def test_no_relevant_observation_does_not_interrupt_execution():
    """完全沒有 remember/record_observation 過任何東西時，_apply_fresh_observation_decision
    不該出錯、也不該攔截任何東西——這是最基本的向後相容案例。
    """
    scripts = {
        "system": ['<|tool_call|>call:run_action("normal task")<|tool_call|>'],
        "verify": ["STATUS: PASS\nREASON: ok"],
        "reflect": [ECHO_REFLECT],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)

    task = TaskNode("TASK-1", "完全沒有相關記憶的任務")
    task.method = "做點事"
    task.condition = "完成"
    task.note = "無"
    task.need_confirm = False
    task.confidence = 0.9
    agent.engine.tasks = [task]
    agent.state = AgentState.EXECUTING
    agent.start()

    wait_until(lambda: not agent.is_running(), timeout=3.0, message="沒有在時限內完成")
    assert agent.client.call_log == ["system", "verify", "reflect"]


def test_stale_observation_does_not_trigger_skip_or_replan():
    """關聯目標的內容變過（Observation 已過期）時，就算 runtime_action 是 skip_task/replan
    也不該生效——過期的結論不能拿來下決策，這是設計裡「不只是文字，但也要先確認新鮮」的核心。

    （跟 test_context_action 一樣，record_observation 建立的 ABOUT 關聯會讓
    _auto_queue_impact_checks 額外插入一個 rel_impact 任務，這裡一併準備好腳本。）
    """
    scripts = {
        "system": [
            '<|tool_call|>call:run_action("normal task")<|tool_call|>',
            '<|tool_call|>call:run_action("rel impact check")<|tool_call|>',
        ],
        "verify": ["STATUS: PASS\nREASON: ok", "STATUS: PASS\nREASON: ok"],
        "reflect": [ECHO_REFLECT, ECHO_REFLECT],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.remember("target_x", "Fact", "任務會關聯到的東西")
    agent.record_observation("obs1", "target_x", "這個步驟不需要做了", 0.9, runtime_action="skip_task")
    # target_x 的內容後來變了（version 只看 properties，改 summary 不會變）
    agent.memory_store.upsert_node("target_x", "Fact", properties={"note": "更新過"})

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

    final_task = next(t for t in agent.engine.tasks if t.id == "TASK-1")
    assert "由 Observation 跳過" not in (final_task.result or ""), \
        "Observation 已過期，不該影響這個任務有沒有被跳過"
    assert final_task.status == TaskStatus.COMPLETED


def test_unrelated_active_working_memory_does_not_leak_into_decision():
    """關鍵回歸測試：修正前的版本用整個 WorkingMemory.active_ids()（跨任務滾動的 LRU 快取）
    判斷關聯性，會導致『上一個任務』還留在快取裡的無關節點，誤觸發這次任務的 skip_task。
    修正後應該只看這次 Retriever 真的為這個任務撈到的節點。
    """
    scripts = {
        "system": [
            '<|tool_call|>call:run_action("task A")<|tool_call|>',
            '<|tool_call|>call:run_action("task B")<|tool_call|>',
        ],
        "verify": ["STATUS: PASS\nREASON: ok", "STATUS: PASS\nREASON: ok"],
        "reflect": [ECHO_REFLECT, ECHO_REFLECT],
    }
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)

    # 一個只跟「上一個任務」有關的 skip_task Observation
    agent.remember("topic_a", "Fact", "任務 A 的主題")
    agent.record_observation("obs_a", "topic_a", "任務 A 不需要做了", 0.9, runtime_action="skip_task")

    task_a = TaskNode("TASK-A", "跟 topic_a 相關的任務")
    task_a.method = "topic_a"
    task_a.condition = "完成"
    task_a.note = "無"
    task_a.need_confirm = False
    task_a.confidence = 0.9

    task_b = TaskNode("TASK-B", "完全不相關的任務")
    task_b.method = "做別的事，跟這個無關"
    task_b.condition = "完成"
    task_b.note = "無"
    task_b.need_confirm = False
    task_b.confidence = 0.9

    agent.engine.tasks = [task_a, task_b]
    agent.state = AgentState.EXECUTING
    agent.start()

    wait_until(lambda: not agent.is_running(), timeout=4.0, message="沒有在時限內完成")

    final_a = next(t for t in agent.engine.tasks if t.id == "TASK-A")
    final_b = next(t for t in agent.engine.tasks if t.id == "TASK-B")

    assert final_a.status == TaskStatus.COMPLETED
    assert "由 Observation 跳過" in final_a.result, "TASK-A 真的關聯到 topic_a，應該被 skip_task 跳過"
    assert final_b.status == TaskStatus.COMPLETED
    assert "由 Observation 跳過" not in (final_b.result or ""), \
        "TASK-B 跟 topic_a 無關，不該被 topic_a 的 skip_task Observation 誤跳過"
    assert agent.client.call_log.count("system") == 1, \
        "只有 TASK-B 真的執行了 system 呼叫，TASK-A 應該被跳過、完全不呼叫 system"


# ----------------------------------------------------------------------
# 3. 優先順序：同時有 replan 與 skip_task 時，replan 應該勝出
# ----------------------------------------------------------------------

def test_replan_takes_priority_over_skip_task_when_both_present():
    """同時有兩個新鮮 Observation、一個 replan 一個 skip_task 時，replan 應該先生效。

    replan 生效後該次 Observation 會被標記 applied、任務重置回 PENDING 重新撿起——
    這時 obs_skip 仍然新鮮、仍然成立，所以第二輪被撿起來時 skip_task 接著生效，
    任務最終被跳過完成，並不是錯誤，而是兩個獨立指令依序各自生效的合理結果。
    這裡驗證的重點是「順序」：replan 一定要先於 skip_task 出現，不能反過來。
    """
    scripts = {"reflect": [ECHO_REFLECT]}
    agent, events, tool_calls = make_agent(scripts, mode=ExecutionMode.AUTO)
    agent.remember("target_x", "Fact", "任務會關聯到的東西")
    agent.record_observation("obs_skip", "target_x", "看起來可以跳過", 0.6, runtime_action="skip_task")
    agent.record_observation("obs_replan", "target_x", "但其實需要重新規劃", 0.9, runtime_action="replan")

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

    logs = [d for t, d in events if t == "log"]
    replan_idx = next((i for i, l in enumerate(logs) if "觸發重新規劃" in str(l)), None)
    skip_idx = next((i for i, l in enumerate(logs) if "[✓ 跳過" in str(l)), None)
    assert replan_idx is not None, "replan 應該有生效"
    assert skip_idx is not None, "obs_replan 被消耗掉之後，obs_skip 仍然新鮮，應該接著生效"
    assert replan_idx < skip_idx, "replan 必須先於 skip_task 生效，這是設計好的優先順序"

    final_task = next(t for t in agent.engine.tasks if t.id == "TASK-1")
    assert final_task.status == TaskStatus.COMPLETED
    assert agent.client.call_log.count("system") == 0, \
        "两個指令都在任務真正執行前就生效了，不該有任何一次真的呼叫 system"


if __name__ == "__main__":
    tests = [
        test_runtime_action_defaults_to_context,
        test_invalid_runtime_action_fails_closed_to_context,
        test_record_observation_return_text_shows_runtime_action,
        test_get_fresh_observations_only_returns_fresh_and_related,
        test_get_fresh_observations_empty_related_ids_returns_nothing,
        test_skip_task_completes_task_without_executing_it,
        test_replan_reroutes_task_without_executing_it,
        test_context_action_does_not_interrupt_normal_execution,
        test_no_relevant_observation_does_not_interrupt_execution,
        test_stale_observation_does_not_trigger_skip_or_replan,
        test_unrelated_active_working_memory_does_not_leak_into_decision,
        test_replan_takes_priority_over_skip_task_when_both_present,
    ]
    for t in tests:
        t()
        print(f"[PASS] {t.__name__}")
