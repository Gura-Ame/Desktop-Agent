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
<|tool_call|>execute_python("w, h = 1920, 1080\\nbox_w, box_h = 300, 300\\nprint(f'x={int(w/2 - box_w/2)}, y={int(h/2 - box_h/2)}')")<|tool_call|>
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
<|tool_call|>execute_python("import math\\ncx, cy, r = 960, 540, 100\\npts = [[int(cx + r*math.cos(t)), int(cy + r*math.sin(t))] for t in [i/20*2*math.pi for i in range(21)]]\\nprint(pts)")<|tool_call|>
<|tool_call|>draw_stroke([[1060, 540], [1057, 571], [1048, 601], [1034, 629]], "#00FF00", 3)<|tool_call|>
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
- 如果新的摘要跟某個既有節點很像，回傳結果裡會附上一段 ⚠️ 提醒（附上那個既有節點的
  id），代表這件事可能已經被記過、只是用了不同的 id。看到提醒時想一下是不是該用
  recall(既有id) 沿用它、或用 relate() 把兩者關聯起來，而不是任由同一件事分散成
  好幾個查不齊全的 id；如果確認真的是不同的事，忽略提醒繼續用新 id 即可。

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
<|tool_call|>remember("parser.parse_expr", "Function", "解析運算式的核心函式")<|tool_call|>
<|tool_call|>record_observation("obs_parse_expr_nullcheck", "parser.parse_expr", "沒有處理空字串輸入，可能會拋出例外", 0.85)<|tool_call|>
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

    "open_chrome_incognito": """
open_chrome_incognito(query="") — 用無痕模式開啟 Chrome，並可直接帶關鍵字搜尋。

- query：留空只開 Google 首頁；有給文字就直接開該關鍵字的 Google 搜尋結果頁。
- 注意：目前是用寫死的 Windows 路徑 "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
  去啟動，如果 Chrome 沒裝在這個預設路徑（例如裝在使用者層級 AppData 而不是系統層級），
  呼叫會失敗並回傳錯誤訊息，不是操作錯誤，是這台電腦的 Chrome 路徑跟預期的不一樣，
  可以改用 search_installed_apps("chrome") 找到實際路徑後用 launch_app 開啟一般模式，
  或是如實告知使用者這個工具在這台機器上用不了。
- 這個工具開的是一般給人看的無痕視窗，不是給你控制用的——如果你需要「自己」讀網頁內容、
  點擊網頁上的東西，請用 browser_open / browser_read_page / browser_click 那組工具，
  不要用這個。
""".strip(),

    "browser_open": """
browser_open(url="") — 開啟一個獨立、專門給你控制用的 debug 模式 Chrome，並導航到指定網址。

【跟 open_chrome_incognito 的差別】open_chrome_incognito 開的是給人看的一般視窗，
你自己完全看不到、也控制不了裡面發生什麼事。browser_open 開的是另一個獨立的 Chrome
（用 --remote-debugging-port 連線控制，獨立的 user-data-dir，不會動到使用者平常用的
Chrome 視窗或登入狀態），開完之後你可以呼叫 browser_read_page 看到裡面的文字內容、
呼叫 browser_click / browser_type 操作裡面的元素。要「讀文件、點網頁」一律用這組。

【基本流程】
1. browser_open("https://...") 開啟並導航到目標網址。
2. browser_read_page() 讀取目前頁面的文字節錄跟可互動元素清單（每個元素都附一個
   可以直接拿去用的 CSS 選擇器）。
3. 如果要點擊/輸入，用上一步拿到的選擇器呼叫 browser_click(selector) 或
   browser_type(selector, text)。
4. 頁面內容變了（點擊後跳轉、AJAX 載入新內容...）就重新呼叫 browser_read_page()
   確認目前狀態，不要憑上一次讀到的內容瞎猜現在畫面長怎樣。
5. 全部做完呼叫 browser_close() 關閉，釋放資源。

- url 留空的話只會回報目前分頁在哪個網址，不會導航（可以用來確認目前狀態）。
- 找不到 Chrome、或環境沒裝 websocket-client 套件時會直接回傳錯誤訊息說明原因，
  如實告知使用者即可，不需要自己猜測解法。
""".strip(),

    "browser_read_page": """
browser_read_page(max_elements=60) — 讀取目前 browser_open 開啟的頁面內容。

回傳格式是「標題、網址、頁面文字節錄（最多 3000 字）、可互動元素清單」，
不是原始 HTML——原始 HTML 對你來說太貴、雜訊也太多，這裡已經先幫你篩選過。
每個可互動元素都附一個可以直接拿去用在 browser_click / browser_type 的 CSS 選擇器，
不需要（也不建議）自己憑空編造選擇器。

- max_elements：最多回傳幾個可互動元素，預設 60，頁面元素特別多可以調高，
  但每多一個都會占用你的 context，非必要不用調太高。
- 如果回傳「還沒導航到任何網址」，代表要先呼叫 browser_open(url)。
""".strip(),

    "browser_click": """
browser_click(selector) — 用 CSS 選擇器點擊網頁上的元素（等同真的點了一下滑鼠）。

- selector 必須是從 browser_read_page() 回傳結果裡拿到的選擇器，不要自己亂猜。
- 點擊後如果觸發了頁面跳轉，這個工具會等頁面載入完成才回傳，並附上點擊後的網址。
- 如果回傳「找不到符合選擇器的元素」，代表頁面內容已經變了（例如上一步點擊已經跳轉），
  重新呼叫 browser_read_page() 確認目前畫面長怎樣，不要對著同一個選擇器重試。
""".strip(),

    "browser_type": """
browser_type(selector, text) — 用 CSS 選擇器在輸入框/文字區塊打字。

- selector 一樣建議來自 browser_read_page() 的回傳結果。
- 這個工具只會設定輸入框的值並觸發 input/change 事件，不會自己按 Enter 或送出表單，
  如果要送出，通常還需要接著呼叫 browser_click() 點擊送出按鈕。
""".strip(),

    "search_files_by_content": """
search_files_by_content(pattern, root_dir="~", file_glob="*", max_results=50, case_sensitive=False, context_lines=1, max_scan=50000)
— 用正則表達式在 root_dir 底下遞迴搜尋文字內容，類似輕量版的 grep。

跟 build_code_graph 是互補關係：build_code_graph 分析「已經知道要看哪個檔案」之後
函式彼此怎麼呼叫；這個工具負責更前面一步——不知道要看哪個檔案時，先用這個工具
找出關鍵字/字串/TODO/設定值出現在哪個檔案的哪一行，不侷限於 Python 檔案，
也不需要先解析語法。

- pattern 是正則表達式（Python re 語法），不是純字面字串比對——如果只是想找
  一個固定字串，記得先用 re.escape 的邏輯想過特殊字元（. * ( ) 等）會不會被
  誤判成正則語法；不確定的話可以先用 execute_python 呼叫 re.escape() 處理過
  再傳進來。
- file_glob 是檔名的比對樣式，預設 "*" 代表所有檔案。可以寫萬用字元
  （例如 "*.py"、"config.*"）做精確篩選；如果只給一個關鍵字沒有寫任何
  萬用字元（例如直接寫 "config"），會自動當成 *config* 做檔名子字串比對，
  不用先想清楚正確的 glob 語法。
- root_dir 預設是使用者的家目錄（~），不是這個 App 自己的安裝路徑——
  適合「幫我找電腦上的某個檔案」這種需求；如果已經知道明確的專案路徑，
  傳進去可以縮小範圍、加快搜尋。
- 結果裡每一筆是「相對路徑:行號」加上前後 context_lines 行，命中的那一行會用
  「→」標出來。
- 找到的筆數一旦達到 max_results 就會停止並在結果最前面註明「已達上限」，
  這種情況下不代表沒有更多符合的內容了，是主動被截斷，需要的話可以縮小
  root_dir/file_glob 範圍或提高 max_results 再查一次，不要誤以為已經找完全部。
- max_scan 是另一個獨立的上限：「總共實際看過幾個檔案」，避免完全沒找到
  符合內容時，整個搜尋在龐大的目錄裡（例如整個使用者家目錄）沒有 early
  exit、跑到很久才回來。回傳結果裡出現「已達單次掃描上限」代表可能還沒
  掃完就停了，不是「已確認掃過整個 root_dir 都沒有」，建議縮小範圍再查。
- 自動跳過 .git、node_modules、__pycache__、venv、dist、build、AppData、
  $RECYCLE.BIN 等目錄，以及看起來像二進位檔的內容，不需要自己在 pattern
  或 file_glob 裡刻意排除這些。
""".strip(),

    "find_files_by_name": """
find_files_by_name(name_pattern, root_dir="~", max_results=100, case_sensitive=False, max_scan=50000)
— 依檔名找檔案（不看內容），跟 search_files_by_content 是互補關係：那個
工具找「內容裡有沒有某段文字」，這個工具找「有沒有一個檔案叫這個名字」，
用來回答「這台電腦上有沒有 XXX.exe」「桌面上是不是有一個叫 report 開頭的
檔案」這類問題，對圖片、執行檔這類非文字檔也一樣有效（不需要打開內容）。

- name_pattern 可以直接給關鍵字（例如 "report"，會自動當成 *report* 做
  子字串比對），也可以寫明確的萬用字元樣式（例如 "*.log"、"config.*"）
  做精確篩選——已經寫了萬用字元的樣式不會被再包一層。
- root_dir 預設是使用者的家目錄（~），不是這個 App 自己的安裝路徑。
- max_scan 的意義跟 search_files_by_content 一樣：限制「總共看過幾個
  檔案」，避免完全沒找到符合的檔名時，在龐大目錄裡跑很久才回來；回傳結果
  出現「已達單次掃描上限」代表可能還沒掃完，不代表已經確認找遍了整個
  root_dir，建議縮小範圍再查一次。
- max_results 限制的是「找到幾筆」，跟 max_scan 是兩件不同的事：一個限制
  找到的數量，一個限制實際看過的檔案數量。
""".strip(),

    "run_powershell": """
run_powershell(command, timeout=30) — 執行一段 PowerShell 指令，回傳 stdout/stderr/結束代碼。

- 這是 DANGEROUS 等級的工具，跟 execute_python 完全同等級——能執行系統指令
  就等於有這台電腦使用者本人能做到的所有事。系統會在真正執行前暫停，
  跳出來讓使用者決定要不要授權；如果回傳結果是「使用者拒絕授權」，代表
  使用者當下不同意，不是指令寫錯或工具壞掉，不要重複用一樣的指令再試一次，
  換個方法或用 ask_user 直接問使用者想怎麼做。
- timeout 是秒數，指令跑超過這個時間會被強制終止並回報逾時，不會讓 agent
  卡住等一個沒有反應的指令，需要跑比較久的指令記得提高這個值。
- 輸出過長時會被截斷並在結尾註明總長度；如果懷疑重要內容被截斷了，
  改用更精確的指令縮小輸出範圍（例如加篩選條件、只印需要的欄位），
  而不是單純調高 timeout（截斷是輸出長度造成的，跟逾時是兩回事）。
- 這個工具本身不會過濾或封鎖任何指令內容，安全把關完全交給前面提到的
  使用者授權那一步，不要誤以為工具自己會擋掉危險指令。
""".strip(),

    "run_cmd": """
run_cmd(command, timeout=30) — 執行一段 cmd.exe 指令，回傳 stdout/stderr/結束代碼。

跟 run_powershell 是同一個等級、同一套授權機制、同樣的 timeout/輸出截斷規則，
差別只在直譯器是 cmd.exe 不是 PowerShell——某些舊式 DOS 指令或 .bat 腳本用
cmd 執行比較直接，其餘規則跟 run_powershell 完全一樣，請一併參考。
""".strip(),

    "wait_for_screen_stable": """
wait_for_screen_stable(timeout=30, stable_seconds=1.5, poll_interval=0.5, region=None, change_threshold=0.01)
— 等到畫面連續 stable_seconds 秒都沒有明顯變化才回傳，適合「不知道確切要
等多久，但知道畫面安靜下來就代表做完了」的情境（編譯、頁面載入、動畫播完）。

- 用法範例：呼叫 run_action/run_powershell 觸發一個會產生畫面變化的操作
  （編譯、開啟程式）之後，呼叫這個工具等它安靜下來，再接著呼叫
  analyze_image_ocr 或 read_screen_api 讀取最終結果——這個工具本身只負責
  判斷「畫面有沒有變化」，不會幫你判斷「這個變化代表任務完成了沒」，
  那一步永遠是你自己接下來要做的事。
- region 是 (x, y, width, height) 四個數字的範圍，只比對畫面裡的一小塊
  區域（例如編譯輸出視窗的座標範圍），可以避免系統時鐘、游標閃爍這類
  無關的變動讓它誤以為「還沒穩定」；不確定座標的話可以先用
  read_screen_api 或 get_screen_size 抓一次再決定要不要縮小範圍，不給
  的話會比對整個螢幕。
- 逾時（回傳裡出現「逾時」）不代表任務失敗，只代表 timeout 秒內畫面一直
  沒有連續安靜滿 stable_seconds 秒——可能只是這個操作本來就需要更久，
  可以直接用更長的 timeout 再呼叫一次，不需要換別的方法重來。
- timeout 上限是 120 秒，如果需要等更久，請分成多次呼叫，不要傳一個
  超過上限的數字（會直接失敗，不會被自動調整成上限值）。
""".strip(),

    "mouse_down": """
mouse_down(button="left") — 按住滑鼠按鍵不放，不會自動放開，要自己接著
在後續某次呼叫呼叫 mouse_up(button) 才會真的放開。

- 這是「即時控制」的基本單位：drag_mouse 就是 mouse_down + 平滑移動 +
  mouse_up 包成一個方便呼叫的動作；如果只是要拖曳一個東西到某個位置，
  優先用 drag_mouse，不需要自己手動組這三步。只有在拖曳過程中需要穿插
  其他判斷（例如邊拖曳邊檢查畫面變化）才需要自己拆開來用 mouse_down。
- 呼叫過 mouse_down 之後，如果這一輪任務中途結束、或使用者按下停止，
  系統會自動幫你呼叫 release_all_held_inputs() 放開所有還按著的按鍵，
  不會讓使用者的滑鼠卡在按住的狀態——但這是最後一道安全網，不代表你
  可以不管，正常流程還是要自己記得對應呼叫 mouse_up。
""".strip(),

    "drag_mouse": """
drag_mouse(x, y, duration=0.3, button="left") — 從目前滑鼠位置拖曳到
(x, y)，適合拖曳視窗、框選範圍、拖放檔案這類一次到位就能完成的操作。

- duration 是這次拖曳花費的秒數，太快（例如 0.05）某些應用程式的拖放
  事件處理偵測不到中間的移動路徑，會被當成「瞬間放開」而不是「拖曳」，
  預設 0.3 秒是折衷值，遇到偵測不到的情況可以調高再試。
- 如果需要在拖曳途中做其他判斷（不是單純從 A 點拖到 B 點），改用
  mouse_down + move_mouse + mouse_up 自己分開控制，不要硬塞進一次
  drag_mouse 呼叫裡。
""".strip(),

    "press_key": """
press_key(key: str) — 按一下單一按鍵或組合鍵，例如 "enter"、"esc"、
"ctrl+c"、"alt+tab"、"ctrl+shift+s"。

- 組合鍵用 + 分隔多個按鍵名稱，效果是同時按下所有鍵、再一起放開
  （底層對應 pyautogui.hotkey），不是依序個別按下再依序放開。如果需要
  精細控制先後順序（例如先按住 Ctrl 不放，中間穿插其他動作，最後才
  放開），改用 key_down/key_up 自己分開控制，不要用 press_key。
- 按鍵名稱要用 pyautogui 認得的名稱（例如方向鍵是 "up"/"down"/"left"/
  "right"，不是中文或符號），不確定某個鍵怎麼寫的話，先用簡單常見的名稱
  試（字母、數字、enter、esc、tab、space、backspace、delete），失敗了
  再依錯誤訊息調整。
""".strip(),

    "key_down": """
key_down(key: str) — 按住一個按鍵不放，不會自動放開，要自己接著在後續
某次呼叫呼叫 key_up(key) 才會真的放開。

- 用來模擬長按（例如遊戲裡按住方向鍵持續移動），或需要跟滑鼠動作同步的
  情境（按住 Shift 的同時用滑鼠拖曳做連續多選）。單純「按一下」用
  press_key 就好，不需要自己組 key_down + key_up。
- 呼叫過 key_down 之後，如果這一輪任務中途結束、或使用者按下停止，
  系統會自動幫你呼叫 release_all_held_inputs() 放開所有還按著的按鍵，
  但這是最後一道安全網，正常流程還是要自己記得對應呼叫 key_up，不要
  依賴這個安全網當作正常的收尾方式。
""".strip(),
}


def get_tool_doc(name: str) -> str:
    return TOOL_DOCS.get(name, f"找不到 '{name}' 的額外說明文件——這個工具通常代表它用法很直覺，看名稱和參數名就能直接呼叫。")
