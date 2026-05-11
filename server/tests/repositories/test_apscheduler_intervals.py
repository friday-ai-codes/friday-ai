"""：验证 poll_repository_updates 注册间隔为 2 小时（7200 秒）。
不需要启动 APScheduler，只检查命令代码中的触发器参数。
"""
import pathlib
def test_poll_interval_is_2_hours -> None:
 """静态 AST 解析确认 IntervalTrigger(hours=2)，不依赖运行时调度器。"""
 src = pathlib.Path("agents/management/commands/runapscheduler.py").read_text
 assert "IntervalTrigger(hours=2)" in src, (
 "runapscheduler.py 必须使用 IntervalTrigger(hours=2)"
 )
 assert "IntervalTrigger(minutes=30)" not in src, (
 "旧的 IntervalTrigger(minutes=30) 必须已被移除"
 )
def test_poll_interval_log_updated -> None:
 """确认日志字符串已同步更新。"""
 src = pathlib.Path("agents/management/commands/runapscheduler.py").read_text
 assert "every 2 hours" in src
def test_deploy_pitfall_comment_present -> None:
 """确认 Pitfall 4 deploy 注意事项注释已包含。"""
 src = pathlib.Path("agents/management/commands/runapscheduler.py").read_text
 assert "Deploy 注意" in src, "必须包含 Pitfall 4 deploy 注意事项注释（T- Tamper 缓解）"
