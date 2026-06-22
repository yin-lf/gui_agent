"""
雷电模拟器 uiautomator2 手动初始化脚本。
解决 python -m uiautomator2 init 在雷电上报 INSTALL_FAILED_MEDIA_UNAVAILABLE 的问题。
原理：跳过 IME（输入法）安装，只安装核心的两个 APK。

使用方法：
    1. 先确认 adb 能连上模拟器: adb connect 127.0.0.1:5555
    2. 运行本脚本: python init_u2_for_ldplayer.py
"""

import os
import sys
import subprocess
import tempfile
import shutil
import urllib.request
import urllib.error
import ssl
import json
import time

# ============ 配置区（按实际情况修改）============
# 如果 "adb" 不在 PATH 里，改成完整路径如 r"D:\leidian\LDPlayer9\adb.exe"
ADB = "adb"
DEVICE = "127.0.0.1:5555"
# ===============================================


def log(msg):
    print(f"  {msg}")


def run_adb(args, check=True):
    """执行adb命令，返回stdout"""
    cmd = [ADB, "-s", DEVICE] + args
    cmd_str = " ".join(cmd)
    log(f"执行: {cmd_str}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, encoding="utf-8")
    except subprocess.TimeoutExpired:
        log("❌ 命令超时(30s)")
        return ""
    except FileNotFoundError:
        log(f"❌ 找不到 adb 命令！请将 ADB 改为完整路径")
        sys.exit(1)

    if result.stdout.strip():
        for line in result.stdout.strip().split("\n")[:5]:
            log(f"→ {line}")
    if result.returncode != 0 and check:
        err = result.stderr.strip()[:200] if result.stderr else "(无stderr)"
        log(f"⚠️ 返回码={result.returncode}, stderr: {err}")
    return result.stdout


def download_file(url, dest_path):
    """用Python下载文件（绕过Windows curl证书问题）"""
    log(f"下载: {url}")
    # 创建SSL上下文（跳过证书验证，仅用于下载可信资源）
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest_path, "wb") as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = downloaded * 100 // total
                        print(f"\r  进度: {pct}% ({downloaded//1024}KB/{total//1024}KB)", end="", flush=True)
            print()  # 换行
        size_kb = os.path.getsize(dest_path) // 1024
        log(f"✅ 下载完成 ({size_kb}KB)")
        return True
    except Exception as e:
        log(f"❌ 下载失败: {e}")
        return False


def get_pip_cache_apk(name):
    """尝试从 pip 安装的 uiautomator2 包中找到预编译的 APK"""
    import uiautomator2 as u2_pkg
    pkg_dir = os.path.dirname(u2_pkg.__file__)

    # 搜索 APK 文件
    for root, dirs, files in os.walk(pkg_dir):
        for f in files:
            if f.endswith(".apk") and name in f.lower():
                return os.path.join(root, f)
    return None


def main():
    print("=" * 55)
    print("  雷电模拟器 uiautomator2 手动初始化工具")
    print("  (跳过 IME 安装，只安装核心组件)")
    print("=" * 55)

    tmpdir = tempfile.mkdtemp(prefix="u2_ld_")

    try:
        # ---- Step 1: 验证设备连接 ----
        print("\n[1/6] 检查设备连接...")
        serial = run_adb(["get-serialno"]).strip()
        if not serial or "error" in serial.lower():
            print(f"\n❌ 设备未连接！请先执行:")
            print(f"   {ADB} connect {DEVICE}")
            sys.exit(1)
        log(f"✅ 设备在线: {serial}")

        # ---- Step 2: 检查已安装组件 ----
        print("\n[2/6] 检查已安装组件...")
        pkg_list = run_adb(["shell", "pm", "list", "packages", "-3"])
        has_atx = "com.github.uiautomator" in pkg_list
        has_test = "com.github.uiautomator.test" in pkg_list
        log(f"atx-agent (主程序):     {'✅ 已安装' if has_atx else '❌ 未安装'}")
        log(f"test-app (测试应用):   {'✅ 已安装' if has_test else '❌ 未安装'}")
        log(f"IME (输入法):          ⏭️  跳过 (雷电不兼容)")

        # ---- Step 3: 获取或下载 APK ----
        print("\n[3/6] 准备 APK 文件...")

        test_apk_path = os.path.join(tmpdir, "uiautomator.apk")
        atx_apk_path = os.path.join(tmpdir, "atx-agent.apk")

        # 尝试从 uiautomator2 包内获取（最快）
        cached_test = get_pip_cache_apk("uiautomator")
        if cached_test and not has_test:
            shutil.copy2(cached_test, test_apk_path)
            log(f"从本地缓存复制 test-apk")
        elif not has_test:
            # 从 GitHub releases 下载（备用地址）
            url = "https://github.com/openatx/uiautomator2/releases/download/v2.17.0/uiautomator.apk"
            if not download_file(url, test_apk_path):
                log("⚠️ 无法下载 test-apk，将尝试其他方式")

        cached_atx = get_pip_cache_apk("atx-agent")
        if cached_atx and not has_atx:
            shutil.copy2(cached_atx, atx_apk_path)
            log(f"从本地缓存复制 atx-agent")
        elif not has_atx:
            # atx-agent 是平台相关的二进制，需要匹配架构
            # 先检查设备架构
            arch = run_adb(["shell", "getprop", "ro.product.cpu.abi"]).strip()
            log(f"设备CPU架构: {arch or '(未知)'}")

            # 模拟器通常是 x86/x86_64，真机是 arm
            arch_lower = (arch or "").lower()
            if "x86_64" in arch_lower or "x86-64" in arch_lower:
                arch_suffix = "linux_x86_64"
            elif "x86" in arch_lower:
                arch_suffix = "linux_x86"
            elif "arm64" in arch_lower or "aarch64" in arch_lower:
                arch_suffix = "linux_arm64-v8a"
            elif "armeabi" in arch_lower or "arm" in arch_lower:
                arch_suffix = "linux_armv7"
            else:
                arch_suffix = "linux_x86_64"  # 模拟器默认

            url = f"https://github.com/openatx/atx-agent/releases/download/v2.3.5/atx-agent_{arch_suffix}.apk"
            if not download_file(url, atx_apk_path):
                log("⚠️ 无法下载 atx-agent apk")

        # ---- Step 4: 安装 ----
        print("\n[4/6] 安装组件到模拟器...")

        install_flags = ["install", "-r", "-g"]

        if not has_test and os.path.exists(test_apk_path):
            log(f"安装 test-app...")
            run_adb(install_flags + [test_apk_path], check=False)
        elif not has_test:
            log("⚠️ test-apk 不存在且未安装，尝试让 uiauto2 内部处理...")

        if not has_atx and os.path.exists(atx_apk_path):
            log(f"安装 atx-agent...")
            run_adb(install_flags + [atx_apk_path], check=False)
        elif not has_atx:
            log("⚠️ atx-agent apk 不存在且未安装")

        # ---- Step 5: 启动服务 ----
        print("\n[5/6] 启动 ATX Agent 服务...")
        run_adb(["shell", "am", "startservice", "-n", "com.github.uiautomator/.Service"], check=False)
        time.sleep(3)

        # ---- Step 6: 验证 ----
        print("\n[6/6] 最终验证...")

        # 检查安装结果（列出所有第三方包方便排查）
        pkg_list_after = run_adb(["shell", "pm", "list", "packages", "-3"])
        has_atx_ok = "com.github.uiautomator" in pkg_list_after
        # test-app 可能叫不同名字，用模糊匹配
        has_test_ok = any("uiautomator" in p and ("test" in p.lower() or "apk" in p.lower())
                          for p in pkg_list_after.splitlines() if p.strip())

        log(f"atx-agent (com.github.uiautomator): {'✅' if has_atx_ok else '❌'}")
        log(f"test-app (含uiautomator+test/apk):  {'✅' if has_test_ok else '❌'}")
        if not has_test_ok:
            log("  已安装的uiautomator相关包:")
            for line in pkg_list_after.splitlines():
                if "uiautomator" in line.lower():
                    log(f"    {line.strip()}")

        # 尝试通过 HTTP 连接 ATX Agent
        log("尝试连接 ATX Agent HTTP 服务...")
        http_ok = False
        try:
            req = urllib.request.Request(f"http://{DEVICE}:7912/version", timeout=5)
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            resp = urllib.request.urlopen(req, timeout=5, context=ctx)
            version = resp.read().decode().strip()
            log(f"ATX Agent 版本: {version}")
            http_ok = True
        except urllib.error.URLError as e:
            log(f"ATX Agent HTTP 未响应 ({e.reason})")
            log("  首次启动可能需要10-30秒，请稍后重试")
        except Exception as e:
            log(f"ATX Agent HTTP 未响应 ({type(e).__name__}: {e})")
            log("  这可能正常，首次启动需要较长时间")

        # 结果汇总
        print("\n" + "=" * 55)
        all_ok = has_atx_ok and has_test_ok
        if all_ok:
            print("  ✅ 核心组件安装成功！")
            print("=" * 55)
            print()
            print("  接下来验证 Python 连接:")
            print('    python -c "import uiautomator2 as u2; d=u2.connect(\'127.0.0.1:5555\'); print(d.info)"')
            print()
            print("  如果上面报错，再试:")
            print('    python -c "import uiautomator2 as u2; d=u2.connect_usb(); print(d.info)"')
        else:
            print("  ⚠️ 部分组件可能未成功安装")
            print("  建议:")
            print("  1. 雷电设置 → 开启 Root 权限")
            print("  2. 重启模拟器后重新运行此脚本")
        print("=" * 55)

    finally:
        # 清理临时文件
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
