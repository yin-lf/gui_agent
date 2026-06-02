"""Agent 推理层入口：Skill 检测 → HITL → Planner → 输出 TaskTree。"""

import json
import os
import sys

from .llm_client import LLMClient
from .skill_manager import SkillManager
from .hitl import HITLRunner
from .planner import OverviewPlanner
from .prompts import SKILL_GENERATION_SYSTEM, SKILL_GENERATION_USER, TASK_REVISION_SYSTEM, TASK_REVISION_USER


def run(instruction: str | None = None) -> dict:
    """
    运行完整的推理流程。

    Args:
        instruction: 用户指令。如果为 None，则从终端读取。

    Returns:
        dict: TaskTree 序列化后的 JSON 字典。
    """
    # 初始化
    llm = LLMClient()

    print("📂 加载 skill 配置...")
    skill_manager = SkillManager()

    # 获取用户指令
    if instruction is None:
        print("=" * 50)
        print("Agent 推理层：人在环路的任务目标完善与子任务分解")
        print("=" * 50)
        instruction = input("\n请输入您的指令：\n> ").strip()

    if not instruction:
        print("⚠️  指令不能为空。")
        sys.exit(1)

    print(f"\n📝 您的指令：{instruction}\n")

    # Step 0: Skill 检测
    skill_matched = skill_manager.detect(instruction)
    if skill_matched:
        print(f"🎯 识别到领域：{skill_matched.name}（相关App：{'、'.join(skill_matched.apps)}）\n")
    else:
        print("🎯 未匹配到特定领域，使用通用模式。\n")

    # Step 1: HITL 目标完善
    hitl = HITLRunner(llm, skill=skill_matched)
    refined_goal, collected_info = hitl.refine_goal(instruction)

    # Step 2: 子任务分解
    print("📋 正在分解子任务...\n")
    planner = OverviewPlanner(llm, skill=skill_matched)
    task_tree = planner.decompose(instruction, refined_goal, collected_info)

    # Step 3: 输出结果并确认
    result = _confirm_and_output(llm, instruction, task_tree)

    # Step 4: 未命中 skill 时，生成新 skill 并保存
    if not skill_matched:
        _save_new_skill(llm, skill_manager, instruction, refined_goal, collected_info, result)

    return result


def _confirm_and_output(llm: LLMClient, instruction: str, task_tree) -> dict:
    """展示子任务分解结果，用户确认或反馈修改（支持多轮反馈）。"""
    while True:
        print("\n📋 子任务分解结果（DAG 任务树）：")
        task_tree.pretty_print()

        print("\n请确认子任务分解结果：")
        print("  1. 确认无误，继续")
        print("  2. 有问题，需要修改")

        choice = input("\n请选择（1/2）：> ").strip()

        if choice == "1":
            break
        elif choice == "2":
            feedback = input("请描述需要修改的内容（如：第二步搜索关键词不对、缺少某一步等）：\n> ").strip()
            if not feedback:
                continue

            print(f"\n🔄 正在根据反馈重新分解...")
            old_tasks = json.dumps(task_tree.to_dict(), indent=2, ensure_ascii=False)
            messages = [
                {"role": "system", "content": TASK_REVISION_SYSTEM},
                {"role": "user", "content": TASK_REVISION_USER.format(
                    instruction=instruction,
                    old_tasks=old_tasks,
                    feedback=feedback,
                )},
            ]
            try:
                result = llm.chat_json(messages)
                task_tree = _build_tree_from_dict(result)
                print("✅ 已根据反馈重新生成，请再次确认。")
            except Exception as e:
                print(f"⚠️  重新生成失败：{e}")
            continue
        else:
            print("⚠️  无效选择，请输入 1 或 2。")
            continue

    result = task_tree.to_dict()
    print("\n📦 TaskTree JSON 输出：")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # 保存 task_tree JSON
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "task_tree.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n💾 已保存到：{output_file}")

    return result


def _build_tree_from_dict(result: dict):
    """从 LLM 返回的 JSON 重建 TaskTree。"""
    from .models import Task, TaskTree, TaskPriority

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
    return tree


def _save_new_skill(llm: LLMClient, skill_manager: SkillManager,
                    instruction: str, refined_goal: str,
                    collected_info: dict, task_tree: dict):
    """从本次交互中提取新 skill 并保存。"""
    print("\n🆕 未匹配到现有领域，正在从本次交互中提取新 skill...")

    collected_str = "\n".join(f"  - {k}：{v}" for k, v in collected_info.items())
    task_tree_str = json.dumps(task_tree, indent=2, ensure_ascii=False)

    messages = [
        {"role": "system", "content": SKILL_GENERATION_SYSTEM},
        {"role": "user", "content": SKILL_GENERATION_USER.format(
            instruction=instruction,
            refined_goal=refined_goal,
            collected_info=collected_str,
            task_tree=task_tree_str,
        )},
    ]

    try:
        skill_data = llm.chat_json(messages)
        skill_manager.save_new_skill(skill_data)
    except Exception as e:
        print(f"  ⚠️  新 skill 生成失败：{e}")


def main():
    run()


if __name__ == "__main__":
    main()
