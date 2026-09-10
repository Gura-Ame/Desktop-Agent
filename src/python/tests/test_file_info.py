from pathlib import Path

from tools.file_info import get_file_info


def test_get_file_info_returns_metadata(tmp_path: Path):
    path = tmp_path / "example.TXT"
    path.write_text("hello", encoding="utf-8")

    result = get_file_info(str(path))

    assert isinstance(result, dict)
    assert result["path"] == str(path.resolve())
    assert result["name"] == "example.TXT"
    assert result["is_file"] is True
    assert result["is_directory"] is False
    assert result["is_symlink"] is False
    assert result["size_bytes"] == 5
    assert result["extension"] == ".txt"
    assert result["readable"] is True
    assert "created_at" in result
    assert "modified_at" in result
    assert "accessed_at" in result
    assert "mode_octal" in result


def test_get_file_info_supports_directories(tmp_path: Path):
    result = get_file_info(str(tmp_path))

    assert isinstance(result, dict)
    assert result["is_directory"] is True
    assert result["is_file"] is False


def test_get_file_info_missing_path():
    result = get_file_info("definitely-does-not-exist-Desktop-Agent")

    assert isinstance(result, str)
    assert "找不到路徑" in result


def test_get_file_info_rejects_invalid_path():
    result = get_file_info("")

    assert isinstance(result, str)
    assert "非空字串" in result
