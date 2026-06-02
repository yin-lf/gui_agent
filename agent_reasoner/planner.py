"""Overview Planner：LLM 子任务分解 + DAG 构建。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .llm_client import LLMClient
from .models import Task, TaskTree, TaskPriority
from .prompts import TASK_DECOMPOSITION_SYSTEM, TASK_DECOMPOSITION_USER

if TYPE_CHECKING:
    from .skill_manager import Skill


class OverviewPlanner:
    """将完善后的明确目标分解为 DAG 任务树。"""

    def __init__(self, llm: LLMClient, skill: Skill | None = None):
        self.llm = llm
        self.skill = skill

    def decompose(self, instruction: str, refined_goal: str, collected_info: dict) -> TaskTree:
        """
        调用 LLM 将目标分解为子任务 DAG。
        """
        # 注入 skill 的 task_template
        task_template = ""
        if self.skill and self.skill.task_template:
            task_template = f"当前领域指导：\n{self.skill.task_template}"

        collected_str = _format_collected(collected_info)
        messages = [
            {"role": "system", "content": TASK_DECOMPOSITION_SYSTEM.format(
                skill_task_template=task_template
            )},
            {
                "role": "user",
                "content": TASK_DECOMPOSITION_USER.format(
                    instruction=instruction,
                    refined_goal=refined_goal,
                    collected_info=collected_str,
                ),
            },
        ]

        result = self.llm.chat_json(messages)
        return self._build_task_tree(result)

    def _build_task_tree(self, result: dict) -> TaskTree:
        """将 LLM 返回的 JSON 解析为 TaskTree。"""
        tree = TaskTree()

        for task_data in result.get("tasks", []):
            task = Task(
                id=task_data["id"],
                name=task_data["name"],
                description=task_data["description"],
                dependencies=task_data.get("dependencies", []),
                priority=TaskPriority(task_data.get("priority", "medium")),
            )
            tree.add_task(task)

        # 验证 DAG 无环
        if not tree.validate_no_cycle():
            raise ValueError("LLM 生成的任务树存在循环依赖，请重试。")

        return tree


def _format_collected(collected: dict) -> str:
    if not collected:
        return "暂无"
    return "\n".join(f"  - {k}：{v}" for k, v in collected.items())
