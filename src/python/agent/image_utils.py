"""
共用的圖片暫存工具。上傳的圖片是以 base64 data URL 的形式從前端傳過來的
（瀏覽器端用 FileReader 讀成 base64，Python 這邊完全拿不到原始檔案路徑），
但 analyze_image_visuals / analyze_image_ocr 這些視覺工具吃的是磁碟路徑，
所以需要一個共用的地方把 base64 存回暫存檔、換成路徑。

刻意獨立成一個小模組，而不是塞在 agent_llm_client.py 或 llama_client.py
裡面——因為「使用者附圖需要能被視覺工具讀到」這件事跟用哪個 LLM client
無關，是全部 client 都要處理的通用需求（不管本地 Llama 還是遠端 API，
只要那個 API 背後不是真正的多模態模型，圖片都需要有辦法透過路徑走
analyze_image_visuals / analyze_image_ocr 才看得到）。
"""
import base64
import os
import tempfile
from typing import Optional


def save_data_url_to_temp(url: str) -> Optional[str]:
    """把 data:image/...;base64,... （或裸 base64 字串）存成暫存檔，回傳檔案路徑。
    存不下去（格式不是預期的 base64 圖片）就回傳 None，呼叫端要有備援文字，
    不能讓整個訊息處理因為一張圖片格式怪異就整個炸掉。
    """
    try:
        ext = "png"
        if url.startswith("data:"):
            header, b64data = url.split(",", 1)
            if "image/" in header:
                ext = header.split("image/")[1].split(";")[0] or "png"
        else:
            b64data = url
        raw = base64.b64decode(b64data)
        fd, path = tempfile.mkstemp(suffix=f".{ext}", prefix="desktop_agent_img_")
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        return path
    except Exception:
        return None
