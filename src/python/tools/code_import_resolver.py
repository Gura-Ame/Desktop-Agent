"""
Import 語句解析（含相對匯入換算成絕對模組名）。

從 code_graph.py 拆出來——這部分是純粹的字串/AST 運算，不需要碰
MemoryStore，獨立出來後可以完全不依賴任何專案外部狀態地單獨測試。
"""
import ast


def collect_imports(tree: ast.AST, current_module: str = "") -> dict:
    """回傳 {local_name: {"module": 目標模組, "symbol": 目標符號或 None}}。

    symbol 是 None 代表這是整個模組的 import（例如 `import utils`），
    之後遇到 `utils.func()` 這種 Attribute 呼叫，要去查 utils 模組底下的 func；
    symbol 有值代表這是 `from x import y` 這種，local_name 直接呼叫就對應到目標函式。

    相對匯入（from . import x、from ..utils import helper）透過
    resolve_relative_import 計算出絕對模組名，不會被跳過。
    """
    imports = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                imports[local] = {"module": alias.name, "symbol": None}
        elif isinstance(node, ast.ImportFrom):
            if node.level and not node.module and not current_module:
                # 純相對匯入但沒有當前模組資訊，仍然跳過
                continue
            if node.level:
                # 相對匯入：用 current_module 推算絕對模組名
                abs_module = resolve_relative_import(
                    current_module, node.level, node.module or ""
                )
            elif not node.module:
                continue
            else:
                abs_module = node.module

            for alias in node.names:
                local = alias.asname or alias.name
                imports[local] = {"module": abs_module, "symbol": alias.name}
    return imports


def resolve_relative_import(current_module: str, level: int, relative_module: str) -> str:
    """把相對匯入轉換成絕對模組名。

    規則（與 Python importlib 的行為一致）：
    - level=1 表示同層 package（from . import x）→ 去掉 current_module 最後一段
    - level=2 表示上一層（from .. import x）→ 去掉最後兩段，以此類推
    - relative_module 若有值，接在算出的 base 後面

    例子：
      current_module="pkg.sub.foo", level=1, relative_module="utils"
      → base = "pkg.sub"  → "pkg.sub.utils"

      current_module="pkg.sub.foo", level=2, relative_module=""
      → base = "pkg"      → "pkg"

      current_module="pkg.sub.foo", level=1, relative_module=""
      → base = "pkg.sub"  → "pkg.sub"
    """
    parts = current_module.split(".") if current_module else []
    # level 代表往上幾層「包」。若 current 是 a.b.c（檔案），
    # 它所在的包是 a.b，level=1 就留 a.b，level=2 就留 a。
    base_parts = parts[: max(0, len(parts) - level)]
    if relative_module:
        base_parts += relative_module.split(".")
    return ".".join(base_parts) if base_parts else relative_module
