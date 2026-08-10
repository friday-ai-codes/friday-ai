"""Diff-aware Semgrep CLI 封装（Phase 127 / TAINT-01 / D-01..D-05）。

经固定 ``SEMGREP_BIN`` argv 列表调用 ``semgrep scan``（非 ``ci``）；
``--baseline-commit`` = ``git merge-base(target, source)``。
Semgrep 仅 subprocess CLI，禁止作为 Python 模块导入（不进 uv.lock）。
超时 / mirror / CLI 失败 → fail-open 结果对象（稳定 ``error_code``），不阻断建 MR。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.conf import settings

from common.logging import redact_secrets_in_text
from services.repo_mirror import (
    MirrorError,
    ensure_mirror_sha,
    ensure_worktree_for_scan,
)

logger = structlog.get_logger(__name__)

# terminate 到 kill 的宽限期：给 Semgrep 一点时间自己收尾，超过即 SIGKILL
_KILL_GRACE_SECONDS = 5.0

__all__ = [
    "SemgrepScanResult",
    "build_semgrep_argv",
    "parse_semgrep_configs",
    "run_semgrep_scan",
]


@dataclass
class SemgrepScanResult:
    """扫描结构化结果，供 127-04 MR 段挂载。"""

    findings_count: int = 0
    error_code: str | None = None
    baseline_sha: str = ""
    scan_sha: str = ""
    persisted: int = 0
    extras: dict[str, Any] = field(default_factory=dict)


def parse_semgrep_configs(raw: str | None = None) -> list[str]:
    """``SEMGREP_CONFIGS`` CSV → pack 列表（去空白、去空项）。"""
    text = raw if raw is not None else getattr(settings, "SEMGREP_CONFIGS", "") or ""
    return [part.strip() for part in str(text).split(",") if part.strip()]


def build_semgrep_argv(
    *,
    bin_path: str,
    baseline_commit: str,
    configs: list[str],
    timeout: int,
    include_paths: list[str] | None = None,
) -> list[str]:
    """构造固定 argv 列表：``scan`` + ``--baseline-commit`` + packs；不含 ``ci``。"""
    argv: list[str] = [
        bin_path,
        "scan",
        "--baseline-commit",
        baseline_commit,
        "--json",
        "--quiet",
        "--timeout",
        str(int(timeout)),
    ]
    for pack in configs:
        argv.extend(["--config", pack])
    for path in include_paths or []:
        cleaned = (path or "").strip()
        if cleaned:
            argv.extend(["--include", cleaned])
    return argv


async def _resolve_merge_base(repo_dir: Path, target_sha: str, source_sha: str) -> str:
    """``git merge-base(target, source)`` — ⛔ 禁止用 target HEAD 当 baseline。"""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "merge-base",
        target_sha,
        source_sha,
        cwd=str(repo_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    if (proc.returncode or 0) != 0:
        detail = redact_secrets_in_text(stderr.decode(errors="replace")[:300])
        raise MirrorError("unavailable", f"merge-base failed: {detail}")
    sha = stdout.decode().strip().lower()
    if len(sha) < 7:
        raise MirrorError("unavailable", "merge-base returned empty sha")
    return sha


def _resolve_app_token() -> str:
    """Pro token：优先加密 SystemSetting；空则 CE；env 仅 escape hatch（D-09）。

    与 MR 段的 Pro 声明共用 ``semgrep_token.resolve_semgrep_app_token``，口径唯一。
    """
    from services.code_graph.semgrep_token import resolve_semgrep_app_token

    return resolve_semgrep_app_token()


def _kill_quietly(proc: asyncio.subprocess.Process) -> None:
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass


async def _terminate_process(proc: asyncio.subprocess.Process) -> None:
    """先 terminate 再 kill 并回收退出码；已退出则无操作。

    Semgrep 子进程环境里可能带 Pro ``SEMGREP_APP_TOKEN``，放任超时孤儿存活等于把
    凭证留在一个还在烧 CPU/IO 的进程里，fail-open 超时语义也形同虚设（T-127-01）。
    """
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
    except (ProcessLookupError, OSError):
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=_KILL_GRACE_SECONDS)
        return
    except asyncio.CancelledError:
        # 外层取消：至少确保 SIGKILL 已送达，不再 await
        _kill_quietly(proc)
        raise
    except (TimeoutError, asyncio.TimeoutError):
        pass
    _kill_quietly(proc)
    try:
        await proc.wait()
    except Exception:  # noqa: BLE001 — 已 kill，回收失败不再升级
        pass


async def _run_semgrep_cli(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    wall_timeout: float,
) -> tuple[int, bytes, bytes]:
    """跑 Semgrep CLI；本函数是墙钟超时的**唯一**归属方。

    ``finally`` 回收保证超时 / 取消 / 异常三条路径都不会留下 token-bearing 孤儿；
    正常返回时子进程已退出，回收为 no-op。
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=wall_timeout)
    finally:
        await _terminate_process(proc)
    return proc.returncode or 0, stdout, stderr


def _map_severity(raw: str | None) -> str:
    text = (raw or "").strip().upper()
    if text in {"ERROR", "WARNING", "INFO"}:
        return text
    if text in {"CRITICAL", "HIGH"}:
        return "ERROR"
    if text in {"MEDIUM", "MODERATE"}:
        return "WARNING"
    if text in {"LOW", "NOTE"}:
        return "INFO"
    return text or "INFO"


def _parse_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results") or []
    if not isinstance(results, list):
        return []
    parsed: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        start = item.get("start") if isinstance(item.get("start"), dict) else {}
        message = str(extra.get("message") or item.get("message") or "")
        fingerprint = str(extra.get("fingerprint") or item.get("fingerprint") or "")
        if not fingerprint:
            # 稳定退化指纹，避免空指纹碰撞
            fingerprint = (
                f"{item.get('check_id', '')}:{item.get('path', '')}:{start.get('line', 0)}"
            )
        parsed.append(
            {
                "rule_id": str(item.get("check_id") or item.get("rule_id") or "unknown"),
                "severity": _map_severity(str(extra.get("severity") or "")),
                "file_path": str(item.get("path") or ""),
                "line": int(start.get("line") or 0) or None,
                "message": message,
                "fingerprint": fingerprint[:128],
            }
        )
    return parsed


@sync_to_async
def _persist_findings(
    *,
    repository_id: str,
    mr_key: str,
    branch_name: str,
    scan_sha: str,
    findings: list[dict[str, Any]],
) -> int:
    from codegraph.models import SecurityFinding, prepare_finding_message
    from repositories.models import Repository

    try:
        repo = Repository.objects.get(id=repository_id)
    except Repository.DoesNotExist:
        return 0

    count = 0
    for item in findings:
        try:
            message = prepare_finding_message(item.get("message") or "")
            # 二次兜底：若 helper 被旁路也走 redact
            message = redact_secrets_in_text(message)
            SecurityFinding.objects.update_or_create(
                repository=repo,
                fingerprint=item["fingerprint"],
                mr_key=mr_key or "",
                defaults={
                    "branch_name": branch_name or "",
                    "rule_id": item["rule_id"][:512],
                    "severity": item["severity"][:32],
                    "file_path": (item.get("file_path") or "")[:1024],
                    "line": item.get("line"),
                    "message": message,
                    "scan_sha": scan_sha or "",
                    "status": "open",
                },
            )
            count += 1
        except Exception:  # noqa: BLE001 — 单条落库失败不反噬整次扫描
            try:
                logger.warning(
                    "semgrep_finding_persist_failed",
                    category="sampling",
                    component="code_graph",
                    repository_id=str(repository_id),
                    fingerprint=str(item.get("fingerprint") or "")[:64],
                )
            except Exception:
                pass
    return count


async def run_semgrep_scan(
    *,
    repository_id: str,
    source_sha: str,
    target_sha: str,
    mr_key: str = "",
    branch_name: str = "",
    include_paths: list[str] | None = None,
    initiated_by_user_id: str | None = None,
) -> SemgrepScanResult:
    """对 MR source/target 跑 diff-aware Semgrep；失败返回 ``error_code``，永不 raise 阻断。"""
    started = time.monotonic()
    actor = initiated_by_user_id or "system"
    source = (source_sha or "").strip().lower()
    target = (target_sha or "").strip().lower()
    result = SemgrepScanResult(scan_sha=source)

    try:
        logger.info(
            "semgrep_scan_started",
            category="caller",
            component="code_graph",
            repository_id=str(repository_id),
            mr_key=mr_key or "",
            initiated_by_user_id=actor,
            source_sha=source[:12] if source else "",
            target_sha=target[:12] if target else "",
        )
    except Exception:
        pass

    try:
        if not source or not target:
            result.error_code = "unavailable"
            return _finish(result, started, actor, repository_id, mr_key, failed=True)

        # 两端 SHA 必须可解析；worktree 检出 source（被扫描树）
        source_snap = await ensure_mirror_sha(str(repository_id), source)
        await ensure_mirror_sha(str(repository_id), target)
        worktree = await ensure_worktree_for_scan(str(repository_id), source)
        baseline = await _resolve_merge_base(source_snap.repo_dir, target, source)
        result.baseline_sha = baseline

        bin_path = str(getattr(settings, "SEMGREP_BIN", "") or "").strip()
        if not bin_path:
            result.error_code = "unavailable"
            return _finish(result, started, actor, repository_id, mr_key, failed=True)

        rule_timeout = int(getattr(settings, "SEMGREP_TIMEOUT", 5) or 5)
        wall_timeout = float(getattr(settings, "SEMGREP_TASK_TIMEOUT", 180) or 180)
        configs = parse_semgrep_configs()
        argv = build_semgrep_argv(
            bin_path=bin_path,
            baseline_commit=baseline,
            configs=configs,
            timeout=rule_timeout,
            include_paths=include_paths,
        )

        import os

        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        try:
            token = await sync_to_async(_resolve_app_token)()
        except Exception:  # noqa: BLE001 — token 读取失败降级 CE，不阻断扫描
            token = ""
        if token:
            env["SEMGREP_APP_TOKEN"] = token

        try:
            # 超时只由 _run_semgrep_cli 内层 wait_for 归属：外再套一层 wait_for 会把
            # 内层的子进程回收变成"取消中清理"，正是 token-bearing 孤儿的来源。
            rc, stdout, stderr = await _run_semgrep_cli(
                argv,
                cwd=worktree,
                env=env,
                wall_timeout=wall_timeout,
            )
        except TimeoutError:
            result.error_code = "timeout"
            return _finish(result, started, actor, repository_id, mr_key, failed=True)

        # Semgrep：有 finding 时常 rc=1；真正失败多为 >=2
        text = stdout.decode(errors="replace") if stdout else ""
        if not text.strip():
            if rc >= 2:
                result.error_code = "unavailable"
                try:
                    logger.warning(
                        "semgrep_scan_cli_failed",
                        category="caller",
                        component="code_graph",
                        repository_id=str(repository_id),
                        returncode=rc,
                        error=redact_secrets_in_text(
                            (stderr or b"").decode(errors="replace")[:300]
                        ),
                    )
                except Exception:
                    pass
                return _finish(result, started, actor, repository_id, mr_key, failed=True)
            result.findings_count = 0
            return _finish(result, started, actor, repository_id, mr_key, failed=False)

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            result.error_code = "unavailable"
            return _finish(result, started, actor, repository_id, mr_key, failed=True)

        findings = _parse_results(payload if isinstance(payload, dict) else {})
        result.findings_count = len(findings)
        result.persisted = await _persist_findings(
            repository_id=str(repository_id),
            mr_key=mr_key or "",
            branch_name=branch_name or "",
            scan_sha=source,
            findings=findings,
        )
        return _finish(result, started, actor, repository_id, mr_key, failed=False)

    except TimeoutError:
        result.error_code = "timeout"
        return _finish(result, started, actor, repository_id, mr_key, failed=True)
    except MirrorError as exc:
        code = (getattr(exc, "code", None) or "unavailable").strip() or "unavailable"
        if code.startswith("mirror_"):
            result.error_code = code
        elif code in {"unavailable", "timeout", "invalid_params"}:
            result.error_code = "unavailable" if code == "invalid_params" else code
        else:
            result.error_code = "unavailable"
        return _finish(result, started, actor, repository_id, mr_key, failed=True)
    except Exception as exc:  # noqa: BLE001 — fail-open：永不阻断建 MR
        result.error_code = "unavailable"
        try:
            logger.warning(
                "semgrep_scan_failed",
                category="caller",
                component="code_graph",
                repository_id=str(repository_id),
                mr_key=mr_key or "",
                initiated_by_user_id=actor,
                error=redact_secrets_in_text(str(exc))[:300],
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:
            pass
        return result


def _finish(
    result: SemgrepScanResult,
    started: float,
    actor: str,
    repository_id: str,
    mr_key: str,
    *,
    failed: bool,
) -> SemgrepScanResult:
    duration_ms = round((time.monotonic() - started) * 1000, 2)
    try:
        if failed or result.error_code:
            logger.warning(
                "semgrep_scan_failed",
                category="caller",
                component="code_graph",
                repository_id=str(repository_id),
                mr_key=mr_key or "",
                initiated_by_user_id=actor,
                error_code=result.error_code,
                findings_count=result.findings_count,
                baseline_sha=(result.baseline_sha or "")[:12],
                duration_ms=duration_ms,
            )
        else:
            logger.info(
                "semgrep_scan_completed",
                category="caller",
                component="code_graph",
                repository_id=str(repository_id),
                mr_key=mr_key or "",
                initiated_by_user_id=actor,
                findings_count=result.findings_count,
                persisted=result.persisted,
                baseline_sha=(result.baseline_sha or "")[:12],
                duration_ms=duration_ms,
            )
    except Exception:
        pass
    return result
