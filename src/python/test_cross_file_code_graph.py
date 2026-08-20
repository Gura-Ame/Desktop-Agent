"""
測試 CodeGraphBuilder.build_project：跨檔案的 import 解析。
會真的在暫存資料夾建出一個多檔案的假專案來測。

執行方式：
    python test_cross_file_code_graph.py
"""

import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory_store import MemoryStore  # noqa: E402
from code_graph import CodeGraphBuilder  # noqa: E402


def with_temp_project(files: dict):
    """files: {相對路徑: 檔案內容}，會在一個暫存資料夾裡把這些檔案都建出來。"""
    def decorator(fn):
        def wrapper():
            root = tempfile.mkdtemp()
            mem_fd, mem_path = tempfile.mkstemp(suffix=".json")
            os.close(mem_fd)
            os.remove(mem_path)
            try:
                for rel_path, content in files.items():
                    full_path = os.path.join(root, rel_path)
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    with open(full_path, "w", encoding="utf-8") as f:
                        f.write(content)
                store = MemoryStore(mem_path)
                builder = CodeGraphBuilder(store)
                fn(builder, store, root)
            finally:
                shutil.rmtree(root, ignore_errors=True)
                if os.path.exists(mem_path):
                    os.remove(mem_path)
        return wrapper
    return decorator


@with_temp_project({
    "utils.py": "def helper():\n    return 1\n",
    "main.py": "from utils import helper\n\ndef run():\n    return helper()\n",
})
def test_from_import_resolves_cross_file(builder: CodeGraphBuilder, store: MemoryStore, root: str):
    builder.build_project(root)
    assert store.get_node("utils.helper") is not None
    assert store.get_node("main.run") is not None
    assert builder.find_callees("main.run") == ["utils.helper"]
    assert builder.find_callers("utils.helper") == ["main.run"]
    print("[PASS] test_from_import_resolves_cross_file")


@with_temp_project({
    "utils.py": "def helper():\n    return 1\n",
    "main.py": "import utils\n\ndef run():\n    return utils.helper()\n",
})
def test_whole_module_import_resolves_cross_file(builder: CodeGraphBuilder, store: MemoryStore, root: str):
    builder.build_project(root)
    assert builder.find_callees("main.run") == ["utils.helper"]
    print("[PASS] test_whole_module_import_resolves_cross_file")


@with_temp_project({
    "utils.py": "def helper():\n    return 1\n",
    "main.py": "from utils import helper as h\n\ndef run():\n    return h()\n",
})
def test_from_import_with_alias_resolves(builder: CodeGraphBuilder, store: MemoryStore, root: str):
    builder.build_project(root)
    assert builder.find_callees("main.run") == ["utils.helper"]
    print("[PASS] test_from_import_with_alias_resolves")


@with_temp_project({
    "utils.py": "def helper():\n    return 1\n",
    "main.py": "import utils as u\n\ndef run():\n    return u.helper()\n",
})
def test_whole_module_import_with_alias_resolves(builder: CodeGraphBuilder, store: MemoryStore, root: str):
    builder.build_project(root)
    assert builder.find_callees("main.run") == ["utils.helper"]
    print("[PASS] test_whole_module_import_with_alias_resolves")


@with_temp_project({
    "pkg/__init__.py": "",
    "pkg/utils.py": "def helper():\n    return 1\n",
    "main.py": "from pkg.utils import helper\n\ndef run():\n    return helper()\n",
})
def test_nested_package_module_name_matches_import_path(builder: CodeGraphBuilder, store: MemoryStore, root: str):
    builder.build_project(root)
    assert store.get_node("pkg.utils.helper") is not None, (
        f"模組名應該要能正確反映巢狀資料夾路徑，實際節點: {list(store.nodes.keys())}"
    )
    assert builder.find_callees("main.run") == ["pkg.utils.helper"]
    print("[PASS] test_nested_package_module_name_matches_import_path")


@with_temp_project({
    "main.py": (
        "import os\n"
        "import unknown_external_lib\n\n"
        "def run():\n"
        "    os.path.join('a', 'b')\n"
        "    unknown_external_lib.do_something()\n"
    ),
})
def test_unresolved_external_calls_are_skipped_without_error(builder: CodeGraphBuilder, store: MemoryStore, root: str):
    """呼叫目標不在這次建圖範圍內（標準庫、外部套件），應該直接跳過，不報錯、不產生斷鏈。"""
    result = builder.build_project(root)  # 不該丟例外
    assert store.get_node("main.run") is not None
    assert builder.find_callees("main.run") == [], "外部函式庫的呼叫應該被跳過，不建立關聯"
    print("[PASS] test_unresolved_external_calls_are_skipped_without_error")


@with_temp_project({
    "a.py": "def func_a():\n    return 1\n",
    "b.py": "from a import func_a\n\ndef func_b():\n    return func_a()\n",
    "c.py": "from b import func_b\n\ndef func_c():\n    return func_b()\n",
})
def test_transitive_cross_file_chain(builder: CodeGraphBuilder, store: MemoryStore, root: str):
    """a <- b <- c 三個檔案串起來的呼叫鏈，反向查詢也要串得起來。"""
    builder.build_project(root)
    assert builder.find_callers("a.func_a") == ["b.func_b"]
    assert builder.find_callers("b.func_b") == ["c.func_c"]
    print("[PASS] test_transitive_cross_file_chain")


@with_temp_project({
    "utils.py": "def helper():\n    return 1\n",
    "main.py": "def run():\n    return helper()\n",  # 故意沒有 import，只是剛好同名
})
def test_call_to_unimported_same_name_function_not_falsely_linked(builder: CodeGraphBuilder, store: MemoryStore, root: str):
    """main.py 呼叫了一個叫 helper 的函式，但沒有 import 它——不該被誤判成跨檔案呼叫到 utils.helper，
    因為沒有 import 語句可以佐證這個名稱真的是指向 utils 模組。"""
    builder.build_project(root)
    assert builder.find_callees("main.run") == [], (
        "沒有 import 佐證的情況下，同名函式不該被誤判成跨檔案呼叫關係"
    )
    print("[PASS] test_call_to_unimported_same_name_function_not_falsely_linked")


@with_temp_project({
    "a.py": "def foo():\n    return bar()\n\ndef bar():\n    return 1\n",
    "b.py": "from a import foo\n\ndef use_it():\n    return foo()\n",
})
def test_same_file_resolution_still_takes_priority_within_file(builder: CodeGraphBuilder, store: MemoryStore, root: str):
    """同檔案內的呼叫關係解析邏輯不該被跨檔案功能弄壞。"""
    builder.build_project(root)
    assert builder.find_callees("a.foo") == ["a.bar"]
    assert builder.find_callees("b.use_it") == ["a.foo"]
    print("[PASS] test_same_file_resolution_still_takes_priority_within_file")


def test_syntax_error_in_one_file_does_not_break_whole_project():
    root = tempfile.mkdtemp()
    mem_fd, mem_path = tempfile.mkstemp(suffix=".json")
    os.close(mem_fd)
    os.remove(mem_path)
    try:
        with open(os.path.join(root, "broken.py"), "w", encoding="utf-8") as f:
            f.write("def broken(:\n    this is not valid python\n")
        with open(os.path.join(root, "fine.py"), "w", encoding="utf-8") as f:
            f.write("def works():\n    return 1\n")

        store = MemoryStore(mem_path)
        builder = CodeGraphBuilder(store)
        result = builder.build_project(root)  # 不該丟例外中斷整個流程

        broken_path = os.path.join(root, "broken.py")
        fine_path = os.path.join(root, "fine.py")
        assert result[fine_path] == ["fine.works"]
        assert result[broken_path] == []
        assert store.get_node("fine.works") is not None
        print("[PASS] test_syntax_error_in_one_file_does_not_break_whole_project")
    finally:
        shutil.rmtree(root, ignore_errors=True)
        if os.path.exists(mem_path):
            os.remove(mem_path)


def test_build_from_file_still_works_unchanged():
    """既有的單檔案 API 不該被這次改動影響。"""
    root = tempfile.mkdtemp()
    mem_fd, mem_path = tempfile.mkstemp(suffix=".json")
    os.close(mem_fd)
    os.remove(mem_path)
    try:
        filepath = os.path.join(root, "sample.py")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("def a():\n    return b()\n\ndef b():\n    return 1\n")

        store = MemoryStore(mem_path)
        builder = CodeGraphBuilder(store)
        func_ids = builder.build_from_file(filepath, module_name="sample")

        assert set(func_ids) == {"sample.a", "sample.b"}
        assert builder.find_callees("sample.a") == ["sample.b"]
        print("[PASS] test_build_from_file_still_works_unchanged")
    finally:
        shutil.rmtree(root, ignore_errors=True)
        if os.path.exists(mem_path):
            os.remove(mem_path)


if __name__ == "__main__":
    tests = [
        test_from_import_resolves_cross_file,
        test_whole_module_import_resolves_cross_file,
        test_from_import_with_alias_resolves,
        test_whole_module_import_with_alias_resolves,
        test_nested_package_module_name_matches_import_path,
        test_unresolved_external_calls_are_skipped_without_error,
        test_transitive_cross_file_chain,
        test_call_to_unimported_same_name_function_not_falsely_linked,
        test_same_file_resolution_still_takes_priority_within_file,
        test_syntax_error_in_one_file_does_not_break_whole_project,
        test_build_from_file_still_works_unchanged,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
