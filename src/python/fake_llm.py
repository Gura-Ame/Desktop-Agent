"""
假的 OpenAI client：讓 agent_core.py 可以在不連真的 LLM 的情況下被測試。

用法：依照系統提示詞的內容自動分類成 router/planner/decompose/thinking/verify/reflect/system
七種角色，每種角色各自維護一個劇本佇列（scripts[category]），每次呼叫就照順序 pop 一筆出來當回覆。

佇列裡的項目可以是：
- 字串：直接當作回覆內容
- callable(system_prompt, user_prompt) -> str：需要根據當下 prompt 內容動態產生回覆時用，
  最常見的用法是「reflect 原封不動回傳目前的樹」（見 ECHO_REFLECT）
"""

CATEGORY_MARKERS = {
    "router": "你是一個任務分流器",
    "planner": "你是一個 AI 任務規劃器",
    "decompose": "你是任務拆解器",
    "thinking": "高階思考 (Deep Thinking)",
    "verify": "你是任務驗證器",
    "reflect": "你是一個任務狀態檢查器",
    "system": "你是一個具備電腦自動化控制能力",
}


def classify(system_prompt: str) -> str:
    for cat, marker in CATEGORY_MARKERS.items():
        if marker in system_prompt:
            return cat
    return "unknown"


def ECHO_REFLECT(system_prompt: str, user_prompt: str) -> str:
    """模擬「模型看過之後決定什麼都不用改」：把 user_prompt 裡夾帶的目前任務樹原樣抽出來回傳。
    用來測試 Reflect 的保護機制不會因為模型誠實地什麼都不改，就誤判成格式錯誤或遺漏任務。
    """
    marker = "當前完整任務樹:\n"
    idx = user_prompt.find(marker)
    if idx == -1:
        raise AssertionError("測試用的 reflect prompt 應該要包含 '當前完整任務樹:' 這個標記")
    tree_text = user_prompt[idx + len(marker):]
    # render_tree_markdown 開頭會有一行標題 "### 【當前任務樹狀態...】"，那不是合法的 DSL 條目，濾掉
    lines = [l for l in tree_text.split("\n") if not l.startswith("###")]
    return "\n".join(lines)


class _FakeDelta:
    def __init__(self, content):
        self.content = content


class _FakeChunkChoice:
    def __init__(self, content):
        self.delta = _FakeDelta(content)


class _FakeChunk:
    def __init__(self, content):
        self.choices = [_FakeChunkChoice(content)]


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, scripts: dict):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.call_log = []  # 每次呼叫依序記錄分類，方便測試斷言呼叫次數/順序

    def create(self, model=None, messages=None, temperature=0.2, stream=False, **kwargs):
        messages = messages or []
        system_prompt = messages[0]["content"] if messages else ""
        user_prompt = messages[-1]["content"] if messages else ""
        category = classify(system_prompt)
        self.call_log.append(category)

        queue = self.scripts.get(category)
        if not queue:
            raise AssertionError(
                f"測試腳本沒有為類別 '{category}' 準備夠多的回應了"
                f"（system prompt 開頭: {system_prompt[:40]!r}）"
            )

        item = queue.pop(0)
        content = item(system_prompt, user_prompt) if callable(item) else item

        if stream:
            return [_FakeChunk(content)]
        return _FakeResponse(content)


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeOpenAIClient:
    """可以直接指派給 AgentWorker.client 來取代真的 openai.OpenAI() 實例。"""

    def __init__(self, scripts: dict):
        self.completions = _FakeCompletions(scripts)
        self.chat = _FakeChat(self.completions)

    @property
    def call_log(self):
        return self.completions.call_log
