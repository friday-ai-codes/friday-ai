"""Prompt API views — 6 个 async APIView 覆盖 CRUD + Preview + Versions。

implementation-02 Task 2 产出。所有 view 基于 `adrf.views.APIView` 手写
`async def get/post/patch/delete`，permission_classes = [IsAuthenticated]
作为 baseline；写操作在方法内再通过 `_require_write_permission` 辅助做方法级
RBAC 切换（contract）。

错误处理：`_handle_prompt_error()` 把 Plan-01 的 exception 体系映射到 HTTP：
- PromptVariableMissingError → 422
- PromptNotFoundError → 404
- PromptRenderError → 500
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from projects.models import Space
from prompts.exceptions import (
    PromptError,
    PromptNotFoundError,
    PromptRenderError,
    PromptVariableMissingError,
)
from prompts.models import Prompt, PromptScope, PromptVersion
from prompts.permissions import (
    _require_project_read_permission,
    _require_project_write_permission,
    _require_read_permission,
    _require_write_permission,
)
from prompts.serializers import (
    PromptCreateSerializer,
    PromptDetailSerializer,
    PromptListSerializer,
    PromptPreviewRequestSerializer,
    PromptUpdateSerializer,
    PromptVersionSerializer,
)
from prompts.services import (
    activate_version,
    append_version,
    compute_version_diff,
    render_prompt,
)

logger = structlog.get_logger(__name__)


# ============================================================================
# Exception → HTTP mapping（contract 校验结果与 LLM 渲染故障的 HTTP 出口）
# ============================================================================


def _handle_prompt_error(exc: PromptError) -> Response:
    """把 Plan-01 prompt exception 统一映射到 HTTP Response。"""
    if isinstance(exc, PromptVariableMissingError):
        return Response(
            {
                "error": "prompt_variable_missing",
                "slug": exc.slug,
                "missing": exc.missing,
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if isinstance(exc, PromptNotFoundError):
        return Response(
            {"error": "prompt_not_found", "slug": exc.slug},
            status=status.HTTP_404_NOT_FOUND,
        )
    if isinstance(exc, PromptRenderError):
        logger.error(
            "prompt_render_failed",
            slug=exc.slug,
            reason=exc.reason,
        )
        return Response(
            {
                "error": "prompt_render_error",
                "slug": exc.slug,
                "detail": exc.reason,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return Response(
        {"error": "prompt_unknown_error"},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


async def _avalidate(serializer: Any, *, raise_exception: bool = True) -> bool:
    """把 DRF 同步 is_valid() 包装为 async。"""
    return await sync_to_async(serializer.is_valid)(raise_exception=raise_exception)


async def _serialize(serializer_cls: Any, instance: Any, **kwargs: Any) -> Any:
    """在 async 上下文中安全计算 serializer.data（避免同步 ORM 访问报错）。"""
    def _build() -> Any:
        return serializer_cls(instance, **kwargs).data

    return await sync_to_async(_build)()


# ============================================================================
# List + Create
# ============================================================================


class PromptListView(APIView):
    """GET /api/prompts/ + POST /api/prompts/ — list & create。"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="列出 Prompt（按 scope 过滤）",
        description=(
            "`?scope=system` 返回所有系统级 prompt（任何登录用户可读）；"
            "`?scope=project&space_id=<uuid>` 返回指定空间的空间级 prompt "
            "（需 VIEWER+ 成员角色）。可选 `?category=<chat_agent|aux_model|...>` 过滤。"
        ),
        tags=["Prompts"],
    )
    async def get(self, request: Any) -> Response:
        scope = request.query_params.get("scope", "system")
        category = request.query_params.get("category")

        if scope not in (PromptScope.SYSTEM, PromptScope.PROJECT):
            return Response(
                {"error": "invalid_scope", "detail": "scope 必须是 system 或 project"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = Prompt.objects.select_related("active_version")

        if scope == PromptScope.SYSTEM:
            qs = qs.filter(scope=PromptScope.SYSTEM)
        else:
            space_id = request.query_params.get("space_id")
            if not space_id:
                return Response(
                    {
                        "error": "missing_space_id",
                        "detail": "scope=project 必须指定 space_id",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # 空间成员资格检查（security mitigation）
            project = await aget_object_or_404(Space, pk=space_id)
            denied = await _require_project_read_permission(request, project)
            if denied is not None:
                return denied
            qs = qs.filter(scope=PromptScope.PROJECT, space_id=space_id)

        if category:
            qs = qs.filter(category=category)

        items = [p async for p in qs.order_by("slug")]
        data = await _serialize(PromptListSerializer, items, many=True)
        return Response(data)

    @extend_schema(
        summary="创建 Prompt（自动追加首版）",
        description=(
            "系统级 → 仅 superuser 可创建；项目级 → 需目标 project 的 ADMIN 角色。"
            "首版 body 通过 `append_version()` 服务层写入并自动激活（contract）。"
        ),
        request=PromptCreateSerializer,
        tags=["Prompts"],
    )
    async def post(self, request: Any) -> Response:
        serializer = PromptCreateSerializer(data=request.data)
        valid = await _avalidate(serializer, raise_exception=False)
        if not valid:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        scope = data["scope"]

        # 权限：system → superuser，project → space ADMIN
        if scope == PromptScope.SYSTEM:
            if not request.user.is_superuser:
                return Response(
                    {
                        "error": "permission_denied",
                        "detail": "系统级 prompt 仅超级管理员可创建",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
        else:  # PROJECT
            denied = await _require_project_write_permission(request, data["project"])
            if denied is not None:
                return denied

        # 创建 Prompt（is_builtin=False，用户创建的都非 builtin）+ 首版追加
        prompt = await Prompt.objects.acreate(
            slug=data["slug"],
            category=data["category"],
            scope=scope,
            space=data.get("project"),
            title=data["title"],
            description=data.get("description", ""),
            is_builtin=False,
            created_by=request.user,
        )
        await append_version(
            prompt,
            data["body"],
            request.user,
            change_note=data.get("change_note", ""),
        )
        # 重新加载以获取最新的 active_version FK
        prompt = await (
            Prompt.objects.select_related("active_version", "active_version__prompt")
            .aget(pk=prompt.pk)
        )
        response_data = await _serialize(PromptDetailSerializer, prompt)
        logger.info(
            "prompt_created",
            slug=prompt.slug,
            scope=scope,
            space_id=str(prompt.space_id) if prompt.space_id else None,
        )
        return Response(response_data, status=status.HTTP_201_CREATED)


# ============================================================================
# Detail (retrieve / update / delete)
# ============================================================================


class PromptDetailView(APIView):
    """GET/PATCH/DELETE /api/prompts/<uuid>/"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="读取 Prompt 详情",
        description="含 active_version 完整 body 与运行时 declared_variables。",
        tags=["Prompts"],
    )
    async def get(self, request: Any, prompt_id: UUID) -> Response:
        prompt = await aget_object_or_404(
            Prompt.objects.select_related(
                "active_version", "active_version__prompt", "space"
            ),
            pk=prompt_id,
        )
        denied = await _require_read_permission(request, prompt)
        if denied is not None:
            return denied
        data = await _serialize(PromptDetailSerializer, prompt)
        return Response(data)

    @extend_schema(
        summary="编辑 Prompt（body 变更自动追加版本）",
        description=(
            "title / description 原地更新。body 变更走 `append_version()`（contract），"
            "字节级相等时幂等跳过。"
        ),
        request=PromptUpdateSerializer,
        tags=["Prompts"],
    )
    async def patch(self, request: Any, prompt_id: UUID) -> Response:
        prompt = await aget_object_or_404(
            Prompt.objects.select_related(
                "active_version", "active_version__prompt", "space"
            ),
            pk=prompt_id,
        )
        denied = await _require_write_permission(request, prompt)
        if denied is not None:
            return denied

        serializer = PromptUpdateSerializer(data=request.data, partial=True)
        valid = await _avalidate(serializer, raise_exception=False)
        if not valid:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        # inline 字段（title / description）
        inline_fields: list[str] = []
        if "title" in data:
            prompt.title = data["title"]
            inline_fields.append("title")
        if "description" in data:
            prompt.description = data["description"]
            inline_fields.append("description")
        if inline_fields:
            inline_fields.append("updated_at")
            await prompt.asave(update_fields=inline_fields)

        # body 变更 → append_version（幂等由 services 层处理）
        if "body" in data:
            await append_version(
                prompt,
                data["body"],
                request.user,
                change_note=data.get("change_note", ""),
            )

        # 重新加载以拿到最新 active_version（可能是新追加的，也可能是幂等跳过的原版本）
        prompt = await (
            Prompt.objects.select_related(
                "active_version", "active_version__prompt", "space"
            )
            .aget(pk=prompt.pk)
        )
        response_data = await _serialize(PromptDetailSerializer, prompt)
        return Response(response_data)

    @extend_schema(
        summary="删除 Prompt",
        description=(
            "is_builtin=True 且 scope=system 的 Prompt 禁止删除（security mitigation）；"
            "其他返回 204 并级联删除 PromptVersion。"
        ),
        tags=["Prompts"],
    )
    async def delete(self, request: Any, prompt_id: UUID) -> Response:
        prompt = await aget_object_or_404(
            Prompt.objects.select_related("space"),
            pk=prompt_id,
        )
        denied = await _require_write_permission(request, prompt)
        if denied is not None:
            return denied

        if prompt.is_builtin and prompt.scope == PromptScope.SYSTEM:
            return Response(
                {
                    "error": "builtin_not_deletable",
                    "detail": "内置系统级 prompt 禁止删除",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        await prompt.adelete()
        logger.info(
            "prompt_deleted",
            slug=prompt.slug,
            scope=prompt.scope,
            prompt_id=str(prompt_id),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ============================================================================
# Preview
# ============================================================================


class PromptRenderPreviewView(APIView):
    """POST /api/prompts/<uuid>/preview/ — 渲染预览。"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="渲染 Prompt 预览",
        description=(
            "调用 `render_prompt()` 服务层，对传入 variables 做 contract 声明校验 + "
            "contract 三步清洗 + Jinja2 sandbox 渲染。变量缺失返回 422。"
        ),
        request=PromptPreviewRequestSerializer,
        tags=["Prompts"],
    )
    async def post(self, request: Any, prompt_id: UUID) -> Response:
        prompt = await aget_object_or_404(
            Prompt.objects.select_related(
                "active_version", "active_version__prompt", "space"
            ),
            pk=prompt_id,
        )
        denied = await _require_read_permission(request, prompt)
        if denied is not None:
            return denied

        req = PromptPreviewRequestSerializer(data=request.data)
        valid = await _avalidate(req, raise_exception=False)
        if not valid:
            return Response(req.errors, status=status.HTTP_400_BAD_REQUEST)
        variables = req.validated_data.get("variables", {})

        try:
            rendered = await render_prompt(
                slug=prompt.slug,
                project_id=(
                    str(prompt.space_id) if prompt.space_id else None
                ),
                variables=variables,
                fallback="",
            )
        except PromptError as exc:
            return _handle_prompt_error(exc)

        return Response({"rendered": rendered})


# ============================================================================
# Versions (list / diff / activate)
# ============================================================================


class PromptVersionListView(APIView):
    """GET /api/prompts/<uuid>/versions/"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="列出 Prompt 所有版本",
        description="按 version DESC 排序。含每版 body + declared_variables。",
        tags=["Prompts"],
    )
    async def get(self, request: Any, prompt_id: UUID) -> Response:
        prompt = await aget_object_or_404(
            Prompt.objects.select_related("space"), pk=prompt_id
        )
        denied = await _require_read_permission(request, prompt)
        if denied is not None:
            return denied

        versions = [
            v async for v in prompt.versions.order_by("-version")
        ]
        data = await _serialize(PromptVersionSerializer, versions, many=True)
        return Response(data)


class PromptVersionDiffView(APIView):
    """GET /api/prompts/<uuid>/versions/<int:v1_num>/diff/<int:v2_num>/"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="计算两个版本之间的 unified diff",
        description="返回 difflib.unified_diff 纯文本，前端用 jsdiff 渲染。",
        tags=["Prompts"],
    )
    async def get(
        self,
        request: Any,
        prompt_id: UUID,
        v1_num: int,
        v2_num: int,
    ) -> Response:
        prompt = await aget_object_or_404(
            Prompt.objects.select_related("space"), pk=prompt_id
        )
        denied = await _require_read_permission(request, prompt)
        if denied is not None:
            return denied

        v1 = await aget_object_or_404(
            PromptVersion, prompt=prompt, version=v1_num
        )
        v2 = await aget_object_or_404(
            PromptVersion, prompt=prompt, version=v2_num
        )
        diff_text = compute_version_diff(v1, v2)
        return Response(
            {
                "diff": diff_text,
                "v1": v1_num,
                "v2": v2_num,
            }
        )


class PromptActivateVersionView(APIView):
    """POST /api/prompts/<uuid>/activate/<uuid:version_id>/"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="切换 active_version 指针（回滚通道）",
        description=(
            "pointer flip only（contract），不创建新版本。仅写权限用户可调用："
            "系统级 → superuser，项目级 → 项目 ADMIN。security mitigation：复合查询 "
            "绑定 prompt 避免跨 prompt 误切换。"
        ),
        tags=["Prompts"],
    )
    async def post(
        self,
        request: Any,
        prompt_id: UUID,
        version_id: UUID,
    ) -> Response:
        prompt = await aget_object_or_404(
            Prompt.objects.select_related(
                "active_version", "active_version__prompt", "space"
            ),
            pk=prompt_id,
        )
        denied = await _require_write_permission(request, prompt)
        if denied is not None:
            return denied

        target = await aget_object_or_404(
            PromptVersion, pk=version_id, prompt=prompt
        )
        await activate_version(prompt, target)
        # 刷新以拿到最新 active_version 指针
        prompt = await (
            Prompt.objects.select_related(
                "active_version", "active_version__prompt", "space"
            )
            .aget(pk=prompt.pk)
        )
        data = await _serialize(PromptDetailSerializer, prompt)
        return Response(data)
