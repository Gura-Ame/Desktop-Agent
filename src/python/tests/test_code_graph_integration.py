import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
"""
測試 code_graph.py / code_impact.py 真正接進 agent_core.py 的部分：
1. build_code_graph / find_callers / find_callees 這三個工具可以透過 <|tool_call|> 語法被呼叫
2. 任務完成後，系統會自動比對任務標題/方法裡有沒有提到已知函式，機械式插入影響檢查任務——
   不需要模型自己記得要問「這個改了誰會受影響」

執行方式：
    python test_code_graph_integration.py
"""

import os
import sys
import time
import tempfile
import textwrap


from agent.agent_core import AgentWorker, AgentState  # noqa: E402
from agent.task_system import ExecutionMode, TaskNode, TaskStatus  # noqa: E402
from fake_llm import FakeOpenAIClient, ECHO_REFLECT  # noqa: E402


def wait_until(predicate, timeout=2.0, interval=0.01, message="等待逾時"):
    start = time.time()
    while not predicate():
        if time.time() - start > timeout:
            raise AssertionError(message)
        time.sleep(interval)


SAMPLE_SOURCE = textwrap.dedent("""
    def helper(x):
        return x + 1

    def handle_login(user):
        return helper(user)

    def route_request(req):
        return handle_login(req)
""")


def make_agent(scripts, memory_path, mode=ExecutionMode.AUTO):
    events = []

    def on_event(t, d):
        events.append((t, d))

    agent = AgentWorker({}, event_callback=on_event, default_mode=mode, memory_path=memory_path)
    agent.client = FakeOpenAIClient(scripts)
    return agent, events


def with_temp_env(fn):
    def wrapper():
        mem_fd, mem_path = tempfile.mkstemp(suffix=".json")
        os.close(mem_fd)
        os.remove(mem_path)
        src_fd, src_path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(src_fd, "w", encoding="utf-8") as f:
            f.write(SAMPLE_SOURCE)
        try:
            fn(mem_path, src_path)
        finally:
            if os.path.exists(mem_path):
                os.remove(mem_path)
            if os.path.exists(src_path):
                os.remove(src_path)
    return wrapper


@with_temp_env
def test_build_code_graph_and_find_callers_via_tool_call(mem_path, src_path):
    clean_src_path = src_path.replace("\\", "/")
    scripts = {
        "system": [
            f'<|tool_call|>build_code_graph("{clean_src_path}", "sample")<|tool_call|>',
            '<|tool_call|>find_callers("sample.helper")<|tool_call|>',
            "查完了，helper 被 handle_login 呼叫。",
        ],
    }
    agent, events = make_agent(scripts, mem_path)
    agent.set_user_prompt("幫我分析一下這個檔案的呼叫關係")
    agent.state = AgentState.IDLE
    agent.start()
    wait_until(lambda: not agent.is_running())

    chunk_texts = "".join(str(d) for t, d in events if t == "chunk_patch")
    assert "sample.helper" in chunk_texts or any(
        "sample.helper" in str(d) for t, d in events if t == "chunk_patch"
    )
    # 直接檢查底層的 store，確定 build_code_graph 真的建立了節點
    assert agent.memory_store.get_node("sample.helper") is not None
    assert agent.memory_store.get_node("sample.handle_login") is not None
    assert agent.code_graph.find_callers("sample.helper") == ["sample.handle_login"]
    print("[PASS] test_build_code_graph_and_find_callers_via_tool_call")


@with_temp_env
def test_completed_task_mentioning_known_function_auto_queues_impact_checks(mem_path, src_path):
    agent, events = make_agent({}, mem_path)
    # 模擬先前已經對這個檔案 build 過關聯圖（不透過工具呼叫，直接呼叫底層方法比較單純）
    agent.code_graph.build_from_file(src_path, module_name="sample")

    task = TaskNode("TASK-1", "修改 handle_login 讓它支援雙因子驗證")
    task.method = "編輯 handle_login 函式的內容"
    agent.engine.tasks = [task]

    agent._auto_queue_impact_checks(task)

    ids = [t.id for t in agent.engine.tasks]
    assert "TASK-1.impact1" in ids, f"應該自動插入影響檢查任務，實際: {ids}"
    impact_task = next(t for t in agent.engine.tasks if t.id == "TASK-1.impact1")
    assert "sample.route_request" in impact_task.title, "route_request 是唯一呼叫 handle_login 的函式"
    assert any("自動插入" in str(d) for t, d in events if t == "log")
    print("[PASS] test_completed_task_mentioning_known_function_auto_queues_impact_checks")


@with_temp_env
def test_task_not_mentioning_any_known_function_does_not_queue_anything(mem_path, src_path):
    agent, events = make_agent({}, mem_path)
    agent.code_graph.build_from_file(src_path, module_name="sample")

    task = TaskNode("TASK-1", "計算矩形的面積")
    task.method = "用 execute_python 算 w*h"
    agent.engine.tasks = [task]

    agent._auto_queue_impact_checks(task)

    assert len(agent.engine.tasks) == 1, "沒有提到任何已知函式，不該插入任何任務"
    print("[PASS] test_task_not_mentioning_any_known_function_does_not_queue_anything")


@with_temp_env
def test_full_task_completion_flow_triggers_impact_checks(mem_path, src_path):
    """端到端：任務走完整個 think/execute/verify 流程正常完成後，
    影響檢查任務有沒有真的被插進 Task Tree 裡（不是只測 _auto_queue_impact_checks 本身）。"""
    scripts = {
        "system": ['<|tool_call|>execute_python("print(1)")<|tool_call|>'],
        "verify": ["STATUS: PASS\nREASON: 已完成修改"],
        "reflect": [ECHO_REFLECT],
    }
    agent, events = make_agent(scripts, mem_path, mode=ExecutionMode.AUTO)
    agent.code_graph.build_from_file(src_path, module_name="sample")

    task = TaskNode("TASK-1", "修改 handle_login 函式")
    task.method = "編輯程式碼"
    task.condition = "修改完成"
    task.need_confirm = False
    agent.engine.tasks = [task]

    resolved = agent._process_task(task)

    assert resolved is True
    assert task.status == TaskStatus.COMPLETED
    ids = [t.id for t in agent.engine.tasks]
    assert "TASK-1.impact1" in ids
    print("[PASS] test_full_task_completion_flow_triggers_impact_checks")


if __name__ == "__main__":
    tests = [
        test_build_code_graph_and_find_callers_via_tool_call,
        test_completed_task_mentioning_known_function_auto_queues_impact_checks,
        test_task_not_mentioning_any_known_function_does_not_queue_anything,
        test_full_task_completion_flow_triggers_impact_checks,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
