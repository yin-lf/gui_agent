"""屏幕状态感知：截图 + 控件树获取，基于 uiautomator2。"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class ScreenState:
    """一次屏幕采样的完整状态。"""
    hierarchy_xml: str = ""          # 完整控件树 XML
    screenshot_path: Optional[str] = None  # 截图保存路径
    timestamp: float = 0.0           # 采样时间戳
    current_package: Optional[str] = None   # 当前前台App包名
    current_activity: Optional[str] = None  # 当前Activity

    @property
    def xml_size(self) -> int:
        return len(self.hierarchy_xml)


class ScreenCaptor:
    """屏幕状态采集器，封装 uiautomator2 的截图和控件树获取。"""

    def __init__(self, device, screenshot_dir: str | None = None):
        """
        Args:
            device: uiautomator2.Device 实例
            screenshot_dir: 截图保存目录，默认为 ./screenshots/
        """
        self.device = device
        if screenshot_dir is None:
            screenshot_dir = os.path.join(os.path.dirname(__file__), "screenshots")
        self.screenshot_dir = screenshot_dir
        os.makedirs(self.screenshot_dir, exist_ok=True)
        self._screenshot_counter = 0

    def capture(self, screenshot: bool = True) -> ScreenState:
        """
        采集当前屏幕状态（控件树 + 可选截图）。

        Returns:
            ScreenState: 包含控件树 XML 和截图路径
        """
        state = ScreenState(timestamp=time.time())

        # 获取控件树
        try:
            state.hierarchy_xml = self.device.dump_hierarchy()
        except Exception as e:
            state.hierarchy_xml = f"<error>获取控件树失败: {e}</error>"

        # 获取当前 App 信息
        try:
            info = self.device.info
            state.current_package = info.get("currentPackageName")
            state.current_activity = info.get("currentActivity")
        except Exception:
            pass

        # 截图
        if screenshot:
            try:
                self._screenshot_counter += 1
                filename = f"screen_{self._screenshot_counter:04d}_{int(state.timestamp)}.png"
                filepath = os.path.join(self.screenshot_dir, filename)
                self.device.screenshot(filepath)
                state.screenshot_path = filepath
            except Exception as e:
                print(f"⚠️  截图失败：{e}")

        return state

    def wait_for_change(
        self,
        timeout: float = 10.0,
        interval: float = 0.5,
        old_state: ScreenState | None = None,
    ) -> ScreenState | None:
        """
        等待屏幕发生变化（控件树改变或页面跳转）。

        Args:
            timeout: 最大等待时间(秒)
            interval: 检查间隔(秒)
            old_state: 上一次的屏幕状态，如果为None则用当前状态作为基准

        Returns:
            变化后的新 ScreenState，超时返回 None
        """
        if old_state is None:
            old_state = self.capture(screenshot=False)

        deadline = time.time() + timeout
        while time.time() < deadline:
            new_state = self.capture(screenshot=False)
            # 判断是否变化：包名/Activity变了 或 控件树内容变了
            if (new_state.current_package != old_state.current_package or
                new_state.current_activity != old_state.current_activity or
                new_state.hierarchy_xml != old_state.hierarchy_xml):
                return self.capture(screenshot=True)  # 变化了，重新带截图采集
            time.sleep(interval)

        print(f"⏳ 等待屏幕变化超时 ({timeout}s)")
        return None

    def get_current_app_name(self) -> str:
        """获取当前前台 App 的可读名称。"""
        try:
            pkg = self.device.info.get("currentPackageName", "")
            # 常见映射
            app_names = {
                "com.tencent.mm": "微信",
                "com.alibaba.android.rimet": "钉钉",
                "com.sina.weibo": "微博",
                "com.qiyi.video": "爱奇艺",
                "com.netease.cloudmusic": "网易云音乐",
                "com.tencent.qqmusic": "QQ音乐",
                "com.kugou.android": "酷狗音乐",
                "com.meituan.takeoutnew": "美团外卖",
                "com.meituan.app": "美团",
                "com.ele.me": "饿了么",
                "com.ctrip.viewhotel": "携程旅行",
                "android": "系统",
            }
            return app_names.get(pkg, pkg)
        except Exception:
            return "未知"
