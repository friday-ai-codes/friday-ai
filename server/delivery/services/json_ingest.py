"""JSON 批量摄取：空间解析预览 + 有界并发摄取协调器。

用户在「批量摄取」粘贴一组 ``{space, work_item_id, work_item_type?, mr_url?}``：

- ``aresolve_items``：逐项把「空间」（UUID / 飞书 key / 模糊名）解析到 ``Space``，
  拼出工作项三元组与详情 URL，返回逐项校验结果（无副作用，供前端预览/编辑）。
- ``run_json_batch``：用 ``asyncio.Semaphore`` 控并发（默认 3、最大 10）跑每项
  ``ingest_from_refs``；429/限流的「等待重试」下沉到 embedding / Feishu 客户端的
  tenacity（见 ``services/embedding.py`` / ``feishu/client.py``），此处只管并发上限。
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from delivery.services.ingest_orchestrator import build_board_url, ingest_from_refs
from delivery.services.space_resolver import SpaceResolution, aresolve_space

logger = structlog.get_logger(__name__)

__all__ = [
    "DEFAULT_WORK_ITEM_TYPE",
    "DEFAULT_CONCURRENCY",
    "MAX_CONCURRENCY",
    "aresolve_items",
    "run_json_batch",
    "clamp_concurrency",
]

DEFAULT_WORK_ITEM_TYPE = "story"
DEFAULT_CONCURRENCY = 3
MAX_CONCURRENCY = 10

_SPACE_ERROR_MSG = {
    SpaceResolution.EMPTY: "空间为空",
    SpaceResolution.AMBIGUOUS: "空间名匹配到多个，请改用飞书 key 或系统 id 消歧",
    SpaceResolution.NOT_FOUND: "未找到对应空间",
}


def clamp_concurrency(value: Any) -> int:
    """并发数夹取到 [1, MAX_CONCURRENCY]，非法值回退默认。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_CONCURRENCY
    return max(1, min(n, MAX_CONCURRENCY))


def _coerce_work_item_id(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


async def aresolve_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """逐项解析空间 → 工作项三元组 + 详情 URL + 校验状态（只读，不落库）。"""
    results: list[dict[str, Any]] = []
    for raw in items:
        space_input = str(raw.get("space", "") or "").strip()
        work_item_type = (
            str(raw.get("work_item_type") or "").strip() or DEFAULT_WORK_ITEM_TYPE
        )
        mr_url = str(raw.get("mr_url") or "").strip()
        work_item_id = _coerce_work_item_id(raw.get("work_item_id"))

        project, reason = await aresolve_space(space_input)
        key = (project.feishu_project_key or "") if project else ""

        error = ""
        if work_item_id <= 0:
            error = "work_item_id 缺失或非法"
        elif project is None:
            error = _SPACE_ERROR_MSG.get(reason, "空间无法解析")
        elif not key:
            error = "该空间未配置飞书 project key，无法定位工作项"

        resolved = not error
        results.append(
            {
                "space": space_input,
                "space_id": str(project.id) if project else "",
                "space_name": project.name if project else "",
                "feishu_project_key": key,
                "work_item_id": work_item_id,
                "work_item_type": work_item_type,
                "mr_url": mr_url,
                "board_url": build_board_url(key, work_item_type, work_item_id) if resolved else "",
                "match_reason": reason,
                "resolved": resolved,
                "error": error,
            }
        )
    return results


async def run_json_batch(specs: list[dict[str, Any]], concurrency: int) -> None:
    """有界并发跑每项 ``ingest_from_refs``（每项已建好 IngestRun，run_id 在 spec 内）。

    Args:
        specs: ``[{run_id, feishu_project_key, work_item_type, work_item_id, mr_url, board_url}]``
        concurrency: 并发上限（已夹取）。
    """
    sem = asyncio.Semaphore(clamp_concurrency(concurrency))

    async def _one(spec: dict[str, Any]) -> None:
        async with sem:
            try:
                await ingest_from_refs(
                    spec["run_id"],
                    feishu_project_key=spec.get("feishu_project_key", ""),
                    work_item_type=spec.get("work_item_type", DEFAULT_WORK_ITEM_TYPE),
                    work_item_id=spec.get("work_item_id", 0),
                    mr_url=spec.get("mr_url", ""),
                    board_url=spec.get("board_url", ""),
                )
            except Exception:  # noqa: BLE001 — 单项异常不阻断整批（ingest_from_refs 已内部降级）
                logger.exception("json_ingest_item_failed", run_id=spec.get("run_id"))

    await asyncio.gather(*(_one(s) for s in specs), return_exceptions=True)
