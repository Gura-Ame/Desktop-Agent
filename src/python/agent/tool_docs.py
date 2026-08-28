"""
工具詳細使用說明的懶加載倉庫。

設計理念：
- SYSTEM_PROMPT 裡只放「這個工具是做什麼的」一行摘要，讓模型知道有哪些工具可用、
  大概能做什麼——這部分每次呼叫模型都會被送進 context，所以必須精簡。
- 真正「怎麼用」的細節規則、格式規範、範例，放在這裡，只有在真的要用到某個工具時
  才會被送進 context：
  1. 模型可以主動呼叫 read_tool_doc(name) 先查好再呼叫。
  2. 就算模型沒有主動查，第一次實際呼叫某個標了文件的工具時，系統也會自動把
     完整說明連同執行結果一起回傳給它（見 agent_llm_client._execute_tools），
     確保就算模型偷懶不查文件，也不會因為不知道格式規則而白白失敗一次。
  之後同一個工具在同一次對話裡就不會重複贈送文件了（除非模型自己又呼叫 read_tool_doc）。

只有「規則多、容易用錯」的工具才值得放在這裡佔用 token；像 move_mouse(x, y) 這種
一行摘要就講完的工具，不需要額外文件。
"""

TOOL_DOCS = {
    "execute_python": """
execute_python(code: str) — 執行 Python 程式碼，回傳 print() 印出的內容。

規則：
- 凡涉及幾何座標計算、數學演算、或任何超過心算難度的邏輯，一律先呼叫這個工具算出結果、
  print 出來，再拿著印出的結果去呼叫其他工具（畫圖、操作等），不要自己心算座標後硬編。
- 需要一連串座標點（例如描一個圓、一條曲線）時，用這個工具算出完整的點列表並 print 出來，
  再原封不動貼進 draw_stroke 的 points 參數，不要自己手動一個個猜寫座標。

範例：
<|tool_call|>call:execute_python("w, h = 1920, 1080\\nbox_w, box_h = 300, 300\\nprint(f'x={int(w/2 - box_w/2)}, y={int(h/2 - box_h/2)}')")<|tool_call|>
""".strip(),

    "draw_box": """
draw_box(x, y, width, height, label="", color="#FF0000") — 在螢幕上畫矩形框，用來標記 UI 元素位置。

- 座標系統跟 get_screen_size() / read_screen_api() 回傳的是同一套，不需要換算。
- color 必須是 6 位數 Hex 色碼（例如 "#FF0000"、"#00FF00"），不能用顏色名稱或縮寫。
""".strip(),

    "draw_line": """
draw_line(x1, y1, x2, y2, color="#FFFF00") — 畫一條直線，用於劃線或指引方向。
color 必須是 6 位數 Hex 色碼。
""".strip(),

    "draw_stroke": """
draw_stroke(points, color="#00FF00", width=3) — 自由塗鴉/連續畫筆，沿著一串座標點連續畫線。

- points 格式固定是「多個 [x, y] 座標組成的 list」，例如 [[100, 200], [120, 210], [140, 230]]。
  就算只想標記單一個點，也要包成 [[x, y]] 這樣只有一個元素的 list，不能直接傳 [x, y]。
- 點數建議至少 3～5 個以上才畫得出平滑的形狀；只給 1 個點時系統會畫一個實心圓點當標記。
- 點數多時務必先用 execute_python 算出完整座標列表再原封不動傳進來，不要手動一個個猜寫。
- color 必須是 6 位數 Hex 色碼。

範例（先用 execute_python 算出一圈圓形座標，再連續畫出來）：
<|tool_call|>call:execute_python("import math\\ncx, cy, r = 960, 540, 100\\npts = [[int(cx + r*math.cos(t)), int(cy + r*math.sin(t))] for t in [i/20*2*math.pi for i in range(21)]]\\nprint(pts)")<|tool_call|>
<|tool_call|>call:draw_stroke([[1060, 540], [1057, 571], [1048, 601], [1034, 629]], "#00FF00", 3)<|tool_call|>
""".strip(),

    "erase_at": """
erase_at(x, y, radius=40) — 橡皮擦，擦除指定座標 (x, y) 半徑內的筆跡或框線。
判斷依據是沿著整條 stroke 判斷有沒有落在範圍內，不是只看線段的端點。
""".strip(),

    "read_screen_api": """
read_screen_api(max_elements=60) — 讀取目前螢幕畫面的 UI 快照。

流程規範：
1. 呼叫後你只會收到 UI 快照 ID (snapshot_id) 與主要互動元件摘要，不是整份原始資料。
2. 如果摘要中已經包含你要點擊的元件 ID，直接使用其座標點擊即可。
3. 若摘要中沒有找到目標元件，呼叫 query_screen_element(snapshot_id, keyword="目標名稱") 去
   同一份快照裡檢索，不要因為沒找到就重新呼叫 read_screen_api 重讀整個畫面。
""".strip(),

    "query_screen_element": """
query_screen_element(snapshot_id, keyword) — 在一份已經讀取過的 UI 快照裡，用關鍵字檢索
特定元件的座標。snapshot_id 來自前一次 read_screen_api() 的回傳結果，不要自己編造。
""".strip(),

    "remember": """
remember(id, type, summary="", properties=None) — 長期記住一個東西（可以是任何概念：
一個函式、一個定理、一個推導出來的結論、一份設定...），跨任務、跨對話持續存在。

- id：自己取一個好辨識的名字，例如 "lemma_vieta_jumping"、"parser.tokenize"。
- type：分類，例如 "Lemma"、"Function"、"Fact"。
- summary：一行精簡摘要，不超過 30 字，寫長也會被自動截斷，直接寫關鍵重點就好。
- properties：放額外細節的 dict，選填。
- 同一個 id 再呼叫一次會直接更新內容，不會產生重複節點。

什麼時候該用：解題中途得出關鍵引理、分析程式碼發現某個函式的行為、或任何「以後大概率
還會重複用到」的結論。不需要每件小事都記。
""".strip(),

    "recall": """
recall(id) — 用**精確的 id** 把之前 remember 過的東西讀回來，包含摘要、屬性、跟其他東西的關聯。
不確定精確 id 時不要用這個亂猜，先用 search_memory(keyword) 找。
""".strip(),

    "search_memory": """
search_memory(keyword) — 用**關鍵字**找記憶，不需要知道精確的 id。
如果只是大概記得「好像有記過跟這個有關的東西」，先用這個查，不要憑印象亂猜 id 直接呼叫 recall
（很可能猜錯，recall 只會告訴你找不到）。找到的東西會自動放進當下可以看到的範圍，不用再
另外呼叫一次 recall。
""".strip(),

    "relate": """
relate(source_id, rel, target_id) — 幫兩個已經記住的東西建立關聯
（例如 relate("lemma_A", "USED_BY", "proof_final")）。兩邊的 id 都必須先用 remember 記住過。
""".strip(),

    "recall_related": """
recall_related(id, rel=None) — 查誰跟這個東西有關聯（雙向都查）。
rel 可以指定只看某一種關聯類型，不填就全部列出來。
""".strip(),

    "record_observation": """
record_observation(id, about_id, conclusion, confidence=0.8, runtime_action="context") — 記錄一次「分析出來的結論」。
跟 remember 不一樣的地方是它會自動記下當時被分析對象的版本，之後可以判斷結論還新不新鮮。
about_id 必須是已經用 remember 記住過的東西。
runtime_action 預設為 "context"，只把結論提供給模型；可明確指定 "skip_task"（跳過相關 task）或
"replan"（讓相關 task 進入重新規劃）。只有關聯對象內容沒有變動、結論仍新鮮時才會生效。

範例（先記住一個函式，再記錄對它的分析結論）：
<|tool_call|>call:remember("parser.parse_expr", "Function", "解析運算式的核心函式")<|tool_call|>
<|tool_call|>call:record_observation("obs_parse_expr_nullcheck", "parser.parse_expr", "沒有處理空字串輸入，可能會拋出例外", 0.85)<|tool_call|>
""".strip(),

    "recall_observation": """
recall_observation(id) — 讀回之前用 record_observation 記錄的結論，會自動檢查有沒有過期。
如果被分析的對象內容後來變過了，會明確提醒你「可能已經過期」，而不是悄悄把舊結論當新的給你。
""".strip(),

    "recall_with_event": """
recall_with_event(id, event_id) — 查某個東西在特定事件情境下的屬性
（套用那次事件對它的局部覆寫，而不是目前最新的狀態）。
""".strip(),

    "build_code_graph": """
build_code_graph(filepath, module_name=None) — 解析**單一個** .py 檔案，把裡面的函式呼叫關係
記錄下來。只認得同一個檔案內互相呼叫的關係，import 進來的外部函式抓不到。
要分析整個專案、或不確定某個函式的呼叫者可能在別的檔案，優先用 build_code_graph_for_project。
""".strip(),

    "build_code_graph_for_project": """
build_code_graph_for_project(root_dir) — 解析**整個資料夾**底下所有 .py 檔案（含子資料夾），
並且會解析 import，跨檔案的呼叫關係也解析得到（例如 a.py 裡 `from utils import helper` 之後
呼叫 helper()，會正確連到 utils.py 裡的 helper 函式）。
只認得 `import x`、`from x import y` 這幾種常見寫法，動態呼叫、相對匯入（`from . import x`）抓不到。
""".strip(),

    "find_callers": """
find_callers(func_id) — 查誰呼叫了這個函式。func_id 格式是 "模組名.函式名"（例如 "parser.tokenize"）。
用 build_code_graph_for_project 建立的話，模組名是檔案相對於資料夾根目錄的點號路徑
（例如 pkg/utils.py 會是 "pkg.utils"）；用 build_code_graph 單檔建立的話，模組名預設是檔名去掉副檔名。
修改一個函式之前，想知道改了會不會影響到別的地方，可以先查一下這個。
""".strip(),

    "find_callees": """
find_callees(func_id) — 查這個函式呼叫了誰，格式規則同 find_callers。
""".strip(),

    "analyze_image_visuals": """
analyze_image_visuals(image_path="", task="<MORE_DETAILED_CAPTION>", text_input="") — 呼叫 Florence-2 視覺模型進行畫面理解、風格分析或物件偵測。

- image_path：本地圖片檔案路徑。若不填或傳空字串 `""`，系統會自動對目前桌面全螢幕截圖並分析。
- task：視覺任務模式，可選：
  - "<MORE_DETAILED_CAPTION>"（極詳細描述，預設）
  - "<DETAILED_CAPTION>"（中等描述）
  - "<CAPTION>"（簡短摘要）
  - "<OD>"（物件邊界框偵測）
  - "<DENSE_REGION_CAPTION>"（全圖區域密集標註）
  - "<REGION_PROPOSAL>"（候選區塊提議）
- text_input：可選的額外文字提示詞（例如針對特定物件做 grounding 時使用）。
- 提醒：分析完成後，若短時間內不需再讀圖，請呼叫 unload_florence_model() 釋放顯存。
""".strip(),

    "analyze_image_ocr": """
analyze_image_ocr(image_path="", task="<OCR_RAW>") — 呼叫 PaddleOCR v4 專用文字模型進行無幻覺文字/代碼識別或 UI 座標提取。

- image_path：本地圖片檔案路徑。若不填或傳空字串 `""`，系統會自動對目前桌面全螢幕截圖並辨識。
- task：OCR 任務模式：
  - "<OCR_RAW>"：按閱讀順序（由上到下、由左到右）逐行提取純文字與程式碼，無幻覺。
  - "<OCR_GEOMETRY>"：提取所有文字區塊的中心點像素座標 (pixel_center)、像素邊界框 (pixel_rect) 與 1000x1000 歸一化座標 (norm_1000_box) 的 JSON。需要點擊特定按鈕或分析 UI 位置時請使用此模式。
- 提醒：分析完成後可呼叫 unload_paddleocr_model() 卸載。
""".strip(),
}


def get_tool_doc(name: str) -> str:
    return TOOL_DOCS.get(name, f"找不到 '{name}' 的額外說明文件——這個工具通常代表它用法很直覺，看名稱和參數名就能直接呼叫。")
