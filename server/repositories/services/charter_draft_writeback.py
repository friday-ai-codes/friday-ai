"""确认门章程回灌的**唯一写入面**（Phase 112-05，CHARTER-03）。

三段契约：

- **本模块是确认门章程回灌的唯一写入面**：``charter_service.adraft_charter`` 只接受
  「自己蒸馏出的草案」，不接受调用方传入的草案内容——确认门需要把人工裁决出的职责
  聚合与移除理由定向写成草案，故新增 :func:`asubmit_charter_draft`。
  ``charter_service.py`` **逐字未改**（本 plan 只 import 并调用其现有公开 API）。
- **归一逐字复用 ``charter_service.normalize_charter_draft``**，绝不另写一套白名单：
  ``owned_domains.status`` 枚举回退、``boundaries`` 缺 rule 跳过、正文截断、
  ``evolution`` 枚举回退全部与 AI 起草路径同源，演进时只有一处要改。
- **三分支落库语义与 ``adraft_charter`` 等价**，且对 ``human_confirmed`` 章程**只写
  ``draft_content``**（CHARTER-01 不变量：AI 不覆盖人工）：

  =========================  ==================================================
  DB 现状                    行为
  =========================  ==================================================
  无 charter                 ``create(source=ai_draft, version=1)``
  已有且 ``source=ai_draft``  正式字段就地更新（``version`` 不变）
  已有 ``source=human_confirmed``  **只写 ``draft_content``**，正式字段一个不碰
  =========================  ==================================================

``merge=True``（缺省）时对三个 list 字段做**按 key 去重的追加合并**
（``domain`` / ``rule`` / ``(kind,target)`` 为去重键），标量字段仅在草案非空时覆盖——
回灌是「补一条领域/禁区候选」，不该把既有条目冲掉。

best-effort：任何异常经 ``redact_secrets_in_text`` 脱敏后 warning 并返回 ``None``——
章程回灌绝不反噬确认门的锁定动作（锁定是人工裁决的结果，不能因旁路依赖失败回滚）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from asgiref.sync import sync_to_async

from common.logging import redact_secrets_in_text

if TYPE_CHECKING:
    from repositories.models import RepoCharter

logger = structlog.get_logger(__name__)

__all__ = ["asubmit_charter_draft"]

# 合并键：按业务标识去重，避免同一领域/禁区被重复回灌成多条
_MERGE_KEYS = {
    "owned_domains": ("domain",),
    "boundaries": ("rule",),
    "placement_preferences": ("kind", "target"),
}
_SCALAR_FIELDS = ("positioning", "audience", "form", "evolution")

# `owned_domains[].domain` 的长度兜底：它是被 `score_charter_match` 拿去做子串 / n-gram
# 匹配的**领域名**，超长文本（如一整段职责描述）与任意需求几乎必然有交集，会让该仓对
# 什么需求都命中。调用方应给短领域名，这里只是最后一道防线。
_MAX_DOMAIN_CHARS = 40


def _merge_key(field: str, item: Any) -> tuple:
    keys = _MERGE_KEYS[field]
    src = item if isinstance(item, dict) else {}
    return tuple(str(src.get(key) or "") for key in keys)


def _merge_list(field: str, existing: Any, incoming: list) -> list:
    """按 key 去重的追加合并：既有条目保留在前，新 key 追加在后。"""
    merged = [item for item in (existing or []) if isinstance(item, dict)]
    seen = {_merge_key(field, item) for item in merged}
    for item in incoming:
        key = _merge_key(field, item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


async def asubmit_charter_draft(
    repository_id: str,
    draft: dict,
    *,
    initiated_by_user_id: str = "system",
    merge: bool = True,
) -> RepoCharter | None:
    """把调用方给出的章程草案定向写入（``source=ai_draft`` 语义，人工 confirm 才生效）。

    Args:
        repository_id: 目标仓 id（不存在 / 非法 uuid → 返回 ``None``，不抛）。
        draft: 章程草案 dict（经 ``normalize_charter_draft`` 白名单归一）。
        initiated_by_user_id: 触发用户归因（无触发用户记 ``system``）。
        merge: ``True``（缺省）按 key 去重追加合并 list 字段、标量仅非空覆盖；
            ``False`` 按覆盖语义（与 ``adraft_charter`` 的整份替换一致）。

    Returns:
        写入后的 ``RepoCharter``；依赖不可用 / 仓不存在 / 落库失败 → ``None``。
    """
    # 归一逐字复用 charter_service 的公开白名单（绝不另写一套）
    from repositories.services.charter_service import normalize_charter_draft

    normalized = _cap_domain_names(normalize_charter_draft(draft))
    try:
        charter, source_before, wrote_draft_content = await sync_to_async(_persist)(
            str(repository_id), normalized, merge
        )
    except Exception as exc:  # noqa: BLE001 — best-effort：回灌失败绝不反噬确认门锁定
        logger.warning(
            "charter_draft_submit_failed",
            category="caller",
            component="charter_draft_writeback",
            repository_id=str(repository_id),
            initiated_by_user_id=initiated_by_user_id,
            error=redact_secrets_in_text(str(exc)),
        )
        return None
    if charter is None:
        logger.warning(
            "charter_draft_submit_failed",
            category="caller",
            component="charter_draft_writeback",
            repository_id=str(repository_id),
            initiated_by_user_id=initiated_by_user_id,
            error="repository_not_found",
        )
        return None

    logger.info(
        "charter_draft_submitted",
        category="caller",
        component="charter_draft_writeback",
        repository_id=str(repository_id),
        initiated_by_user_id=initiated_by_user_id,
        source_before=source_before,
        wrote_draft_content=wrote_draft_content,
        charter_version=charter.version,
    )
    return charter


def _cap_domain_names(draft: dict) -> dict:
    """``owned_domains[].domain`` 长度兜底（见 ``_MAX_DOMAIN_CHARS``）。"""
    domains = draft.get("owned_domains")
    if not isinstance(domains, list):
        return draft
    for item in domains:
        if isinstance(item, dict) and item.get("domain"):
            item["domain"] = str(item["domain"])[:_MAX_DOMAIN_CHARS]
    return draft


def _apply_draft(charter: Any, draft: dict, merge: bool) -> None:
    """把归一后的草案套到 charter 的**正式字段**（仅 ai_draft 分支调用）。"""
    for field in _MERGE_KEYS:
        incoming = draft.get(field) or []
        if merge:
            setattr(charter, field, _merge_list(field, getattr(charter, field, []), incoming))
        else:
            setattr(charter, field, list(incoming))
    for field in _SCALAR_FIELDS:
        value = draft.get(field)
        if not merge or value:
            setattr(charter, field, value if value is not None else "")


def _merge_draft_content(existing: Any, draft: dict, merge: bool) -> dict:
    """human_confirmed 分支：草案只落 ``draft_content``，同样按 key 去重追加。"""
    if not merge or not isinstance(existing, dict) or not existing:
        return dict(draft)
    from repositories.services.charter_service import normalize_charter_draft

    merged = normalize_charter_draft(existing)
    for field in _MERGE_KEYS:
        merged[field] = _merge_list(field, merged.get(field), draft.get(field) or [])
    for field in _SCALAR_FIELDS:
        value = draft.get(field)
        if value:
            merged[field] = value
    return merged


def _persist(repository_id: str, draft: dict, merge: bool) -> tuple[Any, str, bool]:
    """三分支落库（与 ``adraft_charter`` 行为等价）。

    ``select_for_update`` 必须在同步函数内（RESEARCH-ROUTING P2）；首次并发起草撞
    OneToOne 唯一约束时重跑一次读-改路径（镜像 ``adraft_charter`` 的 MN-05 处理）。
    """
    from django.db import IntegrityError, transaction

    from repositories.models import RepoCharter, Repository

    def _write() -> tuple[Any, str, bool]:
        with transaction.atomic():
            repo = Repository.objects.filter(id=repository_id).first()
            if repo is None:
                return None, "", False
            charter = RepoCharter.objects.select_for_update().filter(repository=repo).first()
            if charter is None:
                created = RepoCharter.objects.create(
                    repository=repo,
                    source=RepoCharter.Source.AI_DRAFT,
                    version=1,
                    **draft,
                )
                return created, "", False
            if charter.source == RepoCharter.Source.AI_DRAFT:
                # 仍是草案：正式字段就地更新（version 不变）
                _apply_draft(charter, draft, merge)
                charter.save()
                return charter, str(RepoCharter.Source.AI_DRAFT), False
            # human_confirmed：只写 draft_content，正式字段一个不碰（CHARTER-01）
            charter.draft_content = _merge_draft_content(charter.draft_content, draft, merge)
            charter.save(update_fields=["draft_content", "updated_at"])
            return charter, str(RepoCharter.Source.HUMAN_CONFIRMED), True

    try:
        return _write()
    except IntegrityError:
        return _write()
