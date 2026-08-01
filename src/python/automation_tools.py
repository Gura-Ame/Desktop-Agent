from pywinauto import Desktop
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
import uuid
import time
from typing import Dict, List, Optional

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

class ScreenCache:
    def __init__(self, ttl_seconds: int = 300):
        self._cache: Dict[str, dict] = {}
        self.ttl = ttl_seconds

    def save_snapshot(self, full_elements: List[dict], screenshot_path: Optional[str] = None) -> str:
        """將全量畫面資料存入 Disk/RAM 快取，回傳 snapshot_id"""
        snap_id = f"snap_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        
        # 只保留互動性較高的元件做為 Context 摘要 (按鈕、輸入框、選單)
        interactive_summary = []
        for idx, elem in enumerate(full_elements):
            elem["id"] = idx  # 賦予內部索引
            elem_type = elem.get("type", "").lower()
            text = elem.get("text", "")
            
            # 簡化摘要標記
            if any(k in elem_type for k in ["button", "edit", "menu", "check", "combo"]) or len(text) > 0:
                interactive_summary.append({
                    "id": idx,
                    "type": elem["type"],
                    "text": text[:20],  # 截斷過長文字
                    "window": elem["window"]
                })

        self._cache[snap_id] = {
            "timestamp": time.time(),
            "full_elements": full_elements,
            "screenshot_path": screenshot_path,
            "summary": interactive_summary[:20]  # LLM 只看前 20 個重要元件
        }
        return snap_id

    def query_element(self, snap_id: str, keyword: str) -> List[dict]:
        """按關鍵字精準查詢座標，不佔用主 Context"""
        snap = self._cache.get(snap_id)
        if not snap:
            return []
        
        results = []
        kw = keyword.lower()
        for elem in snap["full_elements"]:
            if kw in elem.get("text", "").lower() or kw in elem.get("type", "").lower():
                results.append(elem)
        return results

    def get_element_by_id(self, snap_id: str, elem_id: int) -> Optional[dict]:
        snap = self._cache.get(snap_id)
        if snap and 0 <= elem_id < len(snap["full_elements"]):
            return snap["full_elements"][elem_id]
        return None

screen_cache = ScreenCache()

def read_screen(max_elements: int = 60, save_screenshot_path: str = "temp_screen.png"):
    """
    讀取螢幕上的 UI 元素。
    優先使用 UI Automation Tree (Accessibility) 抓取元件文字與座標；
    若無回應或抓不到有效文字，則 Fallback 至螢幕截圖（可搭配 OCR 處理）。
    """
    elements_info = []

    # 1. 嘗試走 UI Automation Tree
    try:
        desktop = Desktop(backend="uia")
        # 抓取目前桌面上可見的頂層視窗
        windows = desktop.windows(visible_only=True)

        for win in windows:
            if len(elements_info) >= max_elements:
                break

            try:
                win_rect = win.rectangle()
                if win_rect.width() <= 0 or win_rect.height() <= 0:
                    continue

                win_title = win.window_text().strip()

                # 遍歷視窗內部的 descendant 元件
                for elem in win.descendants():
                    if len(elements_info) >= max_elements:
                        break
                    try:
                        if not elem.is_visible():
                            continue

                        text = elem.window_text().strip()
                        rect = elem.rectangle()

                        # 只留下有文字且佔據合理尺寸的有效元件
                        if text and rect.width() > 0 and rect.height() > 0:
                            elements_info.append({
                                "window": win_title if win_title else "Unknown Window",
                                "type": elem.friendly_class_name(),
                                "text": text,
                                "center_coord": ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2),
                                "bounding_box": [rect.left, rect.top, rect.right, rect.bottom]
                            })
                    except Exception:
                        continue
            except Exception:
                continue

        # 只要有抓到 UIA 元素就直接回傳結果
        if elements_info:
            return {
                "mode": "uia",
                "count": len(elements_info),
                "elements": elements_info
            }
    except Exception as e:
        print(f"[read_screen] UIA 樹抓取異常: {e}")

    # 2. Fallback: 拍攝螢幕截圖供 OCR 或 Vision 模型讀取
    try:
        pyautogui.screenshot(save_screenshot_path)
        
        # 若專案中有接入 rapidocr_onnxruntime / easyocr，可在這裡直接執行 OCR
        # 範例：
        # ocr_results = run_ocr(save_screenshot_path)
        
        return {
            "mode": "screenshot_fallback",
            "message": "UIA 無法取得畫面結構，已擷取螢幕畫面",
            "image_path": os.path.abspath(save_screenshot_path)
        }
    except Exception as e:
        return f"讀取螢幕失敗（UIA 與截圖均失敗）: {str(e)}"

# read_screen 修改：只回傳 snapshot_id 與精簡摘要
def read_screen_api(max_elements: int = 60):
    raw_result = read_screen(max_elements=max_elements)
    
    if isinstance(raw_result, dict) and raw_result.get("mode") == "uia":
        full_elements = raw_result["elements"]
        snap_id = screen_cache.save_snapshot(full_elements)
        
        return {
            "snapshot_id": snap_id,
            "total_count": len(full_elements),
            "summary_interactive_elements": screen_cache._cache[snap_id]["summary"],
            "note": "若目標不在 summary 中，請呼叫 query_screen_element(snapshot_id, keyword) 查找座標"
        }
    return raw_result

# 新增精準查詢工具供 Agent 呼叫
def query_screen_element(snapshot_id: str, keyword: str):
    matches = screen_cache.query_element(snapshot_id, keyword)
    if not matches:
        return f"在快照 {snapshot_id} 中找不到包含 '{keyword}' 的元件"
    return [{
        "id": m["id"],
        "text": m["text"],
        "center_coord": m["center_coord"]
    } for m in matches]