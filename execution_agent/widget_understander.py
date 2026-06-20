"""控件理解层：用 LLM 将自然语言操作意图映射到安卓控件树中的具体控件。

这是执行层的核心模块——连接「人类语言描述的操作」和「机器可执行的控件操作」。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import Action, ActionType, WidgetTarget
from .prompts import WIDGET_MATCH_SYSTEM, WIDGET_MATCH_USER

if TYPE_CHECKING:
    from ..agent_reasoner.llm_client import LLMClient
    from .screen_state import ScreenState


class WidgetUnderstander:
    """控件语义匹配器：操作意图 → 具体控件 + 操作类型。"""

    def __init__(self, llm: LLMClient):
        self.llm = llm
        # 控件树 XML 截断长度（防止超 token 限制）
        self._max_xml_length = 15000

    def find_action(
        self,
        step_intent: str,
        raw_text: str,
        screen_state: ScreenState,
        current_app_name: str = "",
    ) -> Action:
        """
        根据操作意图和当前屏幕状态，确定要执行的具体操作。

        Args:
            step_intent: 提炼后的操作意图（如"在搜索框输入'夜曲'"）
            raw_text: 原始描述文本
            screen_state: 当前屏幕的完整状态（含控件树）
            current_app_name: 当前前台 App 名称

        Returns:
            Action: 包含操作类型、目标控件、输入内容等的原子操作
        """
        # 先做快速规则匹配（常见操作不需要调 LLM）
        quick_action = self._quick_match(step_intent)
        if quick_action:
            return quick_action

        # 规则无法处理，调用 LLM 匹配控件
        return self._llm_match(step_intent, raw_text, screen_state, current_app_name)

    def _quick_match(self, intent: str) -> Action | None:
        """快速规则匹配：不依赖控件树的纯意图判断。注意：更具体的模式要排在前面！"""
        intent_lower = intent.lower()

        # Home 键（必须在"返回"之前检测，避免"返回主页"被误判为press_back）
        if any(kw in intent_lower for kw in ["回到桌面", "返回主页", "home", "主屏幕"]):
            return Action(action_type=ActionType.PRESS_HOME, reasoning="检测到回到桌面操作")

        # 返回键（排除已匹配Home的情况）
        if any(kw in intent_lower for kw in ["返回", "退回", "back", "回到上一页"]):
            return Action(action_type=ActionType.PRESS_BACK, reasoning="检测到返回操作")

        # 等待
        import re
        wait_match = re.search(r"等待?(\d+)?(?:秒|s)?", intent)
        if wait_match or "等待" in intent_lower or "稍候" in intent_lower:
            t = float(wait_match.group(1)) if wait_match and wait_match.group(1) else 2.0
            return Action(
                action_type=ActionType.WAIT,
                wait_time=t,
                reasoning=f"检测到等待操作，等待{t}秒",
            )

        return None

    def _llm_match(
        self,
        step_intent: str,
        raw_text: str,
        screen_state: ScreenState,
        current_app_name: str,
    ) -> Action:
        """调用 LLM 在控件树中找到目标控件。"""
        xml = self._truncate_xml(screen_state.hierarchy_xml)

        messages = [
            {"role": "system", "content": WIDGET_MATCH_SYSTEM},
            {"role": "user", "content": WIDGET_MATCH_USER.format(
                step_intent=step_intent,
                raw_text=raw_text,
                current_app=current_app_name,
                hierarchy_xml=xml,
            )},
        ]

        try:
            result = self.llm.chat_json(messages)
            return self._parse_llm_result(result)
        except Exception as e:
            print(f"⚠️  LLM 控件匹配失败：{e}")
            # 兜底：返回一个空目标的 click 操作，让执行器去尝试
            return Action(
                action_type=ActionType.CLICK,
                target=None,
                reasoning=f"LLM匹配失败({e})，使用兜底方案",
            )

    def _parse_llm_result(self, result: dict) -> Action:
        """将 LLM 返回的 JSON 解析为 Action 对象。"""
        action_str = result.get("action", "click")
        action_type = self._parse_action_type(action_str)

        target_data = result.get("target", {})
        target = WidgetTarget(
            text=target_data.get("text") or None,
            resource_id=target_data.get("resource_id") or None,
            class_name=target_data.get("class") or None,
            content_desc=target_data.get("content_desc") or None,
            bounds=target_data.get("bounds"),
        )

        input_text = result.get("input_text") or None
        swipe_direction = result.get("swipe_direction") or None
        wait_time = float(result.get("wait_time", 0) or 0)
        reasoning = result.get("reasoning", "")

        return Action(
            action_type=action_type,
            target=target if not target.is_empty() else None,
            input_text=input_text,
            swipe_direction=swipe_direction,
            wait_time=wait_time,
            reasoning=reasoning,
        )

    @staticmethod
    def _parse_action_type(action_str: str) -> ActionType:
        mapping = {
            "click": ActionType.CLICK,
            "set_text": ActionType.SET_TEXT,
            "scroll": ActionType.SCROLL,
            "long_press": ActionType.LONG_PRESS,
            "swipe": ActionType.SWIPE,
            "press_back": ActionType.PRESS_BACK,
            "press_home": ActionType.PRESS_HOME,
            "wait": ActionType.WAIT,
        }
        return mapping.get(action_str.lower(), ActionType.CLICK)

    @staticmethod
    def _truncate_xml(xml: str, max_length: int = 15000) -> str:
        """截断过长的控件树 XML，保留重要部分。"""
        if len(xml) <= max_length:
            return xml

        # 从尾部截断，保留开头（通常重要的控件在前面）
        truncated = xml[:max_length]
        # 尝试在最后一个完整节点处截断
        last_node_end = truncated.rfind("</node>")
        if last_node_end > max_length * 0.8:
            truncated = truncated[:last_node_end + 7]
        truncated += "\n<!-- XML 已截断，省略了部分子节点 -->"
        return truncated
