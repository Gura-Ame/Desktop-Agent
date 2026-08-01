"""
Code Graph：把你原本 a()/b() 的想法具體實作出來。

用 ast 解析一個 .py 檔案，把每個函式變成 MemoryStore 裡的一個 Object，
並且分析函式內部呼叫了哪些同檔案的其他函式，記成 CALLS 關聯。

之後要問「我改了 b()，誰會受影響？」就不用讓模型自己亂猜，
而是直接對 Disk 做一次反向查詢 (get_incoming)。

限制（先求用得上，不求完美）：
- 只分析同一個檔案內的呼叫關係，import 進來的外部函式抓不到
- 只用簡單的名稱比對 (ast.Name / ast.Attribute.attr)，動態呼叫、多型、裝飾器包裝都可能漏掉
- 沒有處理同名函式（例如兩個不同 class 裡都有 __init__）互相搞混的情況
之後要做跨檔案/跨模組的完整呼叫圖，可以在這個模組上擴充，介面不用大改。
"""

import ast
import os

from memory_store import MemoryStore


class CodeGraphBuilder:
    def __init__(self, store: MemoryStore):
        self.store = store

    def build_from_file(self, filepath: str, module_name: str = None):
        """解析一個 .py 檔案，回傳這次建立/更新的函式節點 id 列表。"""
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

    def find_callers(self, func_id: str):
        """誰呼叫了這個函式？—— 就是「改 b() 要通知誰」那個查詢。"""
        return self.store.get_incoming(func_id, rel="CALLS")

    def find_callees(self, func_id: str):
        return self.store.get_outgoing(func_id, rel="CALLS")
