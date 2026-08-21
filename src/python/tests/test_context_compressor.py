import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
"""
context_compressor.py 的單元測試。純 stdlib + memory_store，不需要真的 LLM。

執行方式：
    python test_context_compressor.py
"""

import os
import sys
import tempfile


from memory.memory_store import MemoryStore  # noqa: E402
from agent.context_compressor import ContextCompressor  # noqa: E402


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
def test_baseline_established_once_and_is_idempotent(store):
    c = ContextCompressor(store, growth_ratio=0.2)
    c.establish_baseline(100)
    assert c.baseline_tokens == 100
    c.establish_baseline(999)  # 第二次呼叫應該是 no-op
    assert c.baseline_tokens == 100
    print("[PASS] test_baseline_established_once_and_is_idempotent")


@with_temp_store
def test_reset_baseline_allows_new_value(store):
    c = ContextCompressor(store)
    c.establish_baseline(100)
    c.reset_baseline()
    assert c.baseline_tokens is None
    c.establish_baseline(50)
    assert c.baseline_tokens == 50
    print("[PASS] test_reset_baseline_allows_new_value")


@with_temp_store
def test_should_compress_threshold(store):
    c = ContextCompressor(store, growth_ratio=0.2)
    c.establish_baseline(1000)
    assert c.should_compress(1100) is False, "成長 10%，還沒到 20% 門檻"
    assert c.should_compress(1200) is False, "剛好 20%，用嚴格大於，不觸發"
    assert c.should_compress(1201) is True, "超過 20% 才要壓縮"
    print("[PASS] test_should_compress_threshold")


@with_temp_store
def test_should_compress_false_without_baseline(store):
    c = ContextCompressor(store)
    assert c.should_compress(999999) is False, "還沒建立基準前不應該觸發壓縮"
    print("[PASS] test_should_compress_false_without_baseline")


@with_temp_store
def test_estimate_tokens_consistent(store):
    c = ContextCompressor(store)
    short = [{"role": "user", "content": "hi"}]
    long_ = [{"role": "user", "content": "x" * 1000}]
    assert c.estimate_tokens(short) < c.estimate_tokens(long_)
    print("[PASS] test_estimate_tokens_consistent")


@with_temp_store
def test_compress_short_history_is_noop(store):
    c = ContextCompressor(store)
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]

    def fail_if_called(system_prompt, user_prompt):
        raise AssertionError("歷史這麼短不應該真的去呼叫模型壓縮")

    result = c.compress(fail_if_called, history, keep_last_turns=2)
    assert result == history
    print("[PASS] test_compress_short_history_is_noop")


@with_temp_store
def test_compress_writes_structured_facts_and_shrinks_history(store):
    c = ContextCompressor(store, growth_ratio=0.2)

    history = [
        {"role": "user", "content": "幫我規劃一個三天的東京行程"},
        {"role": "assistant", "content": "好的，第一天建議去淺草寺..."},
        {"role": "user", "content": "我不喜歡人多的地方，換一個"},
        {"role": "assistant", "content": "了解，改成去代代木公園..."},
        {"role": "user", "content": "第二天呢？"},
        {"role": "assistant", "content": "第二天可以去箱根一日遊..."},
    ]

    fake_llm_response = (
        "- id: trip_preference\n"
        "- type: Constraint\n"
        "- summary: 使用者不喜歡人多的地方，行程要避開熱門觀光區\n"
        "- detail: 已把淺草寺換成代代木公園\n"
        "- id: trip_day2\n"
        "- type: Decision\n"
        "- summary: 第二天安排箱根一日遊\n"
        "- detail: \n"
    )

    def fake_call_llm(system_prompt, user_prompt):
        assert "上下文壓縮器" in system_prompt
        assert "淺草寺" in user_prompt, "要壓縮的內容應該有被組進 transcript"
        return fake_llm_response

    new_history = c.compress(fake_call_llm, history, keep_last_turns=2)

    # 1. history 應該明顯變短：只剩一則壓縮摘要 + 最後 2 輪原文
    assert len(new_history) == 3
    assert new_history[0]["role"] == "system"
    assert "trip_preference" not in new_history[0]["content"]  # id 不用出現在摘要文字裡
    assert "不喜歡人多" in new_history[0]["content"] or "避開熱門觀光區" in new_history[0]["content"]
    assert new_history[1] == history[-2]
    assert new_history[2] == history[-1]

    # 2. 結構化事實應該真的被寫進 MemoryStore
    node = store.get_node("trip_preference")
    assert node is not None
    assert node.type == "Constraint"
    assert "不喜歡人多" in node.summary

    node2 = store.get_node("trip_day2")
    assert node2 is not None
    assert node2.type == "Decision"

    # 3. baseline 應該根據壓縮後的新 history 重新校正過，不是沿用壓縮前的舊值
    assert c.baseline_tokens == c.estimate_tokens(new_history)

    print("[PASS] test_compress_writes_structured_facts_and_shrinks_history")


@with_temp_store
def test_compress_handles_response_with_no_parsable_facts(store):
    c = ContextCompressor(store)
    history = [{"role": "user", "content": f"turn {i}"} for i in range(6)]

    new_history = c.compress(lambda s, u: "（模型亂回，格式不對）", history, keep_last_turns=2)

    assert len(new_history) == 3
    assert "沒有抽出明確的結構化事實" in new_history[0]["content"]
    assert new_history[1:] == history[-2:]
    print("[PASS] test_compress_handles_response_with_no_parsable_facts")


if __name__ == "__main__":
    tests = [
        test_baseline_established_once_and_is_idempotent,
        test_reset_baseline_allows_new_value,
        test_should_compress_threshold,
        test_should_compress_false_without_baseline,
        test_estimate_tokens_consistent,
        test_compress_short_history_is_noop,
        test_compress_writes_structured_facts_and_shrinks_history,
        test_compress_handles_response_with_no_parsable_facts,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
