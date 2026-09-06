"""
tools/input_tools.py 的測試。這台測試機沒有真的螢幕/X 環境，pyautogui
本身在 import 階段就會嘗試連線一個真的顯示環境，所以在 import
tools.input_tools 之前先在 sys.modules 裡塞一個假的 pyautogui 模組——
跟 test_wait_tools.py 是同一種精神，重點驗證「這個模組自己的邏輯」
（held-input 追蹤、參數檢查、回傳文字），不是真的測滑鼠鍵盤能不能動。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from _fake_pyautogui import ensure_fake_pyautogui
ensure_fake_pyautogui()

import tools.input_tools as input_tools
from tools.input_tools import (
    click_mouse,
    drag_mouse,
    key_down,
    key_up,
    mouse_down,
    mouse_up,
    press_key,
    release_all_held_inputs,
    scroll_mouse,
)


def setup_function(_):
    """每個測試開始前重置假的 pyautogui mock 呼叫紀錄跟 held-input 狀態，
    避免不同測試之間互相污染。連 side_effect 也要一併清掉——reset_mock()
    預設不會清 side_effect，如果某個測試（例如底下模擬 keyUp 拋例外那個）
    設了 side_effect 卻沒被這裡清乾淨，會汙染到後面所有測試。
    """
    for name in ["moveTo", "click", "mouseDown", "mouseUp", "dragTo",
                 "scroll", "write", "press", "hotkey", "keyDown", "keyUp"]:
        mock_fn = getattr(input_tools.pyautogui, name)
        mock_fn.reset_mock(side_effect=True)
    input_tools._held_mouse_buttons.clear()
    input_tools._held_keys.clear()


def test_click_mouse_with_coordinates_passes_them_through():
    click_mouse(button="right", x=10, y=20, clicks=2)
    input_tools.pyautogui.click.assert_called_once_with(
        button="right", clicks=2, x=10, y=20
    )


def test_click_mouse_rejects_non_positive_clicks():
    result = click_mouse(clicks=0)
    assert "必須是正整數" in result
    input_tools.pyautogui.click.assert_not_called()


def test_mouse_down_then_up_tracks_and_clears_held_state():
    mouse_down("left")
    assert "left" in input_tools._held_mouse_buttons
    mouse_up("left")
    assert "left" not in input_tools._held_mouse_buttons


def test_drag_mouse_rejects_non_positive_duration():
    result = drag_mouse(1, 2, duration=0)
    assert "必須是正數" in result
    input_tools.pyautogui.dragTo.assert_not_called()


def test_drag_mouse_calls_dragTo_with_expected_args():
    drag_mouse(100, 200, duration=0.5, button="left")
    input_tools.pyautogui.dragTo.assert_called_once_with(
        100, 200, duration=0.5, button="left"
    )


def test_scroll_mouse_rejects_zero_amount():
    result = scroll_mouse(0)
    assert "不能是 0" in result
    input_tools.pyautogui.scroll.assert_not_called()


def test_scroll_mouse_moves_first_when_coordinates_given():
    scroll_mouse(-5, x=1, y=2)
    input_tools.pyautogui.moveTo.assert_called_once_with(1, 2)
    input_tools.pyautogui.scroll.assert_called_once_with(-5)


def test_press_key_single_key_uses_press_not_hotkey():
    press_key("enter")
    input_tools.pyautogui.press.assert_called_once_with("enter")
    input_tools.pyautogui.hotkey.assert_not_called()


def test_press_key_combo_uses_hotkey_with_split_keys():
    press_key("ctrl+shift+s")
    input_tools.pyautogui.hotkey.assert_called_once_with("ctrl", "shift", "s")
    input_tools.pyautogui.press.assert_not_called()


def test_press_key_rejects_empty_string():
    result = press_key("   ")
    assert "不能是空字串" in result


def test_key_down_then_up_tracks_and_clears_held_state():
    key_down("ctrl")
    assert "ctrl" in input_tools._held_keys
    key_up("ctrl")
    assert "ctrl" not in input_tools._held_keys


def test_release_all_held_inputs_releases_everything_and_reports_it():
    mouse_down("left")
    key_down("ctrl")
    key_down("shift")

    result = release_all_held_inputs()

    assert "mouse:left" in result
    assert "key:ctrl" in result
    assert "key:shift" in result
    assert input_tools._held_mouse_buttons == set()
    assert input_tools._held_keys == set()
    input_tools.pyautogui.mouseUp.assert_called_once_with(button="left")
    assert input_tools.pyautogui.keyUp.call_count == 2


def test_release_all_held_inputs_with_nothing_held_says_so():
    result = release_all_held_inputs()
    assert "沒有任何按住的按鍵需要釋放" in result


def test_release_all_held_inputs_continues_even_if_one_release_raises():
    """萬一某個按鍵釋放失敗（例如按鍵名稱後來變得不合法），不該讓其他
    還按著的按鍵因此永遠釋放不到——這是緊急釋放機制最不該失敗的地方。
    """
    mouse_down("left")
    key_down("ctrl")
    input_tools.pyautogui.keyUp.side_effect = Exception("boom")

    result = release_all_held_inputs()

    input_tools.pyautogui.mouseUp.assert_called_once_with(button="left")
    assert input_tools._held_mouse_buttons == set()
    assert input_tools._held_keys == set(), "即使 keyUp 拋例外，held 狀態也該被清掉，不能卡在舊狀態"
    assert "mouse:left" in result


if __name__ == "__main__":
    tests = [
        test_click_mouse_with_coordinates_passes_them_through,
        test_click_mouse_rejects_non_positive_clicks,
        test_mouse_down_then_up_tracks_and_clears_held_state,
        test_drag_mouse_rejects_non_positive_duration,
        test_drag_mouse_calls_dragTo_with_expected_args,
        test_scroll_mouse_rejects_zero_amount,
        test_scroll_mouse_moves_first_when_coordinates_given,
        test_press_key_single_key_uses_press_not_hotkey,
        test_press_key_combo_uses_hotkey_with_split_keys,
        test_press_key_rejects_empty_string,
        test_key_down_then_up_tracks_and_clears_held_state,
        test_release_all_held_inputs_releases_everything_and_reports_it,
        test_release_all_held_inputs_with_nothing_held_says_so,
        test_release_all_held_inputs_continues_even_if_one_release_raises,
    ]
    for t in tests:
        setup_function(None)
        t()
        print(f"[PASS] {t.__name__}")
    print(f"\n全部 {len(tests)} 個測試通過。")
