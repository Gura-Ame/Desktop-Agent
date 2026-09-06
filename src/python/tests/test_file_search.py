"""
tools/file_search.py 的測試：一個輕量版 grep 工具，讓 agent 不知道要看哪個檔案時
可以先用正則表達式跨檔案找內容。
"""
import os
import tempfile
import shutil

from tools.file_search import search_files_by_content, find_files_by_name, _looks_binary


def make_tree(files: dict) -> str:
    """在一個臨時目錄裡依 {相對路徑: 內容} 建好一批檔案，回傳根目錄路徑。"""
    root = tempfile.mkdtemp()
    for rel_path, content in files.items():
        full_path = os.path.join(root, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        if isinstance(content, bytes):
            with open(full_path, "wb") as f:
                f.write(content)
        else:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
    return root


def test_finds_matching_line_with_file_and_line_number():
    root = make_tree({
        "a.py": "def foo():\n    return 1\n",
        "b.py": "def bar():\n    TODO_MARKER = 1\n    return TODO_MARKER\n",
    })
    try:
        result = search_files_by_content("TODO_MARKER", root_dir=root)
        assert "b.py:2" in result
        assert "a.py" not in result
        print("[PASS] test_finds_matching_line_with_file_and_line_number")
    finally:
        shutil.rmtree(root)


def test_no_match_returns_explanatory_message_not_error():
    root = make_tree({"a.py": "print('hello')\n"})
    try:
        result = search_files_by_content("nonexistent_pattern_xyz", root_dir=root)
        assert "沒有找到" in result
        print("[PASS] test_no_match_returns_explanatory_message_not_error")
    finally:
        shutil.rmtree(root)


def test_invalid_regex_returns_error_string_not_exception():
    root = make_tree({"a.py": "x = 1\n"})
    try:
        result = search_files_by_content("(unclosed", root_dir=root)
        assert "語法錯誤" in result
        print("[PASS] test_invalid_regex_returns_error_string_not_exception")
    finally:
        shutil.rmtree(root)


def test_nonexistent_root_dir_returns_error_string():
    result = search_files_by_content("x", root_dir="/definitely/not/a/real/path/xyz")
    assert "不是一個存在的資料夾" in result
    print("[PASS] test_nonexistent_root_dir_returns_error_string")


def test_file_glob_filters_by_filename_pattern():
    root = make_tree({
        "a.py": "MATCH_ME = 1\n",
        "b.txt": "MATCH_ME = 1\n",
    })
    try:
        result = search_files_by_content("MATCH_ME", root_dir=root, file_glob="*.py")
        assert "a.py" in result
        assert "b.txt" not in result
        print("[PASS] test_file_glob_filters_by_filename_pattern")
    finally:
        shutil.rmtree(root)


def test_case_insensitive_by_default_and_case_sensitive_when_requested():
    root = make_tree({"a.py": "Hello World\n"})
    try:
        assert "找到" in search_files_by_content("hello", root_dir=root)
        result = search_files_by_content("hello", root_dir=root, case_sensitive=True)
        assert "沒有找到" in result
        print("[PASS] test_case_insensitive_by_default_and_case_sensitive_when_requested")
    finally:
        shutil.rmtree(root)


def test_context_lines_included_around_match():
    root = make_tree({
        "a.py": "line1\nline2\nTARGET\nline4\nline5\n",
    })
    try:
        result = search_files_by_content("TARGET", root_dir=root, context_lines=1)
        assert "line2" in result
        assert "line4" in result
        assert "line1" not in result  # 超出 context_lines=1 的範圍
        assert "line5" not in result
        print("[PASS] test_context_lines_included_around_match")
    finally:
        shutil.rmtree(root)


def test_max_results_truncates_and_says_so():
    files = {f"f{i}.py": "TARGET\n" for i in range(5)}
    root = make_tree(files)
    try:
        result = search_files_by_content("TARGET", root_dir=root, max_results=2)
        assert "已達上限" in result
        print("[PASS] test_max_results_truncates_and_says_so")
    finally:
        shutil.rmtree(root)


def test_max_results_not_exceeded_reports_no_truncation_note():
    files = {f"f{i}.py": "TARGET\n" for i in range(2)}
    root = make_tree(files)
    try:
        result = search_files_by_content("TARGET", root_dir=root, max_results=50)
        assert "已達上限" not in result
        print("[PASS] test_max_results_not_exceeded_reports_no_truncation_note")
    finally:
        shutil.rmtree(root)


def test_skips_default_ignored_directories():
    root = make_tree({
        "src/real.py": "TARGET\n",
        "node_modules/pkg/index.js": "TARGET\n",
        ".git/COMMIT_EDITMSG": "TARGET\n",
        "__pycache__/foo.pyc": "TARGET\n",
    })
    try:
        result = search_files_by_content("TARGET", root_dir=root)
        assert "real.py" in result
        assert "node_modules" not in result
        assert ".git" not in result
        assert "__pycache__" not in result
        print("[PASS] test_skips_default_ignored_directories")
    finally:
        shutil.rmtree(root)


def test_skips_binary_like_files():
    root = make_tree({
        "binary.dat": b"TARGET\x00\x01\x02binary junk",
        "text.py": "TARGET\n",
    })
    try:
        result = search_files_by_content("TARGET", root_dir=root)
        assert "text.py" in result
        assert "binary.dat" not in result
        print("[PASS] test_skips_binary_like_files")
    finally:
        shutil.rmtree(root)


def test_looks_binary_detects_null_byte():
    assert _looks_binary(b"hello\x00world") is True
    assert _looks_binary(b"hello world") is False
    print("[PASS] test_looks_binary_detects_null_byte")


def test_skips_oversized_files():
    root = make_tree({
        "huge.py": "TARGET\n" + ("x" * 10),  # 內容本身很小，這裡改用 monkeypatch 更精準
    })
    try:
        import tools.file_search as file_search_module
        original_limit = file_search_module.MAX_FILE_SIZE_BYTES
        file_search_module.MAX_FILE_SIZE_BYTES = 5  # 逼近 0，讓任何非空檔案都被視為過大
        try:
            result = search_files_by_content("TARGET", root_dir=root)
            assert "沒有找到" in result
        finally:
            file_search_module.MAX_FILE_SIZE_BYTES = original_limit
        print("[PASS] test_skips_oversized_files")
    finally:
        shutil.rmtree(root)


def test_relative_paths_are_reported_not_absolute():
    root = make_tree({"nested/dir/file.py": "TARGET\n"})
    try:
        result = search_files_by_content("TARGET", root_dir=root)
        assert os.path.join("nested", "dir", "file.py") in result
        assert root not in result  # 不該把完整絕對路徑洩漏進結果裡
        print("[PASS] test_relative_paths_are_reported_not_absolute")
    finally:
        shutil.rmtree(root)


def test_invalid_max_results_returns_error_string():
    root = make_tree({"a.py": "x\n"})
    try:
        result = search_files_by_content("x", root_dir=root, max_results=0)
        assert "max_results" in result
        print("[PASS] test_invalid_max_results_returns_error_string")
    finally:
        shutil.rmtree(root)


def test_find_files_by_name_matches_filename_pattern():
    root = make_tree({
        "app.log": "log content\n",
        "app.py": "print(1)\n",
        "sub/error.log": "another log\n",
    })
    try:
        result = find_files_by_name("*.log", root_dir=root)
        assert "app.log" in result
        assert os.path.join("sub", "error.log") in result
        assert "app.py" not in result
        print("[PASS] test_find_files_by_name_matches_filename_pattern")
    finally:
        shutil.rmtree(root)


def test_find_files_by_name_reports_file_size():
    root = make_tree({"data.bin": b"x" * 1234})
    try:
        result = find_files_by_name("*.bin", root_dir=root)
        assert "1,234 bytes" in result
        print("[PASS] test_find_files_by_name_reports_file_size")
    finally:
        shutil.rmtree(root)


def test_find_files_by_name_no_match_returns_explanatory_message():
    root = make_tree({"a.txt": "hi\n"})
    try:
        result = find_files_by_name("*.nonexistent_ext", root_dir=root)
        assert "沒有找到" in result
        print("[PASS] test_find_files_by_name_no_match_returns_explanatory_message")
    finally:
        shutil.rmtree(root)


def test_find_files_by_name_nonexistent_root_dir_returns_error_string():
    result = find_files_by_name("*.py", root_dir="/definitely/not/a/real/path/xyz")
    assert "不是一個存在的資料夾" in result
    print("[PASS] test_find_files_by_name_nonexistent_root_dir_returns_error_string")


def test_find_files_by_name_invalid_max_results_returns_error_string():
    root = make_tree({"a.txt": "hi\n"})
    try:
        result = find_files_by_name("*.txt", root_dir=root, max_results=0)
        assert "max_results" in result
        print("[PASS] test_find_files_by_name_invalid_max_results_returns_error_string")
    finally:
        shutil.rmtree(root)


def test_find_files_by_name_case_insensitive_by_default():
    root = make_tree({"README.md": "hi\n"})
    try:
        result = find_files_by_name("readme.*", root_dir=root)
        assert "README.md" in result
        result2 = find_files_by_name("readme.*", root_dir=root, case_sensitive=True)
        assert "沒有找到" in result2
        print("[PASS] test_find_files_by_name_case_insensitive_by_default")
    finally:
        shutil.rmtree(root)


def test_find_files_by_name_truncates_and_says_so():
    files = {f"f{i}.log": "x\n" for i in range(5)}
    root = make_tree(files)
    try:
        result = find_files_by_name("*.log", root_dir=root, max_results=2)
        assert "已達上限" in result
        print("[PASS] test_find_files_by_name_truncates_and_says_so")
    finally:
        shutil.rmtree(root)


def test_find_files_by_name_skips_default_ignored_directories():
    root = make_tree({
        "src/real.log": "x\n",
        "node_modules/pkg/debug.log": "x\n",
    })
    try:
        result = find_files_by_name("*.log", root_dir=root)
        assert "real.log" in result
        assert "node_modules" not in result
        print("[PASS] test_find_files_by_name_skips_default_ignored_directories")
    finally:
        shutil.rmtree(root)


def test_find_files_by_name_plain_keyword_matches_as_substring():
    # 沒有寫萬用字元的「report」應該自動當成 *report* 子字串比對
    root = make_tree({
        "my_report_2024.docx": "x",
        "unrelated.txt": "x",
    })
    try:
        result = find_files_by_name("report", root_dir=root)
        assert "my_report_2024.docx" in result
        assert "unrelated.txt" not in result
        print("[PASS] test_find_files_by_name_plain_keyword_matches_as_substring")
    finally:
        shutil.rmtree(root)


def test_find_files_by_name_explicit_glob_is_not_fuzzy_wrapped():
    # 已經自己寫了萬用字元的樣式不該被再包一層子字串比對——
    # "a*.txt" 應該只比對「a 開頭」，如果被誤包成 "*a*.txt*" 就會連
    # "xabcy.txt" 這種 a 不在開頭的檔名也一起中，超出使用者明確指定的範圍。
    root = make_tree({"abc.txt": "x", "xabcy.txt": "x"})
    try:
        result = find_files_by_name("a*.txt", root_dir=root)
        assert "abc.txt" in result
        assert "xabcy.txt" not in result
        print("[PASS] test_find_files_by_name_explicit_glob_is_not_fuzzy_wrapped")
    finally:
        shutil.rmtree(root)


def test_search_files_by_content_plain_file_glob_keyword_matches_as_substring():
    root = make_tree({
        "config.py": "TARGET\n",
        "other.py": "TARGET\n",
    })
    try:
        result = search_files_by_content("TARGET", root_dir=root, file_glob="config")
        assert "config.py" in result
        assert "other.py" not in result
        print("[PASS] test_search_files_by_content_plain_file_glob_keyword_matches_as_substring")
    finally:
        shutil.rmtree(root)


def test_find_files_by_name_respects_max_scan_limit():
    files = {f"f{i}.txt": "x" for i in range(10)}
    root = make_tree(files)
    try:
        result = find_files_by_name("*.txt", root_dir=root, max_scan=3)
        assert "掃描上限" in result
        print("[PASS] test_find_files_by_name_respects_max_scan_limit")
    finally:
        shutil.rmtree(root)


def test_find_files_by_name_invalid_max_scan_returns_error_string():
    root = make_tree({"a.txt": "x"})
    try:
        result = find_files_by_name("*.txt", root_dir=root, max_scan=0)
        assert "max_scan" in result
        print("[PASS] test_find_files_by_name_invalid_max_scan_returns_error_string")
    finally:
        shutil.rmtree(root)


def test_search_files_by_content_invalid_max_scan_returns_error_string():
    root = make_tree({"a.txt": "x"})
    try:
        result = search_files_by_content("x", root_dir=root, max_scan=-1)
        assert "max_scan" in result
        print("[PASS] test_search_files_by_content_invalid_max_scan_returns_error_string")
    finally:
        shutil.rmtree(root)


def test_default_root_dir_is_user_home_not_cwd():
    from tools.file_search import DEFAULT_SEARCH_ROOT
    assert DEFAULT_SEARCH_ROOT == os.path.expanduser("~")
    assert DEFAULT_SEARCH_ROOT != "."
    print("[PASS] test_default_root_dir_is_user_home_not_cwd")


if __name__ == "__main__":
    tests = [
        test_finds_matching_line_with_file_and_line_number,
        test_no_match_returns_explanatory_message_not_error,
        test_invalid_regex_returns_error_string_not_exception,
        test_nonexistent_root_dir_returns_error_string,
        test_file_glob_filters_by_filename_pattern,
        test_case_insensitive_by_default_and_case_sensitive_when_requested,
        test_context_lines_included_around_match,
        test_max_results_truncates_and_says_so,
        test_max_results_not_exceeded_reports_no_truncation_note,
        test_skips_default_ignored_directories,
        test_skips_binary_like_files,
        test_looks_binary_detects_null_byte,
        test_skips_oversized_files,
        test_relative_paths_are_reported_not_absolute,
        test_invalid_max_results_returns_error_string,
        test_find_files_by_name_matches_filename_pattern,
        test_find_files_by_name_reports_file_size,
        test_find_files_by_name_no_match_returns_explanatory_message,
        test_find_files_by_name_nonexistent_root_dir_returns_error_string,
        test_find_files_by_name_invalid_max_results_returns_error_string,
        test_find_files_by_name_case_insensitive_by_default,
        test_find_files_by_name_truncates_and_says_so,
        test_find_files_by_name_skips_default_ignored_directories,
        test_find_files_by_name_plain_keyword_matches_as_substring,
        test_find_files_by_name_explicit_glob_is_not_fuzzy_wrapped,
        test_search_files_by_content_plain_file_glob_keyword_matches_as_substring,
        test_find_files_by_name_respects_max_scan_limit,
        test_find_files_by_name_invalid_max_scan_returns_error_string,
        test_search_files_by_content_invalid_max_scan_returns_error_string,
        test_default_root_dir_is_user_home_not_cwd,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
