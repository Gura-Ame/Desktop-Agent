import sys
import os
import subprocess
import threading
from collections.abc import Callable
from typing import Any, Optional

class LlamaServerManager:
    def __init__(self, event_callback: Callable[[str, Any], None]):
        self.process: Optional[subprocess.Popen[str]] = None
        self.event_callback = event_callback
        self._read_thread: Optional[threading.Thread] = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start_server(self, model_path: str, n_ctx: int = 2048, port: int = 12356, python_exe: str = sys.executable):
        if self.is_running():
            self.event_callback("log", "[Server] 服務已在運行中。")
            return

        if not os.path.exists(model_path):
            self.event_callback("log", f"[錯誤] 模型檔案不存在: {model_path}")
            self.event_callback("server_status", {"running": False, "msg": "模型檔案不存在"})
            return

        args = [python_exe, "-m", "llama_cpp.server", "--model", model_path, "--n_ctx", str(n_ctx), "--port", str(port)]
        self.process = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )

        self.event_callback("log", f"[Server] 正在啟動 Llama-CPP Server...\n[Command] {' '.join(args)}")
        self.event_callback("server_status", {"running": True, "msg": "服務啟動中..."})

        self._read_thread = threading.Thread(target=self._read_output, daemon=True)
        self._read_thread.start()

    def stop_server(self):
        process = self.process
        if process is not None and process.poll() is None:
            self.event_callback("log", "[Server] 正在停止 Llama-CPP Server...")
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
            self.event_callback("log", "[Server] Llama-CPP Server 已停止。")
            self.event_callback("server_status", {"running": False, "msg": "離線"})

    def _read_output(self):
        # Hold one immutable process/stream reference for this reader thread.  The
        # manager may be stopped while the thread is running, so re-reading
        # self.process here would be both unsafe at runtime and Optional to Pylance.
        process = self.process
        if process is None or process.stdout is None:
            return
        stdout = process.stdout
        for line in iter(stdout.readline, ''):
            if not line:
                break
            self.event_callback("log", line)
            if any(k in line for k in ["Uvicorn running on", "Application startup complete", "HTTP Request"]):
                self.event_callback("server_status", {"running": True, "msg": "連線就緒 (Running)"})
        stdout.close()
        process.wait()
        self.event_callback("server_status", {"running": False, "msg": "已停止"})
