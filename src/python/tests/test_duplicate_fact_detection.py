import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
"""
測試 remember() 新增的「這個摘要跟既有節點很像，可能是重複」提醒（設計文件第 2 點：
只保存唯一事實，不要讓同一件事被存成好幾個不同的 id）。

這只是提示，不是強制擋下——語意判斷本來就沒有絕對答案，交給模型自己決定
要不要處理，系統只負責在寫入當下就提醒，而不是讓重複悄悄發生而沒人注意到。
"""
import tempfile

from agent.agent_core import AgentWorker, AgentState
from agent.task_system import ExecutionMode


def make_agent(memory_path):
    agent = AgentWorker({}, event_callback=lambda t, d: None,
                         default_mode=ExecutionMode.AUTO, memory_path=memory_path)
    return agent


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
def test_first_remember_of_a_concept_has_no_warning(memory_path):
    agent = make_agent(memory_path)
    result = agent.remember("rust_ownership", "Concept", "Rust 的所有權機制")
    assert "⚠️" not in result


@with_temp_memory
def test_very_similar_summary_under_different_id_triggers_warning(memory_path):
    agent = make_agent(memory_path)
    agent.remember("rust_ownership", "Concept", "Rust 語言的所有權機制說明")
    result = agent.remember("ownership_in_rust", "Concept", "Rust 語言的所有權機制介紹")

    assert "⚠️" in result
    assert "rust_ownership" in result, "警告裡應該指名是跟哪個既有 id 很像"


@with_temp_memory
def test_clearly_different_summaries_do_not_trigger_warning(memory_path):
    agent = make_agent(memory_path)
    agent.remember("rust_ownership", "Concept", "Rust 語言的所有權機制")
    result = agent.remember("dinner_with_friend", "Event", "昨天跟朋友吃牛排")
    assert "⚠️" not in result


@with_temp_memory
def test_different_type_does_not_trigger_warning_even_if_summary_similar(memory_path):
    """就算摘要文字很像，只要 type 不同，通常不是『同一件事存成兩個 id』的情況，
    不該誤判成重複——例如一個 Function 節點的摘要恰好跟一個 Fact 節點很像，
    純屬巧合，不該被當成重複警告。
    """
    agent = make_agent(memory_path)
    agent.remember("func_a", "Function", "處理使用者輸入的驗證邏輯")
    result = agent.remember("fact_b", "Fact", "處理使用者輸入的驗證邏輯")
    assert "⚠️" not in result


@with_temp_memory
def test_updating_existing_id_does_not_trigger_warning(memory_path):
    """remember 同一個 id 兩次是正常的更新操作（upsert），不該被當成跟自己重複。"""
    agent = make_agent(memory_path)
    agent.remember("rust_ownership", "Concept", "Rust 的所有權機制")
    result = agent.remember("rust_ownership", "Concept", "Rust 的所有權機制（更新版）")
    assert "⚠️" not in result


@with_temp_memory
def test_empty_summary_does_not_trigger_warning_check(memory_path):
    """沒有摘要就沒有文字可以比對相似度，直接跳過檢查，不該因此出錯。"""
    agent = make_agent(memory_path)
    agent.remember("rust_ownership", "Concept", "Rust 的所有權機制")
    result = agent.remember("something_else", "Concept", "")
    assert "⚠️" not in result


@with_temp_memory
def test_warning_picks_the_most_similar_existing_node_when_multiple_exist(memory_path):
    agent = make_agent(memory_path)
    agent.remember("topic_unrelated", "Concept", "昨天的天氣很好")
    agent.remember("topic_close", "Concept", "Rust 語言的所有權機制說明")
    result = agent.remember("topic_new", "Concept", "Rust 語言的所有權機制介紹")

    assert "⚠️" in result
    assert "topic_close" in result
    assert "topic_unrelated" not in result


if __name__ == "__main__":
    test_first_remember_of_a_concept_has_no_warning()
    print("[PASS] test_first_remember_of_a_concept_has_no_warning")
    test_very_similar_summary_under_different_id_triggers_warning()
    print("[PASS] test_very_similar_summary_under_different_id_triggers_warning")
    test_clearly_different_summaries_do_not_trigger_warning()
    print("[PASS] test_clearly_different_summaries_do_not_trigger_warning")
    test_different_type_does_not_trigger_warning_even_if_summary_similar()
    print("[PASS] test_different_type_does_not_trigger_warning_even_if_summary_similar")
    test_updating_existing_id_does_not_trigger_warning()
    print("[PASS] test_updating_existing_id_does_not_trigger_warning")
    test_empty_summary_does_not_trigger_warning_check()
    print("[PASS] test_empty_summary_does_not_trigger_warning_check")
    test_warning_picks_the_most_similar_existing_node_when_multiple_exist()
    print("[PASS] test_warning_picks_the_most_similar_existing_node_when_multiple_exist")
