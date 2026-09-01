"""
AST 走訪：收集一個檔案裡所有函式定義（含 class 前綴、裝飾器）。

從 code_graph.py 拆出來——這部分是純粹的「讀 AST、收集資訊」，
跟 CodeGraphBuilder 怎麼把這些資訊寫進 MemoryStore 完全無關，
拆開後兩邊都更容易單獨理解跟測試。
"""
import ast


class FuncCollector(ast.NodeVisitor):
    """走訪 AST，收集每個函式的完整限定名（含 class 前綴）、裝飾器、AST node。

    對比裸 ast.walk：
    - 維護 class_stack，讓同一個檔案裡兩個 class 各自的 __init__ 可以正確區分
      → func_defs key 為 "ClassName.func_name"，而不是單純 "func_name"。
    - 同時偵測裝飾器，存進 decorators list，供外層標記 has_decorator。
    """

    def __init__(self):
        self.func_defs: dict[str, tuple] = {}  # qualified_name -> (func_id_placeholder, node, decorators)
        self._class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef):
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._register(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._register(node)

    def _register(self, node):
        parts = self._class_stack + [node.name]
        qname = ".".join(parts)  # e.g. "MyClass.__init__" or "standalone_func"
        decorators = [self._decorator_name(d) for d in node.decorator_list]
        # 若重名（極罕見，但可能），保留先定義的，並在其 decorators 裡記錄衝突資訊
        if qname not in self.func_defs:
            self.func_defs[qname] = (None, node, decorators)  # func_id 由外層填入
        # 進入函式體內（允許有巢狀函式），但巢狀函式也會被收集進來並有自己的完整路徑
        self.generic_visit(node)

    @staticmethod
    def _decorator_name(dec_node) -> str:
        if isinstance(dec_node, ast.Name):
            return dec_node.id
        if isinstance(dec_node, ast.Attribute):
            return f"{FuncCollector._node_name(dec_node.value)}.{dec_node.attr}"
        if isinstance(dec_node, ast.Call):
            return FuncCollector._decorator_name(dec_node.func)
        return "<decorator>"

    @staticmethod
    def _node_name(node) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{FuncCollector._node_name(node.value)}.{node.attr}"
        return "?"


# 相容別名：舊程式碼如果直接 import 私有名稱 _FuncCollector 也不會壞。
_FuncCollector = FuncCollector
