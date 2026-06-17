"""对账 + 两模式清理服务（Phase 23 Plan 02，EXCL-04 / EXCL-06）。

本模块把 23-01 的单文件删除入口 ``purge_file`` 升级为「规则驱动的批量对账清理」：

- :func:`compute_reconciliation` —— **对账**：枚举仓库已索引文件集合
  （``FileIndex.file_path`` ∪ ``ChunkRegistry.file_path``，双源并去重），与现行排除
  匹配器（复用 Phase 22 ``build_matcher_for_repo``）逐路径比对，列出「已索引但现命中
  排除」的差异文件（EXCL-06）。

  **degraded 语义（W3 / T-23-05）**：匹配器**构造**失败时，对账诊断本身不可信——
  此刻绝不能把空差异渲染成「已一致」假干净。故置 ``degraded=True`` + ``error``、
  ``match_count=0``、``excluded_paths=[]``，让失败贯通 dataclass→serializer→client 如实
  可见。注意：单文件 ``is_excluded`` 判定的运行期异常由 matcher 内部 fail-closed
  （命中）兜底，**不**污染 degraded——degraded 只反映构造期失败。

- :func:`run_cleanup` —— **清理**：对差异文件逐一调 ``purge_file`` 删净五个派生数据面
  （EXCL-04），best-effort 逐文件隔离（单文件失败记 ``failures`` 不阻断其余）。清理后
  调度 repo_summaries / repo_index_nodes 重建（best-effort，失败不致命——摘要/树是可重建
  聚合，DOMAIN §9.3）。每次清理持久化一条 ``CleanupRun``（running→completed/failed），
  其结果可经状态查询端点回流前端（W1/W2）。

  **两模式边界**：``mode="normal"`` 仅清派生索引面；``mode="sensitive"`` 在普通清理
  基础上**懒导入** ``services.sensitive_purge.purge_sensitive_planes``（23-03 提供）清操作
  记录面，其返回 dict（含 unscrubbed/caveat）落入 ``CleanupReport.sensitive`` 与
  ``CleanupRun.sensitive``。懒导入失败不破坏普通清理已完成结果——记 failures + 写
  ``CleanupRun.error``。普通模式对敏感模块**零依赖**。

- :func:`log_purge_event` —— 清理审计埋点（``purge.started`` / ``purge.completed``），
  风格对齐 ``services.exclusion.log_exclusion_blocked``，供审计里程碑复用（T-23-09）。

所有 ORM / ``CleanupRun`` 写入均经 ``sync_to_async``（async 约束）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from asgiref.sync import sync_to_async

from audit.services import taxonomy
from audit.services.audit_service import AuditService
from services.exclusion import build_matcher_for_repo
from services.purge import PurgeResult, purge_file

# v0.5 既有 purge.* 结构化埋点收口到 AuditService 单一写入入口（INV-6 / Phase 54）：
# event 字符串 → 具名 action 常量映射，在 run_cleanup 异步调用点经 aemit 落库。
_PURGE_ACTION_MAP: dict[str, str] = {
    "purge.started": taxonomy.ACTION_PURGE_STARTED,
    "purge.completed": taxonomy.ACTION_PURGE_COMPLETED,
}


async def _emit_purge_audit(
    event: str,
    *,
    mode: str,
    repository_id: str,
    match_count: int,
    failures: list[str] | None = None,
) -> None:
    """把 purge.* 埋点收口到 AuditService（actor=None 系统清理，fail-soft 由入口兜底）。"""
    action = _PURGE_ACTION_MAP.get(event)
    if action is None:
        return
    await AuditService.aemit(
        action=action,
        actor=None,
        target_type="repository",
        target_id=repository_id,
        metadata={
            "mode": mode,
            "match_count": match_count,
            "failures": failures or [],
        },
        source="purge",
    )


logger = structlog.get_logger(__name__)

__all__ = [
    "ReconcileReport",
    "CleanupReport",
    "compute_reconciliation",
    "run_cleanup",
    "log_purge_event",
]

# 合法清理模式。``sensitive`` 委托 23-03，普通模式不依赖之。
VALID_MODES: tuple[str, ...] = ("normal", "sensitive")


@dataclass
class ReconcileReport:
    """对账结果（含 degraded/error，W3 贯通到 serializer/client）。"""

    indexed_count: int = 0
    excluded_paths: list[str] = field(default_factory=list)
    match_count: int = 0
    suggested_mode: str = "normal"
    degraded: bool = False
    error: str = ""


@dataclass
class CleanupReport:
    """清理结果（普通模式 ``sensitive`` 恒为 None）。"""

    mode: str = "normal"
    purged_paths: list[str] = field(default_factory=list)
    per_file: list[PurgeResult] = field(default_factory=list)
    sensitive: dict | None = None
    failures: list[str] = field(default_factory=list)
    # 对账诊断不可信（匹配器构造失败）→ fail-closed 中止清理（BL-01，W3）。
    degraded: bool = False


async def _indexed_file_paths(repository_id: str) -> list[str]:
    """枚举仓库已索引文件路径：``FileIndex.file_path`` ∪ ``ChunkRegistry.file_path``。

    双源并集去重（T-23-05）：单看 FileIndex 会漏掉只在 ChunkRegistry 留痕的残留，
    反之亦然；取并集确保对账不漏报。
    """

    def _query() -> list[str]:
        from code_relations.models import ChunkRegistry
        from repositories.models import FileIndex

        paths: set[str] = set(
            FileIndex.objects.filter(repository_id=repository_id).values_list(
                "file_path", flat=True
            )
        )
        paths |= set(
            ChunkRegistry.objects.filter(repository_id=repository_id).values_list(
                "file_path", flat=True
            )
        )
        return sorted(p for p in paths if p)

    return await sync_to_async(_query)()


async def compute_reconciliation(repository_id: str) -> ReconcileReport:
    """对比「已索引文件集合 vs 现行排除规则」，列出差异文件（EXCL-06）。

    匹配器**构造**失败 → ``degraded=True`` + ``error``（W3，不谎报「已一致」）。
    """
    repo_id = str(repository_id)
    indexed = await _indexed_file_paths(repo_id)
    report = ReconcileReport(indexed_count=len(indexed))

    try:
        matcher = await build_matcher_for_repo(repo_id)
    except Exception as exc:  # noqa: BLE001 — 构造失败：对账诊断不可信，置 degraded（W3）
        logger.warning(
            "reconcile.matcher_build_failed",
            repository_id=repo_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        report.degraded = True
        report.error = f"{type(exc).__name__}: {exc}"
        report.match_count = 0
        report.excluded_paths = []
        return report

    # 单文件 is_excluded 运行期异常由 matcher 内部 fail-closed（命中）兜底，不污染 degraded。
    excluded = sorted({p for p in indexed if matcher.is_excluded(p)})
    report.excluded_paths = excluded
    report.match_count = len(excluded)
    report.suggested_mode = "normal"
    return report


async def _get_or_create_run(repository_id: str, mode: str, cleanup_run_id: str | None):
    """取（传入 id）或新建一条 ``CleanupRun(status=running)``。"""
    from repositories.models import CleanupRun

    if cleanup_run_id:
        run = await CleanupRun.objects.filter(id=cleanup_run_id).afirst()
        if run is not None:
            run.status = CleanupRun.Status.RUNNING
            run.mode = mode
            await run.asave(update_fields=["status", "mode"])
            return run

    return await CleanupRun.objects.acreate(
        repository_id=repository_id,
        mode=mode,
        status=CleanupRun.Status.RUNNING,
    )


async def _finalize_run(
    run,
    *,
    status: str,
    match_count: int,
    failures: list[str],
    sensitive: dict | None,
    error: str,
) -> None:
    """收尾 ``CleanupRun``：写终态 / 计数 / 失败 / sensitive 结果 / completed_at。"""
    from django.utils import timezone

    run.status = status
    run.match_count = match_count
    run.failures = failures
    run.sensitive = sensitive
    run.error = error
    run.completed_at = timezone.now()
    await run.asave(
        update_fields=[
            "status",
            "match_count",
            "failures",
            "sensitive",
            "error",
            "completed_at",
        ]
    )


async def run_cleanup(
    repository_id: str,
    mode: str = "normal",
    paths: list[str] | None = None,
    cleanup_run_id: str | None = None,
) -> CleanupReport:
    """对差异文件逐一调 ``purge_file`` 删净派生面（EXCL-04），持久化 ``CleanupRun``。

    Args:
        repository_id: 仓库 UUID 字符串。
        mode: ``normal``（仅派生索引面）/ ``sensitive``（额外清操作记录面，23-03）。
        paths: 差异文件列表；缺省时先 :func:`compute_reconciliation` 取 ``excluded_paths``。
        cleanup_run_id: 既有 ``CleanupRun`` 行 id（API 先建 running 行拿 run_id 再派发）；
            缺省则新建。

    Returns:
        :class:`CleanupReport` —— ``purged_paths`` / ``per_file`` / ``sensitive`` / ``failures``。

    Raises:
        ValueError: ``mode`` 非法。
    """
    repo_id = str(repository_id)
    if mode not in VALID_MODES:
        raise ValueError(f"未知清理模式: {mode!r}（合法值 {VALID_MODES}）")

    run = await _get_or_create_run(repo_id, mode, cleanup_run_id)

    if paths is None:
        recon = await compute_reconciliation(repo_id)
        # BL-01：对账 degraded（匹配器构造失败）时诊断不可信，绝不静默以
        # status=completed/match_count=0 收尾（否则把"未清"伪装成"已清"——
        # 敏感模式下等于安全泄漏，违反 CLAUDE.md/AGENTS.md fail-closed 约束）。
        # 此处是权威 fail-closed 收尾点，不依赖前端 TOCTOU 禁用（GET 正常→后台重算失败）。
        if recon.degraded:
            error = recon.error or "对账匹配器构造失败，诊断不可信，已中止清理（fail-closed）"
            await _finalize_run(
                run,
                status="failed",
                match_count=0,
                failures=["reconcile_degraded"],
                sensitive=None,
                error=error,
            )
            logger.warning(
                "cleanup.reconcile_degraded",
                repository_id=repo_id,
                mode=mode,
                error=error,
            )
            log_purge_event(
                "purge.completed",
                mode=mode,
                repository_id=repo_id,
                match_count=0,
                failures=["reconcile_degraded"],
            )
            await _emit_purge_audit(
                "purge.completed",
                mode=mode,
                repository_id=repo_id,
                match_count=0,
                failures=["reconcile_degraded"],
            )
            return CleanupReport(mode=mode, failures=["reconcile_degraded"], degraded=True)
        paths = recon.excluded_paths
    target_paths = list(paths)

    report = CleanupReport(mode=mode)
    run_error = ""

    log_purge_event(
        "purge.started", mode=mode, repository_id=repo_id, match_count=len(target_paths)
    )
    await _emit_purge_audit(
        "purge.started", mode=mode, repository_id=repo_id, match_count=len(target_paths)
    )

    # --- 普通清理：逐文件 purge_file，best-effort 逐文件隔离 ---
    for path in target_paths:
        try:
            result = await purge_file(repo_id, path)
            report.per_file.append(result)
            report.purged_paths.append(path)
            if not result.ok:
                report.failures.extend(f"{path}:{f}" for f in result.failures)
        except Exception as exc:  # noqa: BLE001 — 单文件失败不阻断其余（best-effort）
            logger.warning(
                "cleanup.purge_file_failed",
                repository_id=repo_id,
                rel_path=path,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            report.failures.append(f"{path}:exception:{type(exc).__name__}")

    # --- 敏感清理：懒导入委托 23-03，结果落 CleanupReport/CleanupRun.sensitive ---
    if mode == "sensitive":
        try:
            from services.sensitive_purge import purge_sensitive_planes  # 懒导入（23-03 提供）

            report.sensitive = await purge_sensitive_planes(repo_id, report.purged_paths)
        except Exception as exc:  # noqa: BLE001 — 敏感模块未就绪不破坏普通清理已完成结果
            logger.warning(
                "cleanup.sensitive_unavailable",
                repository_id=repo_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            report.failures.append(f"sensitive:{type(exc).__name__}:{exc}")
            run_error = f"敏感清理未就绪/失败: {type(exc).__name__}: {exc}"

    # --- 摘要 / 索引树重建：best-effort 后台调度，失败不致命（可重建聚合）---
    _schedule_summary_rebuild(repo_id)

    final_status = "completed" if not report.failures else "failed"
    await _finalize_run(
        run,
        status=final_status,
        match_count=len(target_paths),
        failures=report.failures,
        sensitive=report.sensitive,
        error=run_error,
    )

    log_purge_event(
        "purge.completed",
        mode=mode,
        repository_id=repo_id,
        match_count=len(target_paths),
        failures=report.failures,
    )
    await _emit_purge_audit(
        "purge.completed",
        mode=mode,
        repository_id=repo_id,
        match_count=len(target_paths),
        failures=report.failures,
    )
    return report


def _schedule_summary_rebuild(repository_id: str) -> None:
    """best-effort 后台调度 repo_summaries + repo_index_nodes 重建（失败不致命）。

    摘要/索引树是从派生面聚合而来的可重建产物（DOMAIN §9.3），清理后调度重建以反映
    新状态；调度或重建失败仅记 warning，绝不影响清理主流程。
    """
    repo_id = str(repository_id)
    try:
        from services.background_runner import run_in_background

        async def _rebuild() -> None:
            try:
                from codegraph.services.repo_summary_builder import RepoSummaryBuilder

                await RepoSummaryBuilder.build(repository_id=repo_id)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "cleanup.summary_rebuild_failed", repository_id=repo_id, exc_info=True
                )
            try:
                from codegraph.services.repo_index_tree import RepoIndexTreeBuilder

                await RepoIndexTreeBuilder.build(repo_id)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "cleanup.index_nodes_rebuild_failed", repository_id=repo_id, exc_info=True
                )

        run_in_background(_rebuild, name=f"cleanup-summary-rebuild:{repo_id}")
    except Exception:  # noqa: BLE001 — 调度失败不致命
        logger.warning(
            "cleanup.summary_rebuild_dispatch_failed", repository_id=repo_id, exc_info=True
        )


def log_purge_event(
    event: str,
    *,
    mode: str,
    repository_id: str,
    match_count: int,
    failures: list[str] | None = None,
) -> None:
    """结构化清理审计埋点（``purge.started`` / ``purge.completed``，T-23-09）。"""
    logger.info(
        event,
        mode=mode,
        repository_id=str(repository_id),
        match_count=match_count,
        failures=failures or [],
    )
