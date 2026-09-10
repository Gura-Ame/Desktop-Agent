"""
Agent 安全 / 權限系統：在模型真的執行一個工具之前，依照工具的風險等級決定
要不要先暫停、跳出來問使用者「這個可以做嗎」。
"""

from enum import Enum
from typing import Dict, Set


class ToolRisk(Enum):
    SAFE = "safe"
    MODERATE = "moderate"
    DANGEROUS = "dangerous"


class PermissionMode(Enum):
    ASK = "ask"
    ASK_DANGEROUS_ONLY = "ask_dangerous_only"
    AUTO = "auto"


DEFAULT_RISK = ToolRisk.DANGEROUS

TOOL_RISK_LEVELS: Dict[str, ToolRisk] = {
    # SAFE：唯讀查詢，不會對系統或使用者的資料造成任何影響
    "get_screen_size": ToolRisk.SAFE,
    "get_mouse_position": ToolRisk.SAFE,
    "get_active_window": ToolRisk.SAFE,
    "inspect_window": ToolRisk.SAFE,
    "search_installed_apps": ToolRisk.SAFE,
    "read_screen_api": ToolRisk.SAFE,
    "query_screen_element": ToolRisk.SAFE,
    "search_files_by_content": ToolRisk.SAFE,
    "find_files_by_name": ToolRisk.SAFE,
    "get_file_info": ToolRisk.SAFE,
    "read_tool_doc": ToolRisk.SAFE,
    "ask_user": ToolRisk.SAFE,
    "recall": ToolRisk.SAFE,
    "search_memory": ToolRisk.SAFE,
    "recall_related": ToolRisk.SAFE,
    "recall_observation": ToolRisk.SAFE,
    "recall_with_event": ToolRisk.SAFE,
    "find_callers": ToolRisk.SAFE,
    "find_callees": ToolRisk.SAFE,
    "browser_read_page": ToolRisk.SAFE,
    "analyze_image_visuals": ToolRisk.SAFE,
    "analyze_image_ocr": ToolRisk.SAFE,
    "unload_florence_model": ToolRisk.SAFE,
    "unload_paddleocr_model": ToolRisk.SAFE,
    "unload_all_vision_models": ToolRisk.SAFE,
    "wait": ToolRisk.SAFE,
    "wait_for_screen_stable": ToolRisk.SAFE,
    "release_all_held_inputs": ToolRisk.SAFE,
    "_show_mouse_trajectory": ToolRisk.SAFE,
    "_show_typing_preview": ToolRisk.SAFE,

    # MODERATE：有副作用，但範圍有限、大致可回復
    "remember": ToolRisk.MODERATE,
    "relate": ToolRisk.MODERATE,
    "record_observation": ToolRisk.MODERATE,
    "build_code_graph": ToolRisk.MODERATE,
    "build_code_graph_for_project": ToolRisk.MODERATE,
    "draw_box": ToolRisk.MODERATE,
    "draw_line": ToolRisk.MODERATE,
    "draw_stroke": ToolRisk.MODERATE,
    "erase_at": ToolRisk.MODERATE,
    "clear_drawings": ToolRisk.MODERATE,
    "browser_click": ToolRisk.MODERATE,
    "browser_type": ToolRisk.MODERATE,

    # DANGEROUS：難以復原，或者能做的事範圍幾乎沒有邊界
    "execute_python": ToolRisk.DANGEROUS,
    "run_powershell": ToolRisk.DANGEROUS,
    "run_cmd": ToolRisk.DANGEROUS,
    "mouse_down": ToolRisk.DANGEROUS,
    "mouse_up": ToolRisk.DANGEROUS,
    "drag_mouse": ToolRisk.DANGEROUS,
    "scroll_mouse": ToolRisk.DANGEROUS,
    "press_key": ToolRisk.DANGEROUS,
    "key_down": ToolRisk.DANGEROUS,
    "key_up": ToolRisk.DANGEROUS,
    "move_mouse": ToolRisk.DANGEROUS,
    "click_mouse": ToolRisk.DANGEROUS,
    "type_text": ToolRisk.DANGEROUS,
    "launch_app": ToolRisk.DANGEROUS,
    "open_chrome_incognito": ToolRisk.DANGEROUS,
    "browser_open": ToolRisk.DANGEROUS,
    "browser_close": ToolRisk.DANGEROUS,
}


def risk_of(tool_name: str) -> ToolRisk:
    return TOOL_RISK_LEVELS.get(tool_name, DEFAULT_RISK)


class PermissionManager:
    """管理「這個工作階段裡，使用者已經允許哪些工具」以及整體授權策略。"""

    def __init__(self, mode: PermissionMode = PermissionMode.ASK):
        self.mode = mode
        self._granted_this_session: Set[str] = set()

    def set_mode(self, mode: PermissionMode):
        self.mode = mode

    def grant(self, tool_name: str):
        self._granted_this_session.add(tool_name)

    def revoke(self, tool_name: str):
        self._granted_this_session.discard(tool_name)

    def revoke_all(self):
        self._granted_this_session.clear()

    def is_granted(self, tool_name: str) -> bool:
        return tool_name in self._granted_this_session

    def needs_confirmation(self, tool_name: str) -> bool:
        if self.is_granted(tool_name):
            return False
        risk = risk_of(tool_name)
        if risk == ToolRisk.SAFE:
            return False
        if self.mode == PermissionMode.AUTO:
            return False
        if self.mode == PermissionMode.ASK_DANGEROUS_ONLY:
            return risk == ToolRisk.DANGEROUS
        return True
