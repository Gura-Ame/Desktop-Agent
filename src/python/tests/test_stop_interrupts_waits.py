"""
request_stop() 會同時做兩件事：設定 _stop_event，以及把 is_paused_for_input /
is_paused_for_permission 直接設回 False。ask_user() 跟 request_tool_permission()
的等待迴圈用的是 `while is_paused_for_xxx: ... if stop_event: raise ...`，
如果 request_stop() 把 is_paused_for_xxx 設回 False 的時機比迴圈下一次檢查
_stop_event 還早，迴圈會直接因為 while 條件變 False 而正常結束，迴圈內那個
`raise InterruptedError` 完全不會被跑到——結果變成使用者按了停止，
ask_user()/request_tool_permission() 卻回傳一個看起來像正常結果的值，
而不是真的中斷。這是這次加權限系統時，測 request_tool_permission 才意外
發現的既有問題（ask_user 也有一樣的寫法），這裡把兩邊都釘住。
"""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.agent_core import AgentWorker
from agent.tool_permissions import PermissionMode


def _make_agent():
    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)
    events = []
    agent = AgentWorker(
        {"dangerous_tool": lambda: "ran"},
        event_callback=lambda t, d: events.append((t, d)),
        memory_path=memory_path,
    )
    return agent, events, memory_path


def test_stopping_while_ask_user_is_waiting_raises_interrupted_not_a_fake_reply():
    agent, events, memory_path = _make_agent()
    try:
        def stopper():
            start = time.time()
            while not any(e[0] == "waiting_input" for e in events):
                if time.time() - start > 5.0:
                    raise AssertionError("等不到 waiting_input 事件")
                time.sleep(0.02)
            agent.request_stop()

        t = threading.Thread(target=stopper)
        t.start()
        try:
            agent.ask_user("你還在嗎？")
            raised = False
        except InterruptedError:
            raised = True
        t.join(timeout=2.0)
        assert raised, (
            "使用者在 ask_user 等待中按下停止，應該要中斷、"
            "不該把「使用者已停止」偽裝成一句正常的使用者回覆"
        )
        print("[PASS] test_stopping_while_ask_user_is_waiting_raises_interrupted_not_a_fake_reply")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_stopping_while_request_tool_permission_is_waiting_raises_interrupted():
    agent, events, memory_path = _make_agent()
    agent.permission_manager.set_mode(PermissionMode.ASK)
    try:
        def stopper():
            start = time.time()
            while not any(e[0] == "permission_request" for e in events):
                if time.time() - start > 5.0:
                    raise AssertionError("等不到 permission_request 事件")
                time.sleep(0.02)
            agent.request_stop()

        t = threading.Thread(target=stopper)
        t.start()
        try:
            agent.request_tool_permission("dangerous_tool", "")
            raised = False
        except InterruptedError:
            raised = True
        t.join(timeout=2.0)
        assert raised
        print("[PASS] test_stopping_while_request_tool_permission_is_waiting_raises_interrupted")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_request_stop_releases_any_held_mouse_or_keyboard_inputs():
    """如果 agent 剛好卡在 mouse_down/key_down 之後、還沒呼叫對應的 up
    就被停止，request_stop() 應該自動釋放，不讓使用者的滑鼠鍵盤卡住。
    這裡不需要真的 pyautogui，只需要驗證 request_stop() 真的有去查表
    呼叫 available_functions 裡註冊的 release_all_held_inputs。
    """
    released = {"called": False}

    def fake_release():
        released["called"] = True
        return "released"

    agent, events, memory_path = _make_agent()
    agent.available_functions["release_all_held_inputs"] = fake_release
    try:
        agent.request_stop()
        assert released["called"] is True, (
            "request_stop() 應該要呼叫 available_functions 裡的 "
            "release_all_held_inputs，避免滑鼠鍵盤卡在按住的狀態"
        )
        print("[PASS] test_request_stop_releases_any_held_mouse_or_keyboard_inputs")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


def test_request_stop_does_not_crash_when_release_function_missing():
    """有些測試/情境的 available_functions 裡根本沒有註冊
    release_all_held_inputs（例如最小化的測試 fixture）——request_stop()
    不該因此拋例外，這個安全網本身失敗或不存在都不該讓「停止」這個動作
    本身失敗。
    """
    agent, events, memory_path = _make_agent()
    agent.available_functions.pop("release_all_held_inputs", None)
    try:
        agent.request_stop()  # 不該拋例外
        print("[PASS] test_request_stop_does_not_crash_when_release_function_missing")
    finally:
        if os.path.exists(memory_path):
            os.remove(memory_path)


if __name__ == "__main__":
    tests = [
        test_stopping_while_ask_user_is_waiting_raises_interrupted_not_a_fake_reply,
        test_stopping_while_request_tool_permission_is_waiting_raises_interrupted,
        test_request_stop_releases_any_held_mouse_or_keyboard_inputs,
        test_request_stop_does_not_crash_when_release_function_missing,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
