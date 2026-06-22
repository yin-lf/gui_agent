"""执行层（GUI交互层）数据模型：Action、Step、WidgetTarget、ExecutionResult。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ==================== 操作类型 ====================

class ActionType(Enum):
    CLICK = "click"
    SET_TEXT = "set_text"
    SCROLL = "scroll"
    LONG_PRESS = "long_press"
    SWIPE = "swipe"
    PRESS_BACK = "press_back"
    PRESS_HOME = "press_home"
    WAIT = "wait"
    KEY_EVENT = "key_event"       # ADB 键盘事件（搜索/回车/完成等）


# ==================== 目标控件 ====================

@dataclass
class WidgetTarget:
    """LLM 从控件树中选中的目标控件。"""
    text: Optional[str] = None
    resource_id: Optional[str] = None
    class_name: Optional[str] = None
    content_desc: Optional[str] = None
    bounds: Optional[list] = None  # [x1, y1, x2, y2]

    def to_selector(self) -> dict:
        """转为 uiautomator2 的 selector 字典。

        uiauto2 支持的 key：resourceId, text, className, description
        注意：content-desc 在 uiauto2 中对应 key 名为 'description'，不是 'contentDescription'
        """
        sel = {}
        if self.resource_id:
            sel["resourceId"] = self.resource_id
        if self.text:
            sel["text"] = self.text
        if self.class_name:
            sel["className"] = self.class_name
        if self.content_desc:
            sel["description"] = self.content_desc   # uiauto2 用 'description' 不是 'contentDescription'
        return sel

    def is_empty(self) -> bool:
        """判断目标控件是否完全为空（没有任何定位信息）。"""
        return not any([self.text, self.resource_id, self.class_name,
                         self.content_desc, self.bounds])

    def summary(self) -> str:
        parts = []
        if self.text: parts.append(f'text="{self.text}"')
        if self.resource_id: parts.append(f'id="{self.resource_id}"')
        if self.class_name: parts.append(f'class="{self.class_name}"')
        if self.content_desc: parts.append(f'desc="{self.content_desc}"')
        return ", ".join(parts) if parts else "(空)"


# ==================== 原子操作 ====================

@dataclass
class Action:
    """一个原子操作（点击/输入/滑动等）。"""
    action_type: ActionType
    target: Optional[WidgetTarget] = None
    input_text: Optional[str] = None       # SET_TEXT 时要输入的内容
    reasoning: str = ""                     # LLM 选择该控件的推理过程
    swipe_direction: Optional[str] = None  # up / down / left / right
    wait_time: float = 0.0                 # WAIT 时等待的秒数
    key_code: int = 0                      # KEY_EVENT 时要发送的键码（如66=回车/搜索）

    def summary(self) -> str:
        if self.action_type == ActionType.PRESS_BACK:
            return "按返回键"
        if self.action_type == ActionType.PRESS_HOME:
            return "按Home键"
        if self.action_type == ActionType.WAIT:
            return f"等待 {self.wait_time}s"
        if self.action_type == ActionType.KEY_EVENT:
            key_names = {3: "HOME", 4: "BACK", 24: "音量+", 25: "音量-",
                        66: "回车/搜索", 67: "删除(退格)", 84: "完成"}
            name = key_names.get(self.key_code, f"KEY_{self.key_code}")
            return f"按键 [{name}(code={self.key_code})]"
        if self.action_type == ActionType.SET_TEXT:
            target_str = self.target.summary() if self.target else "(无目标)"
            return f'在 [{target_str}] 输入 "{self.input_text}"'
        if self.action_type == ActionType.CLICK:
            target_str = self.target.summary() if self.target else "(无目标)"
            return f"点击 [{target_str}]"
        if self.action_type == ActionType.SWIPE:
            return f"向 {self.swipe_direction} 滑动"
        if self.action_type == ActionType.SCROLL:
            target_str = self.target.summary() if self.target else "(无目标)"
            return f"在 [{target_str}] 滚动"
        if self.action_type == ActionType.LONG_PRESS:
            target_str = self.target.summary() if self.target else "(无目标)"
            return f"长按 [{target_str}]"
        return f"{self.action_type.value}(未知)"


# ==================== 执行步骤 ====================

@dataclass
class Step:
    """从 Task description 中拆出的一个执行步骤，可能包含多个原子操作。"""
    raw_text: str                # 原始描述文本
    intent: str                  # 提炼后的操作意图（给LLM看的）
    actions: list[Action] = field(default_factory=list)


# ==================== 执行结果 ====================

class ExecutionStatus(Enum):
    SUCCESS = "success"
    RETRYABLE = "retryable"      # 可重试错误（控件未找到等）
    FATAL = "fatal"              # 致命错误（需要上报异常恢复层）


@dataclass
class ExecutionResult:
    success: bool
    status: ExecutionStatus = ExecutionStatus.SUCCESS
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
    actual_widget: Optional[str] = None   # 实际操作的控件信息
    retry_count: int = 0
    action_summary: str = ""              # 执行的操作摘要
