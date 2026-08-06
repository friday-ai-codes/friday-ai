"""蓝图标题派生（展示与新建缺省共用）。

模板：``{project_name} - 技术方案 - YYYY-MM-DD HH:mm``（Asia/Shanghai 墙钟）。
项目名为空 / 缺失时前缀为「未关联项目」。时间一律按 artifact 创建时刻格式化。
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

__all__ = ["format_blueprint_title", "FALLBACK_PROJECT_NAME"]

FALLBACK_PROJECT_NAME = "未关联项目"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TITLE_SUFFIX = "技术方案"


def format_blueprint_title(project_name: str | None, when: datetime | None) -> str:
    """派生标准蓝图标题。

    ``when`` 缺失时用 ``timezone.now()``；naive datetime 按当前默认时区补齐再转上海。
    """
    name = str(project_name or "").strip() or FALLBACK_PROJECT_NAME
    moment = when if when is not None else timezone.now()
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment, timezone.get_current_timezone())
    local = timezone.localtime(moment, _SHANGHAI)
    return f"{name} - {_TITLE_SUFFIX} - {local.strftime('%Y-%m-%d %H:%M')}"
