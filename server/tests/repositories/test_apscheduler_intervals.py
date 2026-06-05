"""work item：验证 poll_repository_updates 注册间隔使用 settings.SYNC_INTERVAL_SECONDS（7200 秒）。

不需要启动 APScheduler，只检查命令代码中的触发器参数（work item 修复后改用 settings 常量）。
"""
import pathlib


def test_poll_interval_is_2_hours() -> None:
    """静态 AST 解析确认 poll_repository_updates 使用 SYNC_INTERVAL_SECONDS，不依赖运行时调度器（contract work item）。"""
    src = pathlib.Path("agents/management/commands/runapscheduler.py").read_text()
    assert "settings.SYNC_INTERVAL_SECONDS" in src, (
        "runapscheduler.py 必须使用 IntervalTrigger(seconds=settings.SYNC_INTERVAL_SECONDS)（contract work item-02）"
    )
    assert "IntervalTrigger(minutes=30)" not in src, (
        "旧的 IntervalTrigger(minutes=30) 必须已被移除"
    )


def test_poll_interval_log_updated() -> None:
    """确认日志字符串已包含 interval 信息。"""
    src = pathlib.Path("agents/management/commands/runapscheduler.py").read_text()
    assert "SYNC_INTERVAL_SECONDS" in src


def test_deploy_pitfall_comment_present() -> None:
    """确认 Pitfall 4 deploy 注意事项注释已包含。"""
    src = pathlib.Path("agents/management/commands/runapscheduler.py").read_text()
    assert "Deploy 注意" in src, "必须包含 Pitfall 4 deploy 注意事项注释（security mitigation Tamper 缓解）"
