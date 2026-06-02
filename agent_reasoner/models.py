from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional, Dict


# ==================== 枚举 ====================

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskPriority(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class MessageType(Enum):
    ASSIGN_TASK = "assign_task"
    TASK_UPDATE = "task_update"
    TASK_RESULT = "task_result"
    TASK_FAILURE = "task_failure"
    RECOVERY_COMMAND = "recovery_command"


# ==================== Task ====================

@dataclass
class Task:
    id: str
    name: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    dependencies: List[str] = field(default_factory=list)
    worker_type: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    progress: float = 0.0
    current_step: str = ""
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    input_data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["priority"] = self.priority.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        data = data.copy()
        data["status"] = TaskStatus(data["status"])
        data["priority"] = TaskPriority(data["priority"])
        return cls(**data)


# ==================== TaskTree (DAG) ====================

class TaskTree:
    """任务树，有向无环图（DAG），每个节点是 Task，边表示依赖关系。"""

    def __init__(self):
        self.tasks: Dict[str, Task] = {}

    def add_task(self, task: Task):
        self.tasks[task.id] = task

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def get_ready_tasks(self) -> List[Task]:
        """获取所有依赖已满足的待执行任务。"""
        ready = []
        for task in self.tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            deps_met = all(
                self.get_task(dep_id).status == TaskStatus.COMPLETED
                for dep_id in task.dependencies
                if dep_id in self.tasks
            )
            if deps_met:
                ready.append(task)
        return ready

    def get_failed_tasks(self) -> List[Task]:
        return [t for t in self.tasks.values() if t.status == TaskStatus.FAILED]

    def get_completed_tasks(self) -> List[Task]:
        return [t for t in self.tasks.values() if t.status == TaskStatus.COMPLETED]

    def is_complete(self) -> bool:
        return all(
            t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
            for t in self.tasks.values()
        )

    def has_failed(self) -> bool:
        return any(t.status == TaskStatus.FAILED for t in self.tasks.values())

    def validate_no_cycle(self) -> bool:
        """拓扑排序验证 DAG 无环。"""
        visited: set[str] = set()
        temp: set[str] = set()

        def visit(tid: str) -> bool:
            if tid in temp:
                return False
            if tid in visited:
                return True
            temp.add(tid)
            task = self.get_task(tid)
            if task:
                for dep in task.dependencies:
                    if dep in self.tasks and not visit(dep):
                        return False
            temp.remove(tid)
            visited.add(tid)
            return True

        return all(visit(tid) for tid in self.tasks)

    def to_dict(self) -> dict:
        return {tid: t.to_dict() for tid, t in self.tasks.items()}

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def pretty_print(self):
        """以可读格式打印任务树。"""
        for task in self.tasks.values():
            deps = f"（依赖 {', '.join(task.dependencies)}）" if task.dependencies else ""
            print(f"  [{task.id}] {task.name}{deps}")
            print(f"       {task.description}")
