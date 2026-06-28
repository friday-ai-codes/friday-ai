"""HumanTask 统一待办 REST views（Chassis v2 · P8 Human Task Center）。

"一处看全待办，可处理并回流"（adrf，镜像 ``spec_views`` 范式，IsAuthenticated）：

- ``HumanTaskInboxView``：
  - ``get``：统一收件箱 = 物化 HumanTask ∪ 投影（待答澄清 / 待审批 / 失败反应重试）。
    ``?mine=1`` 仅看指派给当前用户的物化待办；``?include_projections=0`` 关投影。
  - ``post``：开一条原生待办（risk_ack / takeover 等），经 ``HumanTaskService.open_task``。
- ``HumanTaskActionView.post``：对**物化**待办执行 ``resolve | skip | reassign``（回流）。
- ``ClarificationAnswerView.post``：对**投影的待答澄清**按题作答（经 ``ClarificationService``
  单一入口回流；答毕该投影从收件箱自然消失）。

写入只经 ``HumanTaskService`` / ``ClarificationService``（INV-6，不旁路既有事实源）。
async 序列化纪律：``.data`` 经 ``sync_to_async``；HumanTaskView 已是纯标量 dict 直接返回。
"""

from __future__ import annotations

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from delivery.api.human_task_serializers import OpenHumanTaskSerializer
from delivery.models import Clarification, HumanTask, HumanTaskStatus
from delivery.services import ClarificationService, HumanTaskService

logger = structlog.get_logger(__name__)

_ACTIONS = frozenset({"resolve", "skip", "reassign"})


def _truthy(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class HumanTaskInboxView(APIView):
    """统一待办收件箱（IsAuthenticated）：GET/POST /api/delivery/human-tasks/。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request):
        mine = _truthy(request.query_params.get("mine"), default=False)
        include_projections = _truthy(
            request.query_params.get("include_projections"), default=True
        )
        assignee_user_id = str(request.user.id) if mine else None

        service = HumanTaskService()
        views = await service.list_inbox(
            assignee_user_id=assignee_user_id,
            include_projections=include_projections,
        )
        return Response([v.to_dict() for v in views])

    async def post(self, request):
        serializer = OpenHumanTaskSerializer(data=request.data)
        ok = await sync_to_async(serializer.is_valid)()
        if not ok:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        vd = serializer.validated_data

        service = HumanTaskService()
        try:
            task = await service.open_task(
                task_type=vd["task_type"],
                scope=vd["scope"],
                subject_id=vd["subject_id"],
                assignee_user_id=vd.get("assignee_user_id") or None,
                assignee_role=vd.get("assignee_role") or None,
                source_signal=vd.get("source_signal") or "",
                due_at=vd.get("due_at"),
                dedup_key=vd.get("dedup_key") or "",
                resolution=vd.get("resolution") or {},
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            await self._serialize_task(task), status=status.HTTP_201_CREATED
        )

    @staticmethod
    async def _serialize_task(task: HumanTask) -> dict:
        return {
            "id": str(task.id),
            "task_type": task.task_type,
            "scope": task.scope,
            "subject_id": task.subject_id,
            "status": task.status,
            "source": "materialized",
            "source_signal": task.source_signal,
            "assignee_user_id": task.assignee_user_id,
            "assignee_role": task.assignee_role,
            "dedup_key": task.dedup_key,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        }


class HumanTaskActionView(APIView):
    """物化待办动作（IsAuthenticated）：POST /api/delivery/human-tasks/<uuid>/<action>/。

    action ∈ {resolve, skip, reassign}。仅对物化 HumanTask 行生效（投影待办经各自来源回流）。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request, task_id, action):
        if action not in _ACTIONS:
            return Response(
                {"error": "action 取值无效"}, status=status.HTTP_400_BAD_REQUEST
            )
        exists = await HumanTask.objects.filter(id=task_id).aexists()
        if not exists:
            return Response(
                {"error": "待办不存在"}, status=status.HTTP_404_NOT_FOUND
            )

        service = HumanTaskService()
        if action == "resolve":
            resolution = request.data.get("resolution") or {}
            if not isinstance(resolution, dict):
                return Response(
                    {"error": "resolution 必须为对象"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            task = await service.resolve(task_id, resolution)
        elif action == "skip":
            reason = request.data.get("reason") or ""
            if not isinstance(reason, str):
                return Response(
                    {"error": "reason 必须为字符串"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            task = await service.skip(task_id, reason=reason)
        else:  # reassign
            task = await service.reassign(
                task_id,
                assignee_user_id=request.data.get("assignee_user_id") or None,
                assignee_role=request.data.get("assignee_role") or None,
            )

        return Response(
            {
                "id": str(task.id),
                "status": task.status,
                "resolved_at": task.resolved_at.isoformat() if task.resolved_at else None,
                "assignee_user_id": task.assignee_user_id,
                "assignee_role": task.assignee_role,
            }
        )


class ClarificationAnswerView(APIView):
    """投影澄清回流（IsAuthenticated）：
    POST /api/delivery/human-tasks/clarification/<uuid>/answer/。

    body ``{answers: [{question_id, selected, freeform_text?}]}`` 经 ``ClarificationService``
    单一入口按题作答（答毕该投影从收件箱自然消失，回流主链路）。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request, clarification_id):
        answers = request.data.get("answers")
        if not isinstance(answers, list) or not answers:
            return Response(
                {"error": "answers 必须为非空列表"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        exists = await Clarification.objects.filter(id=clarification_id).aexists()
        if not exists:
            return Response(
                {"error": "澄清不存在"}, status=status.HTTP_404_NOT_FOUND
            )

        service = ClarificationService()
        await service.answer_round(clarification_id, answers)

        still_pending = await service.ahas_pending(
            await Clarification.objects.filter(id=clarification_id)
            .values_list("session_id", flat=True)
            .afirst()
        )
        return Response(
            {
                "clarification_id": str(clarification_id),
                "status": HumanTaskStatus.OPEN if still_pending else HumanTaskStatus.DONE,
            }
        )
