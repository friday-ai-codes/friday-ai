"""调研聚合 + 结果解析（Phase 39-04，DOMAIN §7/§14）。

map 段闭环的纯逻辑层：

- ``aall_research_tasks_terminal``：barrier 完成判定——该 session 所有 RepoResearchTask
  到达终态（done/failed）。**stale/pending/running 非终态**（stale 须重跑后才满足，
  per §14「所有 RepoResearchTask done/failed → merging」）。
- ``amaybe_complete_research``：所有终态则经 ``ConvergenceSessionService.transition`` 推
  research_complete（researching→merging）——**经 service 转移，engine/callback 不直接
  写 status**（engine 纯度）；并发已推进则 no-op。
- ``parse_partial_plan_content``：容器回调结果解析为结构化 §7 PartialPlan content；
  非结构化优雅降级 file 级摘要；空/不可解析 → None（调用方 mark_failed）。健壮解析
  （缺字段补 []、不 eval/不执行返回内容，T-39-04-01）。
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from delivery.models import ConvergenceSession, RepoResearchTaskStatus
from delivery.services import ConvergenceSessionService

# technical_plan stage graph 中调研阶段的 stage key（barrier 守门用）
_RESEARCH_STAGE = "research"

logger = structlog.get_logger(__name__)

__all__ = [
    "TERMINAL_STATUSES",
    "aall_research_tasks_terminal",
    "amaybe_complete_research",
    "parse_partial_plan_content",
]

# barrier 完成判定集（§14：所有 RepoResearchTask done/failed → merging）。
# stale/pending/running 非终态——stale 须重跑后才满足。
TERMINAL_STATUSES = {RepoResearchTaskStatus.DONE, RepoResearchTaskStatus.FAILED}

# 阻塞 barrier 完成的「在途」状态
_PENDING_STATUSES = (
    RepoResearchTaskStatus.PENDING,
    RepoResearchTaskStatus.RUNNING,
    RepoResearchTaskStatus.STALE,
)

# §7 PartialPlan 列表字段（缺失补 []）
_LIST_FIELDS = (
    "proposed_changes",
    "candidate_files",
    "api_contracts_exposed",
    "dependencies_on_other_repos",
)
# 自由文本降级摘要截断长度
_SUMMARY_MAX = 4000


async def aall_research_tasks_terminal(session_id: Any) -> bool:
    """该 session 至少有一个 RepoResearchTask 且无任何在途态（全部 done/failed）。

    无任何 task → 返回 True（无需调研，直接可推进）。
    """
    from delivery.models import RepoResearchTask

    total = await RepoResearchTask.objects.filter(session_id=session_id).acount()
    if total == 0:
        return True
    pending = await RepoResearchTask.objects.filter(
        session_id=session_id, status__in=_PENDING_STATUSES
    ).aexists()
    return not pending


async def amaybe_complete_research(
    session: ConvergenceSession, *, session_service: ConvergenceSessionService | None = None
) -> bool:
    """所有 RepoResearchTask 终态则经 service 推 research_complete（→ merging）。

    guard ``session.current_stage == research``（并发已推进到别的 stage → no-op return False）；
    经 ``transition(session, "research_complete")`` 转移（**不直接写 status**，engine 纯度）。
    返回是否推进。
    """
    if str(session.current_stage) != _RESEARCH_STAGE:
        return False
    if not await aall_research_tasks_terminal(session.id):
        return False
    svc = session_service or ConvergenceSessionService()
    await svc.transition(session, "research_complete")
    return True


def parse_partial_plan_content(raw: Any, *, repository_id: str) -> dict | None:
    """容器结果解析为结构化 §7 PartialPlan content（健壮 + 优雅降级）。

    入参 ``raw`` = ``TaskResult.raw_output``(dict) 或 ``text_output``(str)。
    - dict 含 §7 字段 → 直采结构化（缺列表字段补 []）。
    - dict 仅有 ``text`` 自由文本 / str → 试 JSON 解析为 §7 dict，否则**降级** file 级
      摘要（research_summary=text[:4000]，列表字段 []）。
    - 空/无可用文本 → None（调用方 mark_failed）。

    始终回填 ``repository_id`` 字段；不 eval/不执行返回内容（T-39-04-01）。
    """
    if isinstance(raw, dict):
        if _has_structured_keys(raw):
            return _build_structured(raw, repository_id)
        text = raw.get("text")
        if isinstance(text, str) and text.strip():
            parsed = _try_parse_json_struct(text)
            if parsed is not None:
                return _build_structured(parsed, repository_id)
            return _degrade(text, repository_id)
        return None

    if isinstance(raw, str) and raw.strip():
        parsed = _try_parse_json_struct(raw)
        if parsed is not None:
            return _build_structured(parsed, repository_id)
        return _degrade(raw, repository_id)

    return None


def _has_structured_keys(d: dict) -> bool:
    return "research_summary" in d or any(f in d for f in _LIST_FIELDS)


def _build_structured(d: dict, repository_id: str) -> dict:
    """从 §7 结构化 dict 提字段（缺列表字段补 []，始终回填 repository_id）。"""
    content: dict[str, Any] = {
        "repository_id": repository_id,
        "research_summary": str(d.get("research_summary", "") or ""),
    }
    for field in _LIST_FIELDS:
        value = d.get(field)
        content[field] = value if isinstance(value, list) else []
    return content


def _degrade(text: str, repository_id: str) -> dict:
    """自由文本优雅降级为 file 级摘要 partial。"""
    return {
        "repository_id": repository_id,
        "research_summary": text[:_SUMMARY_MAX],
        "proposed_changes": [],
        "candidate_files": [],
        "api_contracts_exposed": [],
        "dependencies_on_other_repos": [],
    }


def _try_parse_json_struct(text: str) -> dict | None:
    """试把自由文本解析为含 §7 键的 JSON dict；失败/无 §7 键 → None。"""
    candidate = text.strip()
    # 容忍 ```json ... ``` 围栏 / 模型前言：取首个 { 到末个 }
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = candidate[start : end + 1]
    try:
        obj = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(obj, dict) and _has_structured_keys(obj):
        return obj
    return None
