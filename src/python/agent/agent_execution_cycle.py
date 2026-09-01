"""
這個檔案原本裝了 AgentWorker 整個執行流程（Reasoning/Planning/Task Cycle），
太長了（600+ 行混在一起），已經拆成三個各司其職的檔案：

- agent_routing.py        ：最外層狀態機進入點、IDLE 狀態的 direct/plan 路由判斷
- agent_task_processor.py ：單一任務從頭到尾的執行生命週期（思考/卡住偵測/執行/驗證/拆解）
- agent_reflection.py     ：Reflect（把新資訊回饋進 Task Tree）跟 <|replan|> 標記偵測

這裡保留 AgentExecutionMixin 這個名字、組合上面三個 Mixin，是為了不用同時
改掉 agent_core.py 的 import 跟任何直接
`from agent.agent_execution_cycle import AgentExecutionMixin` 的舊程式碼／
測試——效果完全等價於直接繼承三個 Mixin，只是多一層方便沿用舊名字的轉接。
新程式碼建議直接從對應的檔案 import 需要的 Mixin，不需要特別再經過這裡。
"""
from agent.agent_routing import AgentRoutingMixin
from agent.agent_task_processor import AgentTaskProcessorMixin
from agent.agent_reflection import AgentReflectionMixin


class AgentExecutionMixin(AgentRoutingMixin, AgentTaskProcessorMixin, AgentReflectionMixin):
    """相容用別名，等價於同時繼承 AgentRoutingMixin + AgentTaskProcessorMixin +
    AgentReflectionMixin。新程式碼請直接從對應檔案 import 想要的 Mixin。
    """
    pass
