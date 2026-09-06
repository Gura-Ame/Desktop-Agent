"""
滑鼠/鍵盤的即時控制原語——除了原本就有的「移動到座標」「點一下」
「打一串字」這種一次到位的動作之外，補上「按住不放」「拖曳」「滾動」
「組合鍵」這幾種更貼近人類實際操作方式的動作。

之所以要拆出 mouse_down/mouse_up、key_down/key_up 這種成對的「按住/放開」
而不是只給 drag_mouse/press_key 這種包好的一次性動作，是因為有些情境
需要「按住不放的同時做別的事」（例如按住 Shift 的同時用滑鼠多選、
按住滑鼠左鍵拖曳的過程中穿插檢查畫面），這種情境沒辦法用一個原子動作
表達，需要能分成兩次呼叫、中間插入其他工具呼叫的能力——這正是使用者要的
「即時」控制：不是每個動作都一定要瞬間完成再放開，而是可以維持在「按住」
的狀態，讓後續呼叫接續操作。

風險等級：這裡全部工具都是 DANGEROUS（跟原本的 move_mouse/click_mouse/
type_text 一樣）——直接控制使用者真實的滑鼠鍵盤，能做到使用者自己用滑鼠
鍵盤能做的所有事，見 agent/tool_permissions.py。
"""

import pyautogui

# 追蹤目前「按下但還沒放開」的滑鼠按鍵/鍵盤按鍵——如果 agent 在
# mouse_down/key_down 之後被中斷（不管是一般的停止按鈕還是緊急停止），
# 沒有這份紀錄的話，這些按鍵會一直維持在按住的狀態，繼續影響使用者
# 停止之後的操作（例如卡住的 Ctrl 鍵讓後續打字全部變成快捷鍵、卡住的
# 滑鼠左鍵讓移動滑鼠變成到處拖曳選取）。request_stop() 跟緊急停止都會
# 呼叫 release_all_held_inputs() 清掉這些殘留狀態。
_held_mouse_buttons = set()
_held_keys = set()


def get_screen_size():
    width, height = pyautogui.size()
    return f"Screen resolution is {width}x{height}"


def get_mouse_position():
    x, y = pyautogui.position()
    return f"Current mouse position is ({x}, {y})"


def move_mouse(x: int, y: int, duration: float = 0.0):
    """移動滑鼠到 (x, y)。duration 大於 0 時用平滑移動而不是瞬間跳過去——
    有些應用程式（尤其遊戲、或監聽連續 mousemove 事件的網頁）認的是移動
    路徑本身，瞬間跳過去可能偵測不到；一般情境維持預設的 0（跟原本行為
    一樣，瞬間移動）即可，不需要每次都特地指定。
    """
    pyautogui.moveTo(x, y, duration=max(0.0, duration))
    suffix = f"（花費 {duration} 秒平滑移動）" if duration > 0 else ""
    return f"Mouse moved to ({x}, {y}){suffix}"


def click_mouse(button: str = "left", x: int = None, y: int = None, clicks: int = 1):
    """點擊滑鼠。給 x/y 的話會先移動過去再點，不給的話在目前游標位置點；
    clicks=2 就是雙擊（跟連續呼叫兩次的差異是這裡的兩次點擊間隔是作業系統
    認定「雙擊」的標準間隔，連續呼叫兩次不保證會被辨識成雙擊）。
    """
    if clicks <= 0:
        return "點擊失敗：clicks 必須是正整數"
    kwargs = {"button": button, "clicks": clicks}
    if x is not None and y is not None:
        kwargs["x"] = x
        kwargs["y"] = y
    pyautogui.click(**kwargs)
    where = f" at ({x}, {y})" if x is not None and y is not None else ""
    times = f" x{clicks}" if clicks != 1 else ""
    return f"Clicked {button} mouse button{where}{times}"


def mouse_down(button: str = "left"):
    """按住滑鼠按鍵不放——要自己接著呼叫 mouse_up 才會放開。這是「即時
    控制」的基本單位：drag_mouse 就是靠 mouse_down + 移動 + mouse_up 這
    三步組成的一個方便版本；如果 drag_mouse 不夠用（例如要邊拖曳邊檢查
    畫面、邊拖曳邊決定要拖到哪），可以自己拆開來手動控制，記得一定要
    在後續某個時間點呼叫對應的 mouse_up，不然滑鼠按鍵會一直維持在按住
    的狀態，影響使用者接下來所有的滑鼠操作。
    """
    pyautogui.mouseDown(button=button)
    _held_mouse_buttons.add(button)
    return f"滑鼠 {button} 鍵已按住（尚未放開，記得之後要呼叫 mouse_up）"


def mouse_up(button: str = "left"):
    pyautogui.mouseUp(button=button)
    _held_mouse_buttons.discard(button)
    return f"滑鼠 {button} 鍵已放開"


def drag_mouse(x: int, y: int, duration: float = 0.3, button: str = "left"):
    """從目前滑鼠位置拖曳到 (x, y)——等同 mouse_down + 平滑移動 + mouse_up
    包成一個方便呼叫的動作，適合拖曳視窗、框選範圍、拖放檔案這類一次到位
    就能完成的操作。需要在拖曳途中做其他判斷的話，改用 mouse_down +
    move_mouse + mouse_up 自己分開控制。
    """
    if duration <= 0:
        return "拖曳失敗：duration 必須是正數"
    pyautogui.dragTo(x, y, duration=duration, button=button)
    return f"已用 {button} 鍵拖曳到 ({x}, {y})（花費 {duration} 秒）"


def scroll_mouse(amount: int, x: int = None, y: int = None):
    """滾動滑鼠滾輪。amount 正數往上捲、負數往下捲（跟實體滑鼠滾輪的直覺
    方向一致），數值大小對應捲動幅度（不是固定的行數，實際幅度依作業系統
    設定而定）。給 x/y 的話會先移動過去再捲動，不給的話在目前游標位置捲動。
    """
    if amount == 0:
        return "捲動失敗：amount 不能是 0"
    if x is not None and y is not None:
        pyautogui.moveTo(x, y)
    pyautogui.scroll(amount)
    where = f" at ({x}, {y})" if x is not None and y is not None else ""
    return f"Scrolled {amount}{where}"


def type_text(text: str, interval: float = 0.05):
    """輸入一整串文字。interval 是每個字元之間的間隔秒數，太快某些應用
    程式的輸入框會漏接字元，預設 0.05 秒是折衷值；如果目標欄位反應明顯
    比較慢，可以調高這個值再試一次。
    """
    pyautogui.write(text, interval=max(0.0, interval))
    return f"Typed text: {text}"


def press_key(key: str):
    """按一下單一按鍵或組合鍵，例如 "enter"、"esc"、"ctrl+c"、"alt+tab"。
    組合鍵用 + 分隔，效果等同同時按下所有鍵、再一起放開（pyautogui.hotkey
    的行為），不是依序個別按下再依序放開——如果需要更精細地控制先後順序
    （例如先按住 Ctrl，中間穿插其他動作，最後才放開），改用 key_down/
    key_up 自己分開控制。
    """
    keys = [k.strip() for k in key.split("+") if k.strip()]
    if not keys:
        return "按鍵失敗：key 不能是空字串"
    if len(keys) == 1:
        pyautogui.press(keys[0])
    else:
        pyautogui.hotkey(*keys)
    return f"Pressed key: {key}"


def key_down(key: str):
    """按住一個按鍵不放——要自己接著呼叫 key_up 才會放開。用來模擬長按
    （例如遊戲裡按住方向鍵移動），或需要跟滑鼠動作同步的情境（按住 Shift
    的同時用滑鼠拖曳做連續多選）。記得一定要在後續某個時間點呼叫對應的
    key_up，不然這個鍵會一直維持在按住的狀態，影響使用者接下來的操作。
    """
    pyautogui.keyDown(key)
    _held_keys.add(key)
    return f"按鍵 '{key}' 已按住（尚未放開，記得之後要呼叫 key_up）"


def key_up(key: str):
    pyautogui.keyUp(key)
    _held_keys.discard(key)
    return f"按鍵 '{key}' 已放開"


def release_all_held_inputs() -> str:
    """緊急釋放所有目前還按著沒放開的滑鼠按鍵/鍵盤按鍵。

    request_stop()（一般停止跟緊急停止都會走到這裡）會呼叫這個函式，
    確保 agent 被中斷在 mouse_down/key_down 之後、還沒來得及呼叫對應的
    up 時，不會把使用者的滑鼠鍵盤留在按住的狀態——這是這組「即時控制」
    工具存在按住/放開這種成對設計時，必須同時存在的安全網，不然使用者
    停止 agent 之後還要自己意識到「啊，Ctrl 鍵好像還按著」才能修正。
    """
    released = []
    for button in list(_held_mouse_buttons):
        try:
            pyautogui.mouseUp(button=button)
            released.append(f"mouse:{button}")
        except Exception:
            pass
        _held_mouse_buttons.discard(button)
    for key in list(_held_keys):
        try:
            pyautogui.keyUp(key)
            released.append(f"key:{key}")
        except Exception:
            pass
        _held_keys.discard(key)
    return f"已釋放: {', '.join(released)}" if released else "沒有任何按住的按鍵需要釋放"
