"""
給 agent 用來「等一件事發生 / 等一件事做完」的工具。

獨立成一組工具而不是叫模型自己空轉，是因為很多桌面自動化流程本質上需要
等待——編譯、程式啟動、動畫、頁面載入——這些事情 agent 沒辦法用「純推理」
猜到什麼時候好了，只能實際觀察畫面。

兩個工具對應兩種「等待」：
- wait(seconds)：agent 自己知道大概要等多久時用的固定時間等待。
- wait_for_screen_stable(...)：agent 不知道確切要等多久，只知道「畫面
  安靜下來」代表某件事做完了（編譯、載入、動畫播完……），用連續比對螢幕
  截圖的方式偵測「安靜下來」的那一刻，比盲目 sleep 一個寫死的秒數更貼近
  真實情況，也比每隔幾秒就手動截圖問一次模型有沒有變化更省 token。

  這個工具的結束條件（畫面有沒有變化）是它自己判斷的，但「這個變化代表
  什麼」完全交給 agent 接下來自己呼叫 analyze_image_ocr / read_screen_api /
  analyze_image_visuals 等工具判斷——這裡只回答「畫面剛剛安靜下來了」或
  「逾時了畫面還在動」，不會也不該去猜測任務語意上是不是真的完成了。
  這正是使用者要求「結束條件應該由 agent 自己知道」的設計：這個工具只提供
  一個通用、跟任務語意無關的「安靜偵測器」，語意判斷永遠留給 agent 自己
  接下來的下一步工具呼叫。
"""

import time
from typing import Optional, Tuple

import pyautogui
from PIL import Image, ImageChops

# 單次呼叫最多等這麼多秒，避免模型不小心傳一個離譜的數字把 agent 卡住太久。
# 這兩個工具的等待迴圈目前沒有辦法回應使用者中途按下的「停止」——跟
# execute_python 執行一段很慢的程式碼是同一種既有限制（見 AGENT_NOTES.md），
# 不是這裡特別新增的問題，但也因此更需要一個保守的封頂值。
MAX_WAIT_SECONDS = 120

# 灰階差異值低於這個門檻的像素視為雜訊/壓縮誤差，不算「變了」——螢幕截圖
# 本身多少會有這種程度的雜訊，太敏感的話永遠偵測不到「穩定」。
_NOISE_THRESHOLD = 20


def wait(seconds: float, reason: str = "") -> str:
    """單純等待固定秒數。reason 只是給人看的說明，不影響實際行為，但寫清楚
    「為什麼要等」，有助於之後回顧 log 時看懂這一步在做什麼。
    """
    if seconds <= 0:
        return "等待失敗：seconds 必須是正數"
    if seconds > MAX_WAIT_SECONDS:
        return f"等待失敗：單次最多等待 {MAX_WAIT_SECONDS} 秒，如果需要等更久，請分成多次呼叫"
    time.sleep(seconds)
    suffix = f"（{reason}）" if reason else ""
    return f"已等待 {seconds} 秒{suffix}"


def _screenshot(region: Optional[Tuple[int, int, int, int]]) -> Image.Image:
    if region is not None:
        return pyautogui.screenshot(region=region)
    return pyautogui.screenshot()


def _changed_ratio(img_a: Image.Image, img_b: Image.Image) -> float:
    """回傳兩張圖之間「有明顯變化的像素比例」，0.0 代表完全一樣。
    只看灰階差異是否超過雜訊門檻，不追求精確色差比對——這裡要偵測的是
    「畫面有沒有明顯變化」，不是逐像素比對的精確 diff 工具。
    """
    if img_a.size != img_b.size:
        return 1.0
    total_pixels = img_a.size[0] * img_a.size[1]
    if total_pixels == 0:
        return 0.0
    diff = ImageChops.difference(img_a.convert("L"), img_b.convert("L"))
    histogram = diff.histogram()
    changed_pixels = sum(histogram[_NOISE_THRESHOLD:])
    return changed_pixels / total_pixels


def wait_for_screen_stable(
    timeout: float = 30,
    stable_seconds: float = 1.5,
    poll_interval: float = 0.5,
    region: Optional[Tuple[int, int, int, int]] = None,
    change_threshold: float = 0.01,
) -> str:
    """持續截圖比對，等到畫面連續 stable_seconds 秒都沒有明顯變化才回傳。

    適合「不知道確切要等多久，但知道畫面安靜下來就代表做完了」的情境，
    例如：呼叫 run_action 觸發編譯後，用這個工具等到輸出視窗停止捲動，
    再接著呼叫 analyze_image_ocr 讀取最終結果文字。

    - region 是 (x, y, width, height)，只比對畫面裡的一小塊區域（例如編譯
      輸出視窗的範圍），忽略其他地方的變化（系統時鐘、游標閃爍），避免被
      無關的變動誤導成「還沒穩定」。不給的話比對整個螢幕。
    - change_threshold 是「變化比例超過多少才算真的變了」，數字越小越敏感。
    - 逾時只代表「timeout 秒內畫面一直沒有連續安靜滿 stable_seconds 秒」，
      不代表任務失敗，也可能只是這個操作本來就需要更久——可以用更長的
      timeout 再試一次，或改良 region 縮小比對範圍。
    """
    if timeout <= 0 or stable_seconds <= 0 or poll_interval <= 0:
        return "等待失敗：timeout / stable_seconds / poll_interval 都必須是正數"
    if timeout > MAX_WAIT_SECONDS:
        return f"等待失敗：timeout 最多 {MAX_WAIT_SECONDS} 秒，如果需要等更久，請分成多次呼叫"
    if stable_seconds > timeout:
        return "等待失敗：stable_seconds 不能比 timeout 還長"

    start = time.time()
    last_change_at = start
    prev_img = _screenshot(region)

    while True:
        elapsed = time.time() - start
        if elapsed >= timeout:
            return (
                f"逾時：{timeout} 秒內畫面沒有連續安靜滿 {stable_seconds} 秒"
                "（不代表任務失敗，可能只是需要更久，或這個區域本來就一直有東西在動）"
            )

        time.sleep(min(poll_interval, max(0.0, timeout - elapsed)))
        curr_img = _screenshot(region)
        ratio = _changed_ratio(prev_img, curr_img)
        now = time.time()

        if ratio > change_threshold:
            last_change_at = now
        elif now - last_change_at >= stable_seconds:
            return (
                f"畫面已穩定（連續 {stable_seconds:.1f} 秒沒有明顯變化），"
                f"共等待了 {now - start:.1f} 秒"
            )

        prev_img = curr_img
