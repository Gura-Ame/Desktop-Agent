import sys
import os
import json
import warnings
import threading
import pyautogui
import ctypes

# 必須在 QApplication 初始化前導入
import PyQt6.QtWebEngineWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
import webview

os.environ["QT_LOGGING_RULES"] = "qt.qpa.window.warning=false"
warnings.filterwarnings("ignore", category=UserWarning, module="pywinauto")

import tools.automation_tools as tools
from overlay import ScreenOverlay, OverlayManager
from agent.agent_core import AgentWorker, AgentState
from agent.task_system import ExecutionMode
from server_manager import LlamaServerManager

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
        }

        self.agent = AgentWorker(
            self.available_functions,
            event_callback=self.dispatch_event,
        )
        self.server_mgr = LlamaServerManager(event_callback=self.dispatch_event)

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

    def update_api_config(self, base_url: str, api_key: str, model_name: str):
        self.agent.update_api_config(base_url, api_key, model_name)
        return {"status": "ok"}

    def toggle_local_server(self, model_path: str):
        if self.server_mgr.is_running():
            self.server_mgr.stop_server()
            self.dispatch_event("server_status", {"running": False, "msg": "已停止"})
        else:
            self.server_mgr.start_server(model_path)
            self.dispatch_event(
                "server_status", {"running": True, "msg": "本地伺服器運行中"}
            )
        return {"status": "ok"}

    def clear_drawings(self):
        self.overlay_manager.clear_drawings()
        return {"status": "ok"}

    def clear_history(self):
        self.agent.clear_conversation_history()
        return {"status": "ok"}

def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    # COM 必須用 STA（Apartment-threaded），否則 WebEngine 剪貼簿會 0x800401f0
    # 我也不知道為啥刪了這個就崩 哈哈
    COINIT_APARTMENTTHREADED = 0x2
    try:
        ctypes.windll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    except Exception:
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)

    overlay = ScreenOverlay()
    overlay.show()

    api = JsApi(overlay)
    window = webview.create_window(
        title="AI UI Desktop Agent",
        url="http://localhost:5173",
        js_api=api,
        width=1280,
        height=600,
        resizable=True,
    )
    api.set_window(window)

    webview.start(gui="edgechromium", debug=True)


if __name__ == "__main__":
    main()
