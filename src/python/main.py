import sys
import os
import json
import warnings
import pyautogui
import ctypes

# 1. 必須在 QApplication 初始化前導入 QtWebEngineWidgets
import PyQt6.QtWebEngineWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
import webview

os.environ["QT_LOGGING_RULES"] = "qt.qpa.window.warning=false"
warnings.filterwarnings("ignore", category=UserWarning, module="pywinauto")

import automation_tools as tools
from overlay import ScreenOverlay, OverlayManager
from agent_core import AgentWorker, AgentState
from task_system import ExecutionMode
from server_manager import LlamaServerManager

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.5


class JsApi:
    def __init__(self, overlay):
        self._window = None
        self.overlay = overlay
        self.overlay_manager = OverlayManager(self.overlay)

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
            "clear_drawings": self.overlay_manager.clear_drawings,
            "execute_python": tools.execute_python
        }

        self.agent = AgentWorker(self.available_functions, event_callback=self.dispatch_event)
        self.server_mgr = LlamaServerManager(event_callback=self.dispatch_event)

    def set_window(self, window):
        self._window = window

    def dispatch_event(self, event_type: str, data: any):
        if self._window:
            payload = json.dumps({"type": event_type, "data": data})
            self._window.evaluate_js(f"window.onAgentEvent && window.onAgentEvent({payload});")

    def send_prompt(self, prompt: str):
        if self.agent.is_running():
            return {"status": "busy", "msg": "Agent 正忙碌中"}
        self.agent.set_user_prompt(prompt)
        self.agent.state = AgentState.IDLE
        self.agent.start()
        return {"status": "ok"}

    def confirm_step(self):
        self.agent.confirm_and_start()

    def submit_user_input(self, text: str):
        self.agent.resume_with_user_input(text)

    def set_execution_mode(self, mode_str: str):
        mode = ExecutionMode[mode_str.upper()]
        self.agent.set_execution_mode(mode)

    def update_api_config(self, base_url: str, api_key: str, model_name: str):
        self.agent.update_api_config(base_url, api_key, model_name)

    def toggle_local_server(self, model_path: str):
        if self.server_mgr.is_running():
            self.server_mgr.stop_server()
            self.dispatch_event("server_status", {"running": False, "msg": "已停止"})
        else:
            self.server_mgr.start_server(model_path)
            self.dispatch_event("server_status", {"running": True, "msg": "本地伺服器運行中"})

    def clear_drawings(self):
        self.overlay_manager.clear_drawings()

    def clear_history(self):
        self.agent.history = []


def main():
    # 強制開啟 Windows DPI 高感知，確保繪製座標與螢幕實體像素 1:1 對齊
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    # 2. 在建立 QApplication 前設定 OpenGL 共享上下文
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
        resizable=True
    )
    api.set_window(window)

    webview.start(gui='qt', debug=True)


if __name__ == "__main__":
    main()
