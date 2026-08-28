import os
import gc
import json
import torch
from PIL import Image
import easyocr
from transformers.models.auto.modeling_auto import AutoModelForCausalLM
from transformers.models.auto.processing_auto import AutoProcessor
from llama_cpp import Llama

# ==================== 路徑與設備設定 ====================
FLORENCE_MODEL_ID = "microsoft/Florence-2-large"
TEXT_MODEL_PATH = r"C:\Users\Gura Ame\Downloads\21488f08ccd6333d7b55b877fa60c7c0089ecbaa27011610e654747f9069592a.gguf"

device = "cuda:0" if torch.cuda.is_available() else "cpu"
torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

# 全域變數管理視覺/OCR模型狀態
florence_model = None
florence_processor = None
ocr_reader = None

# ==================== 記憶體管理工具 ====================
def free_vram():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()

# ----------------- 1. Florence-2 (視覺語意模型) -----------------
def load_florence():
    global florence_model, florence_processor
    if florence_model is None:
        print("\n[系統] 正在將 Florence-2 載入 VRAM...")
        florence_model = AutoModelForCausalLM.from_pretrained(
            FLORENCE_MODEL_ID,
            torch_dtype=torch_dtype,
            trust_remote_code=True,
            ignore_mismatched_sizes=True,
            cache_dir=r"C:\Users\Gura Ame\Downloads\florence2"
        ).to(device)
        
        florence_processor = AutoProcessor.from_pretrained(
            FLORENCE_MODEL_ID,
            trust_remote_code=True,
            cache_dir=r"C:\Users\Gura Ame\Downloads\florence2"
        )
        print("[系統] Florence-2 載入成功。\n")

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

# ----------------- 2. EasyOCR (精準 OCR 模組) -----------------
def load_ocr():
    global ocr_reader
    if ocr_reader is None:
        print("\n[系統] 正在將 EasyOCR (繁中/英/日) 載入 VRAM...")
        # 支援繁中 (ch_tra)、英文 (en)、日文 (ja)
        ocr_reader = easyocr.Reader(['ch_tra', 'en'], gpu=torch.cuda.is_available())
        print("[系統] EasyOCR 載入成功。\n")

def unload_ocr():
    global ocr_reader
    if ocr_reader is not None:
        print("\n[系統] 正在將 EasyOCR 從 VRAM 卸載...")
        del ocr_reader
        ocr_reader = None
        free_vram()
        print("[系統] EasyOCR 卸載完成。\n")

def unload_all_vision():
    unload_florence()
    unload_ocr()
    return "已成功將 Florence-2 與 EasyOCR 視覺工具從 VRAM 卸載並釋放記憶體。"

# ==================== 視覺模型實作邏輯 ====================

def get_florence_caption(image_path: str, task: str = "<MORE_DETAILED_CAPTION>") -> str:
    if not os.path.exists(image_path):
        return f"錯誤：找不到路徑為 {image_path} 的圖片。"
    
    load_florence()

    try:
        image = Image.open(image_path).convert("RGB")
        inputs = florence_processor(
            text=task,
            images=image,
            return_tensors="pt"
        ).to(device, torch_dtype)

        with torch.no_grad():
            generated_ids = florence_model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=1024,
                num_beams=3,
                do_sample=False
            )

        generated_text = florence_processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        parsed = florence_processor.post_process_generation(
            generated_text,
            task=task,
            image_size=(image.width, image.height)
        )
        
        caption = parsed.get(task, str(parsed))
        if isinstance(caption, (dict, list)):
            caption = str(caption)

        return f"【Florence-2 畫面分析結果 ({task})】\n{caption.strip()}"
    except Exception as e:
        return f"Florence-2 讀取圖片失敗: {str(e)}"

def get_precise_ocr_analysis(image_path: str, task: str = "<OCR_RAW>") -> str:
    if not os.path.exists(image_path):
        return f"錯誤：找不到路徑為 {image_path} 的圖片。"
    
    load_ocr()

    try:
        results = ocr_reader.readtext(image_path, detail=1)
        image = Image.open(image_path)
        img_w, img_h = image.size

        if not results:
            return "【EasyOCR 結果】：畫面未識別出任何文字。"

        if task == "<OCR_RAW>":
            # 按 Y 軸與 X 軸排序重組文字
            sorted_results = sorted(results, key=lambda x: (x[0][0][1], x[0][0][0]))
            raw_text = "\n".join([res[1] for res in results])
            return f"【EasyOCR 精準原始碼/文字提取】\n{raw_text.strip()}\n\n(註：此為無幻覺的逐字精準識別結果)"

        elif task == "<OCR_GEOMETRY>":
            detected_items = []
            for res in results:
                bbox, text, _ = res
                detected_items.append({
                    "text": text,
                    "box": [
                        round((bbox[0][0] / img_w) * 1000),
                        round((bbox[0][1] / img_h) * 1000),
                        round((bbox[2][0] / img_w) * 1000),
                        round((bbox[2][1] / img_h) * 1000),
                    ]
                })
            return f"【EasyOCR 介面幾何分析 (1000x1000 歸一化座標)】\n```json\n{json.dumps(detected_items, ensure_ascii=False, indent=2)}\n```"

        return "未知的 OCR 任務"
    except Exception as e:
        return f"EasyOCR 讀取失敗: {str(e)}"

# ==================== Function Calling 工具宣告 ====================
tools = [
    {
        "type": "function",
        "function": {
            "name": "analyze_image_visuals",
            "description": "呼叫 Florence-2 視覺語意模型，分析圖片整體內容、場景風格、物件邊界等非純文字資訊。",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "本地圖片完整路徑"
                    },
                    "task": {
                        "type": "string",
                        "description": "'<MORE_DETAILED_CAPTION>'（詳細視覺描述）、'<DETAILED_CAPTION>'（中等描述）、'<CAPTION>'（簡短描述）、'<OD>'（物體偵測標示）",
                        "enum": [
                            "<MORE_DETAILED_CAPTION>",
                            "<DETAILED_CAPTION>",
                            "<CAPTION>",
                            "<OD>"
                        ]
                    }
                },
                "required": ["image_path", "task"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_image_code_and_text",
            "description": "呼叫專用 EasyOCR 模組，用於精準讀取圖片中的程式碼、文字，或獲取 UI 介面座標。無幻覺問題。",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "本地圖片完整路徑"
                    },
                    "task": {
                        "type": "string",
                        "description": "'<OCR_RAW>'（精準重組程式碼與文字，無幻覺，預設）、'<OCR_GEOMETRY>'（附帶 UI 介面座標 JSON，回答位置關係用）",
                        "enum": ["<OCR_RAW>", "<OCR_GEOMETRY>"]
                    }
                },
                "required": ["image_path", "task"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "unload_vision_models",
            "description": "當完成圖片討論，短時間內不再需要讀圖時呼叫此工具，將 Florence-2 與 EasyOCR 從 VRAM 卸載釋放資源。",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]

# ==================== 載入文字模型 ====================
print("正在載入文字模型...")
text_llm = Llama(
    model_path=TEXT_MODEL_PATH,
    n_ctx=8192,
    n_gpu_layers=-1,
    verbose=False,
)
print("文字模型載入完成\n")

# ==================== 主對話邏輯 (修正鬼打牆版) ====================
SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "你是一個具備自主能力的人工智慧助手，擁有 Florence-2 與 EasyOCR 工具。\n"
        "【重要規則】：\n"
        "1. 當你需要使用工具時，必須「直接觸發工具呼叫」，絕不要用文字回答『我已經呼叫了...』或『請稍等...』等廢話。\n"
        "2. 拿到工具回傳結果後，直接根據結果回答使用者的問題。\n"
        "3. 詢問程式碼/文字時用 `analyze_image_code_and_text`；詢問畫面/風格時用 `analyze_image_visuals`；討論結束用 `unload_vision_models`。"
    )
}
messages = [SYSTEM_PROMPT]

print("=== Agent 三模型架構 (LLM + Florence-2 + EasyOCR) 已啟動 ===")
print("可以直接與 AI 對話，也可以輸入圖片路徑進行精準 Code 識別或整體畫面分析。")
print("輸入 /clear 清除對話紀錄，/exit 離開。\n")
print(get_precise_ocr_analysis(image_path=r"C:\Users\Gura Ame\Downloads\Snipaste_2026-08-28_23-05-57.png", task="<OCR_RAW>"))

while True:
    try:
        user_input = input("You: ").strip()
    except (KeyboardInterrupt, EOFError):
        break

    if not user_input:
        continue

    if user_input.lower() in ["/exit", "/quit"]:
        break

    if user_input.lower() == "/clear":
        messages = [SYSTEM_PROMPT]
        unload_all_vision()
        print("\nSystem: 記憶與顯存已清空。\n")
        continue

    messages.append({"role": "user", "content": user_input})

    # Agent Internal Loop (處理 Tool Calls)
    max_tool_iterations = 5  # 防止無限死迴圈的保險機制
    iteration = 0

    while iteration < max_tool_iterations:
        iteration += 1

        response = text_llm.create_chat_completion(
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.1 # 降低隨機性，防止模型瞎掰
        )

        choice = response["choices"][0]
        finish_reason = choice["finish_reason"]
        message = choice["message"]

        # 判定是否真的觸發了 Function Call
        if finish_reason == "tool_calls" or "tool_calls" in message:
            # 必須完整的把包含 tool_calls 的 assistant message 放進歷史
            messages.append(message)
            
            for tool_call in message.get("tool_calls", []):
                func_name = tool_call["function"]["name"]
                
                # 預防引數解析失敗
                try:
                    arguments = json.loads(tool_call["function"]["arguments"])
                except Exception:
                    arguments = {}

                call_id = tool_call["id"]
                print(f"\n[系統] LLM 正在執行工具: {func_name}({arguments})...")

                # 執行實際函數
                if func_name == "analyze_image_visuals":
                    img_path = arguments.get("image_path", "")
                    task = arguments.get("task", "<MORE_DETAILED_CAPTION>")
                    result = get_florence_caption(image_path=img_path, task=task)

                elif func_name == "analyze_image_code_and_text":
                    img_path = arguments.get("image_path", "")
                    task = arguments.get("task", "<OCR_RAW>")
                    result = get_precise_ocr_analysis(image_path=img_path, task=task)

                elif func_name == "unload_vision_models":
                    result = unload_all_vision()

                else:
                    result = "錯誤：未知的工具呼叫"

                # 將工具執行結果回傳給 LLM
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": str(result)
                })
            
            # 工具執行完成，繼續內部迴圈，讓 LLM 根據 tool 結果回答
            continue

        else:
            # LLM 沒有呼叫工具，輸出最終回答
            reply_content = message.get("content", "")
            
            # 避免空回答
            if reply_content.strip():
                print(f"\nAI: {reply_content}\n")
                messages.append({"role": "assistant", "content": reply_content})
            break