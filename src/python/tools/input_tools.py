import pyautogui

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
