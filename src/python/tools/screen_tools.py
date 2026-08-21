import os
import time
import uuid
import warnings
from typing import Dict, List, Optional
warnings.filterwarnings("ignore", category=UserWarning, module="pywinauto")
from pywinauto import Desktop
import pyautogui

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
        
        return {
            "mode": "screenshot_fallback",
            "message": "UIA 無法取得畫面結構，已擷取螢幕畫面",
            "image_path": os.path.abspath(save_screenshot_path)
        }
    except Exception as e:
        return f"讀取螢幕失敗（UIA 與截圖均失敗）: {str(e)}"

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

def query_screen_element(snapshot_id: str, keyword: str):
    matches = screen_cache.query_element(snapshot_id, keyword)
    if not matches:
        return f"在快照 {snapshot_id} 中找不到包含 '{keyword}' 的元件"
    return [{
        "id": m["id"],
        "text": m["text"],
        "center_coord": m["center_coord"]
    } for m in matches]
