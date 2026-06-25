"""Runners app views - 注册/注销/验证/管理 API。"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from adrf.views import APIView
from adrf.viewsets import ModelViewSet
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from permissions.api_permissions import IsSuperUser

from .authentication import RunnerTokenAuthentication
from .models import (
    RegistrationToken,
    Runner,
    RunnerEvent,
    RunnerTaskAssignment,
    generate_token,
    hash_token,
)
from .serializers import (
    RegistrationTokenCreateSerializer,
    RegistrationTokenSerializer,
    RunnerEventSerializer,
    RunnerRegisterResponseSerializer,
    RunnerRegisterSerializer,
    RunnerSerializer,
    RunnerTaskAssignmentSerializer,
)


class IsRunnerAuthenticated(BasePermission):
    """Require a valid runner token-authenticated request."""

    message = "Runner authentication credentials were not provided."

    def has_permission(self, request, view) -> bool:
        return bool(getattr(request, "auth", None))


class RegistrationTokenViewSet(ModelViewSet):
    """Registration token 管理（JWT 认证，限 superuser）。"""

    queryset = RegistrationToken.objects.all().order_by("-created_at")
    serializer_class = RegistrationTokenSerializer
    permission_classes = [IsSuperUser]
    http_method_names = ["get", "post", "delete", "head", "options"]

    async def acreate(self, request, *args, **kwargs):
        serializer = RegistrationTokenCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        token = generate_token()
        reg_token = await RegistrationToken.objects.acreate(
            token_hash=hash_token(token),
            description=data.get("description", ""),
            scope=data["scope"],
            space_id=data.get("project_id"),
            tags=data.get("tags", []),
            run_untagged=data.get("run_untagged", True),
            is_paused=data.get("is_paused", False),
            is_protected=data.get("is_protected", False),
            max_timeout=data.get("max_timeout"),
            expires_at=timezone.now() + timedelta(seconds=data["expires_in"]),
            created_by=request.user,
        )

        response_data = RegistrationTokenSerializer(reg_token).data
        response_data["token"] = token  # 明文 token 仅返回一次
        return Response(response_data, status=status.HTTP_201_CREATED)


class RunnerRegisterView(APIView):
    """Runner 注册（无认证，用 registration token）。"""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    async def post(self, request):
        serializer = RunnerRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 共享注册令牌（GitLab 风格）：容器化部署用 RUNNER_REGISTRATION_TOKEN 环境变量
        # 完成自动注册，无需先在 UI 创建一次性令牌。按 name 幂等，避免数据卷丢失后重复建 Runner。
        master_token = settings.RUNNER_REGISTRATION_TOKEN
        if master_token and secrets.compare_digest(str(data["token"]), str(master_token)):
            return await self._register_with_master_token(request, data)

        token_hashed = hash_token(data["token"])
        now = timezone.now()

        # 原子操作：标记 token 已使用
        updated = await RegistrationToken.objects.filter(
            token_hash=token_hashed, is_used=False, expires_at__gt=now
        ).aupdate(is_used=True, used_at=now)

        if not updated:
            return Response(
                {"detail": "注册令牌无效或已过期"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        reg_token = await RegistrationToken.objects.aget(token_hash=token_hashed)

        # 生成 runner auth token
        runner_token = generate_token()
        runner = await Runner.objects.acreate(
            name=data["name"],
            token_hash=hash_token(runner_token),
            token_prefix=runner_token[:8],
            scope=data["scope"],
            concurrent=data["concurrent"],
            version=data.get("version", ""),
            ip_address=request.META.get("REMOTE_ADDR"),
            # 继承 token 预设配置
            description=reg_token.description,
            tags=reg_token.tags or ["coding"],
            run_untagged=reg_token.run_untagged,
            is_paused=reg_token.is_paused,
            is_protected=reg_token.is_protected,
            max_timeout=reg_token.max_timeout,
        )

        # 绑定项目
        if reg_token.space:
            await runner.spaces.aadd(reg_token.space)

        # 回写 used_by_runner
        reg_token.used_by_runner = runner
        await reg_token.asave(update_fields=["used_by_runner"])

        return Response(
            RunnerRegisterResponseSerializer(
                {
                    "runner_id": runner.id,
                    "runner_token": runner_token,
                    "name": runner.name,
                    "scope": runner.scope,
                }
            ).data,
            status=status.HTTP_201_CREATED,
        )

    async def _register_with_master_token(self, request, data: dict) -> Response:
        """用共享注册令牌注册：按 name 幂等，重注册时轮换 Runner token。"""
        runner_token = generate_token()
        runner = await Runner.objects.filter(name=data["name"]).afirst()
        if runner is None:
            runner = await Runner.objects.acreate(
                name=data["name"],
                token_hash=hash_token(runner_token),
                token_prefix=runner_token[:8],
                scope=data["scope"],
                concurrent=data["concurrent"],
                version=data.get("version", ""),
                ip_address=request.META.get("REMOTE_ADDR"),
                tags=["coding"],
                run_untagged=True,
            )
        else:
            runner.token_hash = hash_token(runner_token)
            runner.token_prefix = runner_token[:8]
            runner.scope = data["scope"]
            runner.concurrent = data["concurrent"]
            runner.version = data.get("version", "")
            runner.ip_address = request.META.get("REMOTE_ADDR")
            runner.is_active = True
            await runner.asave(
                update_fields=[
                    "token_hash",
                    "token_prefix",
                    "scope",
                    "concurrent",
                    "version",
                    "ip_address",
                    "is_active",
                    "updated_at",
                ]
            )

        return Response(
            RunnerRegisterResponseSerializer(
                {
                    "runner_id": runner.id,
                    "runner_token": runner_token,
                    "name": runner.name,
                    "scope": runner.scope,
                }
            ).data,
            status=status.HTTP_201_CREATED,
        )


class RunnerUnregisterView(APIView):
    """Runner 注销（Runner Token 认证）。"""

    authentication_classes = [RunnerTokenAuthentication]
    permission_classes = [IsRunnerAuthenticated]

    async def delete(self, request):
        runner = request.auth
        runner.is_active = False
        await runner.asave(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class RunnerVerifyView(APIView):
    """Runner Token 验证（Runner Token 认证）。"""

    authentication_classes = [RunnerTokenAuthentication]
    permission_classes = [IsRunnerAuthenticated]

    async def get(self, request):
        runner = request.auth
        return Response(
            {
                "id": str(runner.id),
                "name": runner.name,
                "scope": runner.scope,
                "status": runner.status,
                "concurrent": runner.concurrent,
                "version": runner.version,
                "last_heartbeat": runner.last_heartbeat,
            }
        )


class RunnerPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class RunnerViewSet(ModelViewSet):
    """Runner 管理（JWT 认证，限 superuser）。"""

    # 心跳超时阈值：3 倍心跳间隔（Runner 每 30 秒发一次心跳）
    HEARTBEAT_STALE_SECONDS = 90

    queryset = Runner.objects.all().order_by("-registered_at")
    serializer_class = RunnerSerializer
    pagination_class = RunnerPagination
    permission_classes = [IsSuperUser]
    http_method_names = ["get", "delete", "head", "options"]

    def get_queryset(self) -> Any:
        qs = super().get_queryset()
        params = self.request.query_params
        if s := params.get("status"):
            qs = qs.filter(status=s)
        if search := params.get("search"):
            qs = qs.filter(name__icontains=search)
        if tags := params.get("tags"):
            for tag in tags.split(","):
                tag = tag.strip()
                if tag:
                    qs = qs.filter(tags__contains=tag)
        return qs

    async def alist(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """列表前先清理心跳超时的虚假在线 Runner。"""
        stale_threshold = timezone.now() - timedelta(seconds=self.HEARTBEAT_STALE_SECONDS)
        await Runner.objects.filter(
            status="online",
            last_heartbeat__lt=stale_threshold,
        ).aupdate(status="offline", channel_name="")
        return await super().alist(request, *args, **kwargs)

    @action(detail=True, methods=["get"])
    async def tasks(self, request: Request, pk: str | None = None) -> Response:
        """GET /api/runners/{id}/tasks/ — Runner 关联任务列表。"""
        runner = await self.aget_object()
        qs = (
            RunnerTaskAssignment.objects.filter(
                runner=runner,
            )
            .select_related("session")
            .order_by("-assigned_at")
        )
        params = request.query_params
        if s := params.get("status"):
            qs = qs.filter(status=s)
        if since := params.get("since"):
            qs = qs.filter(assigned_at__gte=since)
        if until := params.get("until"):
            qs = qs.filter(assigned_at__lte=until)
        page = await sync_to_async(self.paginate_queryset)(
            qs
        )  # KEEP: DRF paginate_queryset() 无 async API
        serializer = RunnerTaskAssignmentSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=True, methods=["get"])
    async def logs(self, request: Request, pk: str | None = None) -> Response:
        """GET /api/runners/{id}/logs/ — Runner 事件日志。"""
        runner = await self.aget_object()
        qs = RunnerEvent.objects.filter(runner=runner)
        if event_type := request.query_params.get("event_type"):
            qs = qs.filter(event_type=event_type)
        page = await sync_to_async(self.paginate_queryset)(
            qs
        )  # KEEP: DRF paginate_queryset() 无 async API
        serializer = RunnerEventSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)
