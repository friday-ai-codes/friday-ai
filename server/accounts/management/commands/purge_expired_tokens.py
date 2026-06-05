"""清理已过期的 JWT Token 黑名单记录。

定期执行此命令防止 OutstandingToken 和 BlacklistedToken 表膨胀。
用法: python manage.py purge_expired_tokens
"""

import structlog
from django.core.management.base import BaseCommand
from rest_framework_simplejwt.token_blacklist.management.commands.flushexpiredtokens import (
    Command as FlushCommand,
)

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    """清理已过期的 JWT Token 黑名单记录（防止表膨胀）。"""

    help = "清理已过期的 JWT Token 黑名单记录（防止表膨胀）"

    def handle(self, *args: object, **options: object) -> None:
        flush = FlushCommand()
        flush.handle(*args, **options)
        logger.info("expired_tokens_purged")
        self.stdout.write(self.style.SUCCESS("过期 Token 记录已清理"))
