"""
在檔案系統裡搜尋檔案——兩種找法，互補：
- search_files_by_content：內容裡有沒有某段文字（正則表達式），類似輕量版 grep。
- find_files_by_name：檔名/路徑符不符合某個萬用字元樣式，不管內容是什麼。

跟 code_graph 是互補關係：code_graph 分析「已經知道要看哪個檔案」之後，
函式彼此之間怎麼呼叫；這兩個工具負責更前面一步——「一開始要怎麼找到相關的
檔案」，不侷限於 Python 檔案，也不需要先解析語法。

安全性 / 穩定性考量（都是為了避免一次把整個專案的內容塞爆 context，
也避免掃整個使用者目錄掃到天荒地老）：
- 純讀取，不會修改任何檔案。
- 用簡單的 null byte 探測法跳過看起來像二進位檔的內容，避免把圖片/執行檔
  當文字讀進來。
- 單一檔案超過 MAX_FILE_SIZE_BYTES 就跳過，避免遇到超大 log 檔卡住。
- 符合筆數一旦達到 max_results 就提早停止，並在結果裡明確告知「可能還有
  更多」，不會不管三七二十一把整個專案的每一行都吐回去——呼應 SYSTEM_PROMPT
  裡其他工具一貫的原則：寧可讓模型知道結果被截斷、自己決定要不要縮小範圍。
- 掃描的檔案總數一旦達到 max_scan 也會提早停止並說明——這跟 max_results
  是兩件不同的事：max_results 限制「找到幾筆」，max_scan 限制「看過幾個
  檔案」，後者是為了避免「完全沒有符合的結果」時整個沒有 early exit 的
  路徑，讓 root_dir 意外設成整個使用者目錄或整個磁碟時不會一路掃到天荒地老。
- 目錄走訪預設跳過常見的「不該搜的」目錄（.git、node_modules、__pycache__、
  venv、dist、build、AppData、$RECYCLE.BIN 等），也跳過所有以 "." 開頭的
  隱藏目錄。
- root_dir 預設是使用者的家目錄（~），不是目前工作目錄（"."）——這個 agent
  的工作目錄通常是應用程式自己的安裝路徑，不是使用者實際存放檔案的地方，
  預設成家目錄比較符合「幫我找電腦上的某個檔案」這種真實使用情境的直覺。
- name_pattern / file_glob 如果完全沒有寫萬用字元（*、?、[），會自動包成
  *pattern* 做子字串比對——不強制要求呼叫端知道 glob 語法，「report」
  就能直接找到「my_report_2024.docx」，已經自己寫了萬用字元的樣式
  （例如 "*.log"、"config.*"）完全不會被改動，尊重明確指定的意圖。
"""

import fnmatch
import os
import re

MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # 2MB，超過這個大小的單一檔案直接跳過
DEFAULT_MAX_SCAN = 50_000  # 單次呼叫最多實際看過這麼多個檔案，避免掃到天荒地老

# 預設從使用者家目錄開始找，而不是目前工作目錄——後者對「找電腦上的檔案」
# 這種需求來說幾乎沒有意義（那通常是這個 App 自己的安裝路徑）。
DEFAULT_SEARCH_ROOT = os.path.expanduser("~")

DEFAULT_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
    # 使用者家目錄底下常見、體積龐大又幾乎不會是使用者真正想找的目錄
    "AppData", "$RECYCLE.BIN", "System Volume Information",
    ".cache", "Library",
}

_GLOB_METACHARS = set("*?[")


def _fuzzy_pattern(pattern: str) -> str:
    """沒有寫萬用字元的樣式自動包成 *pattern*，讓單純關鍵字也能用。
    見模組開頭的說明。
    """
    if any(ch in pattern for ch in _GLOB_METACHARS):
        return pattern
    return f"*{pattern}*"


def _looks_binary(sample: bytes) -> bool:
    """簡單的二進位檔探測：抽樣裡出現 null byte 就當作二進位檔跳過。
    這不是完美的偵測法，但便宜、對這裡的用途（避免把圖片/執行檔當文字讀）已經夠用。
    """
    return b"\x00" in sample


def _iter_candidate_files(root_dir: str, file_glob: str, max_scan: int = DEFAULT_MAX_SCAN):
    """走訪 root_dir，依字母順序（確保結果穩定、方便測試跟閱讀）逐一 yield
    符合 file_glob 的檔案路徑，跳過 DEFAULT_SKIP_DIRS 跟隱藏目錄，最多實際
    看過 max_scan 個檔案就停止（不管有沒有找到符合的）。
    """
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in DEFAULT_SKIP_DIRS and not d.startswith(".")
        )
        for filename in sorted(filenames):
            if scanned >= max_scan:
                return
            scanned += 1
            if fnmatch.fnmatch(filename, file_glob):
                yield os.path.join(dirpath, filename)


def _read_text_if_safe(filepath: str):
    """讀取檔案內容，遇到太大、讀不到、或看起來像二進位檔的情況回傳 None
    （呼叫端直接跳過，不當成錯誤中斷整個搜尋）。
    """
    try:
        if os.path.getsize(filepath) > MAX_FILE_SIZE_BYTES:
            return None
        with open(filepath, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    if _looks_binary(raw[:4096]):
        return None
    return raw.decode("utf-8", errors="replace")


def _format_match(rel_path: str, lines: list, match_line_idx: int, context_lines: int) -> str:
    """把一筆命中的行數格式化成「檔案路徑:行號」加上前後 context_lines 行，
    命中的那一行用「→」標出來，方便一眼看出重點在哪一行。
    """
    start = max(0, match_line_idx - context_lines)
    end = min(len(lines), match_line_idx + context_lines + 1)
    body = "\n".join(
        f"{'→' if j == match_line_idx else ' '} {j + 1}: {lines[j]}"
        for j in range(start, end)
    )
    return f"{rel_path}:{match_line_idx + 1}\n{body}"


def find_files_by_name(
    name_pattern: str,
    root_dir: str = DEFAULT_SEARCH_ROOT,
    max_results: int = 100,
    case_sensitive: bool = False,
    max_scan: int = DEFAULT_MAX_SCAN,
) -> str:
    """在 root_dir 底下遞迴尋找**檔名**符合 name_pattern 的檔案，回傳相對
    路徑清單。name_pattern 可以是萬用字元樣式（"*.log"、"config.*"），
    也可以直接給關鍵字（"report"）——沒有寫萬用字元的話會自動當成
    *關鍵字* 做子字串比對，不用先想好正確的 glob 語法。

    跟 search_files_by_content 是互補關係：那個工具是「內容裡有沒有某段文字」，
    這個工具是「有沒有一個檔案叫這個名字/長這樣」——用來回答「這台電腦上有沒有
    XXX.exe」「桌面上是不是有一個叫 report 開頭的檔案」這類問題，不需要打開
    檔案內容、對非文字檔（圖片、執行檔）也一樣有效。root_dir 預設是使用者
    家目錄，不用每次都自己指定。

    找不到、參數不合法、目錄不存在等情況一律回傳說明性的字串而不是拋例外，
    跟這個模組裡其他工具的慣例一致。
    """
    if not os.path.isdir(root_dir):
        return f"搜尋失敗：{root_dir} 不是一個存在的資料夾"
    if max_results <= 0:
        return "搜尋失敗：max_results 必須是正整數"
    if max_scan <= 0:
        return "搜尋失敗：max_scan 必須是正整數"

    matched = []
    files_scanned = 0
    truncated = False
    scan_limit_hit = False
    pattern = _fuzzy_pattern(name_pattern)
    compare_pattern = pattern if case_sensitive else pattern.lower()

    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in DEFAULT_SKIP_DIRS and not d.startswith(".")
        )
        for filename in sorted(filenames):
            if files_scanned >= max_scan:
                scan_limit_hit = True
                break
            files_scanned += 1
            candidate = filename if case_sensitive else filename.lower()
            if not fnmatch.fnmatch(candidate, compare_pattern):
                continue
            if len(matched) >= max_results:
                truncated = True
                break
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, root_dir)
            try:
                size = os.path.getsize(full_path)
            except OSError:
                size = None
            size_label = f"{size:,} bytes" if size is not None else "無法讀取大小"
            matched.append(f"{rel_path} ({size_label})")
        if truncated or scan_limit_hit:
            break

    if not matched:
        msg = (
            f"在 {root_dir}（掃描了 {files_scanned} 個檔案）裡"
            f"沒有找到檔名符合 '{name_pattern}' 的檔案。"
        )
        if scan_limit_hit:
            msg += f"（已達單次掃描上限 {max_scan} 個檔案，可能還沒掃完就停了，建議縮小 root_dir 範圍再試一次）"
        return msg

    header = f"在 {files_scanned} 個檔案中找到 {len(matched)} 個檔名符合 '{name_pattern}' 的檔案"
    if truncated:
        header += f"（已達上限 {max_results} 筆，可能還有更多未顯示，請縮小 root_dir 範圍或提高 max_results）"
    elif scan_limit_hit:
        header += f"（已達單次掃描上限 {max_scan} 個檔案就停了，root_dir 底下可能還有沒掃到的地方，建議縮小範圍）"
    return header + ":\n" + "\n".join(matched)


def search_files_by_content(
    pattern: str,
    root_dir: str = DEFAULT_SEARCH_ROOT,
    file_glob: str = "*",
    max_results: int = 50,
    case_sensitive: bool = False,
    context_lines: int = 1,
    max_scan: int = DEFAULT_MAX_SCAN,
) -> str:
    """在 root_dir 底下遞迴搜尋符合 file_glob 的檔案，找出內容裡符合
    pattern（正則表達式）的所有行，回傳一份人類可讀的結果摘要
    （含相對路徑、行號、前後幾行 context）。

    file_glob 沒有寫萬用字元的話（例如直接給 "config"）會自動當成
    *config* 做檔名子字串比對；如果要精確篩選副檔名，明確寫 "*.py" 這種
    樣式。root_dir 預設是使用者家目錄。

    找不到、參數不合法、目錄不存在等情況一律回傳說明性的字串而不是拋例外，
    跟這個專案裡其他工具（build_code_graph、find_callers…）的慣例一致。
    """
    try:
        regex = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
    except re.error as e:
        return f"搜尋失敗：正則表達式 '{pattern}' 語法錯誤 ({e})"

    if not os.path.isdir(root_dir):
        return f"搜尋失敗：{root_dir} 不是一個存在的資料夾"

    if max_results <= 0:
        return "搜尋失敗：max_results 必須是正整數"
    if max_scan <= 0:
        return "搜尋失敗：max_scan 必須是正整數"

    matches = []
    files_scanned = 0
    truncated = False
    effective_glob = _fuzzy_pattern(file_glob)

    candidates = _iter_candidate_files(root_dir, effective_glob, max_scan=max_scan)
    for filepath in candidates:
        text = _read_text_if_safe(filepath)
        if text is None:
            continue
        files_scanned += 1
        lines = text.splitlines()
        rel_path = os.path.relpath(filepath, root_dir)
        for i, line in enumerate(lines):
            if not regex.search(line):
                continue
            if len(matches) >= max_results:
                truncated = True
                break
            matches.append(_format_match(rel_path, lines, i, context_lines))
        if truncated:
            break

    if not matches:
        return (
            f"在 {root_dir}（比對 {files_scanned} 個符合 '{file_glob}' 的檔案）"
            f"裡沒有找到符合 '{pattern}' 的內容。"
        )

    header = f"在 {files_scanned} 個檔案中找到 {len(matches)} 筆符合 '{pattern}' 的結果"
    if truncated:
        header += f"（已達上限 {max_results} 筆，可能還有更多未顯示，請縮小搜尋範圍或提高 max_results）"
    return header + ":\n\n" + "\n\n".join(matches)
