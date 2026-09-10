"""
「瞬間輸入」開關關閉時（預設關閉），滑鼠/鍵盤這幾個會直接控制使用者真實
輸入裝置的工具（move_mouse/click_mouse/drag_mouse/scroll_mouse/type_text/
press_key/key_down）在真的執行之前，先在螢幕 Overlay 上畫出「將會發生
什麼」——滑鼠會移到哪（軌跡線 + 沿路徑移動的圓點）、會打什麼字（逐字顯示
的打字預覽泡泡），再依照目前的權限策略（agent/tool_permissions.py 的
PermissionMode）決定什麼時候真的動手：

- ASK（一律詢問，最保守）：預覽畫出來之後，走既有的
  request_tool_permission 完整詢問流程——這幾個工具本來就是 DANGEROUS
  等級，這裡沒有改變「要不要問」這件事，只是讓使用者在按下允許之前，
  先看得到滑鼠會移到哪、會打什麼字，而不是盲目按允許。
- ASK_DANGEROUS_ONLY（只問高風險）：這裡刻意**不**落回一般的
  PermissionManager.needs_confirmation 判斷（那樣仍然會跳出確認對話框，
  因為這幾個工具本身是 DANGEROUS）。使用者選這個策略，語意上就是「大部分
  情況我不想每次都點確認，但還是想看得到會發生什麼」，所以這裡改成
  畫出預覽、停留 1 秒讓使用者來得及反應/按緊急停止，沒有動作就自動繼續，
  不需要額外點一次按鈕。這是這組工具特有的行為，跟其他 DANGEROUS 工具
  （execute_python、run_powershell）在 ASK_DANGEROUS_ONLY 下仍然會被
  完整詢問不一樣——差異是刻意的：後者的後果通常更難預期/更難逆轉，
  滑鼠移到哪、打了什麼字，使用者自己盯著畫面就能立即判斷對不對。
- AUTO（全部信任）：預覽畫出來後立刻繼續，不停留。

開啟「瞬間輸入」時，這整套邏輯完全不會執行，行為等同這個功能加入之前——
直接照 request_tool_permission 原本的規則走，不畫任何預覽、不額外停留。
"""

import re
import time

from agent.tool_permissions import PermissionMode

PHYSICAL_INPUT_TOOLS = {
    "move_mouse", "click_mouse", "drag_mouse", "scroll_mouse",
    "type_text", "press_key", "key_down",
}

# 各工具的參數名稱順序，用來把 _parse_tool_arguments 拆出來的 (args, kwargs)
# 重新綁定成一個「參數名 -> 值」的字典，不管模型是用位置參數還是關鍵字參數
# 呼叫，這裡都能正確取出 x/y/text/key。
_ARG_NAMES = {
    "move_mouse": ["x", "y", "duration"],
    "click_mouse": ["button", "x", "y", "clicks"],
    "drag_mouse": ["x", "y", "duration", "button"],
    "scroll_mouse": ["amount", "x", "y"],
    "type_text": ["text", "interval"],
    "press_key": ["key"],
    "key_down": ["key"],
}


def _bind_args(func_name, args, kwargs) -> dict:
    names = _ARG_NAMES.get(func_name, [])
    bound = dict(zip(names, args))
    bound.update(kwargs)
    return bound


def _extract_target_xy(func_name, args, kwargs):
    """回傳這次呼叫的目標座標 (x, y)，抓不到（例如 click_mouse 沒給 x/y，
    代表在目前游標位置點擊，沒有真的移動）就回傳 None。
    """
    bound = _bind_args(func_name, args, kwargs)
    x, y = bound.get("x"), bound.get("y")
    if x is None or y is None:
        return None
    try:
        return (float(x), float(y))
    except (TypeError, ValueError):
        return None


def _extract_typing_text(func_name, args, kwargs) -> str:
    bound = _bind_args(func_name, args, kwargs)
    if func_name == "type_text":
        return str(bound.get("text", ""))
    if func_name in ("press_key", "key_down"):
        return str(bound.get("key", ""))
    return ""


class AgentPhysicalInputPreviewMixin:
    """提供「瞬間輸入」開關 + 滑鼠/鍵盤動作預覽/延遲執行的邏輯。"""

    def set_instant_input_enabled(self, enabled: bool):
        """使用者決定要不要允許滑鼠瞬移/瞬間輸入文字（跳過軌跡/打字預覽）。
        不透過 available_functions 暴露給模型——這是使用者對「要不要看到
        動作發生前的預覽」的取捨，模型不該有權限自己決定要不要讓使用者
        看見。預設關閉：預設情況下所有滑鼠鍵盤動作都會先預覽。
        """
        self.instant_input_enabled = enabled
        self.memory_store.set_instant_input_enabled(enabled)
        self.emit(
            "log",
            f"[系統] 瞬間輸入已{'開啟' if enabled else '關閉'}"
            + ("，滑鼠/鍵盤動作不會再顯示軌跡或打字預覽。" if enabled else "，滑鼠/鍵盤動作執行前會先顯示軌跡/打字預覽。")
        )

    def _current_mouse_position(self):
        fn = self.available_functions.get("get_mouse_position")
        if not fn:
            return (0, 0)
        try:
            result = fn()
            m = re.search(r"\((-?\d+),\s*(-?\d+)\)", str(result))
            if m:
                return (int(m.group(1)), int(m.group(2)))
        except Exception:
            pass
        return (0, 0)

    def _show_physical_input_preview(self, func_name, args, kwargs):
        """畫出這次滑鼠/鍵盤動作的預覽。任何一步失敗（例如 overlay 工具
        沒被註冊、參數格式跟預期不同）都只是跳過預覽，不影響動作本身繼續
        往下走——預覽是提升透明度用的，不該因為預覽本身出錯就讓整個工具
        呼叫失敗。
        """
        try:
            target = _extract_target_xy(func_name, args, kwargs)
            if target is not None:
                trajectory_fn = self.available_functions.get("_show_mouse_trajectory")
                if trajectory_fn:
                    current = self._current_mouse_position()
                    trajectory_fn(current, target)

            text = _extract_typing_text(func_name, args, kwargs)
            if text:
                typing_fn = self.available_functions.get("_show_typing_preview")
                if typing_fn:
                    x, y = target if target is not None else self._current_mouse_position()
                    typing_fn(int(x), int(y), text)
        except Exception as e:
            self.emit("log", f"[警告] 顯示滑鼠/鍵盤預覽失敗，略過這一步: {e}")

    def _gate_physical_input(self, func_name, args, kwargs, args_str: str) -> bool:
        """回傳 True 表示可以繼續真的執行這個滑鼠/鍵盤動作，False 表示
        使用者拒絕（或中途被停止）。只有「瞬間輸入」關閉時才會走這整套
        流程，見本檔案開頭的三種模式說明。
        """
        if getattr(self, "instant_input_enabled", False):
            return True

        self._show_physical_input_preview(func_name, args, kwargs)

        mode = self.permission_manager.mode
        if mode == PermissionMode.AUTO:
            return True
        if mode == PermissionMode.ASK_DANGEROUS_ONLY:
            waited = 0.0
            while waited < 1.0:
                if self._should_stop():
                    return False
                time.sleep(0.1)
                waited += 0.1
            return True

        # ASK：預覽已經畫出來了，接著走原本完整的授權對話框流程——
        # 這幾個工具本來就是 DANGEROUS，該問的還是要問。
        return self.request_tool_permission(func_name, args_str)
