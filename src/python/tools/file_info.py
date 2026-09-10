"""Read metadata and filesystem attributes for a single path."""

from __future__ import annotations

import os
import stat
from datetime import datetime


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")


def get_file_info(path: str) -> dict | str:
    """Return useful filesystem metadata without reading the file contents."""
    if not path or not isinstance(path, str):
        return "讀取檔案屬性失敗：path 必須是非空字串"

    expanded = os.path.abspath(os.path.expanduser(path))
    try:
        info = os.stat(expanded)
    except FileNotFoundError:
        return f"讀取檔案屬性失敗：找不到路徑 {expanded}"
    except PermissionError:
        return f"讀取檔案屬性失敗：沒有權限讀取 {expanded}"
    except OSError as e:
        return f"讀取檔案屬性失敗：{e}"

    is_dir = stat.S_ISDIR(info.st_mode)
    is_file = stat.S_ISREG(info.st_mode)
    is_link = os.path.islink(expanded)
    _, extension = os.path.splitext(expanded)

    return {
        "path": expanded,
        "name": os.path.basename(expanded),
        "is_file": is_file,
        "is_directory": is_dir,
        "is_symlink": is_link,
        "size_bytes": info.st_size,
        "extension": extension.lower(),
        "created_at": _timestamp(info.st_ctime),
        "modified_at": _timestamp(info.st_mtime),
        "accessed_at": _timestamp(info.st_atime),
        "readable": os.access(expanded, os.R_OK),
        "writable": os.access(expanded, os.W_OK),
        "executable": os.access(expanded, os.X_OK),
        "mode_octal": oct(stat.S_IMODE(info.st_mode)),
    }


__all__ = ["get_file_info"]
