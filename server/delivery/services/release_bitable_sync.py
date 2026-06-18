"""从飞书上线文档（Bitable）同步上线业务 + MR 链接（预览 + 批量入库编排）。

两段式（对齐用户需求「先检索 → 队列预览 → 勾选 → 批量开始」）：

1. **预览**（``fetch_preview``）：用 DB 已配的飞书自建应用凭证分页拉 Bitable 记录，
   把每行解析成 ``ReleaseRowPreview``（上线业务 / MR / 看板id / 分类 / 上线日期 +
   是否命中已落库仓库）——**只读、不落库、不摄取**。

2. **批量同步**（``sync_release_row``，每行一个后台任务，复用 ``IngestRun`` + batch_id
   做进度）：每行
   - 落 Release 账本（``ReleaseService`` 唯一写入口：``ReleaseRecord`` +
     ``ReleaseArtifact(type=mr)``，看板id → ``work_item_external_id``）；
   - 复用既有 ``_ingest_mr_diff`` 把 MR diff 入知识库（archive + 入图）。

看板id 解析（用户规则）：优先 ``看板id`` 列；为空则从 ``feature分支`` 用正则提取
（``m-<数字>`` 或 ``<数字>-m``，如 ``m-6764053712`` / ``6764053712-m``）。

凭证：复用 ``feishu_bitable`` 的开放平台 token 体系（飞书 IM 配置 = 自建应用凭证），
项目级优先、系统级回退。绝不取项目 plugin token。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from delivery.models import (
    IngestRun,
    ReleaseBatch,
    build_bitable_record_key,
)
from delivery.services.ingest_orchestrator import (
    StepResult,
    _ingest_mr_diff,
    _safe_error,
    _write_step,
)
from delivery.services.ingest_parsing import (
    _norm_path,
    _repo_host_path,
    parse_mr_url,
)
from delivery.services.release_service import ReleaseService
from services.feishu_bitable import (
    BitableClient,
    _aget_system_open_platform_credentials,
    create_bitable_client_for_project,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "ReleaseRowPreview",
    "DEFAULT_BITABLE_APP_TOKEN",
    "DEFAULT_BITABLE_TABLE_ID",
    "aget_bitable_client",
    "aget_feishu_project_key",
    "build_kanban_url",
    "fetch_preview",
    "parse_release_row",
    "extract_kanban_id",
    "sync_release_row",
]

# 默认指向当前上线文档表（后续可移到 SystemSetting；请求可覆盖）。
DEFAULT_BITABLE_APP_TOKEN = "CFQCbbtoVaEhT8sM9XPcPvExnGe"
DEFAULT_BITABLE_TABLE_ID = "tbls2oct7kJNjXtf"

# Bitable 列名（真实上线文档表结构，经开放平台 fields 接口确认）。
_COL_BUSINESS = "上线业务"
_COL_MR_MASTER = "MR（合并Master）"
_COL_KANBAN = "看板id"
_COL_BRANCH = "feature分支"
_COL_CATEGORY = "上线分类"
_COL_DATE = "上线日期"

# 预览默认按上线日期倒序（最近上线优先）：开放平台 GET 列出记录默认按记录创建顺序
# （最早在前），导致首页全是 24 年的历史行、缺 feature 分支 → 看板id 一片空。倒序后
# 首页即最近上线、带 m-<数字> 分支的行，看板id 才能解析出来（用户反馈核心）。
_RELEASE_SORT = [f"{_COL_DATE} DESC"]

# 看板 id 至少 4 位数字（规避 tag 版本等小数字误命中）。
# 前缀 ``m-<数字>``：``m`` 须为词首（前界非字母数字），避免 ``system-12345`` 误命中。
# 后缀 ``<数字>-m``：``m`` 后须为 token 边界（非字母数字），避免 ``12345-master`` 误命中。
_KANBAN_BRANCH_PREFIX_RE = re.compile(r"(?<![a-z0-9])m-(\d{4,})", re.IGNORECASE)
_KANBAN_BRANCH_SUFFIX_RE = re.compile(r"(\d{4,})-m(?![a-z0-9])", re.IGNORECASE)
_DIGITS_RE = re.compile(r"\d{4,}")


# 飞书项目工作项详情 URL 模板（沿用 mcp_tools/work_item_context_service 既有约定：
# URL type 段用通用 ``issue`` 重定向即可，无需 API type_key，PF-09）。
_KANBAN_URL_TEMPLATE = "https://project.feishu.cn/{key}/issue/detail/{id}"


@dataclass(frozen=True)
class ReleaseRowPreview:
    """单行 Bitable 上线记录的解析预览（前端队列展示用）。"""

    record_id: str
    business: str
    mr_url: str
    kanban_id: int | None
    kanban_source: str
    kanban_url: str
    category: str
    release_date: int | None  # ms epoch
    feature_branch: str
    repo_matched: bool
    repo_name: str
    raw_fields: dict[str, Any]

    @property
    def ingestable(self) -> bool:
        """是否可入库：有 MR 且命中已落库仓库。"""
        return bool(self.mr_url and self.repo_matched)


def _as_text(value: Any) -> str:
    """把 Bitable 字段值规整成文本（兼容 str / 数值 / URL dict / 富文本段数组）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        # URL 字段 {link,text}；用户字段 {name}；文本段 {text}
        return str(value.get("link") or value.get("text") or value.get("name") or "")
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(
                    str(item.get("text") or item.get("name") or item.get("link") or "")
                )
        return "".join(parts)
    return str(value)


def extract_kanban_id(kanban_value: Any, branch_value: Any) -> tuple[int | None, str]:
    """解析看板 id：优先 ``看板id`` 列，回退 ``feature分支``（m-<数字> / <数字>-m）。

    Returns:
        ``(kanban_id, source)``；解析不出 → ``(None, "")``。
    """
    kanban_text = _as_text(kanban_value).strip()
    if kanban_text.isdigit():
        return int(kanban_text), _COL_KANBAN

    branch = _as_text(branch_value)
    m = _KANBAN_BRANCH_PREFIX_RE.search(branch) or _KANBAN_BRANCH_SUFFIX_RE.search(branch)
    if m:
        return int(m.group(1)), _COL_BRANCH

    # 看板id 列里夹杂非数字时兜底抽数字串
    m = _DIGITS_RE.search(kanban_text)
    if m:
        return int(m.group(0)), _COL_KANBAN
    return None, ""


def build_kanban_url(kanban_id: int | None, feishu_project_key: str) -> str:
    """看板 id + 飞书空间 key → 工作项详情 URL；缺任一 → 空串（前端据此降级为纯文本）。"""
    if kanban_id is None or not feishu_project_key:
        return ""
    return _KANBAN_URL_TEMPLATE.format(key=feishu_project_key, id=kanban_id)


def parse_release_row(
    record: dict[str, Any],
    *,
    repo_index: dict[tuple[str, str], str],
    feishu_project_key: str = "",
) -> ReleaseRowPreview | None:
    """把一条 Bitable record 解析成 ``ReleaseRowPreview``；纯父记录/空行 → None。

    跳过既无「上线业务」又无 MR 的行（父记录/聚合行）。``feishu_project_key`` 非空时
    据看板 id 拼工作项详情 URL（供前端点击直达飞书项目；为空则不出链接）。
    """
    fields = record.get("fields", {}) or {}
    record_id = record.get("record_id") or record.get("id") or ""

    business = _as_text(fields.get(_COL_BUSINESS)).strip()
    mr_url = _as_text(fields.get(_COL_MR_MASTER)).strip()
    feature_branch = _as_text(fields.get(_COL_BRANCH)).strip()

    if not business and not mr_url:
        return None

    kanban_id, kanban_source = extract_kanban_id(
        fields.get(_COL_KANBAN), fields.get(_COL_BRANCH)
    )

    # 上线日期（ms epoch）
    release_date: int | None = None
    raw_date = fields.get(_COL_DATE)
    if isinstance(raw_date, (int, float)):
        release_date = int(raw_date)

    # 仓库匹配（内存索引，避免逐行扫库）
    repo_name = ""
    if mr_url:
        ref = parse_mr_url(mr_url)
        if ref is not None:
            repo_name = repo_index.get((ref.host, _norm_path(ref.project_path)), "")

    return ReleaseRowPreview(
        record_id=str(record_id),
        business=business,
        mr_url=mr_url,
        kanban_id=kanban_id,
        kanban_source=kanban_source,
        kanban_url=build_kanban_url(kanban_id, feishu_project_key),
        category=_as_text(fields.get(_COL_CATEGORY)).strip(),
        release_date=release_date,
        feature_branch=feature_branch,
        repo_matched=bool(repo_name),
        repo_name=repo_name,
        raw_fields=fields,
    )


async def aget_bitable_client() -> BitableClient | None:
    """构造 BitableClient：项目级飞书自建应用凭证优先，回退系统级；都无 → None。"""
    from projects.models import Project

    async for project in Project.objects.all():
        if project.feishu_app_id and project.feishu_app_secret_encrypted:
            return await create_bitable_client_for_project(project)
    credentials = await _aget_system_open_platform_credentials()
    if credentials:
        return BitableClient(app_id=credentials[0], app_secret=credentials[1])
    return None


async def aget_feishu_project_key() -> str:
    """取一个飞书空间 key（``Project.feishu_project_key``）用于拼看板 URL；无 → 空串。

    看板 id 是飞书项目工作项 id，URL 需空间 simple_name（即 ``feishu_project_key``）。
    本部署通常单飞书空间，取首个已配 key 的 Project 即可；无则返回空串（前端降级为纯文本）。
    """
    from projects.models import Project

    project = await Project.objects.filter(
        feishu_project_key__isnull=False
    ).exclude(feishu_project_key="").afirst()
    return project.feishu_project_key if project else ""


async def _abuild_repo_index() -> dict[tuple[str, str], str]:
    """构建 ``(host, norm_path) → repo_name`` 索引（一次扫库，供预览内存匹配）。"""
    from repositories.models import Repository

    index: dict[tuple[str, str], str] = {}
    async for repo in Repository.objects.all():
        hp = _repo_host_path(repo)
        if hp is not None:
            index[(hp[0], _norm_path(hp[1]))] = repo.name
    return index


async def fetch_preview(
    *,
    app_token: str,
    table_id: str,
    page_token: str | None = None,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页拉 Bitable 并解析成预览行（只读，不落库）。

    Returns:
        ``{rows, page_token, has_more, total}``；rows 为 ``ReleaseRowPreview`` dict。

    Raises:
        ValueError: 未配置飞书开放平台凭证（端点转 400）。
    """
    client = await aget_bitable_client()
    if client is None:
        raise ValueError(
            "未配置飞书开放平台应用凭证（app_id/app_secret）。"
            "请在某个空间的「飞书 IM 配置」或系统设置中配置飞书自建应用。"
        )

    data = await client.list_records(
        app_token,
        table_id,
        page_token=page_token,
        page_size=page_size,
        sort=_RELEASE_SORT,
    )
    repo_index = await _abuild_repo_index()
    feishu_project_key = await aget_feishu_project_key()

    rows: list[dict[str, Any]] = []
    for record in data.get("items", []):
        parsed = parse_release_row(
            record, repo_index=repo_index, feishu_project_key=feishu_project_key
        )
        if parsed is None:
            continue
        rows.append(
            {
                "record_id": parsed.record_id,
                "business": parsed.business,
                "mr_url": parsed.mr_url,
                "kanban_id": parsed.kanban_id,
                "kanban_source": parsed.kanban_source,
                "kanban_url": parsed.kanban_url,
                "category": parsed.category,
                "release_date": parsed.release_date,
                "feature_branch": parsed.feature_branch,
                "repo_matched": parsed.repo_matched,
                "repo_name": parsed.repo_name,
                "ingestable": parsed.ingestable,
                "raw_fields": parsed.raw_fields,
            }
        )

    return {
        "rows": rows,
        "page_token": data.get("page_token"),
        "has_more": data.get("has_more", False),
        "total": data.get("total"),
    }


async def aresolve_release_batch(*, app_token: str, table_id: str) -> ReleaseBatch:
    """幂等取/建该表对应的 ReleaseBatch（经 ReleaseService，INV-6，external_ref 收敛同批）。"""
    external_ref = f"{app_token}:{table_id}"
    await ReleaseService().ingest_batch(
        raw_rows=[],
        source="bitable",
        batch_meta={
            "external_ref": external_ref,
            "name": f"上线文档同步 {table_id}",
        },
    )
    return await ReleaseBatch.objects.aget(external_ref=external_ref)


async def sync_release_row(run_id: str, batch_id: str, payload: dict[str, Any]) -> None:
    """单行同步编排：落 Release 账本 + MR diff 入知识库，进度写回 ``IngestRun(run_id)``。

    ``steps`` 两步：``release``（账本）+ ``mr_diff``（知识库，复用既有 best-effort）。
    """
    run = await IngestRun.objects.aget(id=run_id)
    app_token = payload.get("app_token", "")
    table_id = payload.get("table_id", "")
    record_id = payload.get("record_id", "")
    mr_url = (payload.get("mr_url") or "").strip()

    try:
        # === 步 1：Release 账本（ReleaseService 唯一写入口）===
        try:
            batch = await ReleaseBatch.objects.aget(id=batch_id)
            raw_row = {
                **(payload.get("raw_fields") or {}),
                "record_id": record_id,
                "bitable_record_key": build_bitable_record_key(
                    app_token, table_id, record_id
                ),
                # 看板id → work_item_external_id（ReleaseService 据此反查/占位 WorkItem）
                "work_item_external_id": payload.get("kanban_id"),
                "status": payload.get("category", ""),
                "note": payload.get("business", ""),
            }
            service = ReleaseService()
            record = await service.upsert_record(
                batch=batch, raw_row=raw_row, source="bitable"
            )
            if mr_url:
                await service.add_artifact(
                    release_record=record,
                    artifact_type="mr",
                    ref=mr_url,
                    payload={
                        "business": payload.get("business", ""),
                        "kanban_id": payload.get("kanban_id"),
                        "feature_branch": payload.get("feature_branch", ""),
                    },
                )
            await _write_step(
                run, "release", StepResult(status="ok", identifier=str(record.id))
            )
        except Exception as exc:
            logger.warning(
                "release_sync_ledger_step_failed",
                run_id=str(run.id),
                error=_safe_error(exc),
            )
            await _write_step(
                run, "release", StepResult(status="failed", error=_safe_error(exc))
            )

        # === 步 2：MR diff 入知识库（复用既有 best-effort 编排）===
        if mr_url:
            await _ingest_mr_diff(run, mr_url)
        else:
            await _write_step(
                run, "mr_diff", StepResult(status="skipped", error="无 MR 链接")
            )

        run.status = IngestRun.Status.COMPLETED
        run.completed_at = timezone.now()
        await sync_to_async(run.save)(
            update_fields=["status", "completed_at", "updated_at"]
        )
    except Exception as exc:
        logger.exception("release_sync_row_failed", run_id=str(run.id))
        run.status = IngestRun.Status.FAILED
        run.error = _safe_error(exc)
        run.completed_at = timezone.now()
        await sync_to_async(run.save)(
            update_fields=["status", "error", "completed_at", "updated_at"]
        )
