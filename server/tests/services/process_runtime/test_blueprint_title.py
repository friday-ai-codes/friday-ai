"""format_blueprint_title 纯函数契约（quick 260806-d9y）。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from services.process_runtime.blueprint_title import FALLBACK_PROJECT_NAME, format_blueprint_title

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_format_blueprint_title_uses_shanghai_wall_clock() -> None:
    # 2026-08-06 01:33 UTC → 上海 09:33
    when = datetime(2026, 8, 6, 1, 33, tzinfo=ZoneInfo("UTC"))
    assert format_blueprint_title("高三提分专项", when) == "高三提分专项 - 技术方案 - 2026-08-06 09:33"


@pytest.mark.parametrize("name", ["", None, "   "])
def test_format_blueprint_title_falls_back_for_empty_project_name(name: str | None) -> None:
    when = datetime(2026, 8, 6, 1, 33, tzinfo=ZoneInfo("UTC"))
    assert format_blueprint_title(name, when) == f"{FALLBACK_PROJECT_NAME} - 技术方案 - 2026-08-06 09:33"


def test_format_blueprint_title_uses_now_when_when_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = datetime(2026, 8, 6, 1, 33, tzinfo=ZoneInfo("UTC"))
    monkeypatch.setattr(timezone, "now", lambda: fixed)
    assert format_blueprint_title("项目A", None) == "项目A - 技术方案 - 2026-08-06 09:33"


def test_format_blueprint_title_accepts_naive_datetime() -> None:
    # naive 按 Django 当前时区（Asia/Shanghai）解释
    when = datetime(2026, 8, 6, 9, 33)
    result = format_blueprint_title("项目B", when)
    assert result.endswith(" - 技术方案 - 2026-08-06 09:33")
    assert result.startswith("项目B")
