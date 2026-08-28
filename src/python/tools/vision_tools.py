import os
import gc
import json
from PIL import Image

try:
    # pyrefly: ignore [missing-import]
    from config import FLORENCE_MODEL_ID, FLORENCE_CACHE_DIR
except ImportError:
    FLORENCE_MODEL_ID = "microsoft/Florence-2-large"
    FLORENCE_CACHE_DIR = r"C:\Users\Gura Ame\Downloads\florence2"

florence_model = None
florence_processor = None
paddle_ocr_reader = None


def get_device_and_dtype():
    try:
        import torch

        dev = "cuda:0" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        return dev, dtype
    except ImportError:
        return "cpu", None


def free_vram():
    """強制回收 Python 垃圾物件並釋放 PyTorch 顯存快取。"""
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except ImportError:
        pass


# ==============================================================================
# Florence-2 模型生命週期管理
# ==============================================================================
def load_florence():
    global florence_model, florence_processor
    if florence_model is None:
        try:
            import torch
            from transformers.models.auto.modeling_auto import AutoModelForCausalLM
            from transformers.models.auto.processing_auto import AutoProcessor
        except ImportError as e:
            raise ImportError(
                f"未安裝 Florence-2 所需依賴 (torch/transformers/timm/einops): {e}。"
                "請先執行: pip install torch torchvision transformers timm einops"
            )

        dev, dtype = get_device_and_dtype()
        print("\n[系統] 正在將 Florence-2 載入 VRAM...")
        florence_model = AutoModelForCausalLM.from_pretrained(
            FLORENCE_MODEL_ID,
            torch_dtype=dtype,
            trust_remote_code=True,
            ignore_mismatched_sizes=True,
            cache_dir=FLORENCE_CACHE_DIR,
        ).to(dev)

        florence_processor = AutoProcessor.from_pretrained(
            FLORENCE_MODEL_ID,
            trust_remote_code=True,
            cache_dir=FLORENCE_CACHE_DIR,
        )
        print("[系統] Florence-2 載入完成。\n")



def unload_florence():
    global florence_model, florence_processor
    if florence_model is not None:
        print("\n[系統] 正在將 Florence-2 從 VRAM 卸載...")
        del florence_model
        del florence_processor
        florence_model = None
        florence_processor = None
        free_vram()
        print("[系統] Florence-2 卸載完成。\n")
        return "已成功將 Florence-2 從顯存 (VRAM) 卸載。"
    return "Florence-2 目前未處於載入狀態，無需卸載。"


# ==============================================================================
# PaddleOCR v4 模型生命週期管理
# ==============================================================================
def load_paddleocr():
    global paddle_ocr_reader
    if paddle_ocr_reader is None:
        try:
            from paddleocr import PaddleOCR  # type: ignore[import-untyped,import-not-found]
        except ImportError as e:
            raise ImportError(
                f"未安裝 PaddleOCR 所需依賴 (paddleocr): {e}。"
                "請先執行: pip install paddleocr"
            )

        paddle_ocr_reader = PaddleOCR(
            use_angle_cls=True,
            lang="ch",  # 支援繁體中文、簡體中文與英文
            ocr_version="PP-OCRv4",
            show_log=False,
        )
        print("[系統] PaddleOCR v4 初始化完成。\n")


def unload_paddleocr():
    global paddle_ocr_reader
    if paddle_ocr_reader is not None:
        print("\n[系統] 正在將 PaddleOCR 從記憶體/顯存卸載...")
        del paddle_ocr_reader
        paddle_ocr_reader = None
        free_vram()
        print("[系統] PaddleOCR 卸載完成。\n")
        return "已成功將 PaddleOCR 從記憶體/顯存卸載。"
    return "PaddleOCR 目前未處於載入狀態，無需卸載。"


def unload_all_vision():
    msg_f = unload_florence()
    msg_p = unload_paddleocr()
    return f"【視覺模組卸載結果】\n- {msg_f}\n- {msg_p}"


# ==============================================================================
# Agent 可呼叫工具函式實作
# ==============================================================================
def analyze_image_visuals(
    image_path: str = "",
    task: str = "<MORE_DETAILED_CAPTION>",
    text_input: str = "",
) -> str:
    """
    呼叫 Florence-2 視覺大模型執行視覺任務。
    若 image_path 為空或未提供，自動拍攝當前桌面全螢幕畫面進行分析。
    """
    if not image_path:
        try:
            import pyautogui
            image_path = os.path.abspath("temp_vision_screenshot.png")
            pyautogui.screenshot(image_path)
        except Exception as e:
            return f"自動截圖失敗: {e}"

    if not os.path.exists(image_path):
        return f"錯誤：找不到圖片檔案 {image_path}"

    try:
        load_florence()
    except Exception as e:
        return f"載入 Florence-2 失敗: {e}"

    if florence_model is None or florence_processor is None:
        return "錯誤：Florence-2 模型未能正常初始化"

    try:
        import torch
        dev, dtype = get_device_and_dtype()
        image = Image.open(image_path).convert("RGB")
        prompt = task if not text_input else f"{task} {text_input}"

        inputs = florence_processor(
            text=prompt,
            images=image,
            return_tensors="pt",
        ).to(dev, dtype)

        with torch.no_grad():
            generated_ids = florence_model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=1024,
                num_beams=3,
                do_sample=False,
            )

        generated_text = florence_processor.batch_decode(
            generated_ids, skip_special_tokens=False
        )[0]
        parsed = florence_processor.post_process_generation(
            generated_text, task=task, image_size=(image.width, image.height)
        )

        result_content = parsed.get(task, parsed)
        if isinstance(result_content, (dict, list)):
            result_str = json.dumps(result_content, ensure_ascii=False, indent=2)
        else:
            result_str = str(result_content)

        return f"【Florence-2 任務 [{task}] 分析結果】\n{result_str.strip()}"
    except Exception as e:
        return f"Florence-2 執行失敗: {str(e)}"


def analyze_image_ocr(image_path: str = "", task: str = "<OCR_RAW>") -> str:
    """
    呼叫 PaddleOCR v4 執行精準文字識別或 UI 幾何座標定位。
    若 image_path 為空或未提供，自動拍攝當前桌面全螢幕畫面進行辨識。
    """
    if not image_path:
        try:
            import pyautogui
            image_path = os.path.abspath("temp_ocr_screenshot.png")
            pyautogui.screenshot(image_path)
        except Exception as e:
            return f"自動截圖失敗: {e}"

    if not os.path.exists(image_path):
        return f"錯誤：找不到圖片檔案 {image_path}"

    try:
        load_paddleocr()
    except Exception as e:
        return f"載入 PaddleOCR 失敗: {e}"

    if paddle_ocr_reader is None:
        return "錯誤：PaddleOCR 未能正常初始化"

    try:
        image = Image.open(image_path)
        img_w, img_h = image.size
        ocr_result = paddle_ocr_reader.ocr(image_path, cls=True)

        if not ocr_result or not ocr_result[0]:
            return "【PaddleOCR v4 結果】：畫面上未偵測到任何文字。"

        lines = ocr_result[0]

        if task == "<OCR_RAW>":
            # 按 Y 座標由上到下，X 座標由左到右排序
            sorted_lines = sorted(lines, key=lambda x: (x[0][0][1], x[0][0][0]))
            raw_text = "\n".join([item[1][0] for item in sorted_lines])
            return (
                f"【PaddleOCR v4 精準文字/代碼提取】\n{raw_text.strip()}\n\n"
                f"(註：此為無幻覺的逐字識別結果)"
            )

        elif task == "<OCR_GEOMETRY>":
            detected_items = []
            for item in lines:
                box_pts, (text, conf) = item[0], item[1]
                xs = [p[0] for p in box_pts]
                ys = [p[1] for p in box_pts]

                min_x, max_x = min(xs), max(xs)
                min_y, max_y = min(ys), max(ys)
                center_x = round((min_x + max_x) / 2)
                center_y = round((min_y + max_y) / 2)

                detected_items.append({
                    "text": text,
                    "confidence": round(conf, 3),
                    "pixel_center": [center_x, center_y],
                    "pixel_rect": [round(min_x), round(min_y), round(max_x), round(max_y)],
                    "norm_1000_box": [
                        round((min_y / img_h) * 1000),
                        round((min_x / img_w) * 1000),
                        round((max_y / img_h) * 1000),
                        round((max_x / img_w) * 1000),
                    ],
                })
            return (
                f"【PaddleOCR v4 UI 幾何分析 (含中心點座標與 1000x1000 歸一化座標)】\n"
                f"```json\n{json.dumps(detected_items, ensure_ascii=False, indent=2)}\n```"
            )

        return f"未知的 PaddleOCR 任務類型: {task}"
    except Exception as e:
        return f"PaddleOCR v4 執行失敗: {str(e)}"


def unload_florence_model() -> str:
    """單獨卸載 Florence-2 視覺模型以釋放顯存。"""
    return unload_florence()


def unload_paddleocr_model() -> str:
    """單獨卸載 PaddleOCR 模型以釋放記憶體。"""
    return unload_paddleocr()


def unload_all_vision_models() -> str:
    """一鍵卸載所有視覺與 OCR 模型以完全釋放顯存與記憶體。"""
    return unload_all_vision()
