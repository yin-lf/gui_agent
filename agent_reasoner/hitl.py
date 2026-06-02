"""人在环路（HITL）模块：分轮次追问，open 类型直接问，choice 类型调 LLM 生成选项。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .llm_client import LLMClient
from .prompts import (
    AMBIGUITY_DETECTION_SYSTEM,
    AMBIGUITY_DETECTION_USER,
    INFO_CHECK_SYSTEM,
    INFO_CHECK_USER,
    OPTION_GENERATION_SYSTEM,
    OPTION_GENERATION_USER,
)

if TYPE_CHECKING:
    from .skill_manager import Skill


class HITLRunner:
    """分轮次 HITL 交互：按 skill 的 required_info 逐个询问。"""

    def __init__(self, llm: LLMClient, skill: Skill | None = None):
        self.llm = llm
        self.skill = skill

    def refine_goal(self, instruction: str) -> tuple[str, dict]:
        """
        对用户指令进行 HITL 目标完善。

        返回: (完善后的明确目标, 收集到的所有信息字典)
        """
        # Step 1: 获取需要收集的信息列表
        if self.skill and self.skill.required_info:
            info_list = self.skill.required_info
        else:
            # 无 skill，调用 LLM 检测模糊维度
            detection = self._detect_ambiguity(instruction)
            if not detection.get("is_ambiguous", False):
                print("✅ 指令明确，无需追问。")
                return instruction, {}

            dimensions = detection.get("dimensions", [])
            if not dimensions:
                return instruction, {}

            dimensions.sort(key=lambda d: d.get("priority", 99))
            info_list = [
                {"name": d["name"], "type": "open", "question": d.get("description", d["name"])}
                for d in dimensions
            ]

        # Step 2: 检测用户指令中已经提供了哪些信息
        provided = self._check_provided_info(instruction, info_list)
        pre_collected = {}
        to_ask = []
        for info in info_list:
            name = info["name"]
            if provided.get(name):
                pre_collected[name] = provided[name]
            else:
                to_ask.append(info)

        if pre_collected:
            print("📋 用户指令中已包含：")
            for k, v in pre_collected.items():
                print(f"  ✅ {k}：{v}")
            print()

        if not to_ask:
            print("✅ 所有信息已明确，无需追问。")
            refined = self._summarize_refined_goal(instruction, pre_collected)
            print(f"\n✅ 任务目标已明确：{refined}\n")
            return refined, pre_collected

        print(f"🤔 还需确认 {len(to_ask)} 个信息：")
        for info in to_ask:
            print(f"  - {info['name']}")
        print()

        # Step 3: 逐个询问缺失的信息
        collected: dict[str, str] = dict(pre_collected)

        collected: dict[str, str] = dict(pre_collected)
        total = len(to_ask)
        for i, info in enumerate(to_ask, 1):
            info_type = info.get("type", "open")
            if info_type == "choice":
                answer = self._ask_choice(instruction, info, collected, i, total)
            else:
                answer = self._ask_open(info, i, total)
            collected[info["name"]] = answer

        # Step 3: 汇总完善后的目标
        refined = self._summarize_refined_goal(instruction, collected)
        print(f"\n✅ 任务目标已明确：{refined}\n")
        return refined, collected

    # ------------------------------------------------------------------ #
    #  开放式追问：直接显示 skill 中定义的 question
    # ------------------------------------------------------------------ #

    def _ask_open(self, info: dict, round_num: int, total: int) -> str:
        question = info.get("question", f"请告诉我您的{info['name']}：")
        print(f"--- 第{round_num}轮（共{total}轮）：{info['name']} ---")
        print(f"❓ {question}\n")
        return input("> ").strip()

    # ------------------------------------------------------------------ #
    #  选择题追问：skill 定义 question 和 recommend_by，LLM 生成具体选项
    # ------------------------------------------------------------------ #

    def _ask_choice(
        self, instruction: str, info: dict, collected: dict[str, str],
        round_num: int, total: int,
    ) -> str:
        dim_name = info["name"]
        question = info.get("question", f"请选择{dim_name}：")
        recommend_by = info.get("recommend_by", [])

        # 构建推荐维度提示
        if recommend_by:
            rec_hint = "你必须按以下三个维度推荐恰好3个选项，每个选项附带具体数据：\n"
            for idx, r in enumerate(recommend_by):
                rec_hint += f"  选项{chr(65+idx)}：{r}\n"
        else:
            rec_hint = "请推荐3个选项，每个附带推荐理由。"

        # 强制追问和选项必须围绕当前维度
        force_hint = (
            f"当前维度是「{dim_name}」。"
            f"你的选项必须全部是关于「{dim_name}」的推荐。"
            f"question_type 必须为 choice_question，options 必须有恰好3个选项。"
        )

        collected_str = self._format_collected(collected)
        messages = [
            {"role": "system", "content": OPTION_GENERATION_SYSTEM.format(
                skill_recommend_dimensions=rec_hint + "\n" + force_hint
            )},
            {"role": "user", "content": OPTION_GENERATION_USER.format(
                instruction=instruction,
                dimension_name=dim_name,
                dimension_description=question,
                collected_info=collected_str,
            )},
        ]
        result = self.llm.chat_json(messages)
        options = result.get("options", [])

        # 兜底：LLM 没返回选项则重试一次
        if not options:
            messages[0]["content"] += "\n\n注意：你上一轮没有返回选项，这次必须返回3个选项！"
            result = self.llm.chat_json(messages)
            options = result.get("options", [])

        print(f"--- 第{round_num}轮（共{total}轮）：{dim_name} ---")
        print(f"❓ {question}\n")

        if not options:
            print("（无法生成推荐选项，请直接输入您的选择）")
            return input("> ").strip()

        # 展示选项
        for i, opt in enumerate(options, 1):
            label = opt.get("label", str(i))
            title = opt.get("title", "")
            reason = opt.get("reason", "")
            print(f"  {label}. {title}  —  {reason}")

        # 末尾加"其它"选项
        other_label = chr(65 + len(options))  # A=3个选项后就是D
        print(f"  {other_label}. 其它（手动输入）")

        # 用户选择
        valid_labels = [opt.get("label", str(i)) for i, opt in enumerate(options, 1)]
        valid_labels.append(other_label)
        while True:
            choice = input(f"\n请选择（{'/'.join(valid_labels)}）：> ").strip()
            # 选"其它"→让用户自由输入
            if choice == other_label or choice == "其它":
                custom = input("请输入您的选择：> ").strip()
                return custom
            for opt in options:
                if opt.get("label", "") == choice:
                    print()
                    return f"{opt['title']}（{opt.get('reason', '')}）"
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(options):
                    opt = options[idx]
                    print()
                    return f"{opt['title']}（{opt.get('reason', '')}）"
            except ValueError:
                pass
            print("⚠️  无效选择，请重新输入。")

    # ------------------------------------------------------------------ #
    #  检测用户已提供的信息
    # ------------------------------------------------------------------ #

    def _check_provided_info(self, instruction: str, info_list: list[dict]) -> dict[str, str]:
        """调用 LLM 检测用户指令中已经提供了哪些信息。"""
        # 构建信息项列表
        items = "\n".join(f"  - {info['name']}" for info in info_list)

        messages = [
            {"role": "system", "content": INFO_CHECK_SYSTEM.format(required_info_list=items)},
            {"role": "user", "content": INFO_CHECK_USER.format(instruction=instruction)},
        ]

        result = self.llm.chat_json(messages)
        provided = {}
        for item in result.get("results", []):
            if item.get("provided") and item.get("value"):
                provided[item["name"]] = item["value"]
        return provided

    # ------------------------------------------------------------------ #
    #  LLM 模糊检测（无 skill 时使用）
    # ------------------------------------------------------------------ #

    def _detect_ambiguity(self, instruction: str) -> dict:
        skill_hint = ""
        if self.skill:
            skill_hint = f"当前领域是「{self.skill.name}」。"

        messages = [
            {"role": "system", "content": AMBIGUITY_DETECTION_SYSTEM.format(
                skill_dimensions_hint=skill_hint
            )},
            {"role": "user", "content": AMBIGUITY_DETECTION_USER.format(instruction=instruction)},
        ]
        return self.llm.chat_json(messages)

    # ------------------------------------------------------------------ #
    #  工具方法
    # ------------------------------------------------------------------ #

    def _summarize_refined_goal(self, instruction: str, collected: dict[str, str]) -> str:
        parts = [f"{k}：{v}" for k, v in collected.items()]
        info_str = "，".join(parts)
        return f"{instruction}（{info_str}）" if info_str else instruction

    @staticmethod
    def _format_collected(collected: dict[str, str]) -> str:
        if not collected:
            return "暂无"
        return "\n".join(f"  - {k}：{v}" for k, v in collected.items())
