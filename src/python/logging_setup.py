"""
整個專案共用的統一 log 輸出模組，取代散落在 main.py/webview_bootstrap.py/
agent 各處的裸 print()。用 Python 內建的 logging 模組 + 自訂的 ANSI 顏色
formatter，不引入新的第三方套件（colorama/rich 這類套件在 Windows 終端機
還需要額外初始化步驟才能正確顯示顏色，內建 logging + 手動 ANSI code
反而更可控、依賴更少，這個專案已經夠多依賴了）。

這個模組也是「把面板 log 併到 VS Code console」這個需求的核心：
AgentWorker.emit()（agent/agent_core.py）每次送一則 "log" 事件給前端
LogPanel 顯示的同時，也會呼叫這裡的 log() 印到 stdout——這樣不管是看
App 裡的 LogPanel、還是用 VS Code 的 debugpy 掛 `python main.py` 偵錯時
看 Debug Console，看到的都是同一份內容，不用切來切去對照兩邊。

用法：
    from logging_setup import log
    log("一般訊息")
    log("出問題了", level="error")
    log("前端轉來的訊息", level="warning", channel="frontend")
"""

import logging
import sys

_RESET = "\x1b[0m"
_DIM = "\x1b[90m"

_LEVEL_COLORS = {
    "DEBUG": "\x1b[90m",       # 灰
    "INFO": "\x1b[36m",        # 青
    "WARNING": "\x1b[33m",     # 黃
    "ERROR": "\x1b[31m",       # 紅
    "CRITICAL": "\x1b[1;31m",  # 粗體紅
}

# 額外的「頻道」顏色——同樣等級的訊息，來源不同（agent 自己的狀態訊息、
# 前端轉送過來的 console、webview 啟動流程、工具執行結果）用不同顏色的
# 前綴標籤區分，掃一眼就知道這行是哪裡來的，不用每行都仔細讀內容。
_CHANNEL_COLORS = {
    "agent": "\x1b[35m",       # 紫
    "frontend": "\x1b[34m",    # 藍
    "tool": "\x1b[32m",        # 綠
    "webview": "\x1b[36m",     # 青
}


def _supports_color() -> bool:
    """Windows 舊版 cmd.exe 預設不支援 ANSI escape code，但 VS Code 的
    整合終端機/Debug Console、Windows Terminal、現代 PowerShell 都支援。
    保守判斷：只要輸出目標是一個真的終端機（不是被重導向到檔案/管線）
    就假設支援——就算判斷錯了，最差情況只是輸出裡多了一些看不懂的跳脫碼，
    不影響訊息本身看不看得懂，比起完全不上色、犧牲掉大多數情況下的
    可讀性划算。
    """
    try:
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    except Exception:
        return False


class ColoredFormatter(logging.Formatter):
    """依 level 上色，並在有 channel 資訊時額外標出來源標籤。
    use_color=False 時退化成純文字（例如寫進檔案、或明確關閉顏色時）。
    """

    def __init__(self, use_color: bool = None):
        super().__init__()
        self.use_color = _supports_color() if use_color is None else use_color

    def format(self, record: logging.LogRecord) -> str:
        channel = getattr(record, "channel", None)
        level_name = record.levelname
        message = record.getMessage()
        timestamp = self.formatTime(record, "%H:%M:%S")

        if not self.use_color:
            prefix = f"[{channel}] " if channel else ""
            return f"{timestamp} {level_name:<8} {prefix}{message}"

        level_color = _LEVEL_COLORS.get(level_name, "")
        channel_color = _CHANNEL_COLORS.get(channel, "") if channel else ""
        channel_label = f"{channel_color}[{channel}]{_RESET} " if channel else ""
        return (
            f"{_DIM}{timestamp}{_RESET} "
            f"{level_color}{level_name:<8}{_RESET} "
            f"{channel_label}{message}"
        )


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("desktop_agent")
    logger.setLevel(logging.DEBUG)
    # 不要傳給 root logger 的 handler（避免萬一有人另外設定了 root logging，
    # 導致同一則訊息被印兩次）——這個 logger 自己管自己的 handler。
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(ColoredFormatter())
        logger.addHandler(handler)

    return logger


_logger = _build_logger()


def log(message: str, level: str = "info", channel: str = None):
    """整個專案共用的統一 log 入口。

    level 是字串（"debug"/"info"/"warning"/"error"/"critical"，大小寫
    不拘），不用記 logging 模組那些常數；給不認得的字串一律當 info。
    channel 是選填的來源標籤（"agent"/"frontend"/"tool"/"webview"...），
    純粹是顯示用的分類，不影響訊息實際會不會被印出來。
    """
    level_key = (level or "info").lower()
    fn = getattr(_logger, level_key, None)
    if fn is None:
        fn = _logger.info
    fn(str(message), extra={"channel": channel} if channel else None)
