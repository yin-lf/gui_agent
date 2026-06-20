"""操作执行器：基于 uiautomator2 的原子操作执行，含重试和错误处理。

职责：
1. 将 Action 对象翻译为 uiautomator2 调用
2. 内置重试逻辑（控件未找到时等待后重试）
3. 区分可重试错误和致命错误
"""

from __future__ import annotations

import time

from .models import Action, ActionType, ExecutionResult, ExecutionStatus


class ActionExecutor:
    """原子操作执行器。"""

    # 默认配置
    DEFAULT_WAIT_TIMEOUT = 8.0        # 等待控件出现的最大时间(秒)
    DEFAULT_RETRY_COUNT = 2            # 操作失败后的最大重试次数
    DEFAULT_RETRY_INTERVAL = 1.5       # 重试间隔(秒)
    OPERATION_TIMEOUT = 10.0           # 单次操作超时(秒)

    def __init__(self, device):
        """
        Args:
            device: uiautomator2.Device 实例
        """
        self.device = device
        self.wait_timeout = self.DEFAULT_WAIT_TIMEOUT
        self.retry_count = self.DEFAULT_RETRY_COUNT
        self.retry_interval = self.DEFAULT_RETRY_INTERVAL

    def execute(self, action: Action) -> ExecutionResult:
        """
        执行一个原子操作。

        Args:
            action: 要执行的 Action 对象

        Returns:
            ExecutionResult: 执行结果（含成功/失败状态、错误信息等）
        """
        action_summary = action.summary()
        print(f"  🎬 执行：{action_summary}")

        try:
            handler = {
                ActionType.CLICK: self._exec_click,
                ActionType.SET_TEXT: self._exec_set_text,
                ActionType.SCROLL: self._exec_scroll,
                ActionType.LONG_PRESS: self._exec_long_press,
                ActionType.SWIPE: self._exec_swipe,
                ActionType.PRESS_BACK: self._exec_press_back,
                ActionType.PRESS_HOME: self._exec_press_home,
                ActionType.WAIT: self._exec_wait,
            }.get(action.action_type)

            if handler is None:
                return ExecutionResult(
                    success=False,
                    status=ExecutionStatus.FATAL,
                    error=f"未知的操作类型: {action.action_type}",
                    action_summary=action_summary,
                )

            return handler(action)

        except Exception as e:
            return ExecutionResult(
                success=False,
                status=self._classify_error(e),
                error=str(e),
                action_summary=action_summary,
            )

    def execute_with_retry(self, action: Action) -> ExecutionResult:
        """带重试的操作执行。"""
        last_result = None
        for attempt in range(self.retry_count + 1):  # +1 因为第一次不算重试
            result = self.execute(action)
            result.retry_count = attempt

            if result.success:
                return result

            last_result = result

            # 判断是否可重试
            if result.status == ExecutionStatus.FATAL:
                print(f"  ❌ 致命错误，不重试：{result.error}")
                return result

            # 可重试 → 等待后重试
            if attempt < self.retry_count:
                wait_time = self.retry_interval * (attempt + 1)
                print(f"  ⏳ 操作失败，{wait_time:.1f}s 后重试（{attempt + 1}/{self.retry_count}）：{result.error}")
                time.sleep(wait_time)

        return last_result

    # ==================== 各操作的实现 ====================

    def _exec_click(self, action: Action) -> ExecutionResult:
        """点击操作（含等待控件出现）。"""
        selector = self._build_selector_with_wait(action.target)
        if selector is None:
            return ExecutionResult(
                success=False,
                status=ExecutionStatus.RETRYABLE,
                error="点击操作缺少目标控件信息",
                action_summary=action.summary(),
            )

        try:
            self.device(**selector).click(timeout=self.OPERATION_TIMEOUT)
            widget_info = self._format_target(action.target)
            return ExecutionResult(
                success=True,
                actual_widget=widget_info,
                action_summary=action.summary(),
            )
        except Exception as e:
            err_str = str(e).lower()
            # uiauto2 RPC 兼容性问题 或 控件未找到 → 可重试
            if any(kw in err_str for kw in [
                "not found", "no matching", "timeout",
                "-32002", "-32006", "-32001", "rpcerror",
                "uiobject",
            ]):
                return ExecutionResult(
                    success=False,
                    status=ExecutionStatus.RETRYABLE,
                    error=f"控件操作失败（可重试）：{e}",
                    action_summary=action.summary(),
                )
            raise

    def _exec_set_text(self, action: Action) -> ExecutionResult:
        """文本输入操作。"""
        selector = self._build_selector_with_wait(action.target)
        if selector is None:
            return ExecutionResult(
                success=False,
                status=ExecutionStatus.RETRYABLE,
                error="输入操作缺少目标控件信息",
                action_summary=action.summary(),
            )

        if not action.input_text:
            return ExecutionResult(
                success=False,
                status=ExecutionStatus.FATAL,
                error="输入操作缺少要输入的文本内容",
                action_summary=action.summary(),
            )

        try:
            elem = self.device(**selector)
            # 先清空再输入
            elem.set_text(action.input_text, timeout=self.OPERATION_TIMEOUT)
            widget_info = self._format_target(action.target)
            return ExecutionResult(
                success=True,
                actual_widget=f'在 [{widget_info}] 输入 "{action.input_text}"',
                action_summary=action.summary(),
            )
        except Exception as e:
            err_str = str(e).lower()
            # uiauto2 RPC 兼容性问题 或 控件未找到 → 可重试
            if any(kw in err_str for kw in [
                "not found", "no matching", "timeout",
                "-32002", "-32006", "-32001", "rpcerror",
                "uiobject",
            ]):
                return ExecutionResult(
                    success=False,
                    status=ExecutionStatus.RETRYABLE,
                    error=f"输入操作失败（可重试）：{e}",
                    action_summary=action.summary(),
                )
            raise

    def _exec_scroll(self, action: Action) -> ExecutionResult:
        """滚动操作。"""
        selector = self._build_selector(action.target)
        try:
            if selector:
                self.device(**selector).scroll(timeout=self.OPERATION_TIMEOUT)
            else:
                # 没有指定控件则滚动整个屏幕
                self.device.swipe_ext("up")
            return ExecutionResult(success=True, action_summary=action.summary())
        except Exception as e:
            return ExecutionResult(
                success=False,
                status=ExecutionStatus.RETRYABLE,
                error=f"滚动失败：{e}",
                action_summary=action.summary(),
            )

    def _exec_long_press(self, action: Action) -> ExecutionResult:
        """长按操作。"""
        selector = self._build_selector_with_wait(action.target)
        if selector is None:
            return ExecutionResult(
                success=False,
                status=ExecutionStatus.RETRYABLE,
                error="长按操作缺少目标控件信息",
                action_summary=action.summary(),
            )
        try:
            self.device(**selector).long_click(timeout=self.OPERATION_TIMEOUT)
            return ExecutionResult(
                success=True,
                actual_widget=self._format_target(action.target),
                action_summary=action.summary(),
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                status=ExecutionStatus.RETRYABLE,
                error=f"长按失败：{e}",
                action_summary=action.summary(),
            )

    def _exec_swipe(self, action: Action) -> ExecutionResult:
        """滑动操作。"""
        direction = action.swipe_direction or "up"
        direction_map = {"up": "up", "down": "down", "left": "left", "right": "right"}
        actual_dir = direction_map.get(direction.lower(), "up")

        try:
            self.device.swipe_ext(actual_dir)
            return ExecutionResult(success=True, action_summary=action.summary())
        except Exception as e:
            return ExecutionResult(
                success=False,
                status=ExecutionStatus.RETRYABLE,
                error=f"滑动失败：{e}",
                action_summary=action.summary(),
            )

    def _exec_press_back(self, action: Action) -> ExecutionResult:
        """按返回键。"""
        self.device.press("back")
        return ExecutionResult(success=True, action_summary=action.summary())

    def _exec_press_home(self, action: Action) -> ExecutionResult:
        """按 Home 键。"""
        self.device.press("home")
        return ExecutionResult(success=True, action_summary=action.summary())

    def _exec_wait(self, action: Action) -> ExecutionResult:
        """等待操作。"""
        t = action.wait_time if action.wait_time > 0 else 2.0
        time.sleep(t)
        return ExecutionResult(success=True, action_summary=action.summary())

    # ==================== 工具方法 ====================

    def _build_selector(self, target=None) -> dict | None:
        """构建 uiauto2 selector 字典。"""
        if target is None:
            return None
        return target.to_selector()

    def _build_selector_with_wait(self, target=None) -> dict | None:
        """构建 selector 并等待控件出现。

        注意：uiauto2 的 .wait() RPC 方法有兼容性问题（-32002），
        某些选择器字段组合不支持（如 resourceId+className 同时使用等）。
        因此改用 .exists 轮询方式等待控件出现。
        """
        selector = self._build_selector(target)
        if selector is None:
            return None

        # 用 exists 轮询代替 wait() RPC（更兼容）
        import time as _time
        deadline = _time.time() + self.wait_timeout
        while _time.time() < deadline:
            try:
                elem = self.device(**selector)
                if elem.exists:
                    return selector
            except Exception:
                pass  # 忽略中间异常，继续轮询
            _time.sleep(0.5)

        # 等超时了也返回 selector，让 execute 本身去尝试操作并分类错误
        return selector

    @staticmethod
    def _format_target(target) -> str:
        if target is None:
            return "(无)"
        return target.summary()

    @staticmethod
    def _classify_error(exception: Exception) -> ExecutionStatus:
        """判断错误是否可重试。"""
        err_msg = str(exception).lower()
        retryable_keywords = [
            # 通用控件未找到
            "not found", "no matching", "timeout",
            "uiobject", "null", "cannot locate",
            # uiauto2 RPC 错误码（控件相关的一般都可重试）
            "-32002", "-32006", "-32001",
            "selector", "rpcerror", "jsonrpc error",
        ]
        if any(kw in err_msg for kw in retryable_keywords):
            return ExecutionStatus.RETRYABLE
        return ExecutionStatus.FATAL
