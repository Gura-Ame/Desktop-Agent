"""
logging_setup.py 的測試。重點驗證：訊息真的會被印出來、level 對應到正確
的方法、channel 會出現在輸出裡、有沒有顏色由 use_color 控制而不是硬編碼、
不認得的 level 字串會安全退回 info 而不是拋例外。
"""
import io
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from logging_setup import ColoredFormatter, log, _logger


def _capture_output(fn):
    """暫時把 _logger 的 handler 換成寫到記憶體緩衝區的，跑完 fn() 之後
    回傳緩衝區內容，並把原本的 handler 換回去——不影響其他測試共用的
    全域 logger 狀態。
    """
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(ColoredFormatter(use_color=False))

    original_handlers = _logger.handlers[:]
    _logger.handlers = [handler]
    try:
        fn()
    finally:
        _logger.handlers = original_handlers
    return buffer.getvalue()


def test_log_default_level_is_info():
    output = _capture_output(lambda: log("hello world"))
    assert "INFO" in output
    assert "hello world" in output
    print("[PASS] test_log_default_level_is_info")


def test_log_respects_explicit_level():
    output = _capture_output(lambda: log("careful now", level="warning"))
    assert "WARNING" in output
    assert "careful now" in output
    print("[PASS] test_log_respects_explicit_level")


def test_log_unknown_level_falls_back_to_info_without_raising():
    output = _capture_output(lambda: log("something", level="not_a_real_level"))
    assert "INFO" in output
    assert "something" in output
    print("[PASS] test_log_unknown_level_falls_back_to_info_without_raising")


def test_log_includes_channel_label_when_given():
    output = _capture_output(lambda: log("from frontend", channel="frontend"))
    assert "[frontend]" in output
    print("[PASS] test_log_includes_channel_label_when_given")


def test_log_without_channel_has_no_bracket_label():
    output = _capture_output(lambda: log("plain message"))
    import re
    assert not re.search(r"\[\w+\]", output)
    print("[PASS] test_log_without_channel_has_no_bracket_label")


def test_colored_formatter_adds_ansi_codes_when_color_enabled():
    record = logging.LogRecord(
        name="test", level=logging.ERROR, pathname="", lineno=0,
        msg="boom", args=(), exc_info=None,
    )
    formatted = ColoredFormatter(use_color=True).format(record)
    assert "\x1b[" in formatted
    print("[PASS] test_colored_formatter_adds_ansi_codes_when_color_enabled")


def test_colored_formatter_has_no_ansi_codes_when_color_disabled():
    record = logging.LogRecord(
        name="test", level=logging.ERROR, pathname="", lineno=0,
        msg="boom", args=(), exc_info=None,
    )
    formatted = ColoredFormatter(use_color=False).format(record)
    assert "\x1b[" not in formatted
    assert "boom" in formatted
    print("[PASS] test_colored_formatter_has_no_ansi_codes_when_color_disabled")


def test_error_level_uses_error_color():
    record = logging.LogRecord(
        name="test", level=logging.ERROR, pathname="", lineno=0,
        msg="oops", args=(), exc_info=None,
    )
    formatted = ColoredFormatter(use_color=True).format(record)
    assert "\x1b[31m" in formatted  # 紅色
    print("[PASS] test_error_level_uses_error_color")


def test_log_accepts_non_string_message():
    output = _capture_output(lambda: log({"key": "value"}))
    assert "key" in output
    print("[PASS] test_log_accepts_non_string_message")


if __name__ == "__main__":
    tests = [
        test_log_default_level_is_info,
        test_log_respects_explicit_level,
        test_log_unknown_level_falls_back_to_info_without_raising,
        test_log_includes_channel_label_when_given,
        test_log_without_channel_has_no_bracket_label,
        test_colored_formatter_adds_ansi_codes_when_color_enabled,
        test_colored_formatter_has_no_ansi_codes_when_color_disabled,
        test_error_level_uses_error_color,
        test_log_accepts_non_string_message,
        test_agent_emit_log_event_also_prints_via_logging_setup,
        test_agent_emit_non_log_event_does_not_print,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")


def test_agent_emit_log_event_also_prints_via_logging_setup():
    """agent_core.py 的 AgentWorker.emit() 對 "log" 事件應該除了照原本的
    路徑送給前端，也順手印到這裡的統一 log() 入口——這是「把面板 log
    併到 VS Code console」這個需求實際落地的地方，不是只有 logging_setup
    模組本身要work，還要真的被 AgentWorker 用到。
    """
    import tempfile
    from agent.agent_core import AgentWorker

    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)

    captured = []
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(ColoredFormatter(use_color=False))
    original_handlers = _logger.handlers[:]
    _logger.handlers = [handler]
    try:
        agent = AgentWorker({}, event_callback=lambda t, d: captured.append((t, d)),
                             memory_path=memory_path)
        agent.emit("log", "這是一則測試訊息")
        output = buffer.getvalue()
        assert "這是一則測試訊息" in output
        assert "[agent]" in output
        # 原本送給前端 event_callback 的路徑也不該被拿掉
        assert ("log", "這是一則測試訊息") in captured
        print("[PASS] test_agent_emit_log_event_also_prints_via_logging_setup")
    finally:
        _logger.handlers = original_handlers
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_agent_emit_non_log_event_does_not_print():
    """只有 "log" 這個事件類型才會被印出來，其他事件類型（chunk、
    permission_request…）不該被這個新邏輯意外攔截去印一堆雜訊。
    """
    import tempfile
    from agent.agent_core import AgentWorker

    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)

    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(ColoredFormatter(use_color=False))
    original_handlers = _logger.handlers[:]
    _logger.handlers = [handler]
    try:
        agent = AgentWorker({}, event_callback=lambda t, d: None, memory_path=memory_path)
        agent.emit("chunk", "這不該被印出來")
        output = buffer.getvalue()
        assert "這不該被印出來" not in output
        print("[PASS] test_agent_emit_non_log_event_does_not_print")
    finally:
        _logger.handlers = original_handlers
        if os.path.exists(memory_path):
            os.remove(memory_path)
