"""Skill 管理：加载 .skill 文件，关键词匹配识别领域。"""

import os
from typing import Optional

import yaml


class Skill:
    """一个领域技能的配置。"""

    def __init__(self, data: dict):
        self.name: str = data.get("name", "")
        self.keywords: list[str] = data.get("keywords", [])
        self.apps: list[str] = data.get("apps", [])
        # required_info: 每个 info 有 name, type(open/choice), question, recommend_by(可选)
        self.required_info: list[dict] = data.get("required_info", [])
        self.task_template: str = data.get("task_template", "")
        self._data = data

    def match(self, instruction: str) -> bool:
        """检查用户指令是否命中本 skill 的关键词。"""
        instruction_lower = instruction.lower()
        return any(kw in instruction_lower for kw in self.keywords)


class SkillManager:
    """扫描、加载、匹配 skill 文件。"""

    def __init__(self, skills_dir: str | None = None):
        if skills_dir is None:
            skills_dir = os.path.join(os.path.dirname(__file__), "skills")
        self.skills: list[Skill] = self._load_skills(skills_dir)

    def _load_skills(self, skills_dir: str) -> list[Skill]:
        """扫描目录下所有 .skill 文件并加载。"""
        skills = []
        if not os.path.isdir(skills_dir):
            print(f"⚠️  skills 目录不存在：{skills_dir}")
            return skills

        for fname in os.listdir(skills_dir):
            if not fname.endswith(".skill"):
                continue
            filepath = os.path.join(skills_dir, fname)
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data:
                skills.append(Skill(data))
                print(f"  已加载 skill：{data.get('name', fname)}")
        return skills

    def detect(self, instruction: str) -> Optional[Skill]:
        """关键词匹配，返回命中的 skill，未命中返回 None。"""
        for skill in self.skills:
            if skill.match(instruction):
                return skill
        return None

    def save_new_skill(self, skill_data: dict):
        """将新生成的 skill 保存为 .skill 文件，并加入内存列表。"""
        skills_dir = os.path.join(os.path.dirname(__file__), "skills")
        os.makedirs(skills_dir, exist_ok=True)

        name = skill_data.get("name", "未命名")
        filename = name + ".skill"
        filepath = os.path.join(skills_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(skill_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        skill = Skill(skill_data)
        self.skills.append(skill)
        print(f"  ✅ 已保存新 skill：{filepath}")
        return skill
