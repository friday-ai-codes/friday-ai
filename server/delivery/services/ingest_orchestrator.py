"""一键摄取三步编排（Phase 32-02，ING-01 / CONTEXT Grey Area 1）。

把不可信 ``(board_url, mr_url)`` 串成**既有能力**的三步摄取——本模块是 PURE
ORCHESTRATION，绝不新建底层摄取/检索机制，只复用 P28 upsert / P30 normalizer /
既有 diff RAG：

1. **看板工作项**：``parse_board_url`` → ``WorkItemService().upsert``
   （操作态脊柱单一写入口，INV-6 / source=``mr_reverse``）。
2. **文档 + REFERENCES**：``ingest(IngestionRequest("feishu_document", ...))``——经
   P30 ``feishu_document`` normalizer 同时让 work_item + document 实体进入 knowledge
   可检索面 + ``REFERENCES`` 边（缺段不缺实体）。
3. **MR diff**：``aresolve_repo_and_mr``（SSRF 边界，必须命中已落库 Repository）→
   既有 ``archive_code_change`` 归档 → 组装 ``code_change`` ``IngestionEvent`` 经
   ``ingest_events`` 入图（CodeChangeArchive + code_change 实体 + MODIFIES_CHUNK 边）。

降级范式（§1.4，best-effort 步级隔离）：每步独立 try/except，任一步失败/跳过
**不阻断**其余步骤，结构化结果逐步写入 ``IngestRun.steps`` 持久化（前端可逐步轮询
真实进度）。编排级未捕获异常 → ``IngestRun.status=failed`` + 脱敏 error；正常跑完
（含步级 failed/skipped）→ ``status=completed``（partial 由前端从 completed + 非 ok
推导）。

脱敏契约（T-32-02）：步级/编排级 error 落库前一律复用
``WorkItemService._safe_error``（``_redact_secrets`` + 截断），diff 原文/响应 body
绝不入 ``steps``；code_change payload 仅摘要（archive_id/commit_sha/统计）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from delivery.models import IngestRun
from delivery.services.ingest_parsing import aresolve_repo_and_mr, parse_board_url
from delivery.services.work_item_service import (
    WorkItemIdentity,
    WorkItemService,
    _redact_secrets,
)

logger = structlog.get_logger(__name__)

__all__ = ["StepResult", "ingest_from_urls", "ingest_from_refs", "build_board_url"]

# steps[*].error 截断长度（脱敏：避免拼接大段不可信响应/凭证，对齐 T-28-07）
_ERROR_SNIPPET_LIMIT = 500

# 一键摄取触发器名（结构化日志/ingestion trigger 用）
_TRIGGER = "one_click_ingest"
# MR 反查摄取的 knowledge source_kind（与 task_result 的 "task_result" 区隔）
_MR_SOURCE_KIND = "mr_ingest"


@dataclass(frozen=True)
class StepResult:
    """单步结构化结果（落 ``IngestRun.steps[*]``，形状与 ``default_steps`` 对齐）。

    ``status`` ∈ ok / failed / skipped / pending；``identifier`` 为关联对象标识
    （work_item id / archive id 等），``link`` 为可选外链，``error`` 为脱敏后原因。
    """

    status: str
    identifier: str = ""
    link: str = ""
    error: str = ""


def _safe_error(exc: Exception) -> str:
    """脱敏错误摘要：先抹凭证再截断（复用 work_item_service 的 ``_redact_secrets`` 范式）。

    响应 body / 异常文本可能夹带凭证（误入的 token/secret/Authorization），先
    ``_redact_secrets`` 抹掉键名命中的值与 ``Bearer`` 串再截断；先脱敏后截断避免截到
    token 中段残留半截凭证。绝不向 ``steps[*].error`` 落原始凭证（T-32-02）。
    """
    return _redact_secrets(str(exc))[:_ERROR_SNIPPET_LIMIT]


def build_board_url(feishu_project_key: str, work_item_type: str, work_item_id: int) -> str:
    """由三元组拼飞书工作项详情 URL（仅作展示/留痕，缺段返回空串）。"""
    if not feishu_project_key or not work_item_type or not work_item_id:
        return ""
    return (
        f"https://project.feishu.cn/{feishu_project_key}/{work_item_type}/detail/{work_item_id}"
    )


async def ingest_from_urls(run_id: str, board_url: str, mr_url: str) -> IngestRun:
    """一键摄取三步编排（URL 入口）：解析看板 URL → 委托 ``ingest_from_refs``。

    Args:
        run_id: 已由 dispatch 端点建好的 ``IngestRun`` 主键（UUID str）。
        board_url: 不可信看板/工作项 URL（解析仅抽标识符，不作抓取目标，T-32-01）。
        mr_url: 不可信 MR/PR URL（必须匹配已落库 Repository 才走其凭证 client）。

    Returns:
        终态 ``IngestRun``（status=completed/failed，steps 三项结构化结果）。
    """
    try:
        board = parse_board_url(board_url)
    except Exception as exc:
        # 解析阶段未捕获异常（编排级）：整体 failed + 脱敏 error，不冒泡。
        run = await IngestRun.objects.aget(id=run_id)
        logger.exception("ingest_orchestration_failed", run_id=str(run.id))
        run.status = IngestRun.Status.FAILED
        run.error = _safe_error(exc)
        run.completed_at = timezone.now()
        await sync_to_async(run.save)(
            update_fields=["status", "error", "completed_at", "updated_at"]
        )
        return run

    if board is None:
        return await ingest_from_refs(
            run_id,
            feishu_project_key="",
            work_item_type="",
            work_item_id=0,
            mr_url=mr_url,
            board_url=board_url,
            missing_item_reason="board_url 无法解析（容器型/非标准形态不支持）",
        )
    return await ingest_from_refs(
        run_id,
        feishu_project_key=board.feishu_project_key,
        work_item_type=board.work_item_type,
        work_item_id=board.work_item_id,
        mr_url=mr_url,
        board_url=board_url,
    )


async def ingest_from_refs(
    run_id: str,
    *,
    feishu_project_key: str,
    work_item_type: str,
    work_item_id: int,
    mr_url: str = "",
    board_url: str = "",
    missing_item_reason: str = "",
) -> IngestRun:
    """三步摄取编排（三元组入口）：写 ``IngestRun(run_id)``，best-effort 降级。

    复用既有能力的三步：工作项 upsert / 文档+REFERENCES / MR diff。三元组齐全才跑步
    1/2，否则 skipped；``mr_url`` 为空则步 3 skipped。供 URL 入口与 JSON 批量摄取共用。
    """
    run = await IngestRun.objects.aget(id=run_id)
    has_item = bool(feishu_project_key and work_item_type and work_item_id)
    link = board_url or build_board_url(feishu_project_key, work_item_type, work_item_id)

    try:
        # === 步 1：工作项 upsert（操作态脊柱，INV-6）===
        if not has_item:
            await _write_step(
                run,
                "work_item",
                StepResult(
                    status="skipped",
                    error=missing_item_reason or "缺少工作项标识（空间/ID），跳过工作项摄取",
                ),
            )
        else:
            try:
                work_item = await WorkItemService().upsert(
                    WorkItemIdentity(
                        feishu_project_key=feishu_project_key,
                        work_item_type=work_item_type,
                        work_item_id=work_item_id,
                    ),
                    source="mr_reverse",
                    fetch=True,
                )
                await _write_step(
                    run,
                    "work_item",
                    StepResult(status="ok", identifier=str(work_item.id), link=link),
                )
            except Exception as exc:
                logger.warning(
                    "ingest_work_item_step_failed",
                    run_id=str(run.id),
                    error=_safe_error(exc),
                    error_type=type(exc).__name__,
                )
                await _write_step(
                    run, "work_item", StepResult(status="failed", error=_safe_error(exc))
                )

        # === 步 2：文档 + REFERENCES + work_item knowledge 投影（复用 P30 normalizer）===
        if not has_item:
            await _write_step(
                run,
                "document",
                StepResult(
                    status="skipped",
                    error=missing_item_reason or "缺少工作项标识，跳过文档摄取",
                ),
            )
        else:
            try:
                from knowledge.ingestion import IngestionRequest, ingest

                source_id = f"{feishu_project_key}:{work_item_type}:{work_item_id}"
                # 直接 await（非 aschedule_ingestion）以同步拿成败落 steps。
                # WR-01：normalizer 零产出（Space 不存在 / 无可摄取文档）时 ingest()
                # 静默返回 0，不抛异常——此处据真实产出数记 ok/skipped，避免「零实体
                # 入库却显示成功」的 false-positive（对齐「结构化结果如实展示」目标）。
                events_ingested = await ingest(
                    IngestionRequest(
                        source_kind="feishu_document",
                        source_id=source_id,
                        trigger=_TRIGGER,
                    )
                )
                await _write_step(
                    run,
                    "document",
                    StepResult(
                        status="ok" if events_ingested else "skipped",
                        identifier=source_id,
                        error="" if events_ingested else "未找到可摄取的文档/项目",
                    ),
                )
            except Exception as exc:
                logger.warning(
                    "ingest_document_step_failed",
                    run_id=str(run.id),
                    error=_safe_error(exc),
                    error_type=type(exc).__name__,
                )
                await _write_step(
                    run, "document", StepResult(status="failed", error=_safe_error(exc))
                )

        # === 步 3：MR diff 归档 + 入图（mr_url 为空则 skipped）===
        if mr_url:
            await _ingest_mr_diff(run, mr_url)
        else:
            await _write_step(
                run, "mr_diff", StepResult(status="skipped", error="无 MR 链接")
            )

        # 三步跑完（即便含步级 failed/skipped）→ completed；partial 由前端推导。
        run.status = IngestRun.Status.COMPLETED
        run.completed_at = timezone.now()
        await sync_to_async(run.save)(
            update_fields=["status", "completed_at", "updated_at"]
        )
    except Exception as exc:
        # 编排级未捕获异常（非步级降级）：整体 failed + 脱敏 error。
        logger.exception("ingest_orchestration_failed", run_id=str(run.id))
        run.status = IngestRun.Status.FAILED
        run.error = _safe_error(exc)
        run.completed_at = timezone.now()
        await sync_to_async(run.save)(
            update_fields=["status", "error", "completed_at", "updated_at"]
        )

    return run


async def _ingest_mr_diff(run: IngestRun, mr_url: str) -> None:
    """步 3：MR diff 归档 + code_change 入图（独立 try/except，best-effort）。

    SSRF 边界（T-32-01）：``aresolve_repo_and_mr`` 必须命中已落库 Repository 才放行；
    解析不出/不匹配 → skipped，绝不 fetch 任意用户 URL。``archive_code_change`` 内部
    经项目加密凭证取 token，返回 None 时区分「重复幂等命中」（ok/skipped）与
    「凭证缺失/拉取失败」（failed）。
    """
    try:
        resolved = await aresolve_repo_and_mr(mr_url)
        if resolved is None:
            await _write_step(
                run,
                "mr_diff",
                StepResult(
                    status="skipped",
                    error="mr_url 无法解析或未匹配到已落库仓库（SSRF 边界）",
                ),
            )
            return

        repository, mr_iid = resolved
        from knowledge.diff_archive import (
            aarchive_exists,
            archive_code_change,
            aresolve_mr_commit_anchor,
        )
        from knowledge.ingestion import IngestionEvent, ingest_events

        source_id = f"{repository.id}:{mr_iid}"

        # HDIFF-01 / WR-02：用真实 merge_commit_sha 锚定历史 diff，绝不再合成 mr-{iid}。
        # 无法取得 merge_commit_sha（未合并 / 缺凭证 / 元数据拉取失败）→ 如实记 skipped
        # 不静默沿用合成 commit_sha（避免伪历史快照污染对账，T-33-03）。
        anchor = await aresolve_mr_commit_anchor(repository, mr_iid)
        if anchor is None:
            await _write_step(
                run,
                "mr_diff",
                StepResult(
                    status="skipped",
                    error="无法获取 MR merge_commit_sha（未合并或元数据拉取失败），跳过 commit 锚定归档",
                ),
            )
            return

        # commit 锚定真实值：commit_sha=merge_commit_sha、base_branch=target_branch
        # （绝不假设 master，DOMAIN §1.5）；valid_at 经 ingest_events→apply_edge_specs
        # 锚定到 merged_at 业务时间。
        commit_sha = anchor.merge_commit_sha
        base_branch = anchor.target_branch
        branch_name = anchor.source_branch or f"mr/{mr_iid}"
        event_time = anchor.merged_at or timezone.now()

        archive_result = await archive_code_change(
            source_kind=_MR_SOURCE_KIND,
            source_id=source_id,
            repository=repository,
            branch_name=branch_name,
            base_branch=base_branch,
            commit_sha=commit_sha,
            mr_url=mr_url,
            mr_id=mr_iid,
            event_time=event_time,
        )

        if archive_result is None:
            # 返回 None：区分重复幂等命中（已归档，ok）与凭证缺失/拉取失败（failed）。
            if await aarchive_exists(_MR_SOURCE_KIND, source_id):
                await _write_step(
                    run,
                    "mr_diff",
                    StepResult(status="ok", identifier=source_id, link=mr_url),
                )
            else:
                await _write_step(
                    run,
                    "mr_diff",
                    StepResult(
                        status="failed",
                        error="MR diff 归档失败（凭证缺失或平台拉取失败）",
                    ),
                )
            return

        archive = archive_result.archive
        # code_change 事件入图使之可检索；payload 仅摘要（diff 原文绝不进 payload，T-32-02）。
        # kind/origin 用字面值（INV-3：delivery 层不引用 knowledge 模型，读写收口在 knowledge）。
        event = IngestionEvent(
            kind="code_change",
            origin="workflow",
            source_kind=_MR_SOURCE_KIND,
            source_id=source_id,
            title=f"{repository.name} MR !{mr_iid}",
            content=archive_result.content,
            payload={
                "archive_id": str(archive.id),
                "commit_sha": commit_sha,
                "target_branch": base_branch,
                "mr_url": mr_url,
                "mr_id": mr_iid,
                "repository_id": str(repository.id),
                "file_count": archive.file_count,
                "total_additions": archive.total_additions,
                "total_deletions": archive.total_deletions,
            },
            space_id=None,
            repository_id=str(repository.id),
            event_time=event_time,
            edges=tuple(archive_result.edge_specs),
        )
        await ingest_events([event], trigger=_TRIGGER)
        await _write_step(
            run, "mr_diff", StepResult(status="ok", identifier=str(archive.id), link=mr_url)
        )
    except Exception as exc:
        logger.warning(
            "ingest_mr_diff_step_failed",
            run_id=str(run.id),
            error=_safe_error(exc),
            error_type=type(exc).__name__,
        )
        await _write_step(
            run, "mr_diff", StepResult(status="failed", error=_safe_error(exc))
        )


async def _write_step(run: IngestRun, key: str, result: StepResult) -> None:
    """把单步结构化结果写回 ``run.steps[key]`` 并即时持久化（逐步可见）。"""
    run.steps[key] = asdict(result)
    await sync_to_async(run.save)(update_fields=["steps", "updated_at"])
