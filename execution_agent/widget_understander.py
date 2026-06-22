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
        """快速规则匹配：仅处理不需要目标控件的操作。

        可以短路（不需要 LLM 匹配控件）的操作：
        - press_back / press_home / wait
        - 键盘操作（搜索/回车/完成键）→ 用 ADB keyevent
        """
        intent_lower = intent.lower()
        import re

        # Home 键
        if any(kw in intent_lower for kw in ["回到桌面", "返回主页", "home", "主屏幕"]):
            return Action(action_type=ActionType.PRESS_HOME, reasoning="检测到回到桌面操作")

        # 返回键
        if any(kw in intent_lower for kw in ["返回", "退回", "back", "回到上一页"]):
            return Action(action_type=ActionType.PRESS_BACK, reasoning="检测到返回操作")

        # ===== 新增：键盘操作检测 =====
        # 软键盘上的按钮（搜索/回车/完成/下一步）→ 用 ADB keyevent 66
        keyboard_patterns = [
            r"键盘.*?(?:搜索|回车|完成|下一步|enter|go|search)",
            r"(?:点击|按|敲).*(?:键盘上的)?(?:搜索|回车|完成|下一步)",
            r"(?:搜索|回车|完成)键",
            r"(?:搜索|回车|完成)按钮[^a-z]",  # 排除普通按钮
            r"软键盘.*?按钮",
        ]
        for pattern in keyboard_patterns:
            if re.search(pattern, intent_lower):
                return Action(
                    action_type=ActionType.KEY_EVENT,
                    key_code=66,  # KEYCODE_ENTER / KEYCODE_SEARCH
                    reasoning=f"检测到键盘操作（匹配: {pattern}），改用 ADB keyevent 66(回车/搜索)",
                )

        # 独立等待指令（不是附带说明）
        if re.search(r"^等待[\d秒s]*$", intent_lower.strip()) or \
           intent_lower.strip() in ("等待", "稍候", "等待一下"):
            wait_match = re.search(r"等待?(\d+)?(?:秒|s)?", intent)
            t = float(wait_match.group(1)) if (wait_match and wait_match.group(1)) else 2.0
            return Action(action_type=ActionType.WAIT, wait_time=t,
                        reasoning=f"检测到独立等待指令，等待{t}秒")

        # 其他所有操作（点击/输入/滑动/打开App等）→ 返回 None → 走 LLM 控件匹配
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
        except ValueError as e:
            # JSON 解析失败：尝试从原始文本手动提取
            print(f"     ⚠️ JSON解析异常，尝试原始文本回退：{e}")
            try:
                raw_response = self.llm.chat(messages)  # 获取原始文本
                result = self._extract_json_from_text(raw_response)
                if result:
                    return self._parse_llm_result(result)
            except Exception:
                pass
            raise  # 都不行就抛出
        except Exception as e:
            print(f"⚠️  LLM 控件匹配失败：{e}")
            raise  # 不再兜底空目标，让上层决定是否重试

    @staticmethod
    def _extract_json_from_text(text: str) -> dict | None:
        """从 LLM 原始文本中尽力提取 JSON。"""
        import re, json

        # 尝试直接解析
        text = text.strip()

        # 处理 LLM 返回双花括号 {{ }} 的情况（学样了 prompt 模板中的转义）
        if text.startswith("{{") and "}}" in text:
            text = text.replace("{{", "{", 1)   # 只替换开头的 {{
            # 替换最后的 }}
            last_brace = text.rfind("}}")
            if last_brace >= 0:
                text = text[:last_brace] + "}" + text[last_brace + 2:]

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 去掉 markdown 代码块
        if "```" in text:
            lines = text.split("\n")
            cleaned = []
            in_code = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_code = not in_code
                    continue
                if in_code:
                    cleaned.append(line)
            try:
                return json.loads("\n".join(cleaned))
            except json.JSONDecodeError:
                pass

        # 正则提取最外层 {}
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None

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
        key_code = int(result.get("key_code", 0) or 0)

        action = Action(
            action_type=action_type,
            target=target if not target.is_empty() else None,
            input_text=input_text,
            swipe_direction=swipe_direction,
            wait_time=wait_time,
            key_code=key_code,
            reasoning=reasoning,
        )

        # 后处理：检测 LLM 返回的是否为键盘上的控件
        # 如果 LLM 的 reasoning 提到"键盘"或目标特征匹配键盘按钮 → 转为 KEY_EVENT
        if action.action_type == ActionType.CLICK and self._is_likely_keyboard_target(action, reasoning):
            action.action_type = ActionType.KEY_EVENT
            action.key_code = 66  # 默认回车/搜索
            action.reasoning += " [后处理：识别为键盘操作，转为 ADB keyevent]"
            print(f"     ⌨️ 检测到可能是键盘控件，自动转用按键事件")

        return action

    @staticmethod
    def _is_likely_keyboard_target(action: Action, reasoning: str) -> bool:
        """判断 LLM 返回的目标是否是软键盘上的控件。"""
        import re
        # 检查 reasoning 中是否提到键盘
        keyboard_keywords = ["键盘", "软键盘", "inputmethod", "IME", "输入法"]
        if any(kw in reasoning for kw in keyboard_keywords):
            return True

        # 检查目标控件的 class_name 是否是键盘相关
        if action.target and action.target.class_name:
            kb_classes = ["EditText", "inputmethod", "Keyboard"]
            if any(kb in (action.target.class_name or "") for kb in kb_classes):
                return True

        return False

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
            "key_event": ActionType.KEY_EVENT,
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
