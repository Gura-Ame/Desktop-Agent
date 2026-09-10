"""
桌面視窗的啟動流程：DPI/COM 初始化、建立 pywebview 視窗、把 JsApi 掛上 JS bridge。

從 main.py 拆出來——main.py 原本同時裝了「JsApi 對外的 API 介面」跟
「怎麼把視窗生出來、掛上這個介面」，兩者關注點完全不同：JsApi 是「有哪些
功能可以呼叫」，這裡是「視窗本身怎麼生出來、生命週期怎麼跑」。
"""
import ctypes
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
import webview

from overlay import ScreenOverlay
from logging_setup import log


def _init_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _init_com_apartment_threaded():
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


def _init_winforms_text_rendering():
    """在任何 IWin32Window 建立之前呼叫 SetCompatibleTextRenderingDefault。

    pywebview 的 edgechromium 後端會在 webview.start() → setup_app() 裡再呼叫一次；
    若此時已經有視窗（例如過早 show 的 ScreenOverlay，或過早建立的 WinForms 元件），
    會丟出 InvalidOperationException。這裡先呼叫一次，並把 Overlay / Timer 延後到
    start 之後，讓 setup_app 那次呼叫仍然發生在「尚無 WinForms 視窗」的狀態。
    """
    try:
        import clr

        clr.AddReference("System.Windows.Forms")
        import System.Windows.Forms as WinForms

        WinForms.Application.EnableVisualStyles()
        WinForms.Application.SetCompatibleTextRenderingDefault(False)
        return WinForms
    except Exception as e:
        log(f"[系統] 預先初始化 WinForms 文字渲染失敗: {e}", level="error")
        return None


# 需要掛上 JS bridge 的 JsApi 方法名稱清單。用具名 wrapper 逐一掛，而不是直接把
# api 物件整個丟給 pywebview 的 js_api=，是因為 pywebview 6.x 曾經遇到
# js_api 被覆蓋成空物件的問題（見 _make_expose_fn 內的註解），只能用
# window.expose 加上延遲重掛這個 workaround 硬蓋過去。
_EXPOSED_METHOD_NAMES = [
    "ping", "poll_events", "send_prompt", "stop_agent",
    "confirm_step", "submit_user_input", "set_execution_mode",
    "set_forgetting_enabled", "set_activation_enabled",
    "update_api_config", "load_llama_model", "get_llm_status", "check_remote_api",
    "open_chrome_incognito", "clear_drawings", "clear_history",
    "preload_vision_models", "unload_vision_models", "copy_to_clipboard",
    "respond_permission", "set_permission_mode",
    "pick_files", "pick_model_file", "log_from_frontend",
    "set_thinking_enabled",
    "set_instant_input_enabled",
]


def _make_expose_fn(window, api):
    """回傳一個可以重複呼叫的 _expose_api 函式，每次頁面 loaded 都要重掛一次
    （Vite 重新整理也會再觸發一次 loaded），不然 js_api 有機率被覆蓋成空物件。
    """
    def _expose_api():
        # 用具名 wrapper，避免 bound method / __name__ 在 pywebview 6.x 出怪問題
        def _wrap(name):
            def _fn(*args, **kwargs):
                return getattr(api, name)(*args, **kwargs)
            _fn.__name__ = name
            return _fn

        try:
            window.expose(*[_wrap(n) for n in _EXPOSED_METHOD_NAMES if callable(getattr(api, n, None))])
            log("[JsApi] expose 完成")
        except Exception as e:
            log(f"[JsApi] expose 失敗: {e}", level="error")
            return

        try:
            t_poll = window.evaluate_js(
                "window.pywebview && window.pywebview.api "
                "? typeof window.pywebview.api.poll_events : 'n/a'"
            )
            log(f"[JsApi] after expose poll_events typeof = {t_poll}")
        except Exception as e:
            log(f"[JsApi] evaluate_js 失敗: {e}", level="error")

    return _expose_api


def _make_delayed_reexpose_fn(expose_fn):
    def _delayed_reexpose():
        import threading
        import time

        def _run():
            time.sleep(1.0)
            expose_fn()
        threading.Thread(target=_run, daemon=True).start()
    return _delayed_reexpose


def _start_qt_pump_timer(WinForms):
    """在 WinForms 訊息迴圈已跑起來之後，用 Timer 定期 processEvents，
    避免 ScreenOverlay 被 Windows 判定為無回應。
    """
    if WinForms is None:
        try:
            import clr

            clr.AddReference("System.Windows.Forms")
            import System.Windows.Forms as WinForms
        except Exception as e:
            log(f"[系統] 啟動 Qt 事件循環定時器失敗（無法載入 WinForms）: {e}", level="error")
            return None

    try:
        qt_pump_timer = WinForms.Timer()
        qt_pump_timer.Interval = 50

        def _pump_qt_events(sender, args):
            QApplication.processEvents()

        qt_pump_timer.Tick += _pump_qt_events
        qt_pump_timer.Start()
        return qt_pump_timer
    except Exception as e:
        log(f"[系統] 啟動 Qt 事件循環定時器失敗: {e}", level="error")
        return None


def run_app(js_api_cls):
    """啟動整個桌面應用：DPI/COM 初始化 → 開 overlay → 建立主視窗 → 掛上 JS bridge。

    js_api_cls 用參數傳進來（而不是直接 import JsApi）是為了避免這個模組
    跟 main.py 互相 import 造成循環依賴——main.py import 這裡的 run_app，
    這裡不需要反過來知道 JsApi 這個類別長怎樣，只需要知道它「可以被建構、
    可以被塞進 webview」。
    """
    _init_dpi_awareness()
    _init_com_apartment_threaded()

    # 必須在任何視窗 / WinForms 控制項建立之前呼叫，否則 webview.start()
    # 內部的 SetCompatibleTextRenderingDefault 會丟 InvalidOperationException。
    WinForms = _init_winforms_text_rendering()

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)

    # 先建構、先不 show：避免在 webview.start() → setup_app() 之前就出現原生視窗
    overlay = ScreenOverlay()

    api = js_api_cls(overlay)
    window = webview.create_window(
        title="AI UI Desktop Agent",
        url="http://localhost:5173",
        js_api=api,
        width=1280,
        height=600,
        resizable=True,
    )
    api.set_window(window)

    # main.py 裡 create_window 可保留 js_api=api（無害），但真正生效靠 expose
    # fuck pywebview 破問題 不知道為啥js_api會被覆蓋掉，導致前端呼叫 api 會變成空物件
    expose_fn = _make_expose_fn(window, api)
    window.events.loaded += expose_fn

    # Vite SPA：loaded 後再延遲重掛一次，防止第一次被覆蓋
    delayed_reexpose_fn = _make_delayed_reexpose_fn(expose_fn)
    window.events.loaded += delayed_reexpose_fn

    # 主視窗真正出現後再 show overlay、再啟動 Qt pump timer
    # （此時 setup_app 已跑完，SetCompatibleTextRenderingDefault 不會再被踩雷）
    _qt_pump_timer_ref = {"timer": None}

    def _on_shown():
        try:
            if not overlay.isVisible():
                overlay.show()
                QApplication.processEvents()
        except Exception as e:
            log(f"[系統] 顯示 ScreenOverlay 失敗: {e}", level="error")
        if _qt_pump_timer_ref["timer"] is None:
            _qt_pump_timer_ref["timer"] = _start_qt_pump_timer(WinForms)

    # shown 在部分後端較晚才觸發；loaded 也掛一份當保險
    try:
        window.events.shown += _on_shown
    except Exception:
        pass
    window.events.loaded += _on_shown

    webview.start(gui="edgechromium", debug=True)
