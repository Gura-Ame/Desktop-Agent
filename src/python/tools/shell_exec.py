"""
執行使用者允許的 PowerShell / cmd 指令——這是繼 execute_python 之後第二個
「能做任意事」等級的工具，風險完全同等：能執行系統指令，就等於有這台電腦
使用者本人可以做到的所有事（刪檔案、改設定、裝軟體、關機……）。

安全模型：**這個模組本身不做任何指令層級的過濾/黑名單**（不嘗試偵測
"Remove-Item -Recurse"、"format"、"shutdown" 這類危險指令並擋下來）。
理由是黑名單注定會漏、也很容易被換句話說繞過（例如用變數組字串、用別名），
維護一份「看起來安全」但其實有洞的黑名單，比誠實地說「這個工具本身不做
把關」更危險——會讓人誤以為有保護而放鬆警惕。真正的把關交給
agent/tool_permissions.py 那一層：run_powershell / run_cmd 被分類為
DANGEROUS，預設策略下每個工作階段第一次使用都會先跳出來讓使用者自己決定
要不要允許，這是刻意設計成人類看得懂、擋得住的那一道防線，而不是假裝
程式自己能判斷「這句指令安不安全」。

其餘工程面的安全考量（不是「安不安全」而是「會不會失控」）：
- 一定帶 timeout，超時會被強制終止，不會讓一個卡住的指令把整個 agent 卡死。
- stdout/stderr 分開回報，並在過長時截斷，避免一次把一個巨大的輸出塞爆 context。
- 一律用 subprocess 的參數列表形式呼叫直譯器本身（powershell.exe / cmd.exe），
  不透過作業系統的 shell=True 字串拼接，避免這一層自己又引入一次額外的
  shell 注入風險（例如指令字串裡剛好帶有這個模組自己沒預期到的特殊字元）。
  真正要執行的指令內容還是完整交給 command 參數，PowerShell/cmd 自己
  怎麼解讀那個字串，是它們自己的事，不是這個 wrapper 額外加工的結果。
"""

import subprocess

MAX_OUTPUT_CHARS = 8000
DEFAULT_TIMEOUT_SECONDS = 30


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n…（輸出過長，已截斷，總長度 {len(text)} 字元）"


def _run(args: list, command: str, timeout: int) -> str:
    if timeout <= 0:
        return "執行失敗：timeout 必須是正整數"
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return f"執行逾時（超過 {timeout} 秒），指令已被強制終止: {command}"
    except FileNotFoundError as e:
        return f"執行失敗：找不到可執行檔（這台機器上可能沒有這個直譯器）: {e}"
    except Exception as e:
        return f"執行失敗: {e}"

    parts = []
    if proc.stdout.strip():
        parts.append(f"[stdout]\n{_truncate(proc.stdout.strip())}")
    if proc.stderr.strip():
        parts.append(f"[stderr]\n{_truncate(proc.stderr.strip())}")
    if not parts:
        parts.append("（無輸出）")
    parts.append(f"[exit code: {proc.returncode}]")
    return "\n\n".join(parts)


def run_powershell(command: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    """執行一段 PowerShell 指令，回傳 stdout/stderr/結束代碼。

    這是 DANGEROUS 等級的工具（跟 execute_python 同等級），預設授權策略下
    每個工作階段第一次呼叫都會先暫停等待使用者同意，見
    agent/tool_permissions.py。timeout 是秒數，超過會被強制終止並回報逾時，
    不是靜靜地把 agent 卡住。
    """
    return _run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        command,
        timeout,
    )


def run_cmd(command: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    """執行一段 cmd.exe 指令，回傳 stdout/stderr/結束代碼。

    風險等級、timeout 行為跟 run_powershell 完全一樣，差別只在直譯器——
    有些指令（例如某些 .bat 腳本、舊式 DOS 指令）在 cmd 下比在 PowerShell
    下更直接，兩個都提供讓模型自己依情況選。
    """
    return _run(["cmd", "/c", command], command, timeout)
