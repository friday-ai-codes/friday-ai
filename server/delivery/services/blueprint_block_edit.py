"""blueprint_block_edit —— 人工 block 级编辑（Phase 114-04，CLAR-03、DESIGN §6.3）。

三段契约（改动前先读）：

1. **本模块 = block 级 patch 的纯函数节 + service 收口节**。纯函数节
   （:func:`apply_block_ops` 及其 helper）**无 IO / 无 ORM / 无 LLM**，只做结构操作；
   service 节（:func:`aapply_block_edit`）负责「校验 → 落版本 → 重锚定 → 评审人
   upsert」的固定顺序，线程/版本写入一律委托 ``BlueprintLifecycleService`` 与
   ``ArtifactService``（INV-6：本模块零 ORM 写）。
2. **patch 来自用户**（半可信但需可回显）：未知 op、找不到 ``block_id``、缺必填字段
   一律进 ``rejected`` 清单**如实上报**，绝不静默跳过——静默跳过 = 用户以为改了其实
   没改，是最坏的编辑体验。``rejected`` 分两档：硬失败（:data:`HARD_REJECT_REASONS`）
   阻断落版本；提示级（``block_id_immutable``）随成功结果一并回显。
3. **合法性由 ``validate_blueprint`` 兜最终底**：本节只做结构操作，不做语义校验
   （引用完整性 / ``data_source`` 形状 / 枚举合法性全归 jsonschema 与后置校验）。
   service 节在落版本**之前**显式再校验一次，为的是拿到可回显的中文错因；
   ``add_version`` 自身的 ``ArtifactContentInvalid`` 是第二层 fail-closed。
"""

from __future__ import annotations

import copy
import time
from typing import Any, Iterator

import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "OP_REPLACE",
    "OP_INSERT",
    "OP_DELETE",
    "BLOCK_OPS",
    "REASON_UNKNOWN_OP",
    "REASON_BLOCK_NOT_FOUND",
    "REASON_MISSING_BLOCK",
    "REASON_MISSING_BLOCK_ID",
    "REASON_BLOCK_ID_IMMUTABLE",
    "REASON_APPLY_FAILED",
    "HARD_REJECT_REASONS",
    "apply_block_ops",
    "aapply_block_edit",
]

OP_REPLACE = "replace"
OP_INSERT = "insert"
OP_DELETE = "delete"
BLOCK_OPS: frozenset[str] = frozenset({OP_REPLACE, OP_INSERT, OP_DELETE})

POSITION_BEFORE = "before"
POSITION_AFTER = "after"

REASON_UNKNOWN_OP = "unknown_op"
REASON_BLOCK_NOT_FOUND = "block_not_found"
REASON_MISSING_BLOCK = "missing_block"
REASON_MISSING_BLOCK_ID = "missing_block_id"
REASON_BLOCK_ID_IMMUTABLE = "block_id_immutable"
REASON_APPLY_FAILED = "apply_failed"

# 硬失败：出现即不落版本（提示级 block_id_immutable 不在其中）。
HARD_REJECT_REASONS: frozenset[str] = frozenset(
    {
        REASON_UNKNOWN_OP,
        REASON_BLOCK_NOT_FOUND,
        REASON_MISSING_BLOCK,
        REASON_MISSING_BLOCK_ID,
        REASON_APPLY_FAILED,
    }
)

# 编辑后错因回显上界（`validate_blueprint` 的 `_format_error` 已脱敏截断 500 字符，
# 此处再兜一层，防第二层 `ArtifactContentInvalid` 文案更长）。
_MAX_DETAIL_CHARS = 500


def _reject(op: Any, block_id: Any, reason: str) -> dict:
    return {"op": str(op or ""), "block_id": str(block_id or ""), "reason": reason}


def _iter_block_containers(node: Any) -> Iterator[list]:
    """产出 content 中所有「元素为带 ``block_id`` 的 dict」的 list 容器。

    ⚠️ 这不是第二套 ``iter_blocks``：``iter_blocks`` 返回 ``(section_path, block)``
    的**值**，拿不到 block 所在的父 list，而 ``insert`` / ``delete`` 必须操作父容器。
    权威块集合仍由 ``iter_blocks`` 判定——:func:`_locate` 先用它确认 ``block_id``
    存在，再用本函数取容器与下标（见 :func:`_locate` docstring）。
    """
    if isinstance(node, dict):
        for value in node.values():
            yield from _iter_block_containers(value)
        return
    if isinstance(node, list):
        if any(isinstance(item, dict) and item.get("block_id") for item in node):
            yield node
        for item in node:
            if isinstance(item, (dict, list)):
                yield from _iter_block_containers(item)


def _known_block_ids(content: Any) -> set[str]:
    """权威块集合：一律取 ``iter_blocks``（不自写 section_path 递归）。"""
    from services.process_runtime.blueprint_schema import iter_blocks

    return {
        str(block.get("block_id")) for _path, block in iter_blocks(content) if block.get("block_id")
    }


def _locate(content: Any, block_id: str) -> tuple[list | None, int]:
    """定位 ``block_id`` 所在的父 list 与下标；找不到返回 ``(None, -1)``。

    双层判据：① ``block_id`` 必须在 ``iter_blocks(content)`` 的权威集合内——落在
    schema 未知落位上的块不可编辑（否则 patch 能往 ``iter_blocks`` 走不到的角落塞
    内容，115 渲染与重锚定都看不见它）；② 容器与下标由 :func:`_iter_block_containers`
    给出。逐层 ``isinstance`` 防御。
    """
    if not block_id or block_id not in _known_block_ids(content):
        return (None, -1)
    for container in _iter_block_containers(content):
        for index, item in enumerate(container):
            if isinstance(item, dict) and str(item.get("block_id") or "") == block_id:
                return (container, index)
    return (None, -1)


def apply_block_ops(content: Any, ops: Any) -> tuple[dict, list[dict]]:
    """把 block 级 patch ops 应用到蓝图 content，返回 ``(new_content, rejected)``。

    **纯函数**：``new_content`` 是 ``copy.deepcopy(content)`` 的产物，**入参不被原地
    修改**；``rejected`` 条目形状 ``{"op", "block_id", "reason"}``。

    op 形状::

        {"op": "replace" | "insert" | "delete",
         "block_id": str,                       # replace/delete 目标；insert 的锚点
         "block": dict | None,                  # replace/insert 的新块
         "position": "before" | "after"}        # insert 相对锚点的落位，缺省 after

    - ``replace``：整块替换，但 **``block_id`` 以原 id 为准**——允许用户改 id 会把该块
      上的全部线程 anchor 打散（重锚定只能退化成 quoted_text 模糊匹配甚至失锚）。
      入参 id 与原 id 不一致时记一条**提示级** ``block_id_immutable``（不阻断）。
    - ``insert``：在锚点块前/后插入；新块必须自带非空 ``block_id``（缺则
      ``missing_block_id`` —— 无 id 的块 ``iter_blocks`` 收不到，等于写进黑洞）。
    - ``delete``：移除该块。

    **恒不抛**：整体 ``try/except`` 兜底，异常时返回「未改动的深拷贝 + 一条
    ``apply_failed``」，**绝不返回半改内容**（半改内容落版本 = 用户拿到一份自己没写过
    的蓝图）。
    """
    rejected: list[dict] = []
    base: dict = copy.deepcopy(content) if isinstance(content, dict) else {}
    if not isinstance(ops, list):
        return (base, [_reject("", "", REASON_UNKNOWN_OP)])
    try:
        for raw in ops:
            op = str(raw.get("op") or "") if isinstance(raw, dict) else ""
            if op not in BLOCK_OPS:
                rejected.append(
                    _reject(
                        op,
                        raw.get("block_id") if isinstance(raw, dict) else "",
                        REASON_UNKNOWN_OP,
                    )
                )
                continue
            block_id = str(raw.get("block_id") or "")
            new_block = raw.get("block")
            if op in (OP_REPLACE, OP_INSERT) and not isinstance(new_block, dict):
                rejected.append(_reject(op, block_id, REASON_MISSING_BLOCK))
                continue
            if op == OP_INSERT and not str((new_block or {}).get("block_id") or ""):
                rejected.append(_reject(op, block_id, REASON_MISSING_BLOCK_ID))
                continue

            container, index = _locate(base, block_id)
            if container is None:
                rejected.append(_reject(op, block_id, REASON_BLOCK_NOT_FOUND))
                continue

            if op == OP_DELETE:
                container.pop(index)
                continue
            payload = copy.deepcopy(new_block)
            if op == OP_REPLACE:
                if str(payload.get("block_id") or "") != block_id:
                    rejected.append(_reject(op, block_id, REASON_BLOCK_ID_IMMUTABLE))
                payload["block_id"] = block_id
                container[index] = payload
                continue
            position = str(raw.get("position") or POSITION_AFTER)
            container.insert(index if position == POSITION_BEFORE else index + 1, payload)
        return (base, rejected)
    except Exception as exc:  # noqa: BLE001 — 半改内容绝不外流，异常一律回落未改动副本
        from common.logging import redact_secrets_in_text

        logger.warning(
            "blueprint_block_ops_apply_failed",
            category="caller",
            component="blueprint_block_edit",
            op_count=len(ops),
            # 异常文本兜的是半可信 block 正文（可能夹带凭证样本）⇒ 脱敏不可绕过
            error=redact_secrets_in_text(str(exc)),
        )
        rejected.append(_reject("", "", REASON_APPLY_FAILED))
        return (copy.deepcopy(content) if isinstance(content, dict) else {}, rejected)


def _has_hard_reject(rejected: list[dict]) -> bool:
    return any(item.get("reason") in HARD_REJECT_REASONS for item in rejected)


def _edit_result(
    status: str,
    *,
    version_id: str = "",
    version_no: int = 0,
    rejected: list[dict] | None = None,
    detail: str = "",
    reanchor: dict | None = None,
) -> dict:
    """恒定六键返回（下游无需判空分支）。"""
    return {
        "status": status,
        "version_id": version_id,
        "version_no": version_no,
        "rejected": list(rejected or []),
        "detail": str(detail or "")[:_MAX_DETAIL_CHARS],
        "reanchor": dict(reanchor or {}),
    }


async def aapply_block_edit(
    artifact: Any,
    ops: Any,
    *,
    user: Any = None,
    initiated_by_user_id: str = "system",
    session_id: str = "",
    artifact_service: Any = None,
    lifecycle_service: Any = None,
) -> dict:
    """人工 block 编辑的 service 收口（CLAR-03）：**五步固定顺序**，恒定返回键。

    返回 ``{"status", "version_id", "version_no", "rejected", "detail", "reanchor"}``；
    ``status`` 四值语义：

    ==============  ==========================================================
    status          语义
    ==============  ==========================================================
    ``applied``     patch 合法且内容有实质改动 ⇒ 已落新版本、已重锚定、已 upsert 评审人
    ``unchanged``   patch 合法但 content_hash 与 current 相同 ⇒ **不翻版本**、不重锚定
    ``rejected``    patch 结构性硬失败（见 ``rejected[].reason``）⇒ **不落版本**
    ``invalid``     patch 应用后 content 不过 ``validate_blueprint`` ⇒ **不落版本**，
                    ``detail`` 为可直接回显的中文错因（已脱敏截断）
    ==============  ==========================================================

    ⭐ **第 0 步是状态闸**（``is_blueprint_editable``，114-MJ-04）：本函数原先根本不碰状态
    机 ⇒ 一份已 ``confirmed``（甚至 ``implementing`` / ``archived``）的蓝图仍可被继续落
    ``human_edit:`` 版本，而蓝图状态**不变** ⇒ 下游 implementing 链拿到的
    ``current_version`` 已不是当初被确认的那一版，「确认」所锚定的内容被**事后掉包**且
    无痕。越界一律 ``invalid``（端点 400、版本数不变），要改必须先驳回
    （``confirmed → drafting`` 合法边）再重走人审。

    五步（照 ``blueprint_confirm_gate.alock`` 的固定顺序）：

    1. **读最新版本作基线**（``order_by("-version_no").afirst()``）。⛔ **绝不读**
       ``session.current_artifact_version``——上游 ``add_version`` 已推进 current，而
       session 钉住的那一版是旧的，拿它作基线会把 AI 成果覆盖回旧内容
       （``blueprint_confirm_gate.py:546-550`` 同源坑）。
    2. :func:`apply_block_ops` 应用 patch；硬失败即返回 ``rejected``、不落版本。
    3. ⭐ **显式 ``validate_blueprint``**：拿可回显的中文错因（``_format_error`` 已脱敏
       并截断 500 字符），非法直接返回 ``invalid``，**不落半合法版本**。
    4. ``add_version(produced_by_ref=f"human_edit:{user_id}")``——``human_edit:`` 前缀是
       全仓唯一的「这一版是人写的」归属通道（``ArtifactVersion`` 无 ``created_by_user_id``），
       114-04 的 :func:`blueprint_reflow.acollect_human_block_ids` 与 114-03 的人工块
       保护都以它为判据。``ArtifactContentInvalid`` fail-closed 成 ``invalid``。
    5. 落新版本后才：``areanchor_threads``（旧批注重挂新块）→ ``add_reviewer(..., "block_edit")``
       （编辑者进评审人名单，§6.4）→ 结构化日志。**block 正文绝不进日志**（T-114-27）。
    """
    from delivery.models import ArtifactVersion
    from delivery.services.artifact_service import ArtifactContentInvalid, ArtifactService
    from delivery.services.blueprint_lifecycle_service import (
        NOT_EDITABLE_DETAIL,
        BlueprintLifecycleService,
        is_blueprint_editable,
    )

    started = time.monotonic()
    artifacts = artifact_service or ArtifactService()
    lifecycle = lifecycle_service or BlueprintLifecycleService()

    if not is_blueprint_editable(artifact):
        logger.info(
            "blueprint_block_edit_blocked_by_status",
            category="caller",
            component="blueprint_block_edit",
            artifact_id=str(getattr(artifact, "id", "")),
            # 键刻意不叫模型字段名：`test_inv6_no_bypass_blueprint_status_field_write` 把
            # 「字段名 + 等号」形态一律判为旁路写（那条正则正确，用于逮 `**{…}` 绕 CAS）。
            # 本处只读该字段、从不写它，换个键名即可让守卫保持满弦。
            current_status=str(getattr(artifact, "blueprint_status", "") or ""),
            initiated_by_user_id=initiated_by_user_id or "system",
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return _edit_result("invalid", detail=NOT_EDITABLE_DETAIL)

    base = (
        await ArtifactVersion.objects.filter(artifact_id=getattr(artifact, "id", None))
        .order_by("-version_no")
        .afirst()
    )
    if base is None:
        return _edit_result("invalid", detail="蓝图尚无版本，无法编辑")

    new_content, rejected = apply_block_ops(base.content, ops)
    if _has_hard_reject(rejected):
        return _edit_result("rejected", rejected=rejected, detail="patch 存在无法应用的操作")

    from services.process_runtime.blueprint_schema import validate_blueprint

    ok, error = validate_blueprint(new_content)
    if not ok:
        return _edit_result("invalid", rejected=rejected, detail=f"编辑后的蓝图不合法：{error}")

    user_id = str(getattr(user, "id", "") or initiated_by_user_id or "system")
    try:
        version = await artifacts.add_version(
            artifact,
            new_content,
            produced_by_session_id=str(session_id or ""),
            produced_by_ref=f"human_edit:{user_id}",
        )
    except ArtifactContentInvalid as exc:
        from common.logging import redact_secrets_in_text

        logger.warning(
            "blueprint_block_edit_invalid_content",
            category="caller",
            component="blueprint_block_edit",
            artifact_id=str(getattr(artifact, "id", "")),
            initiated_by_user_id=initiated_by_user_id or "system",
            error=redact_secrets_in_text(str(exc)),
        )
        return _edit_result("invalid", rejected=rejected, detail=redact_secrets_in_text(str(exc)))

    if str(version.id) == str(base.id):
        # 同 content_hash 复用 current（`_add_version_sync:148-149`）⇒ 版本未翻，
        # 块序列逐字未变 ⇒ 也不必重锚定。
        return _edit_result(
            "unchanged",
            version_id=str(version.id),
            version_no=int(version.version_no),
            rejected=rejected,
            detail="内容无实质改动，未产生新版本",
        )

    reanchor_counts = await lifecycle.areanchor_threads(
        artifact,
        new_content,
        old_content=base.content if isinstance(base.content, dict) else None,
        initiated_by_user_id=initiated_by_user_id or "system",
    )
    if user is not None:
        await lifecycle.add_reviewer(artifact, user, "block_edit")

    logger.info(
        "blueprint_block_edit_applied",
        category="caller",
        component="blueprint_block_edit",
        artifact_id=str(getattr(artifact, "id", "")),
        version_no=int(version.version_no),
        op_count=len(ops) if isinstance(ops, list) else 0,
        rejected_count=len(rejected),
        reanchor_checked=reanchor_counts.get("checked", 0),
        reanchor_reanchored=reanchor_counts.get("reanchored", 0),
        reanchor_orphaned=reanchor_counts.get("orphaned", 0),
        reanchor_skipped=reanchor_counts.get("skipped", 0),
        initiated_by_user_id=initiated_by_user_id or "system",
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return _edit_result(
        "applied",
        version_id=str(version.id),
        version_no=int(version.version_no),
        rejected=rejected,
        reanchor=reanchor_counts,
    )
