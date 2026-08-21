import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import os
import sys
import time
import tempfile


from agent.agent_core import AgentWorker, AgentState
from agent.task_system import ExecutionMode, TaskNode, TaskStatus
from fake_llm import FakeOpenAIClient, ECHO_REFLECT

ESCALATE_RESPONSE = "<|plan|>需要拆解成多個步驟並逐一驗證是否完成"

PLAN_DSL = """
- [ ] [TASK-1] 整理桌面資料夾
  - 方法: 用 run_action 依序建立分類資料夾並搬移檔案
  - 條件: 資料夾都已分類完成
  - 注意: 不要刪除任何檔案
  - 深度思考: NO
  - 需要拆解: YES
  - 需要確認: NO
  - 信心值: 0.5
- [ ] [TASK-2] 回報整理結果
  - 方法: 用 run_action 印出整理後的清單
  - 條件: 有印出檔案清單
  - 注意: 結果要包含檔案數量
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: YES
  - 信心值: 0.9
"""

DECOMPOSE_DSL = """
- [ ] [TASK-1] 建立分類資料夾
  - 方法: run_action("mkdir docs images")
  - 條件: 資料夾都存在
  - 注意: 已存在就略過
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: NO
  - 信心值: 0.9
- [ ] [TASK-2] 搬移檔案
  - 方法: run_action("move files")
  - 條件: 桌面上不再有零散檔案
  - 注意: 保留資料夾結構
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: NO
  - 信心值: 0.5
"""

THINK_RESPONSE_1 = (
    "分析: 信心值偏低，先確認搬移邏輯是否正確\n"
    "修正方法: run_action(\"move files carefully\")\n"
    "修正注意: 保留資料夾結構，搬移前先確認副檔名\n"
    "拆解: NO\n"
    "新信心值: 0.85\n"
)

THINK_RESPONSE_2 = (
    "分析: 上次失敗是因為條件判斷太嚴格，調整驗證方式\n"
    "修正方法: run_action(\"move files carefully, retry\")\n"
    "修正注意: 保留資料夾結構\n"
    "拆解: NO\n"
    "新信心值: 0.9\n"
)

def wait_until(predicate, timeout=2.0, interval=0.01, message="等待逾時"):
    start = time.time()
    while not predicate():
        if time.time() - start > timeout:
            raise AssertionError(message)
        time.sleep(interval)

def make_agent(scripts: dict, mode=ExecutionMode.SMART):
    events = []

    def on_event(event_type, data):
        events.append((event_type, data))

    tool_calls = []

    def run_action(cmd):
        tool_calls.append(cmd)
        return f"executed: {cmd}"

    fd, memory_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(memory_path)
    agent = AgentWorker({"run_action": run_action}, event_callback=on_event, default_mode=mode,
                         memory_path=memory_path)
    agent.client = FakeOpenAIClient(scripts)
    return agent, events, tool_calls

def send_turn(agent, prompt):
    agent.set_user_prompt(prompt)
    agent.state = AgentState.IDLE
    agent.start()
    wait_until(lambda: not agent.is_running(), message=f"「{prompt}」這輪沒有在時限內完成")
