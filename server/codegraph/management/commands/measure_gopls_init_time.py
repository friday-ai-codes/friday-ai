"""测量 gopls 初始化耗时（work item 90s 实战门 / 60s stretch advisory）。

per work item / work item
==================

- **work item 实战门（硬卡）**：``init_time_ms < 90000``（90s）
- **Stretch advisory**：``init_time_ms < 60000``（60s）；不阻塞 phase 完成

CLI 用例
========

::

    python manage.py measure_gopls_init_time \\
        --repo-root=/path/to/go-repo \\
        --output-json=/tmp/gopls_init_report.json

    # 如本地未装 gopls，advisory skip（exit 0）：
    python manage.py measure_gopls_init_time \\
        --repo-root=/tmp/non_existent --skip-on-missing-binary
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any, Final

import structlog
from django.core.management.base import BaseCommand

logger = structlog.get_logger(__name__)

_EVENT_GOPLS_INIT_MEASURED: Final[str] = "gopls_init_measured"

# 实战门（90s） / stretch advisory（60s）
_GATE_MS: Final[int] = 90_000
_STRETCH_MS: Final[int] = 60_000


class Command(BaseCommand):
    """gopls 初始化耗时测量命令。"""

    help = "测量 gopls 初始化耗时（work item：90s 实战门 / 60s stretch advisory）"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--repo-root",
            type=str,
            required=True,
            help="样本仓库绝对路径（需含 go.mod）",
        )
        parser.add_argument(
            "--output-json",
            type=str,
            default="/tmp/gopls_init_report.json",
            help="JSON 报告输出路径（默认 /tmp/gopls_init_report.json）",
        )
        parser.add_argument(
            "--skip-on-missing-binary",
            action="store_true",
            default=True,
            help="gopls binary 缺失时 advisory skip exit 0（CI 友好；默认开启）",
        )
        parser.add_argument(
            "--timeout-seconds",
            type=float,
            default=120.0,
            help="gopls 初始化 + ping 总超时秒数（默认 120s；大仓库需 buffer）",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # gopls binary 检测
        if shutil.which("gopls") is None:
            if options.get("skip_on_missing_binary", True):
                self.stdout.write(
                    "gopls binary 未装，跳过测量（advisory）。"
                    "安装：go install golang.org/x/tools/gopls@latest"
                )
                return
            self.stderr.write("gopls binary 未在 PATH，且 --skip-on-missing-binary 未开启。")
            raise SystemExit(1)

        repo_root = Path(options["repo_root"])
        output_json = Path(options["output_json"])
        timeout_seconds: float = options["timeout_seconds"]

        report = self._measure(repo_root=repo_root, timeout_seconds=timeout_seconds)

        # 写 JSON 报告
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        self.stdout.write(json.dumps(report, indent=2, ensure_ascii=False))

        init_ms: int = report["init_time_ms"]
        passed: bool = init_ms < _GATE_MS
        stretch_passed: bool = init_ms < _STRETCH_MS

        logger.info(
            _EVENT_GOPLS_INIT_MEASURED,
            init_time_ms=init_ms,
            workspace_symbol_count=report["workspace_symbol_count"],
            gopls_version=report.get("gopls_version"),
            go_version=report.get("go_version"),
            sample_repo=str(repo_root),
            passed=passed,
            stretch_passed=stretch_passed,
        )

        if not passed:
            self.stderr.write(
                f"实战门未通过：init_time_ms={init_ms}ms（要求 < {_GATE_MS}ms = 90s）\n"
                "调优建议：LSP_STARTUP_TIMEOUT_SECONDS=120 + 检查 gopls 版本 ≥ 0.14"
            )
            raise SystemExit(1)

        if not stretch_passed:
            self.stderr.write(
                f"Stretch advisory：init_time_ms={init_ms}ms"
                f"（目标 < {_STRETCH_MS}ms = 60s；不阻塞 phase）"
            )

    def _measure(self, *, repo_root: Path, timeout_seconds: float) -> dict[str, Any]:
        """执行 gopls 初始化计时并返回 JSON 报告 dict。"""
        from codegraph.lsp.go_check import check_go_runtime
        from codegraph.lsp.go_workspace import discover_go_workspace
        from codegraph.lsp.gopls_backend import _GoplsLazyBackend
        from codegraph.lsp.supervisor import LspSupervisor

        check_result = check_go_runtime()
        if not check_result.available:
            return {
                "init_time_ms": -1,
                "workspace_symbol_count": 0,
                "gopls_version": check_result.gopls_version,
                "go_version": check_result.go_version,
                "sample_repo": str(repo_root),
                "passed": False,
                "stretch_passed": False,
                "error": f"gopls 不可用: {check_result.reason}",
            }

        workspace = discover_go_workspace(repo_root)
        if workspace is None:
            self.stdout.write(
                f"advisory skip：在 {repo_root} 未找到 go.mod，跳过测量。"
            )
            return {
                "init_time_ms": -1,
                "workspace_symbol_count": 0,
                "gopls_version": check_result.gopls_version,
                "go_version": check_result.go_version,
                "sample_repo": str(repo_root),
                "passed": False,
                "stretch_passed": False,
                "error": "no go.mod found",
            }

        supervisor = LspSupervisor(
            name="gopls-measure",
            command=list(_GoplsLazyBackend.command),
            workspace_root=workspace.go_mod_root,
            language_ids=list(_GoplsLazyBackend.language_ids),
            initialization_options=dict(_GoplsLazyBackend.initialization_options),
        )

        start = time.monotonic()
        try:
            supervisor.call_async_in_loop(supervisor.ensure_started, timeout=timeout_seconds)
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {
                "init_time_ms": elapsed_ms,
                "workspace_symbol_count": 0,
                "gopls_version": check_result.gopls_version,
                "go_version": check_result.go_version,
                "sample_repo": str(repo_root),
                "passed": False,
                "stretch_passed": False,
                "error": str(exc),
            }

        elapsed_ms = int((time.monotonic() - start) * 1000)

        # workspace/symbol("") ping 计 symbol 数
        workspace_symbol_count = 0
        ping_error: str | None = None
        try:
            async def _ws_coro() -> Any:
                client = supervisor._client
                if client is None:
                    return []
                return await client.request_workspace_symbol("", timeout=30.0)

            symbol_resp = supervisor.call_async_in_loop(_ws_coro, timeout=35.0)
            workspace_symbol_count = len(symbol_resp) if isinstance(symbol_resp, list) else 0
        except Exception as exc:
            ping_error = str(exc)
            logger.warning("gopls_workspace_symbol_ping_failed", error=str(exc))

        # 测量完毕后 stop（不保留 _SUPERVISORS 正式缓存）
        try:
            supervisor.call_async_in_loop(supervisor.stop, timeout=5.0)
        except Exception:
            pass

        return {
            "init_time_ms": elapsed_ms,
            "workspace_symbol_count": workspace_symbol_count,
            "ping_error": ping_error,
            "gopls_version": check_result.gopls_version,
            "go_version": check_result.go_version,
            "sample_repo": str(repo_root),
            "passed": elapsed_ms < _GATE_MS,
            "stretch_passed": elapsed_ms < _STRETCH_MS,
        }
