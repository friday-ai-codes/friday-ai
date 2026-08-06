"""蓝图节点面 REST（quick 260806 节点重跑 + 横向进度）。

两个端点（``IsAuthenticated`` + 项目范围闸，闸实现 import 复用
``blueprint_review_views._aassert_project_scope``——绝不复制第三份）：

- ``GET  artifacts/<uuid>/blueprint/stages/``       —— 按 stage 聚合的节点快照：会话态、
  各节点的 ``stage_state`` 分片、重跑标记与历史、版本谱系清单（横向 stepper 的供数根）。
- ``POST artifacts/<uuid>/blueprint/stages/rerun/`` —— 带操作员指令重跑某个 stage
  （落库全部委托 ``services.process_runtime.blueprint_stage_rerun``，View 零 ORM 写）。

观测：每端点一条 ``caller`` 事件（``component="blueprint_stage_api"``）；
**操作员指令正文不进日志**，只记长度。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from adrf.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from delivery.api.blueprint_review_views import (
    _ARTIFACT_MISSING_DETAIL,
    _aassert_project_scope,
    _aload_artifact,
    _aload_session,
)

logger = structlog.get_logger(__name__)

_COMPONENT = "blueprint_stage_api"

# stage → stage_state 分片键（与各 adapter 的 STAGE_STATE_KEY 逐字对齐；漂移只影响展示）。
_STAGE_STATE_KEYS: dict[str, tuple[str, ...]] = {
    "intake": ("intake", "decomposition"),
    "decompose": ("decompose", "requirement_spec"),
    "route": ("routing",),
    "repo_research": ("repo_research_fitness", "reroute"),
    "repo_confirmation": ("confirmation", "escalation"),
    "spec_gate": ("spec_gate",),
    "repo_plan": ("repo_plan",),
    "merge": ("merge",),
    "ai_review": ("ai_review",),
}

# 后端正式图的展示顺序（116 重排后主路径；reroute 折叠进 repo_research）。
_STAGE_ORDER: tuple[str, ...] = (
    "intake",
    "decompose",
    "route",
    "repo_research",
    "repo_confirmation",
    "spec_gate",
    "repo_plan",
    "merge",
    "ai_review",
)


def _log(event: str, request: Any, artifact_id: Any, started: float, **fields: Any) -> None:
    logger.info(
        event,
        category="caller",
        component=_COMPONENT,
        artifact_id=str(artifact_id),
        initiated_by_user_id=str(getattr(request.user, "id", "") or "system"),
        duration_ms=round((time.monotonic() - started) * 1000, 2),
        **fields,
    )


async def _aversion_rows(artifact_id: Any) -> list[dict]:
    """该 artifact 全部版本（含谱系标签），按 version_no 升序——版本树切换器的供数。"""
    from delivery.models import Artifact, ArtifactVersion

    current_version_id = (
        await Artifact.objects.filter(id=artifact_id)
        .values_list("current_version_id", flat=True)
        .afirst()
    )
    rows = []
    async for row in ArtifactVersion.objects.filter(artifact_id=artifact_id).order_by("version_no"):
        rows.append(
            {
                "version_id": str(row.id),
                "version_no": int(row.version_no or 0),
                "version_label": str(row.version_label or ""),
                "produced_by_ref": str(row.produced_by_ref or ""),
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "is_current": str(row.id) == str(current_version_id or ""),
            }
        )
    return rows


class BlueprintStagesView(APIView):
    """GET .../blueprint/stages/ —— 节点快照（stage_state 分片 + 重跑信息 + 版本谱系）。

    ⭐ **无会话回 200 空结构，⛔ 绝不 404**（同 ``BlueprintEventsView`` 的理由）：会话
    不存在是正常态，404 会被前端分档吞成全页中性空态。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, artifact_id: Any) -> Response:
        from services.process_runtime.blueprint_stage_rerun import (
            RERUNNABLE_STAGES,
            STAGE_RERUN_HISTORY_KEY,
            STAGE_RERUN_KEY,
        )

        started = time.monotonic()
        artifact = await _aload_artifact(artifact_id)
        if artifact is None:
            return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
        denied = await _aassert_project_scope(request, artifact)
        if denied is not None:
            return denied

        versions = await _aversion_rows(artifact_id)
        session = await _aload_session(artifact_id)
        if session is None:
            _log("blueprint_stages_read", request, artifact_id, started, has_session=False)
            return Response(
                {
                    "session_id": "",
                    "current_stage": "",
                    "session_status": "",
                    "run_label": (versions[-1]["version_label"] if versions else "") or "1",
                    "stage_rerun": None,
                    "stage_rerun_history": [],
                    "rerunnable_stages": sorted(RERUNNABLE_STAGES),
                    "stages": [{"key": key, "state": {}} for key in _STAGE_ORDER],
                    "versions": versions,
                }
            )

        stage_state = session.stage_state if isinstance(session.stage_state, dict) else {}
        marker = stage_state.get(STAGE_RERUN_KEY)
        marker = marker if isinstance(marker, dict) else None
        history = stage_state.get(STAGE_RERUN_HISTORY_KEY)
        history = (
            [item for item in history if isinstance(item, dict)]
            if isinstance(history, list)
            else []
        )
        run_label = str((marker or {}).get("run_label") or "")
        if not run_label:
            run_label = (versions[-1]["version_label"] if versions else "") or "1"

        stages = [
            {
                "key": key,
                "state": {
                    state_key: stage_state.get(state_key)
                    for state_key in _STAGE_STATE_KEYS.get(key, ())
                    if state_key in stage_state
                },
            }
            for key in _STAGE_ORDER
        ]

        payload = {
            "session_id": str(session.id),
            "current_stage": str(session.current_stage or ""),
            "session_status": str(session.status or ""),
            "run_label": run_label,
            "stage_rerun": marker,
            "stage_rerun_history": history,
            "rerunnable_stages": sorted(RERUNNABLE_STAGES),
            "stages": stages,
            "versions": versions,
        }
        _log(
            "blueprint_stages_read",
            request,
            artifact_id,
            started,
            has_session=True,
            version_count=len(versions),
        )
        return Response(payload)


class BlueprintStageRerunView(APIView):
    """POST .../blueprint/stages/rerun/ —— 带操作员指令重跑某个 stage。

    body：``{"stage": "<stage key>", "instruction": "<可选补充指令>"}``。
    ``status`` → HTTP 映射：``accepted`` → 200；``invalid`` → 400；``conflict`` → 409。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, artifact_id: Any) -> Response:
        from services.process_runtime.blueprint_stage_rerun import arerun_blueprint_stage

        started = time.monotonic()
        artifact = await _aload_artifact(artifact_id)
        if artifact is None:
            return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
        denied = await _aassert_project_scope(request, artifact)
        if denied is not None:
            return denied

        payload = request.data if isinstance(request.data, dict) else {}
        stage = str(payload.get("stage") or "").strip()
        instruction = str(payload.get("instruction") or "")

        session = await _aload_session(artifact_id)
        result = await arerun_blueprint_stage(
            artifact,
            session,
            stage=stage,
            instruction=instruction,
            user=request.user,
            initiated_by_user_id=str(getattr(request.user, "id", "") or "system"),
        )
        _log(
            "blueprint_stage_rerun_api",
            request,
            artifact_id,
            started,
            stage=stage,
            status=result["status"],
            run_label=result["run_label"],
            instruction_len=len(instruction.strip()),
        )
        if result["status"] == "invalid":
            return Response({"detail": result["detail"]}, status=status.HTTP_400_BAD_REQUEST)
        if result["status"] == "conflict":
            return Response({"detail": result["detail"]}, status=status.HTTP_409_CONFLICT)
        return Response(result)
