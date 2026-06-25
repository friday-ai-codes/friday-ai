"""implementation Hotfix（work item）：v8.1 Space.claude_api_key_encrypted 残留预检命令。

运行时机：`projects.migrations.0009_remove_v81_legacy_claude_fields` 执行**之前**
（release checklist 强制）。

用途：报告有多少 Space 行的 `claude_api_key_encrypted` 非空 —— 这些行会在
      migration 后字段被删除而历史凭证丢失（contract-work item Denial of Service + Tampering）。

典型输出：
    $ python manage.py check_v81_legacy_residue
    [check_v81_legacy_residue] 零残留；0009 migration 可安全执行

或：
    $ python manage.py check_v81_legacy_residue
    [check_v81_legacy_residue] 检测到 3 个 Space 有残留数据：
      - 11111111-...  name=proj-foo
      - 22222222-...  name=proj-bar
      - 33333333-...  name=proj-baz
    执行 migrate 前请先为上述项目在 /admin/providers 或
    /projects/<id>/providers 手动创建 anthropic 凭证，否则历史 API key 将丢失

或（已 migrate 后）：
    $ python manage.py check_v81_legacy_residue
    [check_v81_legacy_residue] 该环境已完成 0009 migration（...）；预检无需执行

实现要点：
  - 走 raw SQL via `connection.cursor()`，不用 ORM（0009 apply 后 Space model
    不再声明 claude_api_key_encrypted 字段，`Space.objects.filter(...)` 会
    AttributeError；Pitfall 5）
  - try/except OperationalError 捕获列不存在错误 → 优雅输出 "已 migrate" 而非 crash
  - 参数全硬编码，无 SQL 注入面（A4 LOW risk）
"""

from __future__ import annotations

from typing import Any

import structlog
from django.core.management.base import BaseCommand
from django.db import OperationalError, connection

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    """v8.1 Space.claude_api_key_encrypted 残留预检（implementation Hotfix work-item item）。"""

    help = (
        "检查 v8.1 遗留 Space.claude_api_key_encrypted 残留数据 —— "
        "在执行 projects.0009 migration 之前运行；若 residue > 0 需先为残留项目手动"
        "添加 ProviderCredential，否则 migrate 会静默丢失凭证"
    )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT id, name FROM projects "
                    "WHERE claude_api_key_encrypted IS NOT NULL "
                    "AND claude_api_key_encrypted != ''"
                )
                rows = cur.fetchall()
        except OperationalError as exc:
            # Pitfall 5：0009 已 apply 时 claude_api_key_encrypted 列已删 → 优雅输出
            self.stdout.write(
                self.style.SUCCESS(
                    f"[check_v81_legacy_residue] 该环境已完成 0009 migration（{exc}）；"
                    "预检无需执行"
                )
            )
            return

        if not rows:
            self.stdout.write(
                self.style.SUCCESS(
                    "[check_v81_legacy_residue] 零残留；0009 migration 可安全执行"
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"[check_v81_legacy_residue] 检测到 {len(rows)} 个 Space 有残留数据："
            )
        )
        for pid, pname in rows:
            self.stdout.write(f"  - {pid}  name={pname}")
        self.stdout.write(
            self.style.ERROR(
                "执行 migrate 前请先为上述项目在 /admin/providers 或 "
                "/projects/<id>/providers 手动创建 anthropic 凭证，"
                "否则历史 API key 将丢失"
            )
        )
