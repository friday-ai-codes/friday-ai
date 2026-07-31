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
        logger.warning(
            "blueprint_block_ops_apply_failed",
            category="caller",
            component="blueprint_block_edit",
            op_count=len(ops),
            error=str(exc),
        )
        rejected.append(_reject("", "", REASON_APPLY_FAILED))
        return (copy.deepcopy(content) if isinstance(content, dict) else {}, rejected)
