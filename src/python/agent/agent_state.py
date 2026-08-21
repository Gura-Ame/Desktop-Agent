from enum import Enum

# 單一任務連續驗證失敗超過這個次數，就不再自己悶著頭重試，改為向使用者提問
MAX_RETRY_PER_TASK = 3

# 有些本地模型（尤其是量化過的小模型）在多輪對話格式沒套用好、或本身能力不夠時，
# 會自己把「使用者：」「助理：」這種角色標籤也一起生成出來，變成自問自答停不下來。
# 這裡不管哪個 prompt 類別都一律帶上，當作最後一道安全網——正常情況下不會被觸發，
# 一旦模型開始寫出這些標籤，立刻在那裡截斷，而不是讓它繼續失控生成下去。
STOP_SEQUENCES = ["\nUSER:", "USER:", "\nASSISTANT:", "ASSISTANT:", "\n使用者:", "\n使用者："]
# 同樣是防失控用的硬上限，不是正常操作的長度限制；正常回應遠遠用不到這麼多。
MAX_RESPONSE_TOKENS = 2048

# 混合記憶：self.history 只維持這麼多則訊息當作「常駐視窗」，維持當下對話的直接連續性；
# 超過的部分每一輪都會被主動濃縮進硬記憶，不是被動等 token 成長超過門檻才觸發。
# 設成 2（也就是只留最近一次來回）是刻意的：像人腦一樣，短期記憶只留「當下這一刻」，
# 其餘一律交給長期記憶負責，盡量把依賴壓在硬記憶這一邊，不是靠 context 硬撐。
HYBRID_WINDOW_MESSAGES = 2

# self.history 存進 MemoryStore 時固定用這個 id（開頭底線代表這是系統內部用的節點，
# 不是模型透過 remember 建立的一般記憶）。
HISTORY_NODE_ID = "_conversation_history"


class AgentState(Enum):
    IDLE = "IDLE"
    WAITING_CONFIRM = "WAITING_CONFIRM"
    EXECUTING = "EXECUTING"
