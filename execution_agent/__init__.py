"""执行层（GUI交互层）—— App Agent。

将推理层输出的 TaskTree（DAG 子任务）在安卓设备上实际执行。

模块组成：
- app_agent: 主控制器，DAG 驱动 + 异常处理
- step_parser: 步骤解析器，Task description → 原子步骤
- widget_understander: 控件理解层，LLM 语义匹配控件
- action_executor: 操作执行器，uiauto2 封装 + 重试
- screen_state: 屏幕状态感知，截图 + 控件树
- models: 数据模型（Action, Step, WidgetTarget, ExecutionResult）
- prompts: Prompt 模板

使用方式：
    import uiautomator2 as u2
    from agent_reasoner.llm_client import LLMClient
    from execution_agent.app_agent import AppAgent

    device = u2.connect()
    llm = LLMClient()
    agent = AppAgent(device, llm)
    report = agent.execute_task_tree(task_tree)
"""

from .app_agent import AppAgent
from .models import Action, ActionType, Step, WidgetTarget, ExecutionResult, ExecutionStatus
from .screen_state import ScreenCaptor, ScreenState
from .step_parser import StepParser
from .widget_understander import WidgetUnderstander
from .action_executor import ActionExecutor

__all__ = [
    "AppAgent",
    "Action",
    "ActionType",
    "Step",
    "WidgetTarget",
    "ExecutionResult",
    "ExecutionStatus",
    "ScreenCaptor",
    "ScreenState",
    "StepParser",
    "WidgetUnderstander",
    "ActionExecutor",
]
