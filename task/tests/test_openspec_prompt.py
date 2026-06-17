"""_get_system_prompt openspec 条件追加守护（Phase 51-03，GATE-02 task 半，D-51-4/D-51-5）。

覆盖 <behavior>：
- follow_openspec=True → system_prompt 在 base 后追加 openspec 指引段（含 openspec / spec / 已批准 关键词）。
- follow_openspec=False/缺省 → system_prompt 与现状逐字一致（base 不变，零回归）。
"""

from pathlib import Path
from unittest.mock import MagicMock

from core.executor import ClaudeRunner


def _runner(follow_openspec: bool) -> ClaudeRunner:
    config = MagicMock()
    config.follow_openspec = follow_openspec
    return ClaudeRunner(config, Path("/tmp"))


def test_prompt_appends_openspec_when_true() -> None:
    """follow_openspec=True → prompt 含 openspec 指引段关键词。"""
    prompt = _runner(True)._get_system_prompt()
    assert "openspec" in prompt
    assert "spec" in prompt
    assert "已批准" in prompt


def test_prompt_unchanged_when_false() -> None:
    """follow_openspec=False → prompt 与 base 逐字一致（不含 openspec 段，零回归）。"""
    base = _runner(False)._get_system_prompt()
    appended = _runner(True)._get_system_prompt()
    # base 不含 openspec 指引段。
    assert "openspec" not in base
    # True 路径 = base + "\n\n" + openspec 段（base 逐字前缀）。
    assert appended.startswith(base + "\n\n")


def test_openspec_guidance_helper_independent() -> None:
    """openspec 指引段经独立 helper 暴露，便于测试（D-51-4）。"""
    guidance = _runner(True)._openspec_guidance()
    assert "openspec" in guidance
    assert guidance  # 非空
