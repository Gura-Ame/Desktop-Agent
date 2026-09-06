"""
agent/emergency_stop.py 的測試。這台測試機沒有安裝 `keyboard` 套件
（就算裝了，在沒有系統管理員權限/沒有真的輸入裝置的沙盒環境裡多半也
沒辦法真的掛上全域鉤子），所以這裡全部用 sys.modules 塞一個假的
`keyboard` 模組——重點驗證「這個模組自己的邏輯」（成功/失敗都不拋例外、
重複註冊會先取消前一個、callback 真的會被觸發），不是真的測全域快捷鍵
能不能攔截到系統層級的按鍵。
"""
import os
import sys
import types
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import agent.emergency_stop as emergency_stop


def setup_function(_):
    """每個測試前確保沒有殘留的註冊狀態、也移除任何假的 keyboard 模組，
    讓每個測試自己決定要不要塞哪一種假模組。
    """
    emergency_stop.stop_emergency_stop_listener()
    sys.modules.pop("keyboard", None)


def _install_fake_keyboard():
    fake = types.ModuleType("keyboard")
    fake.add_hotkey = MagicMock(return_value="handle-123")
    fake.remove_hotkey = MagicMock()
    sys.modules["keyboard"] = fake
    return fake


def test_start_returns_false_when_keyboard_package_missing():
    # setup_function 已經確保 sys.modules 裡沒有 "keyboard"，
    # 且這台機器本來就沒裝這個套件，import 一定會失敗。
    result = emergency_stop.start_emergency_stop_listener(lambda: None)
    assert result is False
    assert emergency_stop.is_listening() is False


def test_start_succeeds_and_registers_expected_hotkey():
    fake = _install_fake_keyboard()
    callback = lambda: None
    result = emergency_stop.start_emergency_stop_listener(callback, hotkey="ctrl+alt+x")

    assert result is True
    assert emergency_stop.is_listening() is True
    assert emergency_stop.current_hotkey() == "ctrl+alt+x"
    fake.add_hotkey.assert_called_once_with("ctrl+alt+x", callback)


def test_start_returns_false_when_add_hotkey_raises():
    fake = _install_fake_keyboard()
    fake.add_hotkey.side_effect = Exception("no permission")

    result = emergency_stop.start_emergency_stop_listener(lambda: None)

    assert result is False
    assert emergency_stop.is_listening() is False


def test_starting_again_replaces_previous_registration():
    fake = _install_fake_keyboard()
    emergency_stop.start_emergency_stop_listener(lambda: None, hotkey="ctrl+a")
    emergency_stop.start_emergency_stop_listener(lambda: None, hotkey="ctrl+b")

    # 第二次註冊之前應該先把第一個取消掉，不會同時有兩組快捷鍵生效
    fake.remove_hotkey.assert_called_once_with("handle-123")
    assert emergency_stop.current_hotkey() == "ctrl+b"


def test_stop_listener_removes_hotkey_and_clears_state():
    fake = _install_fake_keyboard()
    emergency_stop.start_emergency_stop_listener(lambda: None)

    emergency_stop.stop_emergency_stop_listener()

    fake.remove_hotkey.assert_called_once_with("handle-123")
    assert emergency_stop.is_listening() is False
    assert emergency_stop.current_hotkey() is None


def test_stop_listener_when_nothing_registered_does_not_raise():
    emergency_stop.stop_emergency_stop_listener()  # 不該拋例外
    assert emergency_stop.is_listening() is False


def test_triggering_hotkey_calls_the_provided_callback():
    fake = _install_fake_keyboard()
    triggered = {"count": 0}

    def on_trigger():
        triggered["count"] += 1

    emergency_stop.start_emergency_stop_listener(on_trigger, hotkey="ctrl+alt+shift+q")

    # 模擬 keyboard 套件真的偵測到快捷鍵時會做的事：呼叫當初註冊的 callback。
    registered_callback = fake.add_hotkey.call_args[0][1]
    registered_callback()

    assert triggered["count"] == 1


if __name__ == "__main__":
    tests = [
        test_start_returns_false_when_keyboard_package_missing,
        test_start_succeeds_and_registers_expected_hotkey,
        test_start_returns_false_when_add_hotkey_raises,
        test_starting_again_replaces_previous_registration,
        test_stop_listener_removes_hotkey_and_clears_state,
        test_stop_listener_when_nothing_registered_does_not_raise,
        test_triggering_hotkey_calls_the_provided_callback,
    ]
    for t in tests:
        setup_function(None)
        t()
        print(f"[PASS] {t.__name__}")
    print(f"\n全部 {len(tests)} 個測試通過。")
