import ctypes
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pywinauto")
from pywinauto import Application
import pywinauto.findwindows as findwindows

def get_active_window():
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return "目前沒有焦點視窗。"

        app = Application(backend="uia").connect(handle=hwnd)
        dlg = app.window(handle=hwnd)

        rect = dlg.rectangle()
        title = dlg.window_text().strip()
        class_name = dlg.class_name()

        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        return {
            "hwnd": hwnd,
            "title": title if title else None,
            "class_name": class_name,
            "process_id": pid.value,
            "bounding_box": [rect.left, rect.top, rect.right, rect.bottom],
            "center_coord": ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        }
    except Exception as e:
        return f"獲取當前視窗資訊失敗: {str(e)}"

def inspect_window(title_re: str, backend: str = "uia", visible_only: bool = True):
    try:
        app = Application(backend=backend).connect(title_re=title_re, timeout=5)
        dlg = app.top_window()

        elements_info = []
        for elem in dlg.descendants():
            try:
                if visible_only and not elem.is_visible():
                    continue

                text = elem.window_text().strip()
                control_type = elem.friendly_class_name()
                class_name = elem.class_name()
                rect = elem.rectangle()

                if rect.width() <= 0 or rect.height() <= 0:
                    continue

                elements_info.append({
                    "type": control_type,
                    "class_name": class_name,
                    "text": text if text else None,
                    "center_coord": ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2),
                    "bounding_box": [rect.left, rect.top, rect.right, rect.bottom]
                })
            except Exception:
                continue

        return elements_info
    except findwindows.ElementNotFoundError:
        return f"找不到符合標題 '{title_re}' 的視窗。"
    except Exception as e:
        return f"無法獲取視窗資訊: {str(e)}"
