import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
"""
針對 code_import_resolver.py 的單元測試（從 code_graph.py 拆出來的部分）。
拆分時發現舊版 _resolve_relative_import 算了兩次 base_parts、第一次的結果
立刻被第二次覆蓋掉，完全是死碼——這裡的測試直接針對最終公式驗證，
確保拆分/清理死碼後行為沒有跑掉。
"""
import ast

from tools.code_import_resolver import collect_imports, resolve_relative_import


class TestResolveRelativeImport:
    def test_level_1_same_package(self):
        # from . import x，在 pkg.sub.foo 這個檔案裡 → pkg.sub
        assert resolve_relative_import("pkg.sub.foo", 1, "") == "pkg.sub"

    def test_level_1_with_module_name(self):
        # from .utils import helper，在 pkg.sub.foo 裡 → pkg.sub.utils
        assert resolve_relative_import("pkg.sub.foo", 1, "utils") == "pkg.sub.utils"

    def test_level_2_goes_up_two_packages(self):
        # from .. import x，在 pkg.sub.foo 裡 → pkg
        assert resolve_relative_import("pkg.sub.foo", 2, "") == "pkg"

    def test_level_2_with_module_name(self):
        # from ..shared import x，在 pkg.sub.foo 裡：上兩層是 pkg，再接上 shared
        assert resolve_relative_import("pkg.sub.foo", 2, "shared") == "pkg.shared"

    def test_top_level_module_with_level_1(self):
        # current_module 只有一段時，去掉一段之後就空了
        assert resolve_relative_import("foo", 1, "") == ""

    def test_empty_current_module(self):
        assert resolve_relative_import("", 1, "utils") == "utils"


class TestCollectImports:
    def test_plain_import(self):
        tree = ast.parse("import os")
        imports = collect_imports(tree)
        assert imports["os"] == {"module": "os", "symbol": None}

    def test_import_with_alias(self):
        tree = ast.parse("import numpy as np")
        imports = collect_imports(tree)
        assert imports["np"] == {"module": "numpy", "symbol": None}

    def test_from_import(self):
        tree = ast.parse("from os import path")
        imports = collect_imports(tree)
        assert imports["path"] == {"module": "os", "symbol": "path"}

    def test_from_import_with_alias(self):
        tree = ast.parse("from os import path as p")
        imports = collect_imports(tree)
        assert imports["p"] == {"module": "os", "symbol": "path"}

    def test_relative_import_resolved_with_current_module(self):
        tree = ast.parse("from .utils import helper")
        imports = collect_imports(tree, current_module="pkg.sub.foo")
        assert imports["helper"] == {"module": "pkg.sub.utils", "symbol": "helper"}

    def test_relative_import_without_current_module_is_skipped(self):
        """沒有 current_module 資訊時沒辦法算出絕對路徑，應該安全跳過而不是猜錯。"""
        tree = ast.parse("from . import helper")
        imports = collect_imports(tree, current_module="")
        assert "helper" not in imports

    def test_bare_relative_dot_import(self):
        # from . import helper，在 pkg.sub.foo 裡 → pkg.sub.helper
        tree = ast.parse("from . import helper")
        imports = collect_imports(tree, current_module="pkg.sub.foo")
        assert imports["helper"] == {"module": "pkg.sub", "symbol": "helper"}
