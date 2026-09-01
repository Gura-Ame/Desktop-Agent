import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.web_automation import (
    CDPSession,
    browser_click,
    browser_open,
    browser_read_page,
    browser_type,
    _format_read_page_result,
)


class FakeWebSocket:
    """假的 websocket 連線物件，模擬一問一答：send() 記錄送出的訊息，
    recv() 從預先準備好的回應佇列吐出下一筆，讓 CDPSession 可以完全在
    不連真的 Chrome 的情況下被測試。
    """

    def __init__(self):
        self.sent: list[dict] = []
        self._responses: list[dict] = []
        self.closed = False

    def queue_result(self, result: dict):
        """依照送出順序，幫下一次 send() 準備好對應的回應（id 會自動對齊）。"""
        self._responses.append(result)

    def send(self, raw: str):
        self.sent.append(json.loads(raw))

    def recv(self) -> str:
        msg = self.sent[-1]
        result = self._responses.pop(0) if self._responses else {}
        return json.dumps({"id": msg["id"], "result": result})

    def close(self):
        self.closed = True


class TestCDPSession(unittest.TestCase):
    def test_send_matches_response_by_id_and_returns_result(self):
        ws = FakeWebSocket()
        ws.queue_result({"value": 42})
        session = CDPSession(ws)

        result = session.send("Runtime.evaluate", {"expression": "1+1"})

        self.assertEqual(result, {"value": 42})
        self.assertEqual(ws.sent[0]["method"], "Runtime.evaluate")
        self.assertEqual(ws.sent[0]["params"], {"expression": "1+1"})

    def test_message_ids_increment_and_stay_unique(self):
        ws = FakeWebSocket()
        ws.queue_result({})
        ws.queue_result({})
        session = CDPSession(ws)

        session.send("Page.enable")
        session.send("Runtime.enable")

        self.assertEqual(ws.sent[0]["id"], 1)
        self.assertEqual(ws.sent[1]["id"], 2)

    def test_cdp_error_response_raises_runtime_error(self):
        ws = FakeWebSocket()

        class ErrorWs(FakeWebSocket):
            def recv(self):
                msg = self.sent[-1]
                return json.dumps({"id": msg["id"], "error": {"message": "壞掉了"}})

        session = CDPSession(ErrorWs())
        with self.assertRaises(RuntimeError):
            session.send("Page.navigate", {"url": "https://example.com"})

    def test_close_calls_underlying_websocket_close(self):
        ws = FakeWebSocket()
        session = CDPSession(ws)
        session.close()
        self.assertTrue(ws.closed)

    def test_close_does_not_raise_if_underlying_close_fails(self):
        class BrokenWs(FakeWebSocket):
            def close(self):
                raise ConnectionError("已經斷線了")

        session = CDPSession(BrokenWs())
        session.close()  # 不該拋出例外


class FakeSession:
    """給高階函式（browser_open/browser_read_page/...）用的假 session，
    直接用一個 method -> 回傳值 的對照表模擬 CDPSession.send 的行為，
    比起模擬到 websocket 層級更直接，適合測試這幾個函式自己的邏輯
    （組出來的 JS 對不對、怎麼解析回傳值、怎麼處理找不到元素的情況）。
    """

    def __init__(self, eval_results: list):
        # 每次呼叫 Runtime.evaluate 依序吐出 eval_results 裡的下一個值
        self._eval_results = list(eval_results)
        self.calls: list[tuple] = []

    def send(self, method, params=None, timeout=10.0):
        self.calls.append((method, params))
        if method == "Runtime.evaluate":
            value = self._eval_results.pop(0) if self._eval_results else None
            return {"result": {"value": value}}
        return {}


class TestBrowserOpen(unittest.TestCase):
    def test_navigates_and_reports_current_url(self):
        session = FakeSession(eval_results=["complete", "https://example.com/"])
        result = browser_open("https://example.com", _session=session)

        nav_calls = [c for c in session.calls if c[0] == "Page.navigate"]
        self.assertEqual(len(nav_calls), 1)
        self.assertEqual(nav_calls[0][1], {"url": "https://example.com"})
        self.assertIn("https://example.com/", result)
        self.assertIn("不影響使用者平常的 Chrome", result)

    def test_empty_url_does_not_navigate_just_reports_current_page(self):
        session = FakeSession(eval_results=["https://already-open.example/"])
        result = browser_open("", _session=session)

        nav_calls = [c for c in session.calls if c[0] == "Page.navigate"]
        self.assertEqual(nav_calls, [])
        self.assertIn("already-open.example", result)


class TestBrowserReadPage(unittest.TestCase):
    def test_formats_title_url_text_and_elements(self):
        page_data = {
            "title": "範例頁面",
            "url": "https://example.com/",
            "text": "這是頁面內容",
            "elements": [
                {"tag": "a", "label": "登入", "selector": "#login-link"},
                {"tag": "button", "label": "送出", "selector": "form > button"},
            ],
        }
        session = FakeSession(eval_results=[json.dumps(page_data)])

        result = browser_read_page(_session=session)

        self.assertIn("範例頁面", result)
        self.assertIn("https://example.com/", result)
        self.assertIn("這是頁面內容", result)
        self.assertIn("#login-link", result)
        self.assertIn("form > button", result)

    def test_no_page_loaded_yet_gives_helpful_message_not_crash(self):
        session = FakeSession(eval_results=[None])
        result = browser_read_page(_session=session)
        self.assertIn("browser_open", result)

    def test_max_elements_is_embedded_into_generated_script(self):
        session = FakeSession(eval_results=[json.dumps({"title": "", "url": "", "text": "", "elements": []})])
        browser_read_page(max_elements=5, _session=session)

        eval_calls = [c for c in session.calls if c[0] == "Runtime.evaluate"]
        script = eval_calls[0][1]["expression"]
        self.assertIn("elements.length < 5", script)


class TestBrowserClick(unittest.TestCase):
    def test_click_success_reports_new_url(self):
        session = FakeSession(eval_results=["OK", "complete", "https://example.com/after-click"])
        result = browser_click("#submit-button", _session=session)
        self.assertIn("已點擊 #submit-button", result)
        self.assertIn("https://example.com/after-click", result)

    def test_click_not_found_returns_actionable_message_not_crash(self):
        session = FakeSession(eval_results=["NOT_FOUND"])
        result = browser_click(".stale-selector", _session=session)
        self.assertIn("找不到", result)
        self.assertIn("browser_read_page", result)

    def test_selector_is_json_escaped_in_generated_script(self):
        """selector 裡如果剛好有雙引號或反斜線，不能讓組出來的 JS 語法壞掉。"""
        session = FakeSession(eval_results=["OK", "complete", "https://x/"])
        tricky_selector = 'div[data-x="a\\"b"]'
        browser_click(tricky_selector, _session=session)

        eval_calls = [c for c in session.calls if c[0] == "Runtime.evaluate"]
        script = eval_calls[0][1]["expression"]
        # 組出來的內容必須是合法 JSON 字串常值，能被 json.loads 解析回同一個字串
        import re
        m = re.search(r"document\.querySelector\((.+?)\);", script)
        self.assertIsNotNone(m)
        self.assertEqual(json.loads(m.group(1)), tricky_selector)


class TestBrowserType(unittest.TestCase):
    def test_type_success(self):
        session = FakeSession(eval_results=["OK"])
        result = browser_type("#search", "hello world", _session=session)
        self.assertIn("已在 #search 輸入文字", result)

    def test_type_not_found(self):
        session = FakeSession(eval_results=["NOT_FOUND"])
        result = browser_type("#missing", "text", _session=session)
        self.assertIn("找不到", result)

    def test_text_with_quotes_is_safely_embedded(self):
        session = FakeSession(eval_results=["OK"])
        tricky_text = 'she said "hello" and \\ backslash'
        browser_type("#input", tricky_text, _session=session)

        eval_calls = [c for c in session.calls if c[0] == "Runtime.evaluate"]
        script = eval_calls[0][1]["expression"]
        import re
        m = re.search(r"el\.value = (.+?);", script)
        self.assertIsNotNone(m)
        self.assertEqual(json.loads(m.group(1)), tricky_text)


class TestFormatReadPageResult(unittest.TestCase):
    def test_handles_missing_fields_gracefully(self):
        # 就算某些欄位缺漏，也不該整個拋例外
        result = _format_read_page_result({})
        self.assertIn("標題:", result)
        self.assertIn("可互動元素:", result)


if __name__ == "__main__":
    unittest.main()
