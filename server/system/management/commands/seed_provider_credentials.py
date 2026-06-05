"""implementation: seed_provider_credentials —— 从 SystemSetting.ANTHROPIC_* 导入为一条 anthropic/system/default 凭证。

与 `server/system/migrations/0005_seed_provider_credentials.py` 共享
`system.data_migrations.seed_provider_credentials_impl`（单一事实源）。
"""

from __future__ import annotations

from typing import Any, cast

import structlog
from django.apps import apps as django_apps
from django.core.management.base import BaseCommand

from system.data_migrations import seed_provider_credentials_impl

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    """从 SystemSetting.ANTHROPIC_* 导入为一条 anthropic/system/default 凭证（幂等 + 可回滚 + dry-run）。"""

    help = (
        "从 SystemSetting.ANTHROPIC_* 导入为一条 anthropic/system/default 凭证"
        "（幂等 + 可回滚 + dry-run）"
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只打印将要执行的操作，不写库",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run: bool = bool(options.get("dry_run", False))
        # Django OutputWrapper 鸭子类型兼容 IO[str]（具备 write 方法），
        # 但 mypy 看到 class 签名不匹配。data_migrations 只调用 .write，所以
        # cast 到 Any 是与实际协议一致的最小类型放宽。
        result = seed_provider_credentials_impl(
            django_apps,
            dry_run=dry_run,
            stdout=cast(Any, self.stdout),
        )
        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"完成：{result}"))
