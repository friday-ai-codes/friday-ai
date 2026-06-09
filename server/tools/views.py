"""tools app views —— 绑定 CRUD（owner 隔离 + upsert）、可绑定列表、执行端点。

两条主线：
- 绑定 CRUD（``ToolTokenBindingViewSet`` / ``BindableToolsView``）：CookieJWT
  认证，``get_queryset`` 按 ``request.user`` 隔离（T-10-02）；``acreate`` 经
  ``aupdate_or_create`` 收敛为 upsert（T-10-04）。
- 执行端点（``RemoteToolExecuteView``）：PAT-only fail-closed（T-10-03），
  ``begin_interaction_run`` 审计（指纹=token_hash）后透传 ``execute_tool``。
"""

from __future__ import annotations

import time
from typing import Any

from adrf.views import APIView
from adrf.viewsets import ModelViewSet
from asgiref.sync import sync_to_async
from django.db import IntegrityError
from django.utils import timezone
from interactions.entry import AccessTokenAuthentication, begin_interaction_run
from interactions.ledger import arecord_tool_call
from interactions.models import InteractionRun
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from tools.executor import execute_tool

from .models import RemoteTool, ToolTokenBinding
from .serializers import (
    BindableToolSerializer,
    RemoteToolExecuteSerializer,
    ToolTokenBindingCreateSerializer,
    ToolTokenBindingSerializer,
)


class ToolTokenBindingViewSet(ModelViewSet):
    """工具令牌绑定 CRUD —— owner 隔离 + upsert（CookieJWT 认证）。"""

    serializer_class = ToolTokenBindingSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self) -> Any:
        # owner 隔离（T-10-02）：用户只能看见/操作自己的绑定；越权 list 天然空集，
        # 越权 delete 经 aget_object → 404（不泄漏存在性）。
        return (
            ToolTokenBinding.objects.filter(user=self.request.user)
            .select_related("access_token", "remote_tool")
            .order_by("-created_at")
        )

    async def acreate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ToolTokenBindingCreateSerializer(
            data=request.data, context={"request": request}
        )
        # async-safe 校验（per Pitfall 4）：归属 + source/active 关卡在此收成 400。
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        # upsert（per Pitfall 3）：同一 (user, remote_tool) 重复绑定即换令牌，
        # 不撞 unique_together 抛 500。
        # aupdate_or_create 内部是「先 get 再 create」，并发双发（双击/重试）可能
        # 双双 miss get 再竞争 create，撞 unique_together(user, remote_tool) → 500。
        # 捕获 IntegrityError 收敛为对既有绑定的换令牌更新，保证 upsert 语义恒成立。
        try:
            binding, _created = await ToolTokenBinding.objects.aupdate_or_create(
                user=request.user,
                remote_tool=serializer.validated_data["remote_tool"],
                defaults={"access_token": serializer.validated_data["access_token"]},
            )
        except IntegrityError:
            binding = await ToolTokenBinding.objects.aget(
                user=request.user,
                remote_tool=serializer.validated_data["remote_tool"],
            )
            binding.access_token = serializer.validated_data["access_token"]
            await binding.asave(update_fields=["access_token", "updated_at"])
        # 重新取出并预取关联，使输出序列化器零额外同步查询。
        binding = await (
            ToolTokenBinding.objects.select_related("access_token", "remote_tool").aget(
                pk=binding.pk
            )
        )
        return Response(
            ToolTokenBindingSerializer(binding).data, status=status.HTTP_201_CREATED
        )


class BindableToolsView(APIView):
    """可绑定工具列表 —— 仅 source ∈ {mcp, skill} 且 is_active（per MCPB-01）。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Request) -> Response:
        tools = [
            tool
            async for tool in RemoteTool.objects.filter(
                source__in=[RemoteTool.Source.MCP, RemoteTool.Source.SKILL],
                is_active=True,
            ).order_by("name")
        ]
        return Response(BindableToolSerializer(tools, many=True).data)


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
        # 不改 execute_tool 签名、不传 user（Phase 11 gap，per RESEARCH Open Q1）。
        result = await execute_tool(tool_name, arguments)
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
        run.status = (
            InteractionRun.Status.COMPLETED if ok else InteractionRun.Status.ERROR
        )
        run.completed_at = timezone.now()
        await run.asave(update_fields=["status", "completed_at"])
        return Response(result, status=status.HTTP_200_OK)
