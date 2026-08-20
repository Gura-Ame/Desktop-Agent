"""
測試聯想式搜尋：search_memory / MemoryStore.search——
不需要知道精確的 id，靠關鍵字比對 id/type/summary 就能找到相關記憶。

執行方式：
    python test_search_memory.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory_store import MemoryStore  # noqa: E402
from agent_core import AgentWorker  # noqa: E402
from task_system import ExecutionMode  # noqa: E402


def with_temp_store(fn):
    def wrapper():
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(path)
        try:
            store = MemoryStore(path)
            fn(store)
        finally:
            if os.path.exists(path):
                os.remove(path)
    return wrapper


@with_temp_store
def test_search_matches_id(store: MemoryStore):
    store.upsert_node("parser.parse_expr", "Function", summary="解析運算式")
    store.upsert_node("unrelated_thing", "Fact", summary="無關的東西")
    results = store.search("parser")
    assert len(results) == 1
    assert results[0].id == "parser.parse_expr"
    print("[PASS] test_search_matches_id")


@with_temp_store
def test_search_matches_type(store: MemoryStore):
    store.upsert_node("a", "Lemma", summary="第一個引理")
    store.upsert_node("b", "Fact", summary="一個事實")
    results = store.search("lemma")
    assert len(results) == 1
    assert results[0].id == "a"
    print("[PASS] test_search_matches_type")


@with_temp_store
def test_search_matches_summary(store: MemoryStore):
    store.upsert_node("x", "Fact", summary="使用者偏好簡潔的條列式回答")
    results = store.search("條列式")
    assert len(results) == 1
    assert results[0].id == "x"
    print("[PASS] test_search_matches_summary")


@with_temp_store
def test_search_is_case_insensitive(store: MemoryStore):
    store.upsert_node("Parser.ParseExpr", "Function", summary="解析運算式")
    results = store.search("PARSER")
    assert len(results) == 1
    print("[PASS] test_search_is_case_insensitive")


@with_temp_store
def test_search_prioritizes_id_type_over_summary_match(store: MemoryStore):
    store.upsert_node("login_flow", "Function", summary="處理登入流程")
    store.upsert_node("unrelated", "Fact", summary="這裡面剛好也提到 login 這個詞")
    results = store.search("login")
    assert results[0].id == "login_flow", "id 命中應該排在 summary 命中前面"
    assert len(results) == 2
    print("[PASS] test_search_prioritizes_id_type_over_summary_match")


@with_temp_store
def test_search_no_match_returns_empty(store: MemoryStore):
    store.upsert_node("x", "Fact", summary="一些內容")
    assert store.search("完全找不到的關鍵字") == []
    print("[PASS] test_search_no_match_returns_empty")


@with_temp_store
def test_search_respects_limit(store: MemoryStore):
    for i in range(15):
        store.upsert_node(f"item_{i}", "Fact", summary="都跟 test 有關")
    results = store.search("test", limit=5)
    assert len(results) == 5
    print("[PASS] test_search_respects_limit")


@with_temp_store
def test_empty_keyword_returns_empty(store: MemoryStore):
    store.upsert_node("x", "Fact", summary="一些內容")
    assert store.search("") == []
    assert store.search("   ") == []
    print("[PASS] test_empty_keyword_returns_empty")


def _make_agent(memory_path):
    return AgentWorker({}, event_callback=lambda t, d: None,
                        default_mode=ExecutionMode.AUTO, memory_path=memory_path)


def test_search_memory_tool_activates_results_into_working_memory():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(path)
    try:
        agent = _make_agent(path)
        agent.remember("parser.parse_expr", "Function", "解析運算式")

        result = agent.search_memory("parser")
        assert "parser.parse_expr" in result
        assert "parser.parse_expr" in agent.working_memory.active_ids(), (
            "找到的結果應該自動 activate 進 Working Memory，不用再另外呼叫 recall"
        )
        print("[PASS] test_search_memory_tool_activates_results_into_working_memory")
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_search_memory_tool_no_match_message():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(path)
    try:
        agent = _make_agent(path)
        result = agent.search_memory("不存在的東西")
        assert "沒有找到" in result
        print("[PASS] test_search_memory_tool_no_match_message")
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_search_memory_registered_as_tool():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(path)
    try:
        agent = _make_agent(path)
        assert "search_memory" in agent.available_functions
        agent.remember("x", "Fact", "一些內容")
        content = '<|tool_call|>call:search_memory("內容")<|tool_call|>'
        is_tool, combined, interleaved = agent._execute_tools(content)
        assert is_tool is True
        assert "找到" in combined
        print("[PASS] test_search_memory_registered_as_tool")
    finally:
        if os.path.exists(path):
            os.remove(path)


if __name__ == "__main__":
    tests = [
        test_search_matches_id,
        test_search_matches_type,
        test_search_matches_summary,
        test_search_is_case_insensitive,
        test_search_prioritizes_id_type_over_summary_match,
        test_search_no_match_returns_empty,
        test_search_respects_limit,
        test_empty_keyword_returns_empty,
        test_search_memory_tool_activates_results_into_working_memory,
        test_search_memory_tool_no_match_message,
        test_search_memory_registered_as_tool,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
