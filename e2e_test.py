"""
端到端测试：推理层 + 执行层 完整链路验证
场景：用网易云音乐播放周杰伦的《夜曲》

使用方法：
    1. 确保 DEEPSEEK_API_KEY 已设置: set DEEPSEEK_API_KEY=sk-xxx
    2. 雷电模拟器已启动且 adb connect 成功
    3. 模拟器中已安装网易云音乐
    4. 运行: python e2e_test.py
"""

import os
import sys
import json
import time

# 确保项目目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    print("=" * 60)
    print("  GUI Agent 端到端测试")
    print("  场景：网易云音乐播放《夜曲》")
    print("=" * 60)

    # ==================== 阶段1：连接设备 ====================
    print("\n[阶段1] 连接设备...")
    import uiautomator2 as u2

    device = u2.connect("127.0.0.1:5555")
    info = device.info
    print(f"  ✅ 设备连接成功")
    print(f"     分辨率: {info['displayWidth']}x{info['displayHeight']}")
    print(f"     Android: SDK {info['sdkInt']}")
    print(f"     当前App: {info['currentPackageName']}")

    # 确保截图目录存在
    screenshot_dir = os.path.join(os.path.dirname(__file__), "execution_agent", "screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)

    # 截一张初始屏幕
    device.screenshot(os.path.join(screenshot_dir, "e2e_00_initial.png"))
    print("  ✅ 初始截图已保存")

    # ==================== 阶段2：推理层生成 TaskTree ====================
    print("\n[阶段2] 推理层：任务分解...")
    from agent_reasoner.llm_client import LLMClient
    from agent_reasoner.main import run as run_reasoner

    llm = LLMClient()
    print("  LLM 客户端初始化完成")

    # 直接调用推理层（会触发 Skill 检测 → HITL → Planner）
    instruction = "帮我用网易云音乐播放周杰伦的《夜曲》"
    print(f"  用户指令: {instruction}")

    # 注意：run() 默认从终端读取输入，这里传入 instruction 参数
    task_tree_dict = run_reasoner(instruction)
    print(f"  ✅ TaskTree 生成完成，共 {len(task_tree_dict.get('tasks', task_tree_dict))} 个子任务")

    # 保存推理结果
    output_path = os.path.join(os.path.dirname(__file__), "execution_agent", "output", "e2e_task_tree.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(task_tree_dict, f, indent=2, ensure_ascii=False)
    print(f"  ✅ TaskTree 已保存: {output_path}")

    # 打印 TaskTree 内容
    print("\n  生成的任务树:")
    tasks_data = task_tree_dict.get("tasks", list(task_tree_dict.values()))
    for t in tasks_data:
        deps = t.get("dependencies", [])
        dep_str = f" (依赖 {', '.join(deps)})" if deps else ""
        print(f"    [{t['id']}] {t['name']}{dep_str}")

    # ==================== 阶段3：执行层执行 ====================
    print("\n[阶段3] 执行层：在模拟器上执行...")
    from execution_agent.app_agent import AppAgent

    agent = AppAgent(device, llm)

    start_time = time.time()
    report = agent.execute_task_tree_from_dict(task_tree_dict)
    elapsed = time.time() - start_time

    # ==================== 结果汇总 ====================
    print("\n" + "=" * 60)
    print("  测试结果汇总")
    print("=" * 60)
    summary = report["summary"]
    print(f"  总任务数:   {summary['total']}")
    print(f"  成功:       {summary['completed']}")
    print(f"  失败:       {summary['failed']}")
    if summary["failed_ids"]:
        print(f"  失败ID:     {', '.join(summary['failed_ids'])}")
    print(f"  总耗时:     {elapsed:.1f}秒")
    print(f"  操作日志条数: {len(report['execution_log'])}")

    print("\n  各任务详情:")
    for tid, tinfo in report["tasks"].items():
        status_icon = "✅" if tinfo["status"] == "completed" else "❌"
        print(f"    {status_icon} [{tid}] {tinfo['name']} → {tinfo['status']}")
        if tinfo.get("error"):
            print(f"         错误: {tinfo['error']}")

    if report["execution_log"]:
        print("\n  操作日志:")
        for i, log in enumerate(report["execution_log"]):
            icon = "✅" if log["success"] else "❌"
            print(f"    {i+1}. {icon} [{log['task_name'][:12]}] {log['action']}"
                  f" (retry={log['retry_count']})")

    # 最终截图
    final_screenshot = os.path.join(os.path.dirname(__file__), "execution_agent", "screenshots", "e2e_final.png")
    device.screenshot(final_screenshot)
    print(f"\n  📸 最终截图已保存: {final_screenshot}")

    # 保存完整报告
    report_path = os.path.join(os.path.dirname(__file__), "execution_agent", "output", "e2e_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"  📄 完整报告已保存: {report_path}")

    print("\n" + "=" * 60)
    if summary["failed"] == 0:
        print("  🎉 端到端测试全部通过！")
    else:
        print(f"  ⚠️ 有 {summary['failed']} 个任务失败，请查看上方错误信息")
    print("=" * 60)

    return report


if __name__ == "__main__":
    main()
