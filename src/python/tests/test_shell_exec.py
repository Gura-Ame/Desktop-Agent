"""
tools/shell_exec.py 的測試。這台測試機是 Linux，沒有真的 powershell.exe/cmd.exe
可以測，所以這裡全部用 unittest.mock 把 subprocess.run 換掉——重點是驗證
「這個 wrapper 自己」的行為：組出來的參數列表對不對、timeout/找不到執行檔/
其他例外有沒有被吃掉變成說明性字串、輸出過長會不會截斷、stdout/stderr/exit
code 有沒有正確組裝，而不是真的驗證 PowerShell 本身的行為（那是作業系統的事）。
"""
import os
import subprocess
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.shell_exec import run_powershell, run_cmd, MAX_OUTPUT_CHARS


def _fake_completed(stdout="", stderr="", returncode=0):
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


def test_run_powershell_builds_expected_argv():
    with patch("tools.shell_exec.subprocess.run") as mock_run:
        mock_run.return_value = _fake_completed(stdout="hi\n")
        run_powershell("Get-Process")
        args, kwargs = mock_run.call_args
        argv = args[0]
        assert argv[0] == "powershell"
        assert "-NoProfile" in argv
        assert "-NonInteractive" in argv
        assert argv[-2:] == ["-Command", "Get-Process"]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        print("[PASS] test_run_powershell_builds_expected_argv")


def test_run_cmd_builds_expected_argv():
    with patch("tools.shell_exec.subprocess.run") as mock_run:
        mock_run.return_value = _fake_completed(stdout="hi\n")
        run_cmd("dir")
        args, kwargs = mock_run.call_args
        argv = args[0]
        assert argv == ["cmd", "/c", "dir"]
        print("[PASS] test_run_cmd_builds_expected_argv")


def test_successful_run_reports_stdout_and_exit_code():
    with patch("tools.shell_exec.subprocess.run") as mock_run:
        mock_run.return_value = _fake_completed(stdout="line1\nline2\n", returncode=0)
        result = run_powershell("echo hi")
        assert "line1" in result
        assert "line2" in result
        assert "[exit code: 0]" in result
        print("[PASS] test_successful_run_reports_stdout_and_exit_code")


def test_stderr_and_nonzero_exit_code_both_reported():
    with patch("tools.shell_exec.subprocess.run") as mock_run:
        mock_run.return_value = _fake_completed(stderr="boom\n", returncode=1)
        result = run_cmd("bad-command")
        assert "[stderr]" in result
        assert "boom" in result
        assert "[exit code: 1]" in result
        print("[PASS] test_stderr_and_nonzero_exit_code_both_reported")


def test_no_output_reports_explicitly():
    with patch("tools.shell_exec.subprocess.run") as mock_run:
        mock_run.return_value = _fake_completed()
        result = run_powershell("Write-Host -NoNewline ''")
        assert "（無輸出）" in result
        print("[PASS] test_no_output_reports_explicitly")


def test_timeout_returns_explanatory_string_not_exception():
    with patch("tools.shell_exec.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=5)
        result = run_powershell("Start-Sleep 100", timeout=5)
        assert "逾時" in result
        assert "5" in result
        print("[PASS] test_timeout_returns_explanatory_string_not_exception")


def test_missing_interpreter_returns_explanatory_string_not_exception():
    with patch("tools.shell_exec.subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError("powershell not found")
        result = run_powershell("echo hi")
        assert "找不到" in result
        print("[PASS] test_missing_interpreter_returns_explanatory_string_not_exception")


def test_unexpected_exception_returns_explanatory_string_not_crash():
    with patch("tools.shell_exec.subprocess.run") as mock_run:
        mock_run.side_effect = RuntimeError("something weird")
        result = run_cmd("dir")
        assert "執行失敗" in result
        print("[PASS] test_unexpected_exception_returns_explanatory_string_not_crash")


def test_invalid_timeout_returns_error_without_calling_subprocess():
    with patch("tools.shell_exec.subprocess.run") as mock_run:
        result = run_powershell("echo hi", timeout=0)
        assert "timeout" in result
        mock_run.assert_not_called()
        print("[PASS] test_invalid_timeout_returns_error_without_calling_subprocess")


def test_long_output_gets_truncated_with_notice():
    with patch("tools.shell_exec.subprocess.run") as mock_run:
        huge = "x" * (MAX_OUTPUT_CHARS + 500)
        mock_run.return_value = _fake_completed(stdout=huge)
        result = run_powershell("Get-Content bigfile.txt")
        assert "已截斷" in result
        assert len(result) < len(huge) + 200  # 遠比原始輸出短，證明真的被截斷了
        print("[PASS] test_long_output_gets_truncated_with_notice")


if __name__ == "__main__":
    tests = [
        test_run_powershell_builds_expected_argv,
        test_run_cmd_builds_expected_argv,
        test_successful_run_reports_stdout_and_exit_code,
        test_stderr_and_nonzero_exit_code_both_reported,
        test_no_output_reports_explicitly,
        test_timeout_returns_explanatory_string_not_exception,
        test_missing_interpreter_returns_explanatory_string_not_exception,
        test_unexpected_exception_returns_explanatory_string_not_crash,
        test_invalid_timeout_returns_error_without_calling_subprocess,
        test_long_output_gets_truncated_with_notice,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
