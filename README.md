# Desktop-Agent

精簡、具備自我演進能力與長期知識庫的桌面自動化 AI Agent。

---

## 核心理念：`Storage ≠ Memory ≠ Context`

傳統 LLM 依賴長上下文累積對話，導致 Token 膨脹與記憶遺忘。本系統採用三層分離設計：

```
Disk (永久知識庫 / 圖譜) ──[Retriever 自動檢索 + 關聯擴展]──> Working Memory (LRU 暫存) ──[Attention Manager 打分與預算控制]──> Context (精煉上下文)
```

- **Context 是建構出來的，不是讀取出來的**：每次只將當前推理所需的最小必要資訊注入 Context。
- **只存事實與規則，不存重複推導**：抽象知識共享（`INSTANCE_OF`）、情境局部覆寫（Event Override）、結論新鮮度追蹤（`Observation` 與 version 雜湊）。

---

## 系統架構與核心功能

### 1. 跨 Session 長期記憶與 Context Compression System (CCS)
- **Disk Memory (`MemoryStore`)**：基於雙向關聯圖的永久記憶中心（支援 `CALLS`、`INSTANCE_OF`、`ABOUT`、`MENTIONS` 等關聯與 O(1) 反向索引）。
- **Retriever**：使用者發送請求或任務開始前，自動提取關鍵字並沿圖譜延伸一階關聯，跨 Session 將相關知識精準啟動至 Working Memory。
- **Working Memory**：LRU 活躍節點池，維護時間戳與使用頻率。
- **Attention Manager**：依據關聯度、信心值、時效性與確定性動態打分，嚴格在 Token 預算內（如 ~650 tokens）進行選擇性屬性展開，杜絕爆窗。
- **自動對話濃縮 (`ContextCompressor`)**：對話長度超過門檻時自動壓縮為結構化事實，並建立實體關聯。

### 2. Code Graph 程式碼關聯與影響分析
- **AST 跨模組靜態分析**：支援類別限定名（Qualified Names）、相對匯入解析、裝飾器與動態呼叫標記、外部庫參照（`ExternalRef`）。
- **連帶影響預掃**：任務執行前後，自動由呼叫圖查出可能受影響的相依函式，並自動排入 Task Tree 驗證。

### 3. 自適應任務規劃引擎 (`TaskEngine`)
- **Markdown DSL 任務樹**：支援階層化結構、信心值評估、風險操作確認（Smart Confirm）。
- **動態拆解與反思**：遇到複雜任務自動分解為子步驟；步驟完成後進行 Reflect 調整後續規劃並沉澱新知識。
- **卡關自癒機制**：重試次數超限時主動啟動深度思考或向使用者尋求指引。

### 4. 桌面自動化與現代化操作介面
- **自動化工具群**：滑鼠鍵盤操作、視窗探測（UIA/Win32）、畫面識別、Python 腳本動態執行。
- **螢幕 Overlay 標記**：PyQt6 半透明圖層，即時視覺化繪製選框與軌跡。
- **React + Vite 前端**：雙向對話分枝樹（Forking）、即時串流顯示、工具調用視覺化、任務樹即時同步。

---

## 快速開始

### 後端環境 (Python)
```bash
# 安裝依賴
pip install -r requirements.txt  # 或依賴 PyQt6, pywebview, openai, pyautogui, pywinauto

# 啟動後端
python src/python/main.py
```

### 前端介面 (React + Vite)
```bash
# 安裝前端依賴並啟動開發伺服器
npm install
npm run dev
```

### 執行單元測試
```bash
$env:PYTHONUTF8=1; Get-ChildItem -Path src/python/tests -Filter "test_*.py" | ForEach-Object { python $_.FullName }
```
