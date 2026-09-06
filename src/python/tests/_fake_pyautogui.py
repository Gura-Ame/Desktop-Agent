"""
共用的假 pyautogui 模組安裝函式，給 test_wait_tools.py / test_input_tools.py
共用——這兩個測試檔各自需要 pyautogui 上不同的函式（screenshot vs
moveTo/click/mouseDown/...）。

如果各自在 sys.modules 裡塞一個「只包含自己需要的屬性」的假模組，測試
執行順序不同時，後 import 的那個測試檔會看到「pyautogui 已經在
sys.modules 裡了」而跳過安裝，結果拿到一個缺少自己需要的屬性的假模組，
導致測試因為執行順序不同而不穩定通過/失敗（這是真的發生過的問題，不是
假設性的擔憂）。

統一由這裡負責安裝一個「兩邊都需要的屬性通通有」的假模組，不管哪個
測試檔先 import 都一樣，不會有結果隨執行順序改變的問題。

這個檔案故意取名以底線開頭（_fake_pyautogui.py），讓 pytest 的預設收集
規則不會把它當成測試檔案本身去收集執行。
"""
import sys
import types
from unittest.mock import MagicMock

_ATTR_NAMES = [
    "screenshot",
    "size", "position", "moveTo", "click", "mouseDown", "mouseUp",
    "dragTo", "scroll", "write", "press", "hotkey", "keyDown", "keyUp",
]


def ensure_fake_pyautogui():
    """確保 sys.modules["pyautogui"] 存在，且具備所有測試會用到的屬性。
    如果已經存在一個模組（不管是先前某個測試裝的假模組，還是理論上
    真的 pyautogui），只會補齊缺少的屬性，不會整個覆蓋掉重來。
    """
    existing = sys.modules.get("pyautogui")
    if existing is not None and all(hasattr(existing, name) for name in _ATTR_NAMES):
        return existing

    module = existing or types.ModuleType("pyautogui")
    for name in _ATTR_NAMES:
        if not hasattr(module, name):
            setattr(module, name, MagicMock())
    module.size.return_value = (1920, 1080)
    module.position.return_value = (100, 200)
    sys.modules["pyautogui"] = module
    return module
