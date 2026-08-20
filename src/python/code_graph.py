"""
Code Graph：把你原本 a()/b() 的想法具體實作出來。

用 ast 解析 .py 檔案，把每個函式變成 MemoryStore 裡的一個 Object，
並分析函式之間互相呼叫的關係，記成 CALLS 關聯。

之後要問「我改了 b()，誰會受影響？」就不用讓模型自己亂猜，
而是直接對 Disk 做一次反向查詢 (get_incoming)。

兩種用法：
- build_from_file(filepath)：只分析單一檔案，只認得同檔案內的呼叫關係。
  最早的版本，保留下來當作最簡單的入口，介面沒變。
- build_project(root_dir)：分析一整個專案的多個檔案，解析 import，
  能把跨檔案的呼叫（例如 `from utils import helper` 之後呼叫 `helper()`）
  也記成正確的 CALLS 關聯，不再只侷限在同一個檔案內。

限制（先求用得上，不求完美）：
- 只用 ast 做靜態分析，動態呼叫（getattr、字串組出函式名）、多型、裝飾器包裝後
  行為改變的情況都可能漏掉或誤判。
- 跨檔案解析只認得 `import x`、`import x as y`、`from x import y`、
  `from x import y as z` 這幾種常見寫法；相對匯入（`from . import x`）目前跳過不處理，
  因為沒有專案根目錄以外的資訊能可靠算出它實際指向哪個模組。
- 沒有處理同名函式（例如兩個不同 class 裡都有 __init__）互相搞混的情況——
  目前每個檔案內的函式是用「名稱」當 key，同一個檔案裡如果有兩個函式重名
  （多半是意外的 bug，但萬一發生），後定義的會蓋掉先定義的。
- 呼叫目標如果不在這次建圖的範圍內（外部函式庫、沒被包含進來的檔案），
  就直接跳過，不會報錯，也不會生出一個查無此節點的斷鏈。
"""

import ast
import os

from memory_store import MemoryStore


class CodeGraphBuilder:
    def __init__(self, store: MemoryStore):
        self.store = store

    # ------------------------------------------------------------------
    # 單一檔案（原本的入口，介面不變）
    # ------------------------------------------------------------------
    def build_from_file(self, filepath: str, module_name: str = None):
        """解析一個 .py 檔案，回傳這次建立/更新的函式節點 id 列表。
        只認得同一個檔案內的呼叫關係——跨檔案請用 build_project。
        """
        module_name = module_name or os.path.splitext(os.path.basename(filepath))[0]
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)

        func_ids = []
        func_nodes = {}  # 函式名稱 -> (func_id, ast node)，第二輪解析呼叫關係要用

        # 第一輪：先把所有函式節點建出來
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_id = f"{module_name}.{node.name}"
                signature = f"{node.name}({', '.join(a.arg for a in node.args.args)})"
                self.store.upsert_node(
                    func_id, "Function",
                    properties={"file": filepath, "lineno": node.lineno, "signature": signature},
                    summary=ast.get_docstring(node) or signature,
                )
                func_ids.append(func_id)
                func_nodes[node.name] = (func_id, node)

        # 第二輪：所有函式節點都存在之後，才能安全地建立彼此的 CALLS 關聯
        for name, (func_id, node) in func_nodes.items():
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    callee_name = self._resolve_call_name(sub)
                    if callee_name and callee_name in func_nodes and callee_name != name:
                        callee_id = func_nodes[callee_name][0]
                        self.store.add_relation(func_id, "CALLS", callee_id)

        return func_ids

    def _resolve_call_name(self, call_node: ast.Call):
        if isinstance(call_node.func, ast.Name):
            return call_node.func.id
        if isinstance(call_node.func, ast.Attribute):
            return call_node.func.attr
        return None

    # ------------------------------------------------------------------
    # 整個專案（新的入口）：解析 import，支援跨檔案呼叫關係
    # ------------------------------------------------------------------
    def build_project(self, root_dir: str, file_paths: list = None) -> dict:
        """建立一整個專案（或指定的多個檔案）的呼叫關係圖，包含跨檔案的 import 解析。
        回傳 {filepath: [func_ids...]}，讓呼叫端知道每個檔案分別建出了哪些節點。

        分兩輪做，原因是跨檔案呼叫要等「所有檔案的函式節點都已經存在」才查得到目標：
        1. 每個檔案各自解析一次：建函式節點、順便記下這個檔案的 import 對照表。
        2. 全部檔案的節點都建好之後，再走一次每個檔案的呼叫，這次可以用 import
           對照表把 `utils.helper()` 這種呼叫解析到正確的跨檔案目標。
           解析不到的（外部函式庫、沒被包含進這次範圍的檔案、相對匯入）就跳過。
        """
        if file_paths is None:
            file_paths = self._discover_python_files(root_dir)

        parsed = {}  # filepath -> {"func_defs": {name: (func_id, node)}, "imports": {...}}
        result = {}

        # 第一輪：建節點 + 記 import
        for filepath in file_paths:
            module_name = self._module_name_from_path(filepath, root_dir)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source, filename=filepath)
            except (SyntaxError, OSError, UnicodeDecodeError) as e:
                # 單一檔案解析失敗不該讓整個專案的建圖流程中斷，跳過這個檔案繼續其他的
                result[filepath] = []
                continue

            func_defs = {}
            func_ids = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_id = f"{module_name}.{node.name}"
                    signature = f"{node.name}({', '.join(a.arg for a in node.args.args)})"
                    self.store.upsert_node(
                        func_id, "Function",
                        properties={"file": filepath, "lineno": node.lineno, "signature": signature},
                        summary=ast.get_docstring(node) or signature,
                    )
                    func_defs[node.name] = (func_id, node)
                    func_ids.append(func_id)

            parsed[filepath] = {"func_defs": func_defs, "imports": self._collect_imports(tree)}
            result[filepath] = func_ids

        # 第二輪：解析呼叫（含跨檔案），此時所有檔案的函式節點都已經存在了
        for filepath, info in parsed.items():
            func_defs = info["func_defs"]
            imports = info["imports"]
            for name, (func_id, node) in func_defs.items():
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        target_id = self._resolve_call_target(sub, func_defs, imports)
                        if target_id and target_id != func_id and target_id in self.store.nodes:
                            self.store.add_relation(func_id, "CALLS", target_id)

        return result

    def _discover_python_files(self, root_dir: str) -> list:
        found = []
        skip_dirs = {"__pycache__", ".git", "venv", ".venv", "node_modules", ".mypy_cache"}
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for fn in filenames:
                if fn.endswith(".py"):
                    found.append(os.path.join(dirpath, fn))
        return found

    def _module_name_from_path(self, filepath: str, root_dir: str) -> str:
        """把檔案路径換算成 Python import 時會用的點號模組名，
        例如 <root>/pkg/utils.py -> "pkg.utils"，<root>/pkg/__init__.py -> "pkg"。
        這樣自動算出來的模組名才會跟檔案裡實際的 import 語句互相對得上。
        """
        rel = os.path.relpath(filepath, root_dir)
        if rel.endswith(".py"):
            rel = rel[:-3]
        parts = [p for p in rel.split(os.sep) if p not in ("", ".")]
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            return os.path.splitext(os.path.basename(filepath))[0]
        return ".".join(parts)

    def _collect_imports(self, tree: ast.AST) -> dict:
        """回傳 {local_name: {"module": 目標模組, "symbol": 目標符號或 None}}。
        symbol 是 None 代表這是整個模組的 import（例如 `import utils`），
        之後遇到 `utils.func()` 這種 Attribute 呼叫，要去查 utils 模組底下的 func；
        symbol 有值代表這是 `from x import y` 這種，local_name 直接呼叫就對應到目標函式。
        """
        imports = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    imports[local] = {"module": alias.name, "symbol": None}
            elif isinstance(node, ast.ImportFrom):
                if not node.module or node.level:
                    # node.level > 0 代表相對匯入（from . import x），沒有專案結構以外的
                    # 資訊沒辦法可靠算出它實際指向哪個模組，跳過不處理。
                    continue
                for alias in node.names:
                    local = alias.asname or alias.name
                    imports[local] = {"module": node.module, "symbol": alias.name}
        return imports

    def _resolve_call_target(self, call_node: ast.Call, func_defs: dict, imports: dict):
        """比 _resolve_call_name 多考慮了 import 資訊，可以解析出跨檔案的目標 id。"""
        func = call_node.func
        if isinstance(func, ast.Name):
            name = func.id
            if name in func_defs:
                return func_defs[name][0]  # 同檔案內的函式，優先
            if name in imports and imports[name]["symbol"]:
                return f"{imports[name]['module']}.{imports[name]['symbol']}"
            return None
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            base = func.value.id
            if base in imports and imports[base]["symbol"] is None:
                return f"{imports[base]['module']}.{func.attr}"
            return None
        return None

    # ------------------------------------------------------------------
    # 查詢（兩種入口共用）
    # ------------------------------------------------------------------
    def find_callers(self, func_id: str):
        """誰呼叫了這個函式？—— 就是「改 b() 要通知誰」那個查詢。"""
        return self.store.get_incoming(func_id, rel="CALLS")

    def find_callees(self, func_id: str):
        return self.store.get_outgoing(func_id, rel="CALLS")
