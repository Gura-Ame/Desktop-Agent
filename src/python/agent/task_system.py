import re
from enum import Enum
from typing import List, Optional, Tuple


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    WAITING_INPUT = "WAITING_INPUT"
    DECOMPOSED = "DECOMPOSED"  # 容器任務：已被拆解成子任務，本身不會被直接執行


class ExecutionMode(str, Enum):
    AUTO = "AUTO"                  # 全自動，不管任務怎麼標，一律不暫停
    STEP_BY_STEP = "STEP_BY_STEP"  # 全人工，不管任務怎麼標，每一步都暫停
    SMART = "SMART"                # 由模型對每個任務標的「需要確認」決定要不要暫停
    DIRECT = "DIRECT"              # 保留舊值以維持相容，目前無特殊行為


class TaskNode:
    def __init__(self, task_id: str, title: str):
        self.id = task_id
        self.title = title
        self.method: str = ""
        self.condition: str = ""
        self.note: str = ""
        self.need_thinking: bool = False
        self.need_decompose: bool = False   # 是否應該被拆解成子任務再執行
        self.need_confirm: bool = True       # 是否需要人工確認才能執行（預設保守為 YES）
        self.confidence: float = 1.0
        self.status: TaskStatus = TaskStatus.PENDING
        self.result: str = ""  # 由模型填入給未來的自己的資訊

        # --- 階層關係：由 decompose_task 設定，DSL 文字本身無法表達 ---
        self.parent_id: Optional[str] = None
        self.is_decomposed: bool = False  # 這個任務是否已經展開過（避免重複拆解）

        # is_auto_impact_check：由 code_impact.py / relation_impact.py 自動產生的
        # 「檢查是否受影響」任務會標記這個。這種任務的內容必然會提到被改動的節點
        # （這是它存在的目的），如果讓它自己也去跑一次 _auto_queue_impact_checks，
        # 會再次偵測到同一個節點、又插入下一個 rel_impact 任務，且新任務一樣會提到
        # 同一個節點——形成永遠不會停止的連鎖生成。這種任務本身就是「終點」，
        # 執行完就是這條影響鏈的終點，不該再往下衍生。
        self.is_auto_impact_check: bool = False

        # --- 以下為執行期狀態，純內部追蹤用 ---
        self.think_count: int = 0   # 這個任務目前思考過幾次
        self.retry_count: int = 0   # 這個任務目前驗證失敗過幾次

        # --- 卡住偵測用：不能只看 think_count 累積次數，還要看信心值有沒有真的在動 ---
        self.confidence_history: List[float] = []  # 每次 set_confidence 都會 append，用來判斷趨勢
        self.think_limit_override: Optional[int] = None  # 判斷「還在進步」時，臨時放寬的思考上限
        self.stuck_escalation_level: int = 0  # 卡住時目前升級到哪一階：0=尚未升級 1=已試拆解 2=已試擴大檢索

    def set_confidence(self, value: float):
        """所有更新信心值的地方都該走這裡，而不是直接寫 self.confidence，
        這樣 confidence_history 才能完整記錄趨勢，供卡住偵測判斷「是在進步還是真的卡住」。
        """
        self.confidence = value
        self.confidence_history.append(value)

    def reset_stuck_state(self):
        """任務成功完成、或使用者已經介入排除卡關之後呼叫，把卡住偵測的狀態歸零，
        避免舊的升級階段/信心值歷史污染到之後全新的一輪。
        """
        self.confidence_history = [self.confidence]
        self.think_limit_override = None
        self.stuck_escalation_level = 0


class TaskEngine:
    def __init__(self, mode: ExecutionMode = ExecutionMode.STEP_BY_STEP):
        self.mode = mode
        self.tasks: List[TaskNode] = []
        self.raw_tree_text: str = ""
        self.last_parse_error: str = ""  # 最近一次解析失敗的具體原因，給重試流程當回饋用

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------
    def parse_markdown_dsl(self, text: str) -> Optional[List[TaskNode]]:
        """純解析：把 LLM 輸出的 Markdown DSL 轉成 TaskNode list。
        只負責解析，不觸碰 self.tasks —— 呼叫端才決定要不要套用。
        回傳 None 代表解析失敗或沒有任何任務。
        """
        try:
            cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
            cleaned = re.sub(r'```(?:markdown)?', '', cleaned).strip()

            new_tasks = []
            blocks = re.split(r'\n(?=[ \t]*- \[.\])', cleaned)
            for block in blocks:
                if not block.strip():
                    continue

                # id 允許 "TASK-1" 這種純數字，也允許 "TASK-1.1" 這種拆解後的階層 id
                # id 允許英數字/底線/點/連字號組成的任意識別字（例如 "TASK-1"、"TASK-1.1"、
                # "TASK-1.impact1"），限制字元集合是為了避免誤把「[重要] 做某事」這種
                # 標題本身就用中括號開頭的一般文字，誤判成任務 id。
                #
                # 用 re.match 錨定在 block 開頭（容許前導空白），而不是 re.search 掃整個
                # block ——不然如果模型寫的是散文、只是內容裡剛好提到「- [ ] 之類的格式」，
                # re.search 會在段落中間抓到這個巧合的片段，誤判成一個合法任務，
                # 導致真正的格式錯誤被掩蓋掉、不會觸發後續的重試修正機制。
                header_match = re.match(r'[ \t]*- \[(.)\]\s*(?:\[([A-Za-z0-9_.\-]+)\])?\s*(.*)', block)
                if not header_match:
                    continue

                icon_char = header_match.group(1)
                is_done = icon_char.lower() == 'x'
                is_decomposed_marker = icon_char in ('▾', '▼')

                t_id = header_match.group(2) or f"TASK-{len(new_tasks) + 1}"
                title = header_match.group(3).split('\n')[0].strip()

                node = TaskNode(t_id, title)
                if is_done:
                    node.status = TaskStatus.COMPLETED
                    node.result = self._extract_field(block, "結果")
                elif is_decomposed_marker:
                    # 容器任務：欄位內容不重要，套用時一律沿用舊物件
                    node.status = TaskStatus.DECOMPOSED
                else:
                    node.method = self._extract_field(block, "方法")
                    node.condition = self._extract_field(block, "條件")
                    node.note = self._extract_field(block, "注意")

                    think_str = self._extract_field(block, "深度思考").upper()
                    node.need_thinking = "YES" in think_str or "TRUE" in think_str

                    decompose_str = self._extract_field(block, "需要拆解").upper()
                    node.need_decompose = "YES" in decompose_str or "TRUE" in decompose_str

                    confirm_str = self._extract_field(block, "需要確認").upper()
                    if confirm_str:
                        node.need_confirm = "YES" in confirm_str or "TRUE" in confirm_str
                    else:
                        node.need_confirm = True  # 沒標明就保守當作需要確認

                    conf_str = self._extract_field(block, "信心值")
                    try:
                        node.set_confidence(float(conf_str) if conf_str else 0.85)
                    except ValueError:
                        node.set_confidence(0.85)

                new_tasks.append(node)

            if not new_tasks:
                self.last_parse_error = (
                    "找不到任何符合「- [ ] [TASK-n] 標題」格式開頭的任務區塊。"
                    "輸出裡完全沒有一行是以 '- [ ]'、'- [x]' 或 '- [▾]' 開頭的，"
                    "很可能是直接寫了散文/推理過程，而不是照 DSL 清單格式輸出。"
                )
                return None
            self.last_parse_error = ""
            return new_tasks
        except Exception as e:
            self.last_parse_error = f"解析時發生例外: {e}"
            print(f"[TaskEngine DSL 解析失敗]: {e}")
            return None

    def load_initial_plan(self, text: str) -> bool:
        """Planner 第一次產出任務樹時使用：沒有舊狀態需要保護，解析成功就直接套用。"""
        new_tasks = self.parse_markdown_dsl(text)
        if not new_tasks:
            return False
        self.tasks = new_tasks
        self.raw_tree_text = text
        return True

    def apply_reflected_dsl(self, text: str) -> Tuple[bool, str]:
        """Reflect 階段回傳的樹，套用前先做安全驗證：
        目前所有「已完成」或「已拆解」的任務 id，在新樹裡也必須存在、且狀態不能被改掉。
        任何一項不滿足，就整批拒絕、保留原本的任務樹，並回傳明確原因。

        對於受保護的任務，合併時直接沿用舊的 TaskNode 物件本身（而不是新解析出來的），
        這樣可以保留 parent_id / is_decomposed 這些 DSL 文字本身無法表達的內部關聯資訊。
        對於其餘任務，採用新內容，但把舊有的 parent_id 繼承過去。
        """
        new_tasks = self.parse_markdown_dsl(text)
        if not new_tasks:
            return False, "解析失敗：模型輸出的格式不符合 DSL 規則，任務樹維持原狀"

        old_by_id = {t.id: t for t in self.tasks}
        protected_statuses = (TaskStatus.COMPLETED, TaskStatus.DECOMPOSED)
        protected_ids = {tid for tid, t in old_by_id.items() if t.status in protected_statuses}

        new_by_id = {t.id: t for t in new_tasks}

        missing = [tid for tid in protected_ids if tid not in new_by_id]
        if missing:
            return False, f"新樹遺漏了已完成/已拆解的任務 {', '.join(missing)}，拒絕覆蓋，保留原樹"

        downgraded = [
            tid for tid in protected_ids
            if new_by_id[tid].status != old_by_id[tid].status
        ]
        if downgraded:
            return False, f"新樹修改了已完成/已拆解任務的狀態 {', '.join(downgraded)}，拒絕覆蓋，保留原樹"

        merged = []
        for new_t in new_tasks:
            if new_t.id in protected_ids:
                merged.append(old_by_id[new_t.id])
            else:
                if new_t.id in old_by_id:
                    new_t.parent_id = old_by_id[new_t.id].parent_id
                merged.append(new_t)

        self.tasks = merged
        self.raw_tree_text = text
        return True, "任務樹已依照 Reflect 結果更新"

    def decompose_task(self, parent_id: str, dsl_text: str) -> Tuple[bool, str]:
        """把 parent_id 對應的任務拆解成子任務，插入到它後面，並把父任務標記為 DECOMPOSED。"""
        parent = next((t for t in self.tasks if t.id == parent_id), None)
        if parent is None:
            return False, f"找不到父任務 {parent_id}，無法拆解"

        children = self.parse_markdown_dsl(dsl_text)
        if not children:
            return False, "拆解失敗：模型輸出的子任務格式不符合 DSL 規則"

        for i, child in enumerate(children, start=1):
            child.id = f"{parent_id}.{i}"
            child.parent_id = parent_id

        idx = self.tasks.index(parent)
        self.tasks[idx + 1:idx + 1] = children
        parent.status = TaskStatus.DECOMPOSED
        parent.is_decomposed = True
        return True, f"[{parent_id}] 已拆解為 {len(children)} 個子任務"

    def check_and_complete_parent(self, child_id: str):
        """某個子任務完成後，檢查它的兄弟姊妹是否也都完成了；若是，父任務自動標記完成，
        並往上遞迴檢查（支援巢狀拆解）。
        """
        child = next((t for t in self.tasks if t.id == child_id), None)
        if not child or not child.parent_id:
            return

        parent = next((t for t in self.tasks if t.id == child.parent_id), None)
        if not parent:
            return

        siblings = [t for t in self.tasks if t.parent_id == parent.id]
        if siblings and all(s.status == TaskStatus.COMPLETED for s in siblings):
            parent.status = TaskStatus.COMPLETED
            summary = "\n".join(f"  - [{s.id}] {s.title}: {s.result}" for s in siblings)
            parent.result = f"子任務全部完成：\n{summary}"
            self.check_and_complete_parent(parent.id)

    def _extract_field(self, block: str, field_name: str) -> str:
        match = re.search(fr'-\s*{re.escape(field_name)}\s*:\s*(.*)', block)
        return match.group(1).strip() if match else ""

    def get_next_pending_task(self) -> Optional[TaskNode]:
        for task in self.tasks:
            if task.status == TaskStatus.PENDING:
                return task
        return None

    def _depth_of(self, task: TaskNode, id_map: dict) -> int:
        depth = 0
        pid = task.parent_id
        seen = set()
        while pid and pid in id_map and pid not in seen:
            seen.add(pid)
            depth += 1
            pid = id_map[pid].parent_id
        return depth

    def render_tree_markdown(self) -> str:
        """渲染回傳給模型與前端可讀的 Markdown 狀態樹，子任務會依階層縮排。"""
        lines = ["### 【當前任務樹狀態 (Task Tree)】"]
        id_map = {t.id: t for t in self.tasks}

        for t in self.tasks:
            indent = "  " * self._depth_of(t, id_map)

            if t.status == TaskStatus.COMPLETED:
                icon = "x"
            elif t.status == TaskStatus.DECOMPOSED:
                icon = "▾"
            elif t.status == TaskStatus.RUNNING:
                icon = "➜"
            else:
                icon = " "

            lines.append(f"{indent}- [{icon}] [{t.id}] {t.title}")

            if t.status == TaskStatus.COMPLETED:
                lines.append(f"{indent}  - 結果: {t.result if t.result else '已完成'}")
            elif t.status == TaskStatus.DECOMPOSED:
                child_count = sum(1 for c in self.tasks if c.parent_id == t.id)
                lines.append(f"{indent}  - (已拆解為 {child_count} 個子任務，見下方)")
            else:
                if t.method:
                    lines.append(f"{indent}  - 方法: {t.method}")
                if t.condition:
                    lines.append(f"{indent}  - 條件: {t.condition}")
                if t.note:
                    lines.append(f"{indent}  - 注意: {t.note}")
                lines.append(f"{indent}  - 深度思考: {'YES' if t.need_thinking else 'NO'}")
                lines.append(f"{indent}  - 需要拆解: {'YES' if t.need_decompose else 'NO'}")
                lines.append(f"{indent}  - 需要確認: {'YES' if t.need_confirm else 'NO'}")
                lines.append(f"{indent}  - 信心值: {t.confidence:.2f}")
                if t.retry_count > 0:
                    lines.append(f"{indent}  - (已重試 {t.retry_count} 次)")

        return "\n".join(lines)
