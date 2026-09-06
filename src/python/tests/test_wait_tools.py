"""
tools/wait_tools.py 的測試。這台測試機沒有真的螢幕/X 環境可以截圖，
`pyautogui` 這個套件本身在 import 階段就會嘗試連線一個真的顯示環境
（透過 mouseinfo/Xlib），在沒有 DISPLAY 的沙盒裡連 import 都會失敗，
所以這裡在 import tools.wait_tools 之前，先在 sys.modules 裡塞一個假的
pyautogui 模組——跟 test_shell_exec.py 用 unittest.mock 換掉
subprocess.run 是同一種精神，重點驗證「這個模組自己的邏輯」（偵測有沒有
變化、連續安靜多久才回傳），不是真的測螢幕截圖這件事本身能不能動。
"""
import os
import sys
import time
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from _fake_pyautogui import ensure_fake_pyautogui
ensure_fake_pyautogui()

from PIL import Image

from tools.wait_tools import wait, wait_for_screen_stable, _changed_ratio, MAX_WAIT_SECONDS


def _solid_image(color, size=(20, 20)):
    return Image.new("RGB", size, color=color)


def test_wait_sleeps_and_reports_duration():
    start = time.time()
    result = wait(0.05)
    elapsed = time.time() - start
    assert elapsed >= 0.05
    assert "0.05" in result
    print("[PASS] test_wait_sleeps_and_reports_duration")


def test_wait_includes_reason_when_given():
    result = wait(0.01, reason="等對話框跳出來")
    assert "等對話框跳出來" in result
    print("[PASS] test_wait_includes_reason_when_given")


def test_wait_rejects_non_positive_seconds():
    assert "必須是正數" in wait(0)
    assert "必須是正數" in wait(-1)
    print("[PASS] test_wait_rejects_non_positive_seconds")


def test_wait_rejects_over_max_seconds():
    result = wait(MAX_WAIT_SECONDS + 1)
    assert "最多等待" in result
    print("[PASS] test_wait_rejects_over_max_seconds")


def test_changed_ratio_identical_images_is_zero():
    img = _solid_image((100, 100, 100))
    assert _changed_ratio(img, img) == 0.0
    print("[PASS] test_changed_ratio_identical_images_is_zero")


def test_changed_ratio_different_sizes_is_max():
    a = _solid_image((0, 0, 0), size=(10, 10))
    b = _solid_image((0, 0, 0), size=(20, 20))
    assert _changed_ratio(a, b) == 1.0
    print("[PASS] test_changed_ratio_different_sizes_is_max")


def test_changed_ratio_fully_different_colors_is_high():
    a = _solid_image((0, 0, 0))
    b = _solid_image((255, 255, 255))
    assert _changed_ratio(a, b) > 0.9
    print("[PASS] test_changed_ratio_fully_different_colors_is_high")


def test_wait_for_screen_stable_returns_quickly_when_never_changes():
    still = _solid_image((10, 10, 10))
    with patch("tools.wait_tools.pyautogui.screenshot", return_value=still):
        result = wait_for_screen_stable(
            timeout=5, stable_seconds=0.2, poll_interval=0.05
        )
    assert "已穩定" in result
    print("[PASS] test_wait_for_screen_stable_returns_quickly_when_never_changes")


def test_wait_for_screen_stable_waits_out_continuous_changes_then_settles():
    """前幾次截圖顏色一直變（模擬編譯輸出持續捲動），之後固定下來（模擬編譯完成）。"""
    colors = [(0, 0, 0), (50, 50, 50), (100, 100, 100), (150, 150, 150)]
    stable_color = (200, 200, 200)
    call_count = {"n": 0}

    def fake_screenshot(region=None):
        i = call_count["n"]
        call_count["n"] += 1
        if i < len(colors):
            return _solid_image(colors[i])
        return _solid_image(stable_color)

    with patch("tools.wait_tools.pyautogui.screenshot", side_effect=fake_screenshot):
        result = wait_for_screen_stable(
            timeout=5, stable_seconds=0.15, poll_interval=0.05
        )
    assert "已穩定" in result
    print("[PASS] test_wait_for_screen_stable_waits_out_continuous_changes_then_settles")


def test_wait_for_screen_stable_times_out_when_always_changing():
    call_count = {"n": 0}

    def fake_screenshot(region=None):
        call_count["n"] += 1
        # 交替兩個差異夠大的顏色，確保每次都會被 _changed_ratio 判定為「變了」
        return _solid_image((255, 0, 0) if call_count["n"] % 2 == 0 else (0, 0, 255))

    with patch("tools.wait_tools.pyautogui.screenshot", side_effect=fake_screenshot):
        result = wait_for_screen_stable(
            timeout=0.3, stable_seconds=0.1, poll_interval=0.05
        )
    assert "逾時" in result
    print("[PASS] test_wait_for_screen_stable_times_out_when_always_changing")


def test_wait_for_screen_stable_rejects_invalid_arguments():
    assert "必須是正數" in wait_for_screen_stable(timeout=0)
    assert "必須是正數" in wait_for_screen_stable(stable_seconds=-1)
    assert "必須是正數" in wait_for_screen_stable(poll_interval=0)
    print("[PASS] test_wait_for_screen_stable_rejects_invalid_arguments")


def test_wait_for_screen_stable_rejects_stable_seconds_longer_than_timeout():
    result = wait_for_screen_stable(timeout=5, stable_seconds=10)
    assert "不能比" in result
    print("[PASS] test_wait_for_screen_stable_rejects_stable_seconds_longer_than_timeout")


def test_wait_for_screen_stable_rejects_over_max_timeout():
    result = wait_for_screen_stable(timeout=MAX_WAIT_SECONDS + 1)
    assert "最多" in result
    print("[PASS] test_wait_for_screen_stable_rejects_over_max_timeout")


if __name__ == "__main__":
    tests = [
        test_wait_sleeps_and_reports_duration,
        test_wait_includes_reason_when_given,
        test_wait_rejects_non_positive_seconds,
        test_wait_rejects_over_max_seconds,
        test_changed_ratio_identical_images_is_zero,
        test_changed_ratio_different_sizes_is_max,
        test_changed_ratio_fully_different_colors_is_high,
        test_wait_for_screen_stable_returns_quickly_when_never_changes,
        test_wait_for_screen_stable_waits_out_continuous_changes_then_settles,
        test_wait_for_screen_stable_times_out_when_always_changing,
        test_wait_for_screen_stable_rejects_invalid_arguments,
        test_wait_for_screen_stable_rejects_stable_seconds_longer_than_timeout,
        test_wait_for_screen_stable_rejects_over_max_timeout,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
