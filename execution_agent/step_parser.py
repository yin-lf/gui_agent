"""步骤解析器：将 Task 的 description 拆解为可执行的原子步骤列表。

策略：
1. 先用规则做快速拆分（识别常见操作模式）
2. 规则无法覆盖时，调用 LLM 做智能拆分
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .models import Step, ActionType

if TYPE_CHECKING:
    from ..agent_reasoner.llm_client import LLMClient


# ==================== 规则模式 ====================

# 描述中常见的操作关键词 → 对应的操作类型
_ACTION_PATTERNS = [
    # 打开/启动 App
    (r"打开(.+?)(?:App|应用|软件)", ActionType.CLICK, "打开{app}"),
    (r"启动(.+?)(?:App|应用|软件)", ActionType.CLICK, "打开{app}"),
    (r"进入(.+?)(?:App|应用|软件)", ActionType.CLICK, "打开{app}"),

    # 搜索
    (r"(?:在)?(?:搜索框|输入框).*(?:输入|填入|填写|键入)[\"「](.+?)[\"」]", ActionType.SET_TEXT, "在搜索框输入{text}"),
    (r"(?:输入|填入|填写|键入)[\"「](.+?)[\"」].*?(?:搜索|查询)", ActionType.SET_TEXT, "在搜索框输入{text}并搜索"),
    (r"点击.*?(?:搜索|查询)(?:按钮)?", ActionType.CLICK, "点击搜索按钮"),

    # 点击操作
    (r"点击[\"「]?(.+?)[\"」]?.*(?:按钮|选项|标签|入口|图标)?", ActionType.CLICK, "点击{target}"),
    (r"选择[\"「]?(.+?)[\"」]", ActionType.CLICK, "选择{target}"),
    (r"进入[\"「]?(.+?)[\"」]", ActionType.CLICK, "进入{target}"),
    (r"点击(?:播放|暂停|收藏|下载|分享|删除|确认|提交|取消|同意|允许|确定)(?:按钮)?", ActionType.CLICK, "点击{action}按钮"),

    # 输入操作
    (r"(?:在)?.*?(?:地址栏|输入框|文本框).*?(?:输入|填入|填写|键入)[\"「](.+?)[\"」]", ActionType.SET_TEXT, "输入{text}"),

    # 导航操作
    (r"(?:返回|按返回|回到上一页|退回)", ActionType.PRESS_BACK, "按返回键"),
    (r"(?:回到桌面|返回主页|按Home|回到主屏幕)", ActionType.PRESS_HOME, "按Home键"),

    # 滑动/滚动
    (r"(?:向)?(上|下|左|右)?滑动", ActionType.SWIPE, "向{dir}滑动"),
    (r"(?:向下|向上|向左|向右)滚?(?:动|屏)", ActionType.SWIPE, "向{dir}滑动"),

    # 等待
    (r"等待?(\d+)?(?:秒|s)?", ActionType.WAIT, "等待{time}s"),

    # 长按
    (r"长按[\"「]?(.+?)[\"」]?", ActionType.LONG_PRESS, "长按{target}"),
]


class StepParser:
    """将 Task description 解析为 Step 列表。"""

    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm

    def parse(self, task_description: str, task_name: str = "") -> list[Step]:
        """
        将任务描述拆解为执行步骤列表。

        Args:
            task_description: Task 的 description 字段
            task_name: Task 的 name 字段（辅助上下文）

        Returns:
            list[Step]: 拆解后的步骤列表
        """
        steps = []

        # 策略1：基于分隔符的快速拆分
        raw_steps = self._split_by_delimiters(task_description)

        if len(raw_steps) <= 1:
            # 只有一个自然段，尝试规则匹配或 LLM 拆分
            rule_steps = self._parse_by_rules(task_description)
            if rule_steps:
                steps = rule_steps
            elif self.llm:
                steps = self._parse_by_llm(task_description, task_name)
            else:
                # 兜底：整个描述作为一个 step
                steps = [Step(raw_text=task_description, intent=task_description)]
        else:
            # 多个段落，逐个处理
            for raw in raw_steps:
                raw = raw.strip()
                if not raw:
                    continue
                rule_steps = self._parse_by_rules(raw)
                if rule_steps:
                    steps.extend(rule_steps)
                elif self.llm:
                    steps.extend(self._parse_by_llm(raw, task_name))
                else:
                    steps.append(Step(raw_text=raw, intent=raw))

        return steps

    def _split_by_delimiters(self, text: str) -> list[str]:
        """按常见分隔符拆分描述文本。"""
        # 优先级从高到低：中文句号/逗号 → 然后/接着 → 箭头/序号
        delimiters = [
            r"[，,]\s*(?:然后|接着|之后|再|随后|最后)",
            r"[；;]",
            r"→",
            r"\d+[\.、．]",
        ]
        result = [text]
        for delim in delimiters:
            new_result = []
            for part in result:
                new_result.extend(re.split(delim, part))
            result = new_result
        return [s.strip() for s in result if s.strip()]

    def _parse_by_rules(self, text: str) -> list[Step] | None:
        """用正则规则匹配，返回 Step 列表。未匹配到返回 None。"""
        from .models import Action, WidgetTarget

        matched_actions = []
        remaining_text = text

        for pattern, action_type, template in _ACTION_PATTERNS:
            match = re.search(pattern, text)
            if match:
                action = Action(action_type=action_type)
                if action_type == ActionType.SET_TEXT and match.groups():
                    action.input_text = match.group(1)
                elif action_type == ActionType.WAIT:
                    t = match.group(1) if match.groups() and match.group(1) else "2"
                    action.wait_time = float(t)
                elif action_type == ActionType.SWIPE:
                    d = match.group(1) if match.groups() and match.group(1) else "down"
                    action.swipe_direction = d

                # 尝试提取目标控件描述（给后续 WidgetUnderstander 用）
                target_desc = ""
                if match.groups() and action_type in (
                    ActionType.CLICK, ActionType.LONG_PRESS,
                ):
                    target_desc = match.group(1)
                    action.target = WidgetTarget(text=target_desc)

                matched_actions.append(action)
                remaining_text = remaining_text.replace(match.group(0), "").strip()

        if not matched_actions:
            return None

        steps = [Step(
            raw_text=text,
            intent=text,
            actions=matched_actions,
        )]
        return steps

    def _parse_by_llm(self, text: str, task_name: str = "") -> list[Step]:
        """调用 LLM 将描述智能拆分为步骤。"""
        from .prompts import STEP_PARSE_SYSTEM, STEP_PARSE_USER

        messages = [
            {"role": "system", "content": STEP_PARSE_SYSTEM},
            {"role": "user", "content": STEP_PARSE_USER.format(
                task_name=task_name,
                task_description=text,
            )},
        ]
        try:
            result = self.llm.chat_json(messages)
            steps_data = result.get("steps", [])
            steps = []
            for s in steps_data:
                step = Step(
                    raw_text=s.get("raw_text", ""),
                    intent=s.get("intent", ""),
                )
                steps.append(step)
            return steps
        except Exception as e:
            print(f"⚠️  LLM 步骤解析失败，使用兜底方案：{e}")
            return [Step(raw_text=text, intent=text)]
