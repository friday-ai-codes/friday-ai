"""可复用跨仓 PR cross-ref + 方案/工作项追溯 helper（PR-02，wave 收尾路径专用）。

提供多仓 wave 编码收尾（``AICodingNode._finalize_and_notify``）批量创建 MR 后的描述
回写编排：

- ``generate_cross_reference_section``：纯函数，渲染「## 关联 PR」段（兄弟仓链接，排除自身）。
- ``render_traceability_section``：async，经 ``plan_version_id → PlanVersion →
  TechnicalPlan → WorkItem`` 反查渲染「## 关联方案 / 工作项」段（fail-soft）。
- ``add_cross_references``：async，对成功 MR 名单逐个回写 ``原描述 + cross-ref + 追溯段``，
  GitHub ``_get_repo().get_pull().edit(body=)`` / GitLab ``_get_project().mergerequests
  .get().save()``（经 ``asyncio.to_thread`` 包同步 SDK），逐 PR try/except fail-soft。

> 同源 ``CreatePRNode._generate_cross_reference_section`` / ``_add_cross_references``
> （``workflows/nodes/git/pr.py``）。本 helper 为 wave 收尾路径专用——``CreatePRNode``
> （手动节点，英文「## Related PRs」+ 共享单一 body + 并行 gather 回写）保持原样不改，
> 后续统一复用本 helper 留 backlog（D-09 备选：最小 diff / 零回归）。

安全红线：日志仅记 ``mr_url`` / ``repository_name`` / ``has_token`` 布尔——token/凭证绝不
入日志或 PR 描述。
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from repositories.models import Repository
from services.git_credentials import aresolve_git_token
from services.git_platform import get_git_platform_client

logger = structlog.get_logger()


def generate_cross_reference_section(
    current_pr_url: str,
    all_successful: list[dict[str, Any]],
) -> str:
    """渲染「## 关联 PR」段：列出其它兄弟仓 PR 链接（排除自身）。

    Args:
        current_pr_url: 当前 PR 的 ``mr_url``（从列表中排除）。
        all_successful: 全部成功 MR 结果（含 ``mr_url`` / ``repository_name``）。

    Returns:
        Markdown 段；无兄弟（单 PR）时返回空串。
    """
    other = [r for r in all_successful if r.get("mr_url") != current_pr_url]
    if not other:
        return ""

    lines = ["\n---", "## 关联 PR", ""]
    for r in other:
        repo_name = r.get("repository_name", "unknown")
        mr_url = r.get("mr_url", "")
        lines.append(f"- [{repo_name}]({mr_url})")

    return "\n".join(lines)


async def render_traceability_section(plan_version_id: str | None) -> str:
    """渲染「## 关联方案 / 工作项」段；任一跳取不到 / 异常 → 返回空串（fail-soft）。

    经 ``plan_version_id → PlanVersion → TechnicalPlan → WorkItem`` 逐跳反查，全程用
    ``*_id`` 标量 + ``afirst()``（async ORM 安全，规避 ``SynchronousOnlyOperation``）。

    Args:
        plan_version_id: 方案版本 ID（``plan_data.plan_version_id``）。

    Returns:
        Markdown 段；链断或异常时返回空串。
    """
    if not plan_version_id:
        return ""
    try:
        # lazy import 防循环依赖。
        from delivery.models import ArtifactVersion, WorkItem

        av = await ArtifactVersion.objects.filter(id=plan_version_id).afirst()
        if av is None:
            return ""
        # Artifact ← ArtifactVersion.artifact（FK）；用 artifact_id 标量再查规避 lazy-FK。
        artifact = await ArtifactVersion.objects.filter(id=av.id).values(
            "artifact_id", "version_no", "artifact__work_item_id"
        ).afirst()
        if artifact is None:
            return ""

        lines = [
            "\n---",
            "## 关联方案 / 工作项",
            "",
            f"- 技术方案: `{artifact['artifact_id']}` (v{artifact['version_no']})",
        ]
        # WorkItem ← Artifact.work_item（nullable FK）；用 work_item_id 标量。
        work_item_id = artifact.get("artifact__work_item_id")
        if work_item_id:
            wi = await WorkItem.objects.filter(id=work_item_id).afirst()
            if wi is not None:
                # WorkItem 无通用 url 字段——用飞书三元组 + 标题标识，有 prd_url 才附链接
                # （不构造臆造 URL）。
                item_line = f"- 工作项: {wi.work_item_type}/{wi.work_item_id} {wi.title}"
                if wi.prd_url:
                    item_line += f" ({wi.prd_url})"
                lines.append(item_line)

        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001 — 追溯增强 fail-soft，绝不阻塞收尾
        logger.warning("pr_traceability_render_failed", error=str(exc))
        return ""


async def add_cross_references(
    successful_mrs: list[dict[str, Any]],
    *,
    plan_version_id: str | None,
) -> dict[str, bool]:
    """对成功 MR 名单回写描述：追加 cross-ref 段 + 追溯段（逐 PR fail-soft）。

    先渲染一次追溯段（全名单共享），再对每个 MR 经其 ``repository_id`` 重取 ``Repository``
    + ``aresolve_git_token`` + ``get_git_platform_client``，按平台回写
    ``原 description + cross-ref 段 + 追溯段``。逐 PR try/except 隔离——单 PR 失败 / 缺凭证
    标 False 不抛、不影响其它 PR。

    Args:
        successful_mrs: 成功 MR 名单（含 ``repository_id`` / ``repository_name`` /
            ``mr_url`` / ``mr_id`` / ``description``）。
        plan_version_id: 方案版本 ID，用于追溯段反查。

    Returns:
        ``{mr_url: 是否回写成功}`` 映射。
    """
    results: dict[str, bool] = {}
    # 追溯段一次性渲染（fail-soft 已内含，异常返回空串）。
    traceability = await render_traceability_section(plan_version_id)

    for mr in successful_mrs:
        mr_url = mr.get("mr_url", "")
        repo_id = mr.get("repository_id", "")
        repo_name = mr.get("repository_name")
        try:
            repository = await Repository.objects.filter(id=repo_id).afirst()
            if repository is None:
                logger.warning(
                    "coding_cross_reference_skip_no_repo",
                    mr_url=mr_url,
                    repository_name=repo_name,
                )
                results[mr_url] = False
                continue

            section = generate_cross_reference_section(mr_url, successful_mrs)
            new_body = (mr.get("description") or "") + section + traceability

            token = await aresolve_git_token(repository)
            if not token:
                logger.warning(
                    "coding_cross_reference_skip_no_token",
                    mr_url=mr_url,
                    repository_name=repo_name,
                    has_token=False,
                )
                results[mr_url] = False
                continue

            client = get_git_platform_client(repository, token)
            mr_id = mr.get("mr_id", "")

            if hasattr(client, "_get_repo"):
                # GitHub：mr_id = pr.number
                repo_obj = client._get_repo()
                pr = await asyncio.to_thread(repo_obj.get_pull, int(mr_id))
                await asyncio.to_thread(pr.edit, body=new_body)
            elif hasattr(client, "_get_project"):
                # GitLab：mr_id = mr.iid
                project = client._get_project()
                mr_obj = await asyncio.to_thread(project.mergerequests.get, int(mr_id))
                mr_obj.description = new_body
                await asyncio.to_thread(mr_obj.save)
            else:
                logger.warning(
                    "coding_cross_reference_unknown_platform",
                    mr_url=mr_url,
                    repository_name=repo_name,
                )
                results[mr_url] = False
                continue

            logger.info(
                "coding_cross_reference_added",
                mr_url=mr_url,
                repository_name=repo_name,
                has_token=True,
            )
            results[mr_url] = True
        except Exception as exc:  # noqa: BLE001 — 逐 PR cross-ref 回写 fail-soft
            logger.warning(
                "coding_cross_reference_failed",
                mr_url=mr_url,
                repository_name=repo_name,
                error=str(exc),
            )
            results[mr_url] = False

    return results
