"""``_get_system_prompt`` detect_changes 条件追加守护（DIFF-03 / D-01/D-03/D-04）。

照抄 ``test_openspec_prompt.py``：MagicMock config + ``ClaudeRunner._get_system_prompt``。
归属 Plan 124-01。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from core.executor import ClaudeRunner


def _runner(
    *,
    follow_openspec: bool = False,
    knowledge_endpoint: str | None = "https://friday.example.com",
    user_token: str | None = "friday_pat_test",
    task_mode: str = "execute",
) -> ClaudeRunner:
    config = MagicMock()
    config.follow_openspec = follow_openspec
    config.knowledge_endpoint = knowledge_endpoint
    config.user_token = user_token
    config.task_mode = task_mode
    return ClaudeRunner(config, Path("/tmp"))


def test_prompt_appends_detect_changes_when_knowledge_plan() -> None:
    """knowledge_endpoint+user_token+task_mode=plan → 含 detect_changes/自查关键词（D-01/D-03）。"""
    prompt = _runner(task_mode="plan")._get_system_prompt()
    assert "detect_changes" in prompt
    assert "自查" in prompt or "影响面" in prompt
    assert "repository_id" in prompt
    assert "compare" in prompt


def test_prompt_appends_detect_changes_when_execute() -> None:
    """task_mode=execute 且 knowledge 挂载 → 追加自查指引。"""
    prompt = _runner(task_mode="execute")._get_system_prompt()
    assert "detect_changes" in prompt
    assert "base_ref" in prompt


def test_prompt_skips_when_explore_mode() -> None:
    """explore 模式不追加 detect_changes 指引。"""
    prompt = _runner(task_mode="explore")._get_system_prompt()
    assert "detect_changes" not in prompt


def test_prompt_skips_when_knowledge_missing() -> None:
    """缺 knowledge_endpoint 或 user_token 不追加。"""
    assert "detect_changes" not in _runner(knowledge_endpoint=None)._get_system_prompt()
    assert "detect_changes" not in _runner(user_token=None)._get_system_prompt()
    assert "detect_changes" not in _runner(knowledge_endpoint="", user_token="")._get_system_prompt()


def test_detect_changes_guidance_helper_independent() -> None:
    """独立 helper 非空静态文本（T-124-01）。"""
    guidance = _runner()._detect_changes_guidance()
    assert guidance
    assert "detect_changes" in guidance
    # 静态字面量：方法体不得用 f-string / format 拼外部变量（人工可读契约）。
    import inspect

    source = inspect.getsource(ClaudeRunner._detect_changes_guidance)
    assert "f\"" not in source and "f'" not in source
    assert ".format(" not in source


def test_guidance_non_blocking_language() -> None:
    """文案含「继续交付」/「不要因为」类非阻断语义（D-04）。"""
    guidance = _runner()._detect_changes_guidance()
    assert "继续交付" in guidance
    assert "不要因为" in guidance or "不要因" in guidance
    assert "HIGH" in guidance or "CRITICAL" in guidance


def test_openspec_and_detect_changes_can_coexist() -> None:
    """follow_openspec=True 且 knowledge 挂载 → openspec 与 detect_changes 两段都在。"""
    prompt = _runner(follow_openspec=True, task_mode="execute")._get_system_prompt()
    assert "openspec" in prompt
    assert "detect_changes" in prompt
    assert "已批准" in prompt
