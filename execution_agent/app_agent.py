"""App Agent 主控制器：接收推理层的 TaskTree，驱动 DAG 按序执行。

执行流程：
1. 接收推理层输出的 TaskTree（DAG）
2. 按 DAG 依赖关系调度任务
3. 对每个 Task：
   a. 将 description 拆解为原子步骤（Step）
   b. 对每个 Step：
      - 采集当前屏幕状态（控件树 + 截图）
      - 调用 LLM 匹配目标控件
      - 执行操作（含重试）
      - 验证结果
4. 处理异常（重试 / 上报恢复层）
5. 返回完整执行记录
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from .screen_state import ScreenCaptor, ScreenState
from .step_parser import StepParser
from .widget_understander import WidgetUnderstander
from .action_executor import ActionExecutor
from .models import ExecutionResult, ExecutionStatus, Step

if TYPE_CHECKING:
    from ..agent_reasoner.llm_client import LLMClient
    from ..agent_reasoner.models import TaskTree


class AppAgent:
    """GUI 交互层主控制器——将 TaskTree 中的子任务逐一在安卓设备上执行。"""

    def __init__(self, device, llm: LLMClient):
        """
        Args:
            device: uiautomator2.Device 实例
            llm: LLMClient 实例（用于控件理解）
        """
        self.device = device
        self.llm = llm

        # 子模块
        self.captor = ScreenCaptor(device)
        self.parser = StepParser(llm)
        self.understander = WidgetUnderstander(llm)
        self.executor = ActionExecutor(device)

        # 执行状态
        self.execution_log: list[dict] = []   # 操作日志
        self._current_screen: Optional[ScreenState] = None

    def execute_task_tree(self, task_tree: TaskTree) -> dict:
        """
        按 DAG 顺序执行所有子任务。

        Args:
            task_tree: 推理层输出的 TaskTree

        Returns:
            dict: 包含每个任务的执行状态和日志
        """
        print("\n" + "=" * 50)
        print("🤖 App Agent 启动 — GUI 交互层")
        print("=" * 50)

        # 初始屏幕采样
        self._current_screen = self.captor.capture()
        print(f"\n📱 当前 App：{self.captor.get_current_app_name()}")
        print(f"📊 控件树节点数：约 {self._current_screen.xml_size // 100} 百字符")

        total_tasks = len(task_tree.tasks)
        completed = 0
        failed_tasks = []

        while not task_tree.is_complete():
            # 获取所有可执行的任务（依赖已满足）
            ready_tasks = task_tree.get_ready_tasks()

            if not ready_tasks:
                if task_tree.has_failed():
                    print("\n⛔ 存在失败任务且无更多可执行任务，停止执行。")
                    break
                print("\n⚠️ 无可执行任务且没有失败任务，可能存在循环依赖或死锁。")
                break

            for task in ready_tasks:
                completed += 1
                print(f"\n{'─' * 40}")
                print(f"📋 [{task.id}] {task.name} （{completed}/{total_tasks}）")
                print(f"   描述：{task.description}")
                print(f"{'─' * 40}")

                result = self._execute_single_task(task)

                if result.success:
                    task.status = task.status.__class__.COMPLETED
                    task.result = {"status": "completed", "log": result.action_summary}
                    print(f"  ✅ [{task.id}] 执行完成")
                else:
                    if result.status == ExecutionStatus.FATAL:
                        task.status = task.status.__class__.FAILED
                        task.error = result.error
                        failed_tasks.append(task.id)
                        print(f"  ❌ [{task.id}] 致命错误：{result.error}")
                        # 致命错误直接上报，停止执行
                        print(f"  ⚠️  停止执行，上报异常恢复层...")
                        return self._build_report(task_tree, failed_tasks)
                    else:
                        # 可重试错误：标记失败但继续尝试其他任务
                        task.status = task.status.__class__.FAILED
                        task.error = result.error
                        failed_tasks.append(task.id)
                        print(f"  ❌ [{task.id}] 执行失败（可重试）：{result.error}")

        return self._build_report(task_tree, failed_tasks)

    def _execute_single_task(self, task) -> ExecutionResult:
        """执行单个子任务：拆解步骤 → 逐步执行。"""
        # 1. 将 description 拆解为原子步骤
        steps = self.parser.parse(task.description, task.name)
        print(f"  📝 拆分为 {len(steps)} 个步骤")

        for step_idx, step in enumerate(steps, 1):
            print(f"\n  ── 步骤 {step_idx}/{len(steps)}：{step.intent[:60]}{'...' if len(step.intent) > 60 else ''}")

            step_result = self._execute_single_step(step, task.name)

            if not step_result.success:
                return step_result

        return ExecutionResult(success=True, action_summary=f"[{task.id}] 所有步骤完成")

    def _execute_single_step(self, step: Step, task_name: str) -> ExecutionResult:
        """执行单个原子步骤：采集屏幕 → 控件匹配 → 执行操作。"""
        from .models import ActionType

        MAX_MATCH_RETRIES = 2  # 控件匹配重试（App加载中场景）

        for match_attempt in range(MAX_MATCH_RETRIES + 1):
            # 1. 采集当前屏幕状态
            self._current_screen = self.captor.capture()
            current_app = self.captor.get_current_app_name()

            # 2. 控件理解：LLM 匹配目标控件
            try:
                action = self.understander.find_action(
                    step_intent=step.intent,
                    raw_text=step.raw_text,
                    screen_state=self._current_screen,
                    current_app_name=current_app,
                )
            except Exception as e:
                if match_attempt < MAX_MATCH_RETRIES:
                    print(f"     ⏳ LLM 匹配异常，等待后重试 ({match_attempt + 1}/{MAX_MATCH_RETRIES})：{e}")
                    time.sleep(2.0)
                    continue
                raise

            print(f"  🎯 理解结果：{action.summary()}")
            if action.reasoning:
                print(f"     推理：{action.reasoning[:100]}{'...' if len(action.reasoning) > 100 else ''}")

            # 3. 空目标检测：需要控件的操作但目标为空 → 页面可能未加载，等一下重试
            needs_target = action.action_type in (
                ActionType.CLICK, ActionType.SET_TEXT,
                ActionType.SCROLL, ActionType.LONG_PRESS,
            )
            if needs_target and (action.target is None or action.target.is_empty()):
                if match_attempt < MAX_MATCH_RETRIES:
                    print(f"     ⚠️ 目标控件为空（可能页面未加载完），2s 后重新截屏匹配...")
                    time.sleep(2.0)
                    continue
                else:
                    print(f"     ❌ 多次匹配仍无法找到目标控件")

            # 4. 执行操作（带内置重试）
            result = self.executor.execute_with_retry(action)

            # 5. 记录日志
            log_entry = {
                "timestamp": time.time(),
                "task_name": task_name,
                "step_intent": step.intent,
                "action": action.summary(),
                "success": result.success,
                "error": result.error,
                "retry_count": result.retry_count,
                "screenshot": result.screenshot_path or self._current_screen.screenshot_path,
            }
            self.execution_log.append(log_entry)

            # 6. 操作后等待页面响应（智能等待：页面变化后才继续）
            if result.success:
                if action.action_type.value in ("click",):
                    new_screen = self.captor.wait_for_change(
                        timeout=8.0, interval=1.0, old_state=self._current_screen,
                    )
                    if new_screen:
                        self._current_screen = new_screen
                        print(f"     📱 页面已切换 → {self.captor.get_current_app_name()}")
                    else:
                        time.sleep(1.5)
                elif action.action_type.value in ("set_text", "swipe"):
                    time.sleep(1.5)

            return result

        return ExecutionResult(
            success=False, status=ExecutionStatus.RETRYABLE,
            error="多次控件匹配均未找到有效目标",
            action_summary=f"[{task_name}] {step.intent}",
        )

    def _build_report(self, task_tree, failed_tasks: list[str]) -> dict:
        """构建执行报告。"""
        report = {
            "summary": {
                "total": len(task_tree.tasks),
                "completed": len(task_tree.get_completed_tasks()),
                "failed": len(failed_tasks),
                "failed_ids": failed_tasks,
            },
            "tasks": {},
            "execution_log": self.execution_log,
        }

        for tid, task in task_tree.tasks.items():
            report["tasks"][tid] = {
                "name": task.name,
                "status": task.status.value,
                "error": task.error,
                "result": task.result,
            }

        print(f"\n{'=' * 50}")
        print("📊 执行报告：")
        print(f"   总任务：{report['summary']['total']}")
        print(f"   完成：{report['summary']['completed']}")
        print(f"   失败：{report['summary']['failed']}")
        if failed_tasks:
            print(f"   失败ID：{', '.join(failed_tasks)}")
        print(f"   日志条数：{len(self.execution_log)}")
        print(f"{'=' * 50}\n")

        return report

    def execute_task_tree_from_dict(self, tree_dict: dict) -> dict:
        """
        便捷入口：接收 TaskTree 的 JSON dict，内部转换为 TaskTree 对象后执行。

        适用于直接从 task_tree.json 文件或推理层 run() 返回值传入。

        Args:
            tree_dict: 推理层输出的 JSON 字典（含 tasks 列表或 {T1: {...}, T2: {...}} 格式）

        Returns:
            dict: 执行报告
        """
        import json
        from agent_reasoner.models import Task, TaskTree, TaskPriority

        task_tree = TaskTree()

        # 兼容两种格式：{T1: {...}, T2: {...}} 或 {"tasks": [{...}, {...}]}
        if "tasks" in tree_dict:
            items = tree_dict["tasks"]
        else:
            items = tree_dict.values()

        for tdata in items:
            task = Task(
                id=tdata["id"],
                name=tdata["name"],
                description=tdata["description"],
                dependencies=tdata.get("dependencies", []),
                priority=TaskPriority(tdata.get("priority", "medium")),
            )
            task_tree.add_task(task)

        return self.execute_task_tree(task_tree)

