import os
import time
import uuid
import warnings
from typing import Dict, List, Optional

warnings.filterwarnings("ignore", category=UserWarning, module="pywinauto")

from pywinauto import Desktop
import pyautogui

from logging_setup import log


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
            accessible_name = elem.get("accessible_name", "")

            # 簡化摘要標記
            if any(k in elem_type for k in ["button", "edit", "menu", "check", "combo"]) or text or accessible_name:
                interactive_summary.append({
                    "id": idx,
                    "type": elem["type"],
                    "text": text[:20],  # 截斷過長文字
                    "accessible_name": accessible_name[:50],
                    "state": elem.get("state", {}),
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
            searchable = " ".join([
                str(elem.get("text", "")),
                str(elem.get("accessible_name", "")),
                str(elem.get("type", "")),
            ]).lower()
            if kw in searchable:
                results.append(elem)
        return results

    def get_element_by_id(self, snap_id: str, elem_id: int) -> Optional[dict]:
        snap = self._cache.get(snap_id)
        if snap and 0 <= elem_id < len(snap["full_elements"]):
            return snap["full_elements"][elem_id]
        return None


screen_cache = ScreenCache()


def _accessible_name(elem, fallback_text: str = "") -> str:
    """優先使用 UIA accessibility name，沒有時才退回 window_text。"""
    try:
        name = getattr(elem.element_info, "name", "")
        if name:
            return str(name).strip()
    except Exception:
        pass
    return fallback_text.strip()


def _describe_state(elem) -> dict:
    """盡可能取得 UIA 常見狀態；單一屬性失敗不應讓整個元素消失。"""
    state = {}
    for attr in ("is_enabled", "is_checked", "is_selected", "has_focus"):
        try:
            value = getattr(elem, attr)
            value = value() if callable(value) else value
            key = attr[3:] if attr.startswith("is_") else "focused"
            state[key] = bool(value)
        except Exception:
            continue
    return state


def _should_report_element(text: str, accessible_name: str, elem_type: str, rect) -> bool:
    """只回傳有可用語意或明確互動類型、且尺寸合理的元素。"""
    if rect.width() <= 0 or rect.height() <= 0:
        return False
    return bool(text or accessible_name or any(k in elem_type.lower() for k in ["button", "edit", "menu", "check", "combo", "link"]))


def read_screen(max_elements: int = 60, save_screenshot_path: str = "temp_screen.png"):
    """
    讀取螢幕上的 UI 元素。
    優先使用 UI Automation Tree (Accessibility) 抓取元件文字、accessibility name、狀態與座標；
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
                        accessible_name = _accessible_name(elem, text)
                        elem_type = elem.friendly_class_name()
                        rect = elem.rectangle()

                        # 只留下有文字且佔據合理尺寸的有效元件
                        if _should_report_element(text, accessible_name, elem_type, rect):
                            elements_info.append({
                                "window": win_title if win_title else "Unknown Window",
                                "type": elem_type,
                                "text": text,
                                "accessible_name": accessible_name,
                                "state": _describe_state(elem),
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
        log(f"UIA 樹抓取異常: {e}", level="warning", channel="tool")

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
        full_elements = raw_result.get("elements")
        if isinstance(full_elements, list):
            snap_id = screen_cache.save_snapshot(full_elements)

            return {
                "snapshot_id": snap_id,
                "total_count": len(full_elements),
                "summary_interactive_elements": screen_cache._cache.get(snap_id, {}).get("summary", []),
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
        "accessible_name": m.get("accessible_name", ""),
        "state": m.get("state", {}),
        "center_coord": m["center_coord"]
    } for m in matches]
