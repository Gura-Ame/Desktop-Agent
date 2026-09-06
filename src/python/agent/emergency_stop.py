"""
全域緊急停止：不管使用者目前在哪個視窗（agent 可能正在操作其他應用程式，
使用者不見得能馬上點回這個 App 的視窗按「停止」），按下一組全域快捷鍵
就能立刻中斷 agent。

用 `keyboard` 套件做系統層級的全域按鍵監聽（不像一般 GUI 事件只能收到
「自己視窗有焦點時」的按鍵）。這個套件在 Windows 通常需要用系統管理員
權限執行才能正確攔截系統層級的按鍵，這是它的固有限制，不是這裡的程式碼
問題——一般使用者若沒有用系統管理員權限啟動這個 App，全域快捷鍵可能
沒有作用，這種情況下退回用視窗裡原本的「停止」按鈕。同理，`keyboard`
套件根本沒安裝（例如在沒有這個依賴的環境跑）也不該讓整個 agent 因此
無法啟動，一律靜靜地回傳「沒有註冊成功」，由呼叫端決定要不要提醒使用者。

刻意把「怎麼觸發」（全域快捷鍵）跟「觸發了要做什麼」（呼叫端傳進來的
on_trigger callback）分開——這裡完全不知道、也不需要知道 on_trigger
實際上是 AgentWorker.request_stop 或別的什麼，方便測試（可以用假的
callback + 假的 keyboard 模組驗證邏輯，不需要真的有系統管理員權限）。
"""

import threading
from typing import Callable, Optional

DEFAULT_HOTKEY = "ctrl+alt+shift+q"

_lock = threading.Lock()
_registered_hotkey: Optional[str] = None
_hotkey_handle = None


def start_emergency_stop_listener(
    on_trigger: Callable[[], None],
    hotkey: str = DEFAULT_HOTKEY,
) -> bool:
    """註冊全域快捷鍵，觸發時呼叫 on_trigger()。回傳是否註冊成功——
    失敗（通常是 keyboard 套件不存在，或權限不足）不會拋例外，只會
    回傳 False，呼叫端可以選擇記錄一筆 log 提醒使用者，但不該讓整個
    agent 因為這個非必要的輔助功能而無法啟動。

    重複呼叫會先取消前一個註冊，只會有一個全域快捷鍵在生效中。
    """
    global _registered_hotkey, _hotkey_handle
    with _lock:
        _stop_locked()
        try:
            import keyboard
        except ImportError:
            return False
        try:
            _hotkey_handle = keyboard.add_hotkey(hotkey, on_trigger)
            _registered_hotkey = hotkey
            return True
        except Exception:
            _hotkey_handle = None
            _registered_hotkey = None
            return False


def stop_emergency_stop_listener():
    """取消目前註冊的全域快捷鍵（如果有的話）。程式關閉、或需要重新註冊
    不同快捷鍵時呼叫，避免舊的 callback 繼續被觸發。
    """
    with _lock:
        _stop_locked()


def _stop_locked():
    """假設呼叫端已經持有 _lock，內部共用邏輯，避免 start/stop 兩邊重複寫。"""
    global _registered_hotkey, _hotkey_handle
    if _hotkey_handle is not None:
        try:
            import keyboard
            keyboard.remove_hotkey(_hotkey_handle)
        except Exception:
            pass
    _hotkey_handle = None
    _registered_hotkey = None


def is_listening() -> bool:
    return _registered_hotkey is not None


def current_hotkey() -> Optional[str]:
    return _registered_hotkey
