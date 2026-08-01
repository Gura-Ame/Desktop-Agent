
import subprocess
import json
import os
import ctypes
import io
import math
import contextlib
import re
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pywinauto")
import pyautogui
from pywinauto import Application
import pywinauto.findwindows as findwindows

def search_installed_apps(keyword: str):
    try:
        cmd = f'powershell "Get-StartApps | Where-Object {{ $_.Name -like \'*{keyword}*\' }} | Select-Object Name, AppID | ConvertTo-Json"'
        output = subprocess.check_output(cmd, shell=True, text=True).strip()

        if not output:
            return f"No installed application found matching '{keyword}'."

        apps = json.loads(output)
        if isinstance(apps, dict):
            apps = [apps]

        results = [
            f"Name: {app['Name']} (AppID: {app.get('AppID', '')})"
            for app in apps
        ]
        return "\n".join(results)
    except Exception as e:
        return f"Error searching apps: {e}"

def launch_app(app_name_or_path):
    if isinstance(app_name_or_path, (set, list, tuple)):
        app_name_or_path = next(iter(app_name_or_path), "")
    elif isinstance(app_name_or_path, dict):
        app_name_or_path = app_name_or_path.get("app_name_or_path", next(iter(app_name_or_path.values()), ""))

    app_str = str(app_name_or_path).strip("'\" ")
    common_apps = {
        "notepad": "notepad.exe",
        "calc": "calc.exe",
        "cmd": "cmd.exe",
        "mspaint": "mspaint.exe"
    }
    if app_str.lower() in common_apps:
        target = common_apps[app_str.lower()]
        try:
            subprocess.Popen(target, shell=True)
            return f"Successfully launched common app: {target}"
        except Exception:
            pass

    try:
        cmd = f'powershell "Get-StartApps | Where-Object {{ $_.Name -like \'*{app_str}*\' }} | Select-Object Name, AppID | ConvertTo-Json"'
        output = subprocess.check_output(cmd, shell=True, text=True).strip()
        if output:
            data = json.loads(output)
            if isinstance(data, dict):
                data = [data]
            if data and "AppID" in data[0]:
                appid = data[0]["AppID"]
                subprocess.Popen(f'explorer.exe "shell:AppsFolder\\{appid}"')
                return f"Successfully launched installed app '{data[0]['Name']}' (AppID: {appid})"
    except Exception:
        pass

    try:
        subprocess.Popen(app_str, shell=True)
        return f"Successfully launched via shell: {app_str}"
    except Exception:
        pass

    try:
        os.startfile(app_str)
        return f"Successfully started: {app_str}"
    except Exception as e:
        return f"Failed to launch app '{app_str}': {e}"

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

def get_screen_size():
    width, height = pyautogui.size()
    return f"Screen resolution is {width}x{height}"

def get_mouse_position():
    x, y = pyautogui.position()
    return f"Current mouse position is ({x}, {y})"

def move_mouse(x: int, y: int):
    pyautogui.moveTo(x, y)
    return f"Mouse moved to ({x}, {y})"

def click_mouse(button: str = "left"):
    pyautogui.click(button=button)
    return f"Clicked {button} mouse button"

def type_text(text: str):
    pyautogui.write(text, interval=0.05)
    return f"Typed text: {text}"

def execute_python(code: str) -> str:
    buffer = io.StringIO()

    # 1. 優先嘗試當成單一運算式 (Expression) 求值 (Evaluation)
    try:
        res = eval(code, {"math": math, "__builtins__": __builtins__})
        if res is not None:
            return str(res)
    except Exception:
        pass

    # 2. 失敗則作為程式敘述 (Statement) 執行並擷取 print 輸出
    try:
        with contextlib.redirect_stdout(buffer):
            exec(code, {"math": math, "__builtins__": __builtins__})
        output = buffer.getvalue().strip()
        return output if output else "成功（無輸出）"
    except Exception as e:
        return f"執行失敗: {e}"