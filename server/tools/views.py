"""tools app views —— RemoteTool 执行端点。

执行端点（``RemoteToolExecuteView``）：PAT-only fail-closed（T-10-03），
``begin_interaction_run`` 审计（指纹=token_hash）后透传 ``execute_tool``。

注：曾有「工具令牌绑定」CRUD（ToolTokenBindingViewSet / BindableToolsView），
因明文 PAT 绝不落库、绑定无法用于容器注入而被整体移除——PAT 本身即代表
令牌所有者的全部能力，无须按工具绑定。
"""

from __future__ import annotations

import time

from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from interactions.entry import AccessTokenAuthentication, begin_interaction_run
from interactions.ledger import arecord_tool_call
from interactions.models import InteractionRun
from tools.executor import execute_tool

from .serializers import RemoteToolExecuteSerializer


class RemoteToolExecuteView(APIView):
    """RemoteTool 执行端点 —— PAT-only fail-closed + 审计 + executor 透传。"""

    authentication_classes = [AccessTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def handle_exception(self, exc: Exception) -> Response:
        # 匿名/无效 PAT：NotAuthenticated/AuthenticationFailed → 401（不降级 403，
        # per Pitfall 2 / T-10-03，mirror McpToolView）。
        if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
            detail = str(exc.detail) if hasattr(exc, "detail") else str(exc)
            return Response(
                {
                    "ok": False,
                    "error": {"code": "authentication_failed", "message": detail},
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return super().handle_exception(exc)

    async def post(self, request: Request) -> Response:
        serializer = RemoteToolExecuteSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        # 审计：以 owner 身份建顶层 run，指纹=token_hash（绝不明文，per MCPB-02/IDENT-04）。
        run = await begin_interaction_run(request, source="tool")
        tool_name = serializer.validated_data["name"]
        arguments = serializer.validated_data.get("arguments") or {}
        started_at = time.perf_counter()
        # run 透传（101-04）：skill 分支写步级 ToolCallRecord；其余顶层审计逻辑不动。
        result = await execute_tool(tool_name, arguments, run=run)
        # 收尾审计（mirror McpToolView）：记录 tool-call 明细并把 run 推进到终态，
        # 否则 begin_interaction_run 建的 RUNNING run 永不闭合，留下悬挂记录、且
        # X-Friday-Run-ID 复用查询会命中陈旧 run。input/output 经 ledger 写库前
        # redact_for_ledger 兜底脱敏（明文 PAT 只在 Authorization header，不入审计）。
        ok = bool(result.get("ok"))
        duration_ms = max(int((time.perf_counter() - started_at) * 1000), 0)
        await arecord_tool_call(
            run,
            tool_name=tool_name,
            input=arguments,
            output=result,
            status="ok" if ok else "error",
            duration_ms=duration_ms,
            error="" if ok else str((result.get("error") or {})),
        )
        run.status = InteractionRun.Status.COMPLETED if ok else InteractionRun.Status.ERROR
        run.completed_at = timezone.now()
        await run.asave(update_fields=["status", "completed_at"])
        return Response(result, status=status.HTTP_200_OK)
