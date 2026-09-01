import sys
import subprocess
import urllib.parse
import os
import json
import warnings
import threading
import pyautogui

# 必須在 QApplication 初始化前導入（實際的 QApplication/視窗建立已經搬到
# webview_bootstrap.py 的 run_app 裡，這裡 import 只是為了保留這個初始化順序
# 的前置要求：PyQt6.QtWebEngineWidgets 一定要在任何 QApplication 產生之前
# import 過一次，不然某些 WebEngine 功能會出問題）。
import PyQt6.QtWebEngineWidgets

os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = '--remote-debugging-port=9222'
os.environ["QT_LOGGING_RULES"] = "qt.qpa.window.warning=false"
warnings.filterwarnings("ignore", category=UserWarning, module="pywinauto")

import tools.automation_tools as tools
from overlay import ScreenOverlay, OverlayManager
from agent.agent_core import AgentWorker, AgentState
from agent.task_system import ExecutionMode

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.5


class JsApi:
    def __init__(self, overlay):
        self._window = None
        self.overlay = overlay
        self.overlay_manager = OverlayManager(self.overlay)

        # 執行緒安全：背景只 append，前端用 poll_events 拉取
        # 完全不呼叫 evaluate_js，也不依賴 QTimer（避免 PyQt5/PyQt6 混用）
        self._events = []
        self._events_lock = threading.Lock()

        self.available_functions = {
            "open_chrome_incognito": self.open_chrome_incognito,
            "move_mouse": tools.move_mouse,
            "click_mouse": tools.click_mouse,
            "type_text": tools.type_text,
            "get_screen_size": tools.get_screen_size,
            "get_mouse_position": tools.get_mouse_position,
            "get_active_window": tools.get_active_window,
            "inspect_window": tools.inspect_window,
            "search_installed_apps": tools.search_installed_apps,
            "launch_app": tools.launch_app,
            "draw_box": self.overlay_manager.draw_box,
            "draw_line": self.overlay_manager.draw_line,
            "draw_stroke": self.overlay_manager.draw_stroke,
            "clear_drawings": self.overlay_manager.clear_drawings,
            "execute_python": tools.execute_python,
            "read_screen_api": tools.read_screen_api,
            "query_screen_element": tools.query_screen_element,
            "analyze_image_visuals": tools.analyze_image_visuals,
            "analyze_image_ocr": tools.analyze_image_ocr,
            "unload_florence_model": tools.unload_florence_model,
            "unload_paddleocr_model": tools.unload_paddleocr_model,
            "unload_all_vision_models": tools.unload_all_vision_models,
            "browser_open": tools.browser_open,
            "browser_read_page": tools.browser_read_page,
            "browser_click": tools.browser_click,
            "browser_type": tools.browser_type,
            "browser_close": tools.browser_close,
        }

        self.agent = AgentWorker(
            self.available_functions,
            event_callback=self.dispatch_event,
        )

    def set_window(self, window):
        self._window = window

    def dispatch_event(self, event_type: str, data):
        """可從任意執行緒安全呼叫。"""
        # 確保 data 可被 JSON 序列化（poll 時回傳給 JS）
        try:
            json.dumps(data, ensure_ascii=False, default=str)
            safe_data = data
        except Exception:
            safe_data = str(data)

        with self._events_lock:
            self._events.append({"type": event_type, "data": safe_data})

    def poll_events(self):
        """前端定時呼叫。在 pywebview 的 JS bridge 執行緒執行，安全。
        回傳事件列表；chunk 會在同一次 poll 內合併成一筆，減少前端 setState 次數。
        """
        with self._events_lock:
            if not self._events:
                return []
            batch = self._events[:]
            self._events.clear()

        # 合併連續的 chunk
        merged = []
        chunk_buf = []
        for ev in batch:
            if ev["type"] == "chunk":
                chunk_buf.append(ev["data"] if ev["data"] is not None else "")
            else:
                if chunk_buf:
                    merged.append({"type": "chunk", "data": "".join(chunk_buf)})
                    chunk_buf = []
                merged.append(ev)
        if chunk_buf:
            merged.append({"type": "chunk", "data": "".join(chunk_buf)})
        return merged

    # ------------------------------------------------------------------
    # 前端可呼叫的 API
    # ------------------------------------------------------------------
    def send_prompt(self, prompt: str, images=None):
        """
        prompt: 文字
        images: 可選，data URL 字串陣列（data:image/png;base64,...）
        """
        if self.agent.is_running():
            return {"status": "busy", "msg": "Agent 正忙碌中"}
        # pywebview 有時把 list 傳成 tuple / 單一 JSON 字串
        if images is None:
            img_list = []
        elif isinstance(images, str):
            img_list = [images] if images else []
        else:
            img_list = list(images)
        self.agent.set_user_prompt(prompt, images=img_list)
        self.agent.state = AgentState.IDLE
        self.agent.start()
        return {"status": "ok"}

    def stop_agent(self):
        """前端「停止」按鈕：中止目前 Agent 執行。"""
        if not self.agent.is_running():
            return {"status": "ok", "msg": "Agent 未在執行"}
        self.agent.request_stop()
        return {"status": "ok", "msg": "已請求停止"}

    def confirm_step(self):
        self.agent.confirm_and_start()

    def submit_user_input(self, text: str):
        self.agent.resume_with_user_input(text)

    def set_execution_mode(self, mode_str: str):
        try:
            mode = ExecutionMode[mode_str.upper()]
            self.agent.set_execution_mode(mode)
            return {"status": "ok", "mode": mode.value}
        except KeyError:
            return {"status": "error", "msg": f"未知模式: {mode_str}"}

    def set_forgetting_enabled(self, enabled: bool):
        self.agent.set_forgetting_enabled(enabled)
        return {"status": "ok", "enabled": enabled}

    def set_activation_enabled(self, enabled: bool):
        self.agent.set_activation_enabled(enabled)
        return {"status": "ok", "enabled": enabled}

    def update_api_config(self, base_url: str, api_key: str, model_name: str):
        self.agent.update_api_config(base_url, api_key, model_name)
        return {"status": "ok"}

    def load_llama_model(self, model_path: str, n_ctx: int = 8192, n_gpu_layers: int = -1):
        self.agent.load_llama_model(model_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers)
        self.dispatch_event("log", f"[系統] 已切換本地 Llama 模型: {model_path}")
        return {"status": "ok"}

    def open_chrome_incognito(self, query: str = ""):
        """Open Chrome in incognito mode and perform a Google search.
        If `query` is empty, just opens the Google homepage.
        """
        try:
            base_url = "https://www.google.com"
            if query:
                encoded = urllib.parse.quote_plus(query)
                base_url = f"https://www.google.com/search?q={encoded}"
            chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
            subprocess.Popen([chrome_path, "--incognito", base_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "msg": str(e)}

    def clear_drawings(self):
        self.overlay_manager.clear_drawings()
        return {"status": "ok"}

    def clear_history(self):
        self.agent.clear_conversation_history()
        return {"status": "ok"}

    def unload_vision_models(self):
        result = tools.unload_all_vision_models()
        self.dispatch_event("log", f"[系統] {result}")
        return {"status": "ok", "msg": result}

    def ping(self):
        """前端用來確認 bridge 是否真的掛上（console 裡 api 常看起來是空物件）。"""
        return {"status": "ok", "msg": "pong"}

    def copy_to_clipboard(self, text: str):
        """用 Win32 API 寫剪貼簿，避開 WebEngine COM 問題。"""
        try:
            import win32clipboard
            import win32con

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, str(text))
            finally:
                win32clipboard.CloseClipboard()
            return {"status": "ok"}
        except Exception as e:
            try:
                # 後備：Qt clipboard（需在主執行緒；失敗就回傳錯誤）
                from PyQt6.QtWidgets import QApplication

                cb = QApplication.clipboard()
                if cb is not None:
                    cb.setText(str(text))
                    return {"status": "ok", "via": "qt"}
            except Exception:
                pass
            return {"status": "error", "msg": str(e)}


def main():
    from webview_bootstrap import run_app
    run_app(JsApi)


if __name__ == "__main__":
    main()
