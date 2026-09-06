"""
Agent 安全 / 權限系統：在模型真的執行一個工具之前，依照工具的風險等級決定
要不要先暫停、跳出來問使用者「這個可以做嗎」。

跟 Task Tree 既有的「需要確認」（TaskNode.need_confirm）不是同一層防護：
- need_confirm 是**模型自己**對「這個任務」的判斷，模型可能誤判、也可能
  被провокация 誘導成故意標成不需要確認。
- 這裡是**系統層級**、跟模型的自我判斷完全無關的一道獨立防線：不管模型
  怎麼想、也不管這個工具呼叫是在 Task Tree 裡還是 Direct Mode 裡發生的，
  只要工具本身被分類為有風險，就一定要先讓使用者知情同意過一次。

設計成「同一個工具在同一個工作階段裡最多問一次」，而不是每次呼叫都問：
對滑鼠鍵盤這種高頻工具來說，每點一下都跳確認框只會讓使用者練成「看都不看
直接點允許」的反射動作，反而讓這層防護形同虛設。改成「要不要信任這個工具」
問一次，比較貼近使用者實際會怎麼用，也比較不會因為太煩而被關掉。
"""

from enum import Enum
from typing import Dict, Set


class ToolRisk(Enum):
    SAFE = "safe"           # 唯讀查詢/無副作用，永遠不需要確認
    MODERATE = "moderate"   # 有副作用，但範圍有限、大致可回復（記憶寫入、畫面標記、網頁互動）
    DANGEROUS = "dangerous"  # 難以復原或影響範圍大（任意程式碼執行、真實滑鼠鍵盤、啟動應用程式）


class PermissionMode(Enum):
    ASK = "ask"                                # 預設、最保守：MODERATE 跟 DANGEROUS 都要問
    ASK_DANGEROUS_ONLY = "ask_dangerous_only"   # 只有 DANGEROUS 才問，MODERATE 自動放行
    AUTO = "auto"                               # 全部自動放行，完全信任——進階使用者自己選的，不是預設值


# 沒被下面這張表分類到的工具一律當作 DANGEROUS——安全的預設方向是「新工具
# 出現時先假設它有風險」，而不是「先假設它安全」，避免有人加了新工具卻忘記
# 分類，結果因為預設值是 SAFE 而悄悄繞過了這整層防護。
DEFAULT_RISK = ToolRisk.DANGEROUS

TOOL_RISK_LEVELS: Dict[str, ToolRisk] = {
    # --- SAFE：唯讀查詢，不會對系統或使用者的資料造成任何影響 ---
    "get_screen_size": ToolRisk.SAFE,
    "get_mouse_position": ToolRisk.SAFE,
    "get_active_window": ToolRisk.SAFE,
    "inspect_window": ToolRisk.SAFE,
    "search_installed_apps": ToolRisk.SAFE,
    "read_screen_api": ToolRisk.SAFE,
    "query_screen_element": ToolRisk.SAFE,
    "search_files_by_content": ToolRisk.SAFE,
    "find_files_by_name": ToolRisk.SAFE,
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
    "release_all_held_inputs": ToolRisk.SAFE,   # 純粹釋放按鍵，不會按下任何新東西，永遠是安全的

    # --- MODERATE：有副作用，但範圍有限、大致可回復 ---
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

    # --- DANGEROUS：難以復原，或者能做的事範圍幾乎沒有邊界 ---
    "execute_python": ToolRisk.DANGEROUS,       # 能執行任意程式碼，等同完整系統存取權限
    "run_powershell": ToolRisk.DANGEROUS,       # 同上，等同完整系統存取權限
    "run_cmd": ToolRisk.DANGEROUS,              # 同上
    "mouse_down": ToolRisk.DANGEROUS,           # 直接控制使用者真實的滑鼠，且會維持按住狀態
    "mouse_up": ToolRisk.DANGEROUS,
    "drag_mouse": ToolRisk.DANGEROUS,
    "scroll_mouse": ToolRisk.DANGEROUS,
    "press_key": ToolRisk.DANGEROUS,            # 直接控制使用者真實的鍵盤，組合鍵可能觸發任意系統快捷鍵
    "key_down": ToolRisk.DANGEROUS,             # 同上，且會維持按住狀態
    "key_up": ToolRisk.DANGEROUS,
    "move_mouse": ToolRisk.DANGEROUS,           # 直接控制使用者真實的滑鼠
    "click_mouse": ToolRisk.DANGEROUS,          # 點擊可能觸發任何 UI 上做得到的事（送出表單、刪除…）
    "type_text": ToolRisk.DANGEROUS,            # 直接控制使用者真實的鍵盤輸入
    "launch_app": ToolRisk.DANGEROUS,           # 啟動任意應用程式
    "open_chrome_incognito": ToolRisk.DANGEROUS,  # 開啟瀏覽器並導航到任意網址
    "browser_open": ToolRisk.DANGEROUS,
    "browser_close": ToolRisk.DANGEROUS,
}


def risk_of(tool_name: str) -> ToolRisk:
    return TOOL_RISK_LEVELS.get(tool_name, DEFAULT_RISK)


class PermissionManager:
    """管理「這個工作階段裡，使用者已經允許哪些工具」以及整體授權策略。

    刻意不做跨 session 的持久化（重開程式後已授權清單清空）：授權策略本身
    （PermissionMode）是使用者偏好，比照 forgetting/activation 走
    MemoryStore 持久化沒問題；但「哪些工具在上一輪對話裡被允許過」是這一次
    工作階段當下的信任判斷，不應該因為上次開過就永遠對下一次的對話直接放行——
    這裡是安全邊界，跟单纯的使用者偏好性質不同。
    """

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
        """例如清空對話歷史、開始全新任務時，可以選擇性地重置信任狀態。"""
        self._granted_this_session.clear()

    def is_granted(self, tool_name: str) -> bool:
        return tool_name in self._granted_this_session

    def needs_confirmation(self, tool_name: str) -> bool:
        """在還沒問過使用者的前提下，這個工具「這一次」是否需要跳出確認。
        已經被 grant() 過的工具永遠回傳 False（除非之後被 revoke）。
        """
        if self.is_granted(tool_name):
            return False
        risk = risk_of(tool_name)
        if risk == ToolRisk.SAFE:
            return False
        if self.mode == PermissionMode.AUTO:
            return False
        if self.mode == PermissionMode.ASK_DANGEROUS_ONLY:
            return risk == ToolRisk.DANGEROUS
        return True  # ASK 模式：MODERATE 跟 DANGEROUS 都要問
