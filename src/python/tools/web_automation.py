"""
瀏覽器自動化工具：讓 agent 可以直接控制一個開了 remote-debugging 的 Chrome，
讀取網頁文件內容、點擊網頁上的元素——而不是只能用滑鼠座標＋螢幕截圖去猜。

設計取捨：
- 刻意不用 Playwright / Selenium 這類重量級瀏覽器自動化框架。他們會自己管理一套
  獨立的 driver 生命週期、常常需要另外下載自己的瀏覽器二進位檔，跟這個專案
  「直接控制使用者自己這台電腦上已經在用的 Chrome」的精神不合，也違背整個
  多模型架構「輕量、按需載入」的取向。DevTools Protocol (CDP) 本身只是一個
  輕量的 JSON-RPC over WebSocket 協定，直接講就夠用了。
- 用 --remote-debugging-port=9333，刻意跟 main.py 裡 pywebview 自己的 WebView2
  除錯埠 9222 分開，避免搶同一個埠。
- 用一個獨立的 user-data-dir 啟動 Chrome，不會動到使用者平常在用的 Chrome
  視窗/登入狀態——這是全新、獨立的一份瀏覽器 profile。
- browser_read_page 刻意不是整包回傳原始 HTML（對 LLM 來說太貴、雜訊太多），
  而是回傳「文字節錄 + 可互動元素清單（含可以直接拿去用的 CSS 選擇器）」，
  呼應 read_screen_api 對桌面 UI 做的事——只是這裡是對網頁 DOM 做同樣的事。
"""

import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

DEBUG_PORT = 9333

_CHROME_CANDIDATE_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


class CDPSession:
    """跟單一個 Chrome tab 之間，透過 DevTools Protocol 溝通的最小客戶端。

    刻意接收「已經建立好連線的 ws 物件」而不是自己去連，方便測試時注入假的
    ws 物件（不需要真的啟動瀏覽器就能測完整個訊息收發/比對 id/錯誤處理邏輯）。
    """

    def __init__(self, ws):
        self.ws = ws
        self._msg_id = 0
        self._lock = threading.Lock()

    def send(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> Dict[str, Any]:
        with self._lock:
            self._msg_id += 1
            msg_id = self._msg_id
            payload = {"id": msg_id, "method": method, "params": params or {}}
            self.ws.send(json.dumps(payload))
            deadline = time.time() + timeout
            while time.time() < deadline:
                raw = self.ws.recv()
                data = json.loads(raw)
                # CDP 除了我們要的回應之外，也會推播一堆事件通知（沒有 id），
                # 這裡只在意「id 對得上」的那一筆，其他一律忽略、繼續等。
                if data.get("id") == msg_id:
                    if "error" in data:
                        raise RuntimeError(f"CDP 呼叫 {method} 失敗: {data['error']}")
                    return data.get("result", {})
            raise TimeoutError(f"CDP 呼叫 {method} 逾時（{timeout} 秒內沒有收到對應的回應）")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


_state: Dict[str, Any] = {"process": None, "session": None}


def _find_chrome_binary() -> Optional[str]:
    for p in _CHROME_CANDIDATE_PATHS:
        if p and os.path.exists(p):
            return p
    return None


def _http_get_json(url: str, timeout: float = 3.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def _is_debug_port_alive() -> bool:
    try:
        _http_get_json(f"http://127.0.0.1:{DEBUG_PORT}/json/version", timeout=1.0)
        return True
    except Exception:
        return False


def _launch_chrome() -> subprocess.Popen:
    chrome_path = _find_chrome_binary()
    if not chrome_path:
        raise RuntimeError(
            "找不到 Chrome 執行檔，已檢查過的預設安裝路徑都不存在。"
            "如果 Chrome 裝在非預設位置，這個工具目前沒辦法自動找到，"
            "請如實告知使用者這個工具在這台機器上暫時用不了。"
        )
    profile_dir = os.path.join(tempfile.gettempdir(), "desktop_agent_chrome_profile")
    return subprocess.Popen([
        chrome_path,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ])


def _pick_or_create_tab() -> Dict[str, Any]:
    tabs = _http_get_json(f"http://127.0.0.1:{DEBUG_PORT}/json/list")
    page_tabs = [t for t in tabs if t.get("type") == "page"]
    if page_tabs:
        return page_tabs[0]
    return _http_get_json(f"http://127.0.0.1:{DEBUG_PORT}/json/new")


def _ensure_chrome_running_and_get_tab() -> Dict[str, Any]:
    if not _is_debug_port_alive():
        _state["process"] = _launch_chrome()
        for _ in range(50):  # 最多等 10 秒
            time.sleep(0.2)
            if _is_debug_port_alive():
                break
        else:
            raise RuntimeError("Chrome 啟動後 debug port 一直沒有回應，可能啟動失敗或被防火牆擋住。")
    return _pick_or_create_tab()


def _get_session() -> CDPSession:
    if _state["session"] is not None:
        return _state["session"]

    try:
        import websocket  # websocket-client，選用依賴，只有真的用到這個工具才需要
    except ImportError as e:
        raise RuntimeError(
            "需要先安裝 websocket-client 套件才能使用瀏覽器自動化工具：pip install websocket-client"
        ) from e

    tab = _ensure_chrome_running_and_get_tab()
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("拿到的分頁沒有 webSocketDebuggerUrl，無法建立 CDP 連線。")

    ws = websocket.create_connection(ws_url, timeout=10)
    session = CDPSession(ws)
    session.send("Page.enable")
    session.send("Runtime.enable")
    _state["session"] = session
    return session


def _eval_js(session: CDPSession, expression: str) -> Any:
    result = session.send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    return result.get("result", {}).get("value")


def _wait_for_page_load(session: CDPSession, timeout: float = 15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _eval_js(session, "document.readyState") == "complete":
            return
        time.sleep(0.3)


_READ_PAGE_JS_TEMPLATE = r"""
(function() {
    function cssPath(el) {
        if (el.id) return '#' + CSS.escape(el.id);
        var path = [];
        while (el && el.nodeType === 1 && path.length < 5) {
            var selector = el.tagName.toLowerCase();
            if (el.className && typeof el.className === 'string') {
                var cls = el.className.trim().split(/\s+/).slice(0, 2).join('.');
                if (cls) selector += '.' + CSS.escape(cls);
            }
            var siblings = el.parentNode
                ? Array.prototype.filter.call(el.parentNode.children, function(c) { return c.tagName === el.tagName; })
                : [];
            if (siblings.length > 1) selector += ':nth-of-type(' + (siblings.indexOf(el) + 1) + ')';
            path.unshift(selector);
            el = el.parentElement;
        }
        return path.join(' > ');
    }
    var elements = [];
    var interactive = document.querySelectorAll('a, button, input, textarea, select, [role="button"], [onclick]');
    for (var i = 0; i < interactive.length && elements.length < %(max_elements)d; i++) {
        var el = interactive[i];
        var rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        var label = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0, 60);
        elements.push({tag: el.tagName.toLowerCase(), label: label, selector: cssPath(el)});
    }
    return JSON.stringify({
        title: document.title,
        url: location.href,
        text: document.body ? document.body.innerText.slice(0, 3000) : '',
        elements: elements
    });
})()
"""


def _format_read_page_result(data: Dict[str, Any]) -> str:
    lines = [f"標題: {data.get('title', '')}", f"網址: {data.get('url', '')}", "", "頁面文字（節錄）:", data.get("text", ""), "", "可互動元素:"]
    for el in data.get("elements", []):
        lines.append(f"- [{el.get('tag')}] {el.get('label')!r} → 選擇器: {el.get('selector')}")
    return "\n".join(lines)


def browser_open(url: str = "", _session: Optional[CDPSession] = None) -> str:
    session = _session or _get_session()
    if url:
        session.send("Page.navigate", {"url": url})
        _wait_for_page_load(session)
    current_url = _eval_js(session, "location.href")
    return f"已開啟 Chrome（debug mode，獨立 profile，不影響使用者平常的 Chrome），目前網址: {current_url}"


def browser_read_page(max_elements: int = 60, _session: Optional[CDPSession] = None) -> str:
    session = _session or _get_session()
    script = _READ_PAGE_JS_TEMPLATE % {"max_elements": max_elements}
    raw = _eval_js(session, script)
    if not raw:
        return "讀取頁面失敗，可能還沒導航到任何網址——先呼叫 browser_open(url) 開一個頁面。"
    data = json.loads(raw)
    return _format_read_page_result(data)


def browser_click(selector: str, _session: Optional[CDPSession] = None) -> str:
    session = _session or _get_session()
    script = (
        "(function() {"
        f"var el = document.querySelector({json.dumps(selector)});"
        "if (!el) return 'NOT_FOUND';"
        "el.scrollIntoView({block: 'center'});"
        "el.click();"
        "return 'OK';"
        "})()"
    )
    result = _eval_js(session, script)
    if result == "NOT_FOUND":
        return f"找不到符合選擇器 {selector} 的元素，頁面內容可能已經變了，建議重新呼叫 browser_read_page() 確認目前狀態。"
    _wait_for_page_load(session, timeout=5.0)
    current_url = _eval_js(session, "location.href")
    return f"已點擊 {selector}，目前網址: {current_url}"


def browser_type(selector: str, text: str, _session: Optional[CDPSession] = None) -> str:
    session = _session or _get_session()
    script = (
        "(function() {"
        f"var el = document.querySelector({json.dumps(selector)});"
        "if (!el) return 'NOT_FOUND';"
        "el.focus();"
        f"el.value = {json.dumps(text)};"
        "el.dispatchEvent(new Event('input', {bubbles: true}));"
        "el.dispatchEvent(new Event('change', {bubbles: true}));"
        "return 'OK';"
        "})()"
    )
    result = _eval_js(session, script)
    if result == "NOT_FOUND":
        return f"找不到符合選擇器 {selector} 的元素，建議先呼叫 browser_read_page() 確認選擇器是否還正確。"
    return f"已在 {selector} 輸入文字。"


def browser_close() -> str:
    if _state["session"] is not None:
        _state["session"].close()
        _state["session"] = None
    if _state["process"] is not None:
        try:
            _state["process"].terminate()
        except Exception:
            pass
        _state["process"] = None
    return "已關閉 debug mode Chrome。"
