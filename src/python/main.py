import sys
import subprocess
import urllib.parse
import os
import json
import warnings
import threading
import pyautogui
import webview

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
from agent.tool_permissions import PermissionMode

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
            "mouse_down": tools.mouse_down,
            "mouse_up": tools.mouse_up,
            "drag_mouse": tools.drag_mouse,
            "scroll_mouse": tools.scroll_mouse,
            "press_key": tools.press_key,
            "key_down": tools.key_down,
            "key_up": tools.key_up,
            "release_all_held_inputs": tools.release_all_held_inputs,
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
            "search_files_by_content": tools.search_files_by_content,
            "find_files_by_name": tools.find_files_by_name,
            "run_powershell": tools.run_powershell,
            "run_cmd": tools.run_cmd,
            "wait": tools.wait,
            "wait_for_screen_stable": tools.wait_for_screen_stable,
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

        tools.set_vision_log_callback(self.dispatch_event)

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

    def pick_files(self):
        """跳出原生的作業系統檔案選擇對話框，回傳使用者選的檔案路徑清單。

        這是「本機 agent」該有的做法：使用者選的檔案本來就已經在這台機器
        的磁碟上，不需要像網頁應用程式那樣把整個檔案內容讀進瀏覽器記憶體、
        編碼成 base64、再傳一份過來——那樣不但要另外處理大小上限（本機
        場景其實不需要這個限制，檔案本來就在硬碟上，agent 隨時可以自己
        用 execute_python/search_files_by_content 之類的工具直接開檔），
        還會把同一份內容在記憶體裡複製好幾次。這裡直接回傳路徑字串，
        agent 之後用自己既有的工具集依路徑存取即可，完全不經過這層 bridge
        搬運任何檔案內容。取消選擇或沒有視窗可用時回傳空陣列，不拋例外。
        """
        window = getattr(self, "_window", None)
        if window is None:
            return []
        try:
            result = window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True)
            return list(result) if result else []
        except Exception as e:
            print(f"[JsApi] pick_files 失敗: {e}", flush=True)
            return []

    def log_from_frontend(self, level: str, message: str):
        """開發時把前端 webview 的 console 輸出轉印到這個 process 的 stdout，
        讓用 VS Code debugpy 掛 python main.py 偵錯時，Debug Console 能同時
        看到 Python 這邊跟前端那邊發生的事，不用另外開瀏覽器 DevTools 對照。
        前端只有在開發模式（import.meta.env.DEV）才會呼叫這個方法，見
        src/lib/devConsoleBridge.ts。
        """
        print(f"[frontend:{level}] {message}", flush=True)

    def respond_permission(self, decision: str):
        """前端的授權對話框呼叫：decision 必須是 'allow' | 'allow_session' | 'deny'。"""
        self.agent.resume_with_permission_decision(decision)
        return {"status": "ok"}

    def set_permission_mode(self, mode_str: str):
        try:
            mode = PermissionMode(mode_str)
            self.agent.set_permission_mode(mode)
            return {"status": "ok", "mode": mode.value}
        except ValueError:
            return {"status": "error", "msg": f"未知的權限模式: {mode_str}"}

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

    def pick_model_file(self):
        """跳出原生的檔案選擇對話框，專門選取單一 .gguf 模型檔案。"""
        window = getattr(self, "_window", None)
        if window is None:
            return ""
        try:
            result = window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=('GGUF Model (*.gguf)', 'All Files (*.*)')
            )
            if result and len(result) > 0:
                return result[0]
            return ""
        except Exception as e:
            print(f"[JsApi] pick_model_file 失敗: {e}", flush=True)
            return ""

    def get_llm_status(self):
        """回傳目前 LLM client 的載入狀態與模型名稱。"""
        is_llama = False
        model_loaded = False
        model_name = getattr(self.agent, "model_name", "")
        try:
            from agent.llama_client import LlamaClient
            client = getattr(self.agent, "client", None)
            if isinstance(client, LlamaClient):
                is_llama = True
                model_loaded = client.llama is not None
        except Exception:
            pass
        return {
            "status": "ok",
            "is_llama": is_llama,
            "model_loaded": model_loaded,
            "model_name": model_name,
        }

    def check_remote_api(self, base_url: str = ""):
        """從 Python 端探測 Remote API 是否在線（避開前端 CORS）。

        對 OpenAI 相容端點打 GET {base}/models。
        """
        import urllib.error
        import urllib.request

        root = (base_url or "").strip().rstrip("/")
        if not root:
            return {"status": "ok", "running": False, "msg": "未設定 Base URL"}
        url = f"{root}/models"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                code = getattr(resp, "status", None) or resp.getcode()
                if 200 <= int(code) < 300:
                    return {"status": "ok", "running": True, "msg": "在線"}
                return {"status": "ok", "running": False, "msg": f"異常 ({code})"}
        except urllib.error.HTTPError as e:
            return {"status": "ok", "running": False, "msg": f"異常 ({e.code})"}
        except Exception as e:
            return {"status": "ok", "running": False, "msg": f"離線 ({type(e).__name__})"}

    def load_llama_model(self, model_path: str, n_ctx: int = 8192, n_gpu_layers: int = -1):
        if not model_path or not os.path.exists(model_path):
            msg = f"模型檔案不存在: {model_path}"
            self.dispatch_event("log", f"[錯誤] {msg}")
            return {"status": "error", "msg": msg}

        model_filename = os.path.basename(model_path)
        self.dispatch_event("log", f"[系統] 正在載入本地模型: {model_filename} ... 請稍候")
        try:
            self.agent.load_llama_model(model_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers)
            from agent.llama_client import LlamaClient
            client = getattr(self.agent, "client", None)
            if isinstance(client, LlamaClient) and client.llama is None:
                raise RuntimeError("llama 實例未能成功初始化（請檢查 GGUF 相容性或 CUDA 顯存）")
            self.dispatch_event("log", f"[系統] 本地模型載入成功: {model_filename}")
            return {"status": "ok", "model_name": model_filename}
        except Exception as e:
            err_msg = str(e)
            self.dispatch_event("log", f"[錯誤] 本地模型載入失敗: {err_msg}")
            return {"status": "error", "msg": err_msg}

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

    def preload_vision_models(self):
        """在背景執行緒預先載入視覺與 OCR 模型，避免在對話中分析圖片時等待卡頓"""
        def _bg_preload():
            try:
                self.dispatch_event("log", "[系統] 開始背景預先載入視覺模型 (Florence-2 / PaddleOCR)...")
                tools.load_florence()
                tools.load_paddleocr()
                self.dispatch_event("log", "[系統] 視覺模型預載完成！後續圖片分析即可即時回應。")
            except Exception as e:
                self.dispatch_event("log", f"[系統] 預載視覺模型失敗: {e}")

        threading.Thread(target=_bg_preload, daemon=True).start()
        return {"status": "ok", "msg": "已開始背景預載"}

    def unload_vision_models(self):
        result = tools.unload_all_vision_models()
        self.dispatch_event("log", f"[系統] {result}")
        return {"status": "ok", "msg": result}

    def ping(self):
        """前端用來確認 bridge 是否真的掛上（console 裡 api 常看起來是空物件）。"""
        return {"status": "ok", "msg": "pong"}

    def copy_to_clipboard(self, text: str):
        """寫入系統剪貼簿。

        優先用 Qt 的剪貼簿（QApplication.clipboard()）而不是直接呼叫
        win32clipboard——這個應用程式本身就是跑在 PyQt6 上，一直有一個
        真實視窗與訊息迴圈在跑，Qt 的剪貼簿是透過那個真實視窗去持有的；
        Windows 的「剪貼簿記錄」（Win+V）跟雲端剪貼簿同步，依賴的正是
        由一個有訊息迴圈在跑的真實視窗觸發的剪貼簿變更通知。先前這裡
        優先呼叫 win32clipboard.OpenClipboard()（沒有傳入視窗代碼，等同
        OpenClipboard(NULL)），一般的複製貼上都正常（貼上不需要透過
        通知鏈），但因為不是由一個真的視窗持有剪貼簿，Windows 的剪貼簿
        記錄有時候抓不到這次變更——這就是「貼上/複製本身正常，但 Win+V
        歷史記錄裡找不到」這個落差的來源。只有 Qt 這條路徑不可用時
        （理論上不太會發生）才退回 win32clipboard，而且退回時盡量傳入
        前景視窗代碼，而不是完全不傳，至少比原本更接近文件建議的用法。
        """
        try:
            from PyQt6.QtWidgets import QApplication

            # instance() 的 stub 回傳 QCoreApplication | None，
            # clipboard() 只在 QGuiApplication / QApplication 上，
            # 用 isinstance 收窄型別，避免 Pylance reportAttributeAccessIssue。
            app = QApplication.instance()
            if isinstance(app, QApplication):
                cb = app.clipboard()
                if cb is not None:
                    cb.setText(str(text))
                    return {"status": "ok", "via": "qt"}
        except Exception:
            pass

        try:
            import win32clipboard
            import win32con
            import win32gui

            hwnd = win32gui.GetForegroundWindow() or None
            win32clipboard.OpenClipboard(hwnd)
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, str(text))
            finally:
                win32clipboard.CloseClipboard()
            return {"status": "ok", "via": "win32"}
        except Exception as e:
            return {"status": "error", "msg": str(e)}


def main():
    from webview_bootstrap import run_app
    run_app(JsApi)


if __name__ == "__main__":
    main()
