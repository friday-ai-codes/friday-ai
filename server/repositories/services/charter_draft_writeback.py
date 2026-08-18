"""确认门章程回灌的**唯一写入面**（Phase 112-05，CHARTER-03；append-only 修订）。

三段契约：

- **本模块是确认门章程回灌的唯一写入面**：``charter_service.adraft_charter`` 只接受
  「自己蒸馏出的草案」，不接受调用方传入的草案内容——确认门需要把人工裁决出的职责
  聚合与移除理由定向写成草案，故新增 :func:`asubmit_charter_draft`。
- **归一逐字复用 ``charter_service.normalize_charter_draft``**，绝不另写一套白名单。
- **Append-only**：无 charter → 建基线；已有行 → classify 侧信道
  （``appendices`` / ``change_proposals``）+ 指纹持久化；**永不**改正式字段或
  ``draft_content``（D-02/D-04）。``merge=False`` 不再整表覆盖正式 list，仅作
  classify 输入语义。

best-effort：任何异常经 ``redact_secrets_in_text`` 脱敏后 warning 并返回 ``None``——
章程回灌绝不反噬确认门的锁定动作。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import structlog
from asgiref.sync import sync_to_async

from common.logging import redact_secrets_in_text

if TYPE_CHECKING:
    from repositories.models import RepoCharter

logger = structlog.get_logger(__name__)

__all__ = ["asubmit_charter_draft"]

_MAX_DOMAIN_CHARS = 40


async def asubmit_charter_draft(
    repository_id: str,
    draft: dict,
    *,
    initiated_by_user_id: str = "system",
    merge: bool = True,
    fingerprint: str | None = None,
) -> RepoCharter | None:
    """把调用方给出的章程草案定向写入（append-only：建基线或侧信道）。

    Args:
        repository_id: 目标仓 id（不存在 / 非法 uuid → 返回 ``None``，不抛）。
        draft: 章程草案 dict（经 ``normalize_charter_draft`` 白名单归一）。
        initiated_by_user_id: 触发用户归因（无触发用户记 ``system``）。
        merge: 保留参数兼容；不再覆盖正式 list（classify 侧信道）。
        fingerprint: 可选 material fingerprint；省略则从 Repository 证据计算。

    Returns:
        写入后的 ``RepoCharter``；依赖不可用 / 仓不存在 / 落库失败 → ``None``。
    """
    del merge  # 正式字段不再 merge/overwrite；classify 已处理增量
    from repositories.services.charter_service import (
        apply_automation_to_existing_charter,
        create_baseline_charter,
        normalize_charter_draft,
        resolve_fingerprint_for_repository,
    )

    normalized = _cap_domain_names(normalize_charter_draft(draft))
    started = time.monotonic()
    try:
        charter, outcome = await sync_to_async(_persist)(
            str(repository_id),
            normalized,
            fingerprint,
            initiated_by_user_id,
            started,
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
        outcome=outcome,
        charter_version=charter.version,
        appendices_count=len(charter.appendices or []),
        proposals_count=len(charter.change_proposals or []),
        duration_ms=round((time.monotonic() - started) * 1000, 2),
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


def _persist(
    repository_id: str,
    draft: dict,
    fingerprint: str | None,
    initiated_by_user_id: str,
    started: float,
) -> tuple[Any, str]:
    """建基线或侧信道 classify；与 ``adraft_charter`` 自动化语义对齐。"""
    from django.db import IntegrityError, transaction

    from repositories.models import RepoCharter, Repository
    from repositories.services.charter_service import (
        apply_automation_to_existing_charter,
        create_baseline_charter,
        resolve_fingerprint_for_repository,
    )

    def _write() -> tuple[Any, str]:
        with transaction.atomic():
            repo = Repository.objects.filter(id=repository_id).first()
            if repo is None:
                return None, ""
            charter = RepoCharter.objects.select_for_update().filter(repository=repo).first()
            observed = resolve_fingerprint_for_repository(
                repo,
                fingerprint=fingerprint,
                stored=(charter.baseline_fingerprint if charter else "") or "",
            )
            if charter is None:
                created = create_baseline_charter(repo, draft, fingerprint=observed)
                try:
                    logger.info(
                        "wrote_appendix",
                        category="caller",
                        component="charter_draft_writeback",
                        repository_id=str(repository_id),
                        initiated_by_user_id=initiated_by_user_id,
                        outcome="baseline_created",
                    )
                    logger.info(
                        "fingerprint_persisted",
                        category="caller",
                        component="charter_draft_writeback",
                        repository_id=str(repository_id),
                        initiated_by_user_id=initiated_by_user_id,
                        fingerprint=observed,
                    )
                except Exception:  # noqa: BLE001
                    pass
                return created, "baseline_created"

            before_app = len(charter.appendices or [])
            before_prop = len(charter.change_proposals or [])
            apply_automation_to_existing_charter(
                charter,
                draft,
                fingerprint=observed,
                repository_id=str(repository_id),
                initiated_by_user_id=initiated_by_user_id,
                started=started,
            )
            after_app = len(charter.appendices or [])
            after_prop = len(charter.change_proposals or [])
            if after_app == before_app and after_prop == before_prop:
                outcome = "skipped_no_material_change"
            elif after_app > before_app and after_prop == before_prop:
                outcome = "wrote_appendix"
            elif after_prop > before_prop and after_app == before_app:
                outcome = "wrote_proposal"
            else:
                outcome = "wrote_side_channel"
            try:
                logger.info(
                    outcome if outcome.startswith("wrote") or outcome.startswith("skipped") else "fingerprint_persisted",
                    category="caller",
                    component="charter_draft_writeback",
                    repository_id=str(repository_id),
                    initiated_by_user_id=initiated_by_user_id,
                    fingerprint=observed,
                )
            except Exception:  # noqa: BLE001
                pass
            return charter, outcome

    try:
        return _write()
    except IntegrityError:
        return _write()
