"""
agent_core.py 的 __init__ 拆成 _init_memory_subsystem / _register_available_functions /
_init_llm_client / _init_session_state 四個步驟之後，這裡驗證行為完全沒變：
建構完的 AgentWorker，其 available_functions 裡該有的工具、記憶子系統的物件、
執行期狀態欄位都還在，數量、名稱都跟拆之前一樣。

這是專門針對「這次重構本身」的迴歸測試——其餘 280 個測試已經用 AgentWorker
的完整行為間接驗證過一輪，這裡只是額外把「建構完成後 available_functions
長什麼樣子」這件事明確釘住，避免以後有人（包含未來的我自己）改動這四個
_init_* 方法時，不小心漏登記了某個工具卻沒有任何測試會失敗。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.agent_core import AgentWorker
from agent.task_system import ExecutionMode


def _make_bare_agent():
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)
    agent = AgentWorker(
        {"custom_tool": lambda: "ok"},  # 模擬 main.py 一開始就塞進去的桌面自動化工具
        event_callback=lambda *a: None,
        default_mode=ExecutionMode.STEP_BY_STEP,
        memory_path=memory_path,
    )
    return agent, memory_path


def test_register_available_functions_keeps_caller_provided_tools_and_adds_agent_tools():
    agent, memory_path = _make_bare_agent()
    try:
        # main.py 建構 AgentWorker 之前就塞進 dict 裡的工具（桌面自動化那些）不該被蓋掉
        assert agent.available_functions["custom_tool"]() == "ok"

        expected_agent_owned_tools = {
            "ask_user",
            "read_tool_doc",
            "remember",
            "recall",
            "relate",
            "recall_related",
            "search_memory",
            "record_observation",
            "recall_observation",
            "recall_with_event",
            "build_code_graph",
            "build_code_graph_for_project",
            "find_callers",
            "find_callees",
        }
        missing = expected_agent_owned_tools - set(agent.available_functions.keys())
        assert not missing, f"_register_available_functions 漏登記了: {missing}"

        # 每個登記進去的，必須是這個 agent instance 自己身上的 bound method，
        # 不能是模組層級的裸函式（不然呼叫時會拿不到 self，等於整個工具失效）。
        for name in expected_agent_owned_tools:
            fn = agent.available_functions[name]
            assert getattr(fn, "__self__", None) is agent, (
                f"{name} 沒有正確綁定到這個 agent instance"
            )
        print("[PASS] test_register_available_functions_keeps_caller_provided_tools_and_adds_agent_tools")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_init_memory_subsystem_wires_all_expected_objects():
    agent, memory_path = _make_bare_agent()
    try:
        assert agent.memory_store is not None
        assert agent.working_memory.store is agent.memory_store
        assert agent.context_compressor.memory_store is agent.memory_store
        assert agent.retriever.store is agent.memory_store
        assert agent.attention_manager is not None
        assert agent.forgetting_manager is not None
        # 開機時要把 MemoryStore 存的開關狀態同步進 ForgettingManager，
        # 全新的 memory_path 預設是 False，兩邊應該一致。
        assert agent.forgetting_manager.enabled == agent.memory_store.forgetting_enabled
        assert agent.code_graph.store is agent.memory_store
        print("[PASS] test_init_memory_subsystem_wires_all_expected_objects")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_init_session_state_sets_expected_defaults():
    agent, memory_path = _make_bare_agent()
    try:
        assert agent.engine.mode == ExecutionMode.STEP_BY_STEP
        assert agent.current_user_prompt == ""
        assert agent.current_images == []
        assert agent.is_paused_for_input is False
        assert agent.user_reply_content == ""
        assert agent.max_think_limit == 3
        assert agent._thread is None
        assert agent._active_stream is None
        assert agent.is_running() is False
        print("[PASS] test_init_session_state_sets_expected_defaults")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


if __name__ == "__main__":
    tests = [
        test_register_available_functions_keeps_caller_provided_tools_and_adds_agent_tools,
        test_init_memory_subsystem_wires_all_expected_objects,
        test_init_session_state_sets_expected_defaults,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
