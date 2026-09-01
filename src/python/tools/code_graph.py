"""
Code Graph：把你原本 a()/b() 的想法具體實作出來。

用 ast 解析 .py 檔案，把每個函式變成 MemoryStore 裡的一個 Object，
並分析函式之間互相呼叫的關係，記成 CALLS 關聯。

之後要問「我改了 b()，誰會受影響？」就不用讓模型自己亂猜，
而是直接對 Disk 做一次反向查詢 (get_incoming)。

兩種用法：
- build_from_file(filepath)：只分析單一檔案，只認得同檔案內的呼叫關係。
  最早的版本，保留下來當作最簡單的入口，介面沒變。
- build_project(root_dir)：分析一整個專案的多個檔案，解析 import（含相對匯入），
  能把跨檔案的呼叫（例如 `from utils import helper` 之後呼叫 `helper()`）
  也記成正確的 CALLS 關聯，不再只侷限在同一個檔案內。

已知限制（靜態分析本質上的邊界）：
- getattr、字串組出函式名等「完全動態」的呼叫，AST 無法追蹤。
  偵測到 getattr() 呼叫時，函式節點會帶 has_dynamic_call=True 標記。
- 裝飾器可能改變函式行為，裝飾器存在時節點帶 decorators 列表。
  以上兩種標記讓查詢端知道「此節點的靜態圖可能不完整」。
- 範圍外的呼叫目標（外部函式庫、沒被包含進來的檔案），如果能從 import
  追蹤到模組名，會建立 ExternalRef 節點並形成 CALLS 關聯；完全追蹤不到的
  （純猜測、無 import 根據）仍跳過，避免雜訊。
"""

import ast
import os
from typing import Optional, List, Dict, Any, Tuple

from memory.memory_store import MemoryStore
from tools.code_ast_visitor import FuncCollector
from tools.code_import_resolver import collect_imports, resolve_relative_import


# ---------------------------------------------------------------------------
# 主要類別
# ---------------------------------------------------------------------------
class CodeGraphBuilder:
    def __init__(self, store: MemoryStore):
        self.store = store

    # ------------------------------------------------------------------
    # 單一檔案（原本的入口，介面不變）
    # ------------------------------------------------------------------
    def build_from_file(self, filepath: str, module_name: Optional[str] = None):
        """解析一個 .py 檔案，回傳這次建立/更新的函式節點 id 列表。
        只認得同一個檔案內的呼叫關係——跨檔案請用 build_project。

        函式 id 格式：{module_name}.{ClassName.func_name}（含 class 前綴，
        避免不同 class 的同名函式互蓋）。
        """
        module_name = module_name or os.path.splitext(os.path.basename(filepath))[0]
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)

        collector = FuncCollector()
        collector.visit(tree)
        imports = collect_imports(tree, current_module=module_name)

        func_ids = []
        func_defs: dict[str, tuple] = {}  # qualified_name -> (func_id, node, decorators)

        # 第一輪：先把所有函式節點建出來
        for qname, (_, node, decorators) in collector.func_defs.items():
            func_id = f"{module_name}.{qname}"
            signature = f"{node.name}({', '.join(a.arg for a in node.args.args)})"
            props = {
                "file": filepath,
                "lineno": node.lineno,
                "signature": signature,
                "qualified_name": qname,
            }
            if decorators:
                props["has_decorator"] = True
                props["decorators"] = decorators

            self.store.upsert_node(
                func_id, "Function",
                properties=props,
                summary=ast.get_docstring(node) or signature,
            )
            func_ids.append(func_id)
            func_defs[qname] = (func_id, node, decorators)

        # 第二輪：所有函式節點都存在之後，才能安全地建立彼此的 CALLS 關聯
        # imports 也一起帶進來，讓 ExternalRef 可以在 single-file 模式下正常建立
        for qname, (func_id, node, _) in func_defs.items():
            self._link_calls(func_id, node, func_defs, imports=imports)

        return func_ids

    # ------------------------------------------------------------------
    # 整個專案（新的入口）：解析 import，支援跨檔案呼叫關係
    # ------------------------------------------------------------------
    def build_project(self, root_dir: str, file_paths: Optional[list] = None) -> dict:
        """建立一整個專案（或指定的多個檔案）的呼叫關係圖，包含跨檔案的 import 解析。
        回傳 {filepath: [func_ids...]}，讓呼叫端知道每個檔案分別建出了哪些節點。

        分兩輪做，原因是跨檔案呼叫要等「所有檔案的函式節點都已經存在」才查得到目標：
        1. 每個檔案各自解析一次：建函式節點、順便記下這個檔案的 import 對照表。
        2. 全部檔案的節點都建好之後，再走一次每個檔案的呼叫，這次可以用 import
           對照表把 `utils.helper()` 這種呼叫解析到正確的跨檔案目標。
           對於外部函式庫能追蹤到模組名的，建立 ExternalRef 節點；
           完全追蹤不到的仍跳過，不留雜訊。
        """
        if file_paths is None:
            file_paths = self._discover_python_files(root_dir)

        parsed = {}  # filepath -> {"func_defs": {qname: (func_id, node, decs)}, "imports": {...}}
        result = {}

        # 第一輪：建節點 + 記 import
        for filepath in file_paths:
            module_name = self._module_name_from_path(filepath, root_dir)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source, filename=filepath)
            except (SyntaxError, OSError, UnicodeDecodeError):
                # 單一檔案解析失敗不該讓整個專案的建圖流程中斷，跳過這個檔案繼續其他的
                result[filepath] = []
                continue

            collector = FuncCollector()
            collector.visit(tree)

            func_defs: dict[str, tuple] = {}
            func_ids = []
            for qname, (_, node, decorators) in collector.func_defs.items():
                func_id = f"{module_name}.{qname}"
                signature = f"{node.name}({', '.join(a.arg for a in node.args.args)})"
                props = {
                    "file": filepath,
                    "lineno": node.lineno,
                    "signature": signature,
                    "qualified_name": qname,
                }
                if decorators:
                    props["has_decorator"] = True
                    props["decorators"] = decorators

                self.store.upsert_node(
                    func_id, "Function",
                    properties=props,
                    summary=ast.get_docstring(node) or signature,
                )
                func_defs[qname] = (func_id, node, decorators)
                func_ids.append(func_id)

            imports = collect_imports(tree, current_module=module_name)
            parsed[filepath] = {"func_defs": func_defs, "imports": imports}
            result[filepath] = func_ids

        # 第二輪：解析呼叫（含跨檔案），此時所有檔案的函式節點都已經存在了
        for filepath, info in parsed.items():
            for qname, (func_id, node, _) in info["func_defs"].items():
                self._link_calls(func_id, node, info["func_defs"], info["imports"])

        return result

    # ------------------------------------------------------------------
    # 呼叫關係連結（兩種入口共用）
    # ------------------------------------------------------------------
    def _link_calls(self, func_id: str, node, func_defs: dict, imports: dict):
        """走訪函式體，找出所有呼叫，建立 CALLS 關聯。
        同時偵測 getattr() 呼叫並標記 has_dynamic_call。
        """
        has_dynamic = False
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue

            # 偵測 getattr() 呼叫——動態呼叫的主要特徵
            if isinstance(sub.func, ast.Name) and sub.func.id == "getattr":
                has_dynamic = True
                continue

            target_id = self._resolve_call_target(sub, func_defs, imports)
            if target_id and target_id != func_id:
                if target_id in self.store.nodes:
                    self.store.add_relation(func_id, "CALLS", target_id)
                else:
                    # 目標不在圖內，嘗試建立 ExternalRef（只在有明確模組根據時才建）
                    ext_id = self._ensure_external_ref(target_id, imports)
                    if ext_id:
                        self.store.add_relation(func_id, "CALLS", ext_id)

        if has_dynamic:
            n = self.store.nodes.get(func_id)
            if n and not n.properties.get("has_dynamic_call"):
                n.properties["has_dynamic_call"] = True
                n.touch_version()
                self.store.save()

    def _ensure_external_ref(self, target_id: str, imports: dict) -> str | None:
        """若 target_id 對應到一個有 import 根據的外部符號，在 store 裡建立
        type=ExternalRef 的節點，並回傳其 id；否則回傳 None。

        target_id 格式："{module}.{symbol}"，例如 "os.path.join" 或 "requests.get"。
        有 import 根據 = target_id 的第一段（module root）出現在 imports 裡，
        代表這個呼叫確實來自一個明確的 import 語句，不是純猜測。
        """
        if "." not in target_id:
            return None
        # 取第一段 module root 判斷有沒有 import 根據
        root = target_id.split(".")[0]
        # 任何 import 裡有以這個 root 開頭的模組，就認為有根據
        has_basis = any(
            v["module"].split(".")[0] == root or v["module"] == root
            for v in imports.values()
        )
        if not has_basis:
            return None

        if target_id not in self.store.nodes:
            module_part, _, symbol_part = target_id.rpartition(".")
            self.store.upsert_node(
                target_id, "ExternalRef",
                properties={"module": module_part, "name": symbol_part},
                summary=target_id,
            )
        return target_id

    # ------------------------------------------------------------------
    # 檔案探索 + 模組名計算
    # ------------------------------------------------------------------
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
        """把檔案路徑換算成 Python import 時會用的點號模組名，
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

    # ------------------------------------------------------------------
    # 呼叫目標解析
    # ------------------------------------------------------------------
    def _resolve_call_target(self, call_node: ast.Call, func_defs: dict, imports: dict):
        """比 _resolve_call_name 多考慮了 import 資訊，可以解析出跨檔案的目標 id。

        解析優先順序：
        1. 同檔案內的函式（func_defs 裡找得到）
        2. from x import y 帶進來的符號（imports 裡 symbol 有值）
        3. import x 帶進來的模組，搭配 x.func() 的 Attribute 呼叫
        4. 解析不到 → 回傳 None（由 _link_calls 決定是否建 ExternalRef）
        """
        func = call_node.func
        if isinstance(func, ast.Name):
            name = func.id
            # 優先：同檔案內（完整 qname 或單純函式名都試）
            # func_defs key 是 qualified name，可能是 "ClassName.func" 或 "func"
            if name in func_defs:
                return func_defs[name][0]
            # 找以此名稱結尾的 qname（例如 name="foo" 能匹配 "MyClass.foo"）
            matches = [fid for qn, (fid, _, _) in func_defs.items() if qn == name or qn.endswith(f".{name}")]
            if len(matches) == 1:
                return matches[0]
            # 跨檔案：from x import y → 直接呼叫 y()
            if name in imports and imports[name]["symbol"]:
                info = imports[name]
                return f"{info['module']}.{info['symbol']}"
            return None

        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            base = func.value.id
            # import x → x.func()
            if base in imports and imports[base]["symbol"] is None:
                return f"{imports[base]['module']}.{func.attr}"
            # from x import cls → cls.method()（常見於使用類別的方法呼叫）
            if base in imports and imports[base]["symbol"]:
                info = imports[base]
                return f"{info['module']}.{info['symbol']}.{func.attr}"
            return None

        return None

    # ------------------------------------------------------------------
    # 查詢（兩種入口共用）
    # ------------------------------------------------------------------
    def find_callers(self, func_id: str):
        """誰呼叫了這個函式？—— 就是「改 b() 要通知誰」那個查詢。"""
        return self.store.get_incoming(func_id, rel="CALLS")

    def find_callees(self, func_id: str):
        """這個函式呼叫了誰？—— 包含同專案內的函式和 ExternalRef 節點。"""
        return self.store.get_outgoing(func_id, rel="CALLS")
