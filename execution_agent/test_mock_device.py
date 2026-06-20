"""Mock uiautomator2 Device 对象，用于无设备时测试执行层。"""

class MockElement:
    """模拟 uiauto2 的 UiObject。"""
    def __init__(self, exists=True):
        self._exists = exists
        self._text = ""
        self._clicked = False
        self._input_text = ""

    def click(self, timeout=10):
        if not self._exists:
            raise UiObjectNotFoundError(f"控件不存在")
        self._clicked = True

    def set_text(self, text, timeout=10):
        if not self._exists:
            raise UiObjectNotFoundError(f"输入框不存在")
        self._input_text = text

    def long_click(self, timeout=10):
        if not self._exists:
            raise UiObjectNotFoundError(f"控件不存在")

    def scroll(self, timeout=10):
        pass

    @property
    def exists(self):
        return self._exists


class MockSelector:
    """模拟 uiauto2 的选择器链式调用。"""
    def __init__(self, exists=True):
        self._exists = exists
        self._kwargs = {}
        self._last_op = None

    def __call__(self, **kwargs):
        self._kwargs = kwargs
        return self  # 返回自身以支持链式 .click()/.set_text()

    def click(self, timeout=10):
        if not self._exists:
            raise UiObjectNotFoundError(f"控件不存在 (kwargs={self._kwargs})")
        self._last_op = {"op": "click", "kwargs": self._kwargs}

    def set_text(self, text, timeout=10):
        if not self._exists:
            raise UiObjectNotFoundError(f"控件不存在 (kwargs={self._kwargs})")
        self._last_op = {"op": "set_text", "kwargs": {**self._kwargs, "text": text}}

    def long_click(self, timeout=10):
        if not self._exists:
            raise UiObjectNotFoundError(f"控件不存在")
        self._last_op = {"op": "long_click", "kwargs": self._kwargs}

    def scroll(self, timeout=10):
        self._last_op = {"op": "scroll", "kwargs": self._kwargs}

    @property
    def exists(self):
        return self._exists

    def wait(self, timeout=10):
        return self


class UiObjectNotFoundError(Exception):
    pass


class MockDevice:
    """模拟 uiautomator2.Device，记录所有操作调用。"""

    def __init__(self, control_exists=True):
        self.control_exists = control_exists
        self.operations = []
        self._current_pkg = "com.tencent.qqmusic"
        self._current_activity = ".activity.MainActivity"
        self._last_selector = None

    def __call__(self, **kwargs):
        """返回 MockSelector，支持 device(**selector).click() 链式调用。"""
        sel = MockSelector(exists=self.control_exists)
        self._last_selector = sel
        return sel

    # === 直接调用方式（press/swipe/screenshot 等）===
    def swipe_ext(self, direction="up"):
        self.operations.append({"op": "swipe_ext", "kwargs": {"direction": direction}})

    def press(self, key):
        self.operations.append({"op": "press", "kwargs": {"key": key}})

    def screenshot(self, path):
        self.operations.append({"op": "screenshot", "kwargs": {"path": path}})

    # === 状态查询 ===
    @property
    def info(self):
        return {
            "currentPackageName": self._current_pkg,
            "currentActivity": self._current_activity,
            "screenWidth": 1080,
            "screenHeight": 2340,
        }

    def dump_hierarchy(self):
        """返回一个简化的 QQ音乐搜索页控件树 XML。"""
        return '''<hierarchy>
  <node text="QQ音乐" resource-id="com.tencent.qqmusic:id/title_bar_title"
        class="android.widget.TextView" bounds="[0,40,200,80]"
        clickable="false" scrollable="false" checkable="false"/>
  <node text="" resource-id="com.tencent.qqmusic:id/search_input"
        class="android.widget.EditText" bounds="[120,90,880,140]"
        clickable="true" scrollable="false" checkable="false"/>
  <node text="" resource-id="com.tencent.qqmusic:id/search_btn"
        class="android.widget.ImageView" bounds="[900,95,960,135]"
        clickable="true" scrollable="false" checkable="false"/>
  <node text="推荐" class="android.widget.TextView" bounds="[50,160,120,190]"
        clickable="true" scrollable="false" checkable="false"/>
  <node text="热歌榜" class="android.widget.TextView" bounds="[150,160,250,190]"
        clickable="true" scrollable="false" checkable="false"/>
  <node text="新歌榜" class="android.widget.TextView" bounds="[270,160,370,190]"
        clickable="true" scrollable="false" checkable="false"/>
</hierarchy>'''

    def set_current_app(self, pkg, activity):
        """测试辅助：切换当前App。"""
        self._current_pkg = pkg
        self._current_activity = activity

    def get_op_log(self) -> list:
        """获取操作日志。"""
        return self.operations

    def clear_ops(self):
        self.operations = []
