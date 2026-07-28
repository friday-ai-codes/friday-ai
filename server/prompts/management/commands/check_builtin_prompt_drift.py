"""检查存量 DB 的 builtin prompt 漂移。

fresh migrate 契约测试只能证明新库正确，无法发现长期运行实例停留在旧 active
version；本命令为部署后检查提供稳定的非零退出语义，并允许显式 append 修复。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from django.core.management.base import BaseCommand, CommandError, CommandParser

from prompts.builtin_contract import (
    BuiltinPromptDrift,
    detect_builtin_prompt_drift,
    resync_builtin_prompt_drift,
)

logger = structlog.get_logger(__name__)

_LOG_CONTEXT = {
    "category": "sampling",
    "component": "prompts",
    "user_id": "system",
    "initiated_by_user_id": "system",
}


def _safe_log(level: str, event: str, **fields: Any) -> None:
    """观测失败不能改变运维命令原本的退出码语义。"""
    try:
        getattr(logger, level)(event, **_LOG_CONTEXT, **fields)
    except Exception:
        pass


class Command(BaseCommand):
    help = (
        "检查 builtin prompt 的 DB active body 是否与 Python 字面量一致；"
        "fresh migrate 测试无法发现已部署实例的存量漂移"
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--fix",
            action="store_true",
            help="为漂移项 append 新版本并切换 active 指针",
        )

    def _write_drift(self, drift: list[BuiltinPromptDrift]) -> None:
        self.stdout.write(self.style.WARNING(f"检测到 {len(drift)} 个 builtin prompt 漂移："))
        for item in drift:
            self.stdout.write(
                "  - "
                f"{item['slug']} reason={item['reason']} "
                f"py_sha256={item['py_sha256']} db_sha256={item['db_sha256'] or '-'} "
                f"py_length={item['py_length']} db_length={item['db_length']}"
            )
            _safe_log(
                "warning",
                "builtin_prompt_drift_detected",
                slug=item["slug"],
                reason=item["reason"],
                py_sha256=item["py_sha256"],
                db_sha256=item["db_sha256"],
                py_length=item["py_length"],
                db_length=item["db_length"],
            )

    def handle(self, *args: Any, **options: Any) -> None:
        started = time.monotonic()
        _safe_log("info", "builtin_prompt_drift_check_started", fix=bool(options["fix"]))
        try:
            drift = detect_builtin_prompt_drift()
            fixed: list[str] = []
            if options["fix"] and drift:
                fixed = resync_builtin_prompt_drift([item["slug"] for item in drift])
                _safe_log(
                    "info",
                    "builtin_prompt_drift_fix_completed",
                    fixed_count=len(fixed),
                    slugs=fixed,
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                )
                drift = detect_builtin_prompt_drift()
        except Exception as exc:
            _safe_log(
                "error",
                "builtin_prompt_drift_check_failed",
                error_type=type(exc).__name__,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            raise

        duration_ms = round((time.monotonic() - started) * 1000, 2)
        if drift:
            self._write_drift(drift)
            _safe_log(
                "warning",
                "builtin_prompt_drift_check_completed",
                drift_count=len(drift),
                fixed_count=len(fixed),
                success=False,
                duration_ms=duration_ms,
            )
            raise CommandError(f"检测到 {len(drift)} 个 builtin prompt 漂移")

        self.stdout.write(self.style.SUCCESS("builtin prompt 零漂移"))
        _safe_log(
            "info",
            "builtin_prompt_drift_check_completed",
            drift_count=0,
            fixed_count=len(fixed),
            success=True,
            duration_ms=duration_ms,
        )
