"""MergeRequestService —— MergeRequest 实体唯一写入入口（MR-01/02，INV-6）。

所有 ``MergeRequest`` / ``MergeRequestEvent`` 的写入都经本 service 收口（旁路写表由
``test_merge_request_inv6_guard`` grep 守护）。模型层无业务方法。

- ``upsert``：按幂等键 ``(platform, repository, external_id)`` 建/更 MR 当前态。
- ``sync_from_webhook``：解析 GitHub/GitLab 入站 webhook payload → 幂等去重（``dedup_key``
  已存在则跳过）→ upsert MR + append ``MergeRequestEvent``（**原始 payload 经
  ``redact_for_ledger`` 脱敏后落库**）。后台/外部触发携 ``initiated_by_user_id``。

写入经 ``AuditService.aemit``（component=initiatives）；async ORM 走 ``sync_to_async``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction

from audit.services import taxonomy
from audit.services.audit_service import AuditService
from initiatives.models import MergeRequest, MergeRequestEvent, MRPlatform, MRStatus
from interactions.redaction import redact_for_ledger

logger = structlog.get_logger(__name__)

__all__ = ["MergeRequestService", "ParsedMergeRequest", "MergeRequestSyncError"]

_COMPONENT = "initiatives"


class MergeRequestSyncError(Exception):
    """MR webhook 同步非法（如未知平台，API 层转 400）。"""


@dataclass
class ParsedMergeRequest:
    """从 webhook payload 解析出的 MR 归一化态。"""

    external_id: str
    url: str = ""
    title: str = ""
    source_branch: str = ""
    target_branch: str = ""
    status: str = MRStatus.OPEN
    review_status: str = ""
    event_type: str = ""
    repo_url: str = ""


def _normalize_repo_url(url: str) -> str:
    """归一化 git url（去 .git / 末尾斜杠 / 小写）便于跨平台匹配仓库。"""
    u = (url or "").strip().lower().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    return u


def _parse_github(payload: dict[str, Any]) -> ParsedMergeRequest | None:
    """解析 GitHub pull_request / pull_request_review webhook。"""
    pr = payload.get("pull_request") or {}
    if not pr:
        return None
    number = pr.get("number")
    if number is None:
        return None
    merged = bool(pr.get("merged"))
    state = str(pr.get("state") or "open").lower()
    if merged:
        status = MRStatus.MERGED
    elif state == "closed":
        status = MRStatus.CLOSED
    else:
        status = MRStatus.OPEN
    review_status = ""
    event_type = str(payload.get("action") or "")
    review = payload.get("review") or {}
    if review:
        review_status = str(review.get("state") or "").lower()
        event_type = f"review:{review_status}" if review_status else "review"
    repo = payload.get("repository") or {}
    return ParsedMergeRequest(
        external_id=str(number),
        url=str(pr.get("html_url") or ""),
        title=str(pr.get("title") or ""),
        source_branch=str((pr.get("head") or {}).get("ref") or ""),
        target_branch=str((pr.get("base") or {}).get("ref") or ""),
        status=status,
        review_status=review_status,
        event_type=event_type or "pull_request",
        repo_url=str(repo.get("html_url") or repo.get("clone_url") or ""),
    )


def _parse_gitlab(payload: dict[str, Any]) -> ParsedMergeRequest | None:
    """解析 GitLab merge_request webhook（object_attributes）。"""
    attrs = payload.get("object_attributes") or {}
    if not attrs:
        return None
    iid = attrs.get("iid") or attrs.get("id")
    if iid is None:
        return None
    state = str(attrs.get("state") or "opened").lower()
    status_map = {
        "opened": MRStatus.OPEN,
        "reopened": MRStatus.OPEN,
        "locked": MRStatus.OPEN,
        "merged": MRStatus.MERGED,
        "closed": MRStatus.CLOSED,
    }
    status = status_map.get(state, MRStatus.OPEN)
    action = str(attrs.get("action") or "")
    review_status = ""
    if action == "approved":
        review_status = "approved"
    elif action == "unapproved":
        review_status = "unapproved"
    repo = payload.get("repository") or {}
    project = payload.get("project") or {}
    return ParsedMergeRequest(
        external_id=str(iid),
        url=str(attrs.get("url") or ""),
        title=str(attrs.get("title") or ""),
        source_branch=str(attrs.get("source_branch") or ""),
        target_branch=str(attrs.get("target_branch") or ""),
        status=status,
        review_status=review_status,
        event_type=f"merge_request:{action}" if action else "merge_request",
        repo_url=str(
            repo.get("git_http_url") or project.get("web_url") or project.get("git_http_url") or ""
        ),
    )


class MergeRequestService:
    """MergeRequest / MergeRequestEvent 唯一写入入口（INV-6）。"""

    async def upsert(
        self,
        *,
        platform: str,
        external_id: str,
        repository: Any = None,
        project: Any = None,
        work_item: Any = None,
        url: str = "",
        title: str = "",
        source_branch: str = "",
        target_branch: str = "",
        status: str = MRStatus.OPEN,
        review_status: str = "",
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> tuple[MergeRequest, bool]:
        """按幂等键 ``(platform, repository, external_id)`` 建/更 MR 当前态。返回 ``(mr, created)``。"""
        mr, created = await self._upsert_locked(
            platform=platform,
            external_id=external_id,
            repository=repository,
            project=project,
            work_item=work_item,
            url=url,
            title=title,
            source_branch=source_branch,
            target_branch=target_branch,
            status=status,
            review_status=review_status,
        )
        await self._emit(
            mr=mr,
            created=created,
            actor=actor,
            initiated_by_user_id=initiated_by_user_id,
        )
        return mr, created

    @sync_to_async
    def _upsert_locked(
        self,
        *,
        platform: str,
        external_id: str,
        repository: Any,
        project: Any,
        work_item: Any,
        url: str,
        title: str,
        source_branch: str,
        target_branch: str,
        status: str,
        review_status: str,
    ) -> tuple[MergeRequest, bool]:
        with transaction.atomic():
            repo_id = getattr(repository, "id", repository)
            qs = MergeRequest.objects.select_for_update().filter(
                platform=platform, external_id=external_id, repository_id=repo_id
            )
            mr = qs.first()
            if mr is None:
                mr = MergeRequest.objects.create(
                    platform=platform,
                    external_id=external_id,
                    repository=repository,
                    project=project,
                    work_item=work_item,
                    url=url,
                    title=title,
                    source_branch=source_branch,
                    target_branch=target_branch,
                    status=status,
                    review_status=review_status,
                )
                return mr, True
            # 更新可变字段（status/review/url/title/branches；保留既有非空关联）。
            mr.url = url or mr.url
            mr.title = title or mr.title
            mr.source_branch = source_branch or mr.source_branch
            mr.target_branch = target_branch or mr.target_branch
            mr.status = status or mr.status
            if review_status:
                mr.review_status = review_status
            if project is not None and mr.project_id is None:
                mr.project = project
            if work_item is not None and mr.work_item_id is None:
                mr.work_item = work_item
            mr.save(
                update_fields=[
                    "url",
                    "title",
                    "source_branch",
                    "target_branch",
                    "status",
                    "review_status",
                    "project",
                    "work_item",
                    "updated_at",
                ]
            )
            return mr, False

    async def sync_from_webhook(
        self,
        *,
        platform: str,
        payload: dict[str, Any],
        dedup_key: str | None = None,
        initiated_by_user_id: Any = "system",
    ) -> dict[str, Any]:
        """解析入站 webhook → 幂等去重 → upsert MR + append 脱敏事件（MR-02）。

        Returns:
            ``{"created": bool, "deduped": bool, "ignored": bool, "mr_id": str|None, "status": str}``。
        """
        if platform == MRPlatform.GITHUB:
            parsed = _parse_github(payload)
        elif platform == MRPlatform.GITLAB:
            parsed = _parse_gitlab(payload)
        else:
            raise MergeRequestSyncError(f"未知平台: {platform}")

        if parsed is None or not parsed.external_id:
            return {"ignored": True, "created": False, "deduped": False, "mr_id": None}

        key = dedup_key or (
            f"{platform}:{parsed.external_id}:{parsed.event_type}:"
            f"{parsed.status}:{parsed.review_status}"
        )

        repository = await self._match_repository(parsed.repo_url)
        result = await self._sync_locked(
            platform=platform,
            parsed=parsed,
            dedup_key=key,
            repository=repository,
            payload=payload,
            initiated_by_user_id=str(initiated_by_user_id or "system"),
        )
        if result.get("deduped"):
            logger.info(
                "merge_request_webhook_deduped",
                platform=platform,
                external_id=parsed.external_id,
                component=_COMPONENT,
                category="caller",
            )
            return result

        mr = result["mr"]
        await self._emit(
            mr=mr,
            created=result["created"],
            actor=None,
            initiated_by_user_id=initiated_by_user_id,
        )
        return {
            "created": result["created"],
            "deduped": False,
            "ignored": False,
            "mr_id": str(mr.id),
            "status": mr.status,
        }

    @sync_to_async
    def _match_repository(self, repo_url: str) -> Any:
        if not repo_url:
            return None
        from repositories.models import Repository

        target = _normalize_repo_url(repo_url)
        for repo in Repository.objects.filter(is_deleted=False).only("id", "git_url"):
            if _normalize_repo_url(repo.git_url) == target:
                return repo
        return None

    @sync_to_async
    def _sync_locked(
        self,
        *,
        platform: str,
        parsed: ParsedMergeRequest,
        dedup_key: str,
        repository: Any,
        payload: dict[str, Any],
        initiated_by_user_id: str,
    ) -> dict[str, Any]:
        with transaction.atomic():
            # 幂等去重：同 dedup_key 已处理 → 跳过（重复投递不重复同步）。
            if MergeRequestEvent.objects.filter(dedup_key=dedup_key).exists():
                return {"deduped": True, "created": False, "mr_id": None}

            repo_id = getattr(repository, "id", None)
            mr = (
                MergeRequest.objects.select_for_update()
                .filter(
                    platform=platform,
                    external_id=parsed.external_id,
                    repository_id=repo_id,
                )
                .first()
            )
            created = False
            if mr is None:
                mr = MergeRequest.objects.create(
                    platform=platform,
                    external_id=parsed.external_id,
                    repository=repository,
                    url=parsed.url,
                    title=parsed.title,
                    source_branch=parsed.source_branch,
                    target_branch=parsed.target_branch,
                    status=parsed.status,
                    review_status=parsed.review_status,
                )
                created = True
            else:
                mr.url = parsed.url or mr.url
                mr.title = parsed.title or mr.title
                mr.source_branch = parsed.source_branch or mr.source_branch
                mr.target_branch = parsed.target_branch or mr.target_branch
                mr.status = parsed.status or mr.status
                if parsed.review_status:
                    mr.review_status = parsed.review_status
                mr.save(
                    update_fields=[
                        "url",
                        "title",
                        "source_branch",
                        "target_branch",
                        "status",
                        "review_status",
                        "updated_at",
                    ]
                )

            # append-only 事件留痕：原始 payload 经 redact_for_ledger 脱敏后落库（绝不明文）。
            try:
                MergeRequestEvent.objects.create(
                    merge_request=mr,
                    event_type=parsed.event_type,
                    dedup_key=dedup_key,
                    raw_payload=redact_for_ledger(payload),
                    initiated_by_user_id=initiated_by_user_id,
                )
            except IntegrityError:
                # 并发重复投递撞 dedup_key unique → 视为已处理（幂等）。
                return {"deduped": True, "created": False, "mr_id": str(mr.id)}

            return {"deduped": False, "created": created, "mr": mr}

    async def _emit(
        self,
        *,
        mr: MergeRequest,
        created: bool,
        actor: Any,
        initiated_by_user_id: Any,
    ) -> None:
        actor_id = initiated_by_user_id or getattr(actor, "id", None)
        await AuditService.aemit(
            action=taxonomy.ACTION_MERGE_REQUEST_SYNCED,
            actor=actor,
            target_type="merge_request",
            target_id=mr.id,
            target_repr=f"{mr.platform}:{mr.external_id}",
            after={
                "platform": mr.platform,
                "external_id": mr.external_id,
                "status": mr.status,
                "review_status": mr.review_status,
                "created": created,
            },
            metadata={
                "component": _COMPONENT,
                "category": "caller",
                "initiated_by_user_id": str(actor_id) if actor_id else "system",
            },
            source="webhook",
        )
