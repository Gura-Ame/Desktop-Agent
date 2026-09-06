"""
這次加 pick_files / respond_permission / set_permission_mode /
log_from_frontend 時，真的踩過一個坑：main.py 的 JsApi 類別上把方法寫對了，
前端呼叫也沒寫錯，但 webview_bootstrap.py 裡另外維護了一份
_EXPOSED_METHOD_NAMES allowlist——只有在這份清單裡的方法名稱才會真的被
window.expose() 掛到 window.pywebview.api 上。忘記把新方法加進這份清單，
結果就是方法「存在」、前端「呼叫方式也對」，但實際呼叫時 pywebview 找不到
這個方法，行為上完全看不出是漏了哪一步，很容易花時間排查錯地方。

這裡用 ast 靜態解析兩份原始碼比對——刻意不直接 import main.py，因為它在
模組頂層就會 import PyQt6.QtWebEngineWidgets、pywinauto 等只有真的 Windows
桌面環境才會裝的套件，這個測試機是 Linux，直接 import 一定失敗；純解析
語法樹完全不執行任何一行程式碼，天生跨平台。
"""
import ast
import os

MAIN_PY_PATH = os.path.join(os.path.dirname(__file__), "..", "main.py")
BOOTSTRAP_PY_PATH = os.path.join(os.path.dirname(__file__), "..", "webview_bootstrap.py")


def _get_jsapi_public_methods():
    with open(MAIN_PY_PATH, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename="main.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "JsApi":
            return {
                item.name
                for item in node.body
                if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")
            }
    raise AssertionError("main.py 裡找不到 class JsApi，檔案結構是不是變了？")


def _get_exposed_method_names():
    with open(BOOTSTRAP_PY_PATH, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename="webview_bootstrap.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_EXPOSED_METHOD_NAMES"
            for t in node.targets
        ):
            return {
                elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)
            }
    raise AssertionError(
        "webview_bootstrap.py 裡找不到 _EXPOSED_METHOD_NAMES，變數是不是被改名了？"
    )


def test_every_exposed_name_is_a_real_jsapi_method():
    """防止 _EXPOSED_METHOD_NAMES 裡打錯字，或方法後來被改名/刪除卻沒同步。"""
    public_methods = _get_jsapi_public_methods()
    exposed = _get_exposed_method_names()
    typos = exposed - public_methods
    assert not typos, f"_EXPOSED_METHOD_NAMES 裡有些名字在 JsApi 上根本不存在: {typos}"
    print("[PASS] test_every_exposed_name_is_a_real_jsapi_method")


def test_known_frontend_facing_methods_are_exposed():
    """這份清單刻意手動維護、不是自動掃描前端 TS 程式碼——要驗證的是
    「這幾個名字明確應該要能從前端呼叫到」，這是設計意圖，不是現況掃描。
    加新的 JsApi 方法、確定前端會需要呼叫它時，記得同時把名字加進這裡，
    也加進 webview_bootstrap.py 的 _EXPOSED_METHOD_NAMES。
    """
    known_frontend_facing_methods = {
        "ping", "poll_events", "send_prompt", "stop_agent",
        "confirm_step", "submit_user_input", "set_execution_mode",
        "set_forgetting_enabled", "set_activation_enabled",
        "update_api_config", "load_llama_model",
        "clear_drawings", "clear_history", "copy_to_clipboard",
        "respond_permission", "set_permission_mode",
        "pick_files", "log_from_frontend",
    }
    exposed = _get_exposed_method_names()
    missing = known_frontend_facing_methods - exposed
    assert not missing, (
        f"這些方法前端會需要呼叫，但不在 _EXPOSED_METHOD_NAMES 裡，"
        f"pywebview 不會真的把它們掛出去: {missing}"
    )
    print("[PASS] test_known_frontend_facing_methods_are_exposed")


def test_all_known_frontend_facing_methods_actually_exist_on_jsapi():
    """跟上面互補：確認上面那份清單本身沒有寫錯方法名稱（清單裡列的名字
    在 JsApi 上找不到，跟清單本身漏列一樣都是問題，只是方向相反）。
    """
    known_frontend_facing_methods = {
        "ping", "poll_events", "send_prompt", "stop_agent",
        "confirm_step", "submit_user_input", "set_execution_mode",
        "set_forgetting_enabled", "set_activation_enabled",
        "update_api_config", "load_llama_model",
        "clear_drawings", "clear_history", "copy_to_clipboard",
        "respond_permission", "set_permission_mode",
        "pick_files", "log_from_frontend",
    }
    public_methods = _get_jsapi_public_methods()
    missing = known_frontend_facing_methods - public_methods
    assert not missing, f"這些方法名稱在 JsApi 類別上根本不存在: {missing}"
    print("[PASS] test_all_known_frontend_facing_methods_actually_exist_on_jsapi")


if __name__ == "__main__":
    tests = [
        test_every_exposed_name_is_a_real_jsapi_method,
        test_known_frontend_facing_methods_are_exposed,
        test_all_known_frontend_facing_methods_actually_exist_on_jsapi,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
