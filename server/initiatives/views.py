"""initiatives app views（项目/成员 REST API，adrf 异步）。

权限按所属 Space 成员权限 fail-closed（复用 ``PermissionService``）：
- 读（list/retrieve/members list）= Space viewer+ 或项目成员；
- 写（create/update/transition/member 增删改/transfer）= Space admin+ 或 superuser。

所有写入收口于 ``ProjectService``（INV-6）；状态非法流转 / 成员非法操作 fail-loud → 400。
新增 REST 入口经统一中间件自动纳入 QPS/错误率/时长指标。
"""

from __future__ import annotations

from typing import Any

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.shortcuts import aget_object_or_404
from rest_framework import status
from rest_framework.response import Response

from initiatives.models import (
    Artifact,
    ArtifactType,
    MergeRequest,
    Project,
    ProjectBranch,
    ProjectDoc,
    ProjectMember,
    ProjectMemory,
    ProjectMemoryDraft,
    ProjectMemoryStatus,
    ProjectStateApi,
)
from initiatives.permissions import (
    auser_can_access_project,
    auser_is_project_member,
)
from initiatives.serializers import (
    ArtifactCreateSerializer,
    ArtifactSerializer,
    ArtifactTypeCreateSerializer,
    ArtifactTypeSerializer,
    ArtifactTypeUpdateSerializer,
    ArtifactUpdateSerializer,
    ContextLinkManualCreateSerializer,
    ContextLinkRepoDecisionSerializer,
    MergeRequestSerializer,
    ProjectBranchBindRequestSerializer,
    ProjectBranchSerializer,
    ProjectContextLinkSerializer,
    ProjectCreateSerializer,
    ProjectDocContentSerializer,
    ProjectDocHumanBlocksWriteSerializer,
    ProjectDocSerializer,
    ProjectKnowledgeLinkSerializer,
    ProjectMemberAddSerializer,
    ProjectMemberSerializer,
    ProjectMemberUpdateSerializer,
    ProjectMemoryCreateSerializer,
    ProjectMemoryDistillSerializer,
    ProjectMemoryDraftSerializer,
    ProjectMemoryEditSerializer,
    ProjectMemorySerializer,
    ProjectOwnerTransferSerializer,
    ProjectRehomeSerializer,
    ProjectSearchResultSerializer,
    ProjectSerializer,
    ProjectStateApiCreateSerializer,
    ProjectStateApiSerializer,
    ProjectStateApiUpdateSerializer,
    ProjectTransitionSerializer,
    ProjectUpdateSerializer,
)
from initiatives.services import (
    ArtifactError,
    ArtifactService,
    ContextLinkError,
    ContextLinkService,
    DocContentError,
    DocContentNotFound,
    DocContentService,
    FeatureListService,
    HumanWriteForbidden,
    MemoryDistiller,
    MemoryError,
    MemoryPermissionError,
    MemoryService,
    ProjectBranchError,
    ProjectBranchPermissionError,
    ProjectBranchService,
    ProjectDocService,
    ProjectMemberError,
    ProjectRehomeError,
    ProjectSearchService,
    ProjectService,
    ProjectTransitionError,
    SystemReadOnlyError,
)
from initiatives.services.artifact_view import aget_artifact_view
from initiatives.services.doc_content_service import ALLOWED_DOC_TYPES
from initiatives.services.knowledge_graph import (
    ProjectGraphError,
    ProjectKnowledgeGraphService,
)
from permissions.models import SpaceRole
from permissions.services import PermissionService
from projects.models import Space

logger = structlog.get_logger(__name__)
User = get_user_model()


async def _aget_space(space_id):
    return await Space.objects.filter(pk=space_id).afirst()


class ProjectListCreateView(APIView):
    """项目列表（GET，按可见性过滤）+ 创建（POST，幂等）。"""

    async def get(self, request):
        """列出对当前用户可见的项目（Space 成员可见 + 项目成员可见）。

        可选筛选 query 参数（additive，缺省 = 现状）：``space_id`` / ``status`` /
        ``member``(user_id) / ``q``(名称/描述关键词)。

        可选分页（additive）：带 ``limit``（1..100）时返回
        ``{results, total, limit, offset}`` 分页包，供前端无限滚动按需加载；
        不带 ``limit`` 保持原始数组响应，既有调用方零改动。
        统一按 ``created_at`` 倒序（越新越靠前）。
        """
        user = request.user
        filters = {
            "space_id": request.query_params.get("space_id") or "",
            "status": request.query_params.get("status") or "",
            "member": request.query_params.get("member") or "",
            "q": (request.query_params.get("q") or "").strip(),
        }
        limit_raw = request.query_params.get("limit") or ""
        if limit_raw:
            limit = self._parse_int(limit_raw, default=24, lo=1, hi=100)
            offset = self._parse_int(
                request.query_params.get("offset") or "", default=0, lo=0
            )
            projects, total = await self._list_visible_page(user, filters, limit, offset)
            data = await sync_to_async(
                lambda: ProjectSerializer(projects, many=True).data
            )()
            return Response(
                {"results": data, "total": total, "limit": limit, "offset": offset}
            )
        projects = await self._list_visible(user, filters)
        data = await sync_to_async(
            lambda: ProjectSerializer(projects, many=True).data
        )()
        return Response(data)

    @staticmethod
    def _parse_int(raw: str, *, default: int, lo: int, hi: int | None = None) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        if value < lo:
            return lo
        if hi is not None and value > hi:
            return hi
        return value

    def _visible_qs(self, user, filters: dict[str, str]):
        """可见性 + 筛选 queryset；显式倒序（join + distinct 下不依赖模型默认排序）。"""
        from django.db.models import Q

        qs = Project.objects.select_related("space").prefetch_related("members")
        if not user.is_superuser:
            # Space 成员可见 OR 项目成员可见
            qs = qs.filter(
                Q(space__memberships__user=user) | Q(members__user=user)
            )
        # 可选筛选（additive）。
        if filters.get("space_id"):
            qs = qs.filter(space_id=filters["space_id"])
        if filters.get("status"):
            qs = qs.filter(status=filters["status"])
        if filters.get("member"):
            qs = qs.filter(members__user_id=filters["member"])
        if filters.get("q"):
            q = filters["q"]
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
        return qs.distinct().order_by("-created_at")

    @sync_to_async
    def _list_visible(self, user, filters: dict[str, str]) -> list[Project]:
        if not user.is_authenticated:
            return []
        return list(self._visible_qs(user, filters))

    @sync_to_async
    def _list_visible_page(
        self, user, filters: dict[str, str], limit: int, offset: int
    ) -> tuple[list[Project], int]:
        if not user.is_authenticated:
            return [], 0
        qs = self._visible_qs(user, filters)
        total = qs.count()
        return list(qs[offset : offset + limit]), total

    async def post(self, request):
        """创建项目（PROJ-05）。需所属 Space admin+ 权限；(space, feishu_project_key) 幂等。"""
        serializer = ProjectCreateSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        data = serializer.validated_data

        space = await _aget_space(data["space_id"])
        if space is None:
            return Response({"detail": "空间不存在"}, status=status.HTTP_404_NOT_FOUND)

        has_admin = await sync_to_async(PermissionService.has_project_access)(
            request.user, space, SpaceRole.ADMIN
        )
        if not has_admin:
            return Response(
                {"detail": "仅空间管理员可创建项目"}, status=status.HTTP_403_FORBIDDEN
            )

        project, created = await ProjectService().create(
            space=space,
            name=data["name"],
            description=data.get("description", ""),
            feishu_project_key=data.get("feishu_project_key", ""),
            feishu_board_url=data.get("feishu_board_url", ""),
            feishu_board_id=data.get("feishu_board_id", ""),
            created_by=request.user,
            initiated_by_user_id=request.user.id,
        )
        project = await Project.objects.select_related("space").aget(pk=project.id)
        body = await sync_to_async(lambda: ProjectSerializer(project).data)()
        return Response(
            body,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ProjectDetailView(APIView):
    """项目详情（GET）+ 更新（PATCH）。"""

    async def get(self, request, project_id):
        project = await aget_object_or_404(
            Project.objects.select_related("space"), pk=project_id
        )
        allowed = await auser_can_access_project(request.user, project, SpaceRole.VIEWER)
        if not allowed:
            allowed = await auser_is_project_member(request.user, project_id)
        if not allowed:
            return Response({"detail": "无权访问此项目"}, status=status.HTTP_403_FORBIDDEN)
        body = await sync_to_async(lambda: ProjectSerializer(project).data)()
        return Response(body)

    async def patch(self, request, project_id):
        project = await aget_object_or_404(
            Project.objects.select_related("space"), pk=project_id
        )
        allowed = await auser_can_access_project(request.user, project, SpaceRole.ADMIN)
        if not allowed:
            return Response(
                {"detail": "仅空间管理员可修改项目"}, status=status.HTTP_403_FORBIDDEN
            )
        serializer = ProjectUpdateSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)

        updated = await ProjectService().update(
            project_id=project_id,
            actor=request.user,
            initiated_by_user_id=request.user.id,
            **serializer.validated_data,
        )
        updated = await Project.objects.select_related("space").aget(pk=updated.id)
        body = await sync_to_async(lambda: ProjectSerializer(updated).data)()
        return Response(body)


class ProjectTransitionView(APIView):
    """项目状态流转（POST，PROJ-02）。非法流转 → 400。"""

    async def post(self, request, project_id):
        project = await aget_object_or_404(
            Project.objects.select_related("space"), pk=project_id
        )
        allowed = await auser_can_access_project(request.user, project, SpaceRole.ADMIN)
        if not allowed:
            return Response(
                {"detail": "仅空间管理员可变更项目状态"}, status=status.HTTP_403_FORBIDDEN
            )
        serializer = ProjectTransitionSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)

        try:
            updated = await ProjectService().change_status(
                project_id=project_id,
                to_status=serializer.validated_data["to_status"],
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except ProjectTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        updated = await Project.objects.select_related("space").aget(pk=updated.id)
        body = await sync_to_async(lambda: ProjectSerializer(updated).data)()
        return Response(body)


class ProjectMemberListView(APIView):
    """项目成员列表（GET）+ 添加（POST，MEMBER-01）。"""

    async def get(self, request, project_id):
        project = await aget_object_or_404(
            Project.objects.select_related("space"), pk=project_id
        )
        allowed = await auser_can_access_project(request.user, project, SpaceRole.VIEWER)
        if not allowed:
            allowed = await auser_is_project_member(request.user, project_id)
        if not allowed:
            return Response({"detail": "无权访问此项目"}, status=status.HTTP_403_FORBIDDEN)

        members = await sync_to_async(
            lambda: list(
                ProjectMember.objects.filter(project_id=project_id)
                .select_related("user")
                .order_by("created_at")
            )
        )()
        data = await sync_to_async(
            lambda: ProjectMemberSerializer(members, many=True).data
        )()
        return Response(data)

    async def post(self, request, project_id):
        project = await aget_object_or_404(
            Project.objects.select_related("space"), pk=project_id
        )
        allowed = await auser_can_access_project(request.user, project, SpaceRole.ADMIN)
        if not allowed:
            return Response(
                {"detail": "仅空间管理员可添加项目成员"}, status=status.HTTP_403_FORBIDDEN
            )
        serializer = ProjectMemberAddSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)

        target_user = await User.objects.filter(
            pk=serializer.validated_data["user_id"]
        ).afirst()
        if target_user is None:
            return Response({"detail": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)

        try:
            member, created = await ProjectService().add_member(
                project_id=project_id,
                user=target_user,
                role=serializer.validated_data["role"],
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except ProjectMemberError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not created:
            return Response(
                {"detail": "该用户已是项目成员"}, status=status.HTTP_409_CONFLICT
            )
        member = await ProjectMember.objects.select_related("user").aget(pk=member.id)
        body = await sync_to_async(lambda: ProjectMemberSerializer(member).data)()
        return Response(body, status=status.HTTP_201_CREATED)


class ProjectMemberDetailView(APIView):
    """项目成员详情：变更角色（PATCH）/ 移除（DELETE）。"""

    async def patch(self, request, project_id, user_id):
        project = await aget_object_or_404(
            Project.objects.select_related("space"), pk=project_id
        )
        allowed = await auser_can_access_project(request.user, project, SpaceRole.ADMIN)
        if not allowed:
            return Response(
                {"detail": "仅空间管理员可变更成员角色"}, status=status.HTTP_403_FORBIDDEN
            )
        serializer = ProjectMemberUpdateSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)

        member = await ProjectMember.objects.filter(
            project_id=project_id, user_id=user_id
        ).afirst()
        if member is None:
            return Response({"detail": "成员关系不存在"}, status=status.HTTP_404_NOT_FOUND)

        try:
            await ProjectService().change_member_role(
                project_id=project_id,
                user_id=user_id,
                role=serializer.validated_data["role"],
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except ProjectMemberError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        member = await ProjectMember.objects.select_related("user").aget(pk=member.id)
        body = await sync_to_async(lambda: ProjectMemberSerializer(member).data)()
        return Response(body)

    async def delete(self, request, project_id, user_id):
        project = await aget_object_or_404(
            Project.objects.select_related("space"), pk=project_id
        )
        allowed = await auser_can_access_project(request.user, project, SpaceRole.ADMIN)
        if not allowed:
            return Response(
                {"detail": "仅空间管理员可移除项目成员"}, status=status.HTTP_403_FORBIDDEN
            )
        member = await ProjectMember.objects.filter(
            project_id=project_id, user_id=user_id
        ).afirst()
        if member is None:
            return Response({"detail": "成员关系不存在"}, status=status.HTTP_404_NOT_FOUND)

        try:
            await ProjectService().remove_member(
                project_id=project_id,
                user_id=user_id,
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except ProjectMemberError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectOwnerTransferView(APIView):
    """转移主R（POST，MEMBER-02）。新主R 须为既有成员。"""

    async def post(self, request, project_id):
        project = await aget_object_or_404(
            Project.objects.select_related("space"), pk=project_id
        )
        allowed = await auser_can_access_project(request.user, project, SpaceRole.ADMIN)
        if not allowed:
            return Response(
                {"detail": "仅空间管理员可转移主R"}, status=status.HTTP_403_FORBIDDEN
            )
        serializer = ProjectOwnerTransferSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)

        try:
            await ProjectService().transfer_owner(
                project_id=project_id,
                new_owner_user_id=serializer.validated_data["new_owner_user_id"],
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except ProjectMemberError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        members = await sync_to_async(
            lambda: list(
                ProjectMember.objects.filter(project_id=project_id)
                .select_related("user")
                .order_by("created_at")
            )
        )()
        data = await sync_to_async(
            lambda: ProjectMemberSerializer(members, many=True).data
        )()
        return Response(data)


# ============================ 工件（ARTIFACT-02/03/04/05）============================


async def _aget_project_for_write(request, project_id):
    """取项目 + 校验写权限（Space admin+）。返回 (project, error_response)。"""
    project = await aget_object_or_404(
        Project.objects.select_related("space"), pk=project_id
    )
    allowed = await auser_can_access_project(request.user, project, SpaceRole.ADMIN)
    if not allowed:
        return None, Response(
            {"detail": "仅空间管理员可管理工件"}, status=status.HTTP_403_FORBIDDEN
        )
    return project, None


async def _aget_project_for_read(request, project_id):
    """取项目 + 校验读权限（Space viewer+ 或项目成员）。返回 (project, error_response)。"""
    project = await aget_object_or_404(
        Project.objects.select_related("space"), pk=project_id
    )
    allowed = await auser_can_access_project(request.user, project, SpaceRole.VIEWER)
    if not allowed:
        allowed = await auser_is_project_member(request.user, project_id)
    if not allowed:
        return None, Response(
            {"detail": "无权访问此项目"}, status=status.HTTP_403_FORBIDDEN
        )
    return project, None


async def _maybe_autogen_description(artifact: Any, project_id: Any, request: Any) -> None:
    """feature_list 工件创建/更新后，按功能清单自动 AI 重写项目描述（#2，best-effort）。"""
    try:
        from initiatives.services.feature_list_service import FEATURE_LIST_TYPE_KEY

        type_key = getattr(getattr(artifact, "type", None), "key", "")
        if type_key != FEATURE_LIST_TYPE_KEY:
            return
        from initiatives.services.project_description_service import (
            ProjectDescriptionService,
        )

        await ProjectDescriptionService().agenerate_and_save(
            project_id, request.user, initiated_by_user_id=getattr(request.user, "id", None)
        )
    except Exception:  # noqa: BLE001 — 自动描述生成绝不反噬工件创建/更新主流程
        pass


class ProjectDescriptionGenerateView(APIView):
    """手动触发：按 feature list 用 AI 生成/更新项目描述（#2）。"""

    async def post(self, request, project_id):
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        from initiatives.services.project_description_service import (
            ProjectDescriptionService,
        )

        description = await ProjectDescriptionService().agenerate_and_save(
            project_id, request.user, initiated_by_user_id=getattr(request.user, "id", None)
        )
        if not description:
            return Response(
                {"detail": "暂无可用于生成描述的 feature list，或未配置 AI Provider"},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return Response({"description": description})


class ArtifactListCreateView(APIView):
    """项目工件列表（GET）+ 创建（POST，ARTIFACT-02）。"""

    async def get(self, request, project_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        artifacts = await sync_to_async(
            lambda: list(
                Artifact.objects.filter(project_id=project_id).select_related("type")
            )
        )()
        data = await sync_to_async(lambda: ArtifactSerializer(artifacts, many=True).data)()
        return Response(data)

    async def post(self, request, project_id):
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        serializer = ArtifactCreateSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        d = serializer.validated_data
        if not await ArtifactType.objects.filter(pk=d["type_id"]).aexists():
            return Response({"detail": "工件类型不存在"}, status=status.HTTP_404_NOT_FOUND)
        try:
            artifact = await ArtifactService().create_artifact(
                project_id=project_id,
                type_id=d["type_id"],
                title=d["title"],
                carrier=d.get("carrier", ""),
                url=d.get("url", ""),
                content_ref=d.get("content_ref", ""),
                contributor=request.user,
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except ArtifactError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        artifact = await Artifact.objects.select_related("type").aget(pk=artifact.id)
        await _maybe_autogen_description(artifact, project_id, request)
        body = await sync_to_async(lambda: ArtifactSerializer(artifact).data)()
        return Response(body, status=status.HTTP_201_CREATED)


class ArtifactDetailView(APIView):
    """工件详情（GET）+ 更新（PATCH，ARTIFACT-03）+ 删除（DELETE）。"""

    async def get(self, request, project_id, artifact_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        artifact = await Artifact.objects.select_related("type").filter(
            pk=artifact_id, project_id=project_id
        ).afirst()
        if artifact is None:
            return Response({"detail": "工件不存在"}, status=status.HTTP_404_NOT_FOUND)
        body = await sync_to_async(lambda: ArtifactSerializer(artifact).data)()
        return Response(body)

    async def patch(self, request, project_id, artifact_id):
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        if not await Artifact.objects.filter(pk=artifact_id, project_id=project_id).aexists():
            return Response({"detail": "工件不存在"}, status=status.HTTP_404_NOT_FOUND)
        serializer = ArtifactUpdateSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        try:
            await ArtifactService().update_artifact(
                artifact_id=artifact_id,
                actor=request.user,
                initiated_by_user_id=request.user.id,
                **serializer.validated_data,
            )
        except ArtifactError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        artifact = await Artifact.objects.select_related("type").aget(pk=artifact_id)
        await _maybe_autogen_description(artifact, project_id, request)
        body = await sync_to_async(lambda: ArtifactSerializer(artifact).data)()
        return Response(body)

    async def delete(self, request, project_id, artifact_id):
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        if not await Artifact.objects.filter(pk=artifact_id, project_id=project_id).aexists():
            return Response({"detail": "工件不存在"}, status=status.HTTP_404_NOT_FOUND)
        await ArtifactService().delete_artifact(
            artifact_id=artifact_id,
            actor=request.user,
            initiated_by_user_id=request.user.id,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ArtifactViewView(APIView):
    """工件在线查看（GET，ARTIFACT-03）：飞书 doc/表格渲染、外链元数据、md/内部内容。"""

    async def get(self, request, project_id, artifact_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        artifact = await Artifact.objects.select_related(
            "type", "project", "project__space"
        ).filter(pk=artifact_id, project_id=project_id).afirst()
        if artifact is None:
            return Response({"detail": "工件不存在"}, status=status.HTTP_404_NOT_FOUND)
        view_data = await aget_artifact_view(artifact)
        return Response(view_data)


# ============================ 工件类型管理（ARTIFACT-01/05，超管）============================


def _require_superuser(request) -> Response | None:
    if not getattr(request.user, "is_superuser", False):
        return Response({"detail": "仅超级管理员可管理工件类型"}, status=status.HTTP_403_FORBIDDEN)
    return None


class ArtifactTypeListCreateView(APIView):
    """工件类型列表（GET，已认证）+ 新增自定义类型（POST，超管）。"""

    async def get(self, request):
        types = await sync_to_async(lambda: list(ArtifactType.objects.all()))()
        data = await sync_to_async(lambda: ArtifactTypeSerializer(types, many=True).data)()
        return Response(data)

    async def post(self, request):
        denied = _require_superuser(request)
        if denied is not None:
            return denied
        serializer = ArtifactTypeCreateSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        try:
            artifact_type = await ArtifactService().create_type(
                actor=request.user,
                initiated_by_user_id=request.user.id,
                **serializer.validated_data,
            )
        except ArtifactError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        body = await sync_to_async(lambda: ArtifactTypeSerializer(artifact_type).data)()
        return Response(body, status=status.HTTP_201_CREATED)


class ArtifactTypeDetailView(APIView):
    """工件类型更新/禁用（PATCH，超管）+ 删除（DELETE，超管，受保护）。"""

    async def patch(self, request, type_id):
        denied = _require_superuser(request)
        if denied is not None:
            return denied
        if not await ArtifactType.objects.filter(pk=type_id).aexists():
            return Response({"detail": "工件类型不存在"}, status=status.HTTP_404_NOT_FOUND)
        serializer = ArtifactTypeUpdateSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        try:
            artifact_type = await ArtifactService().update_type(
                type_id=type_id,
                actor=request.user,
                initiated_by_user_id=request.user.id,
                **serializer.validated_data,
            )
        except ArtifactError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        body = await sync_to_async(lambda: ArtifactTypeSerializer(artifact_type).data)()
        return Response(body)

    async def delete(self, request, type_id):
        denied = _require_superuser(request)
        if denied is not None:
            return denied
        if not await ArtifactType.objects.filter(pk=type_id).aexists():
            return Response({"detail": "工件类型不存在"}, status=status.HTTP_404_NOT_FOUND)
        try:
            await ArtifactService().delete_type(
                type_id=type_id,
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except ArtifactError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ============================ 知识关联（KLINK-01/02）============================


class ProjectKnowledgeLinkView(APIView):
    """关联知识实体到项目（POST，KLINK-01；Space admin+）。"""

    async def post(self, request, project_id):
        project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        serializer = ProjectKnowledgeLinkSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        try:
            created = await ProjectKnowledgeGraphService().link_knowledge(
                project=project,
                entity_id=serializer.validated_data["entity_id"],
                relation=serializer.validated_data.get("relation", "REFERENCES"),
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except ProjectGraphError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"linked": True, "created": created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ProjectGraphView(APIView):
    """查询项目在交付知识图谱中的关联（GET，KLINK-02 可查询；Space viewer+ 或成员）。"""

    async def get(self, request, project_id):
        project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        direction = request.query_params.get("direction", "both")
        if direction not in ("both", "out", "in"):
            return Response(
                {"detail": "direction must be one of: both, out, in"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            max_hops = int(request.query_params.get("max_hops", "1"))
        except ValueError:
            return Response({"detail": "max_hops 必须为整数"}, status=status.HTTP_400_BAD_REQUEST)
        relations = request.query_params.get("relations")
        relation_list = (
            [r.strip() for r in relations.split(",") if r.strip()] if relations else None
        )
        nodes = await ProjectKnowledgeGraphService().query_graph(
            project=project,
            relations=relation_list,
            direction=direction,
            max_hops=max_hops,
        )
        return Response({"project_id": str(project_id), "nodes": nodes})


# ============================ 项目记忆（MEM-01~04）============================


class ProjectMemoryListCreateView(APIView):
    """项目记忆列表（GET，active）+ 新增（POST，MEM-01；成员校验 fail-closed）。"""

    async def get(self, request, project_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        memories = await sync_to_async(
            lambda: list(
                ProjectMemory.objects.filter(
                    project_id=project_id, status=ProjectMemoryStatus.ACTIVE
                )
            )
        )()
        data = await sync_to_async(
            lambda: ProjectMemorySerializer(memories, many=True).data
        )()
        return Response(data)

    async def post(self, request, project_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        serializer = ProjectMemoryCreateSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        try:
            memory = await MemoryService().append(
                project_id=project_id,
                content=serializer.validated_data["content"],
                contributor=request.user,
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except MemoryPermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except MemoryError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        memory = await ProjectMemory.objects.aget(pk=memory.id)
        body = await sync_to_async(lambda: ProjectMemorySerializer(memory).data)()
        return Response(body, status=status.HTTP_201_CREATED)


class ProjectMemoryDetailView(APIView):
    """记忆编辑（PATCH，MEM-03）+ 废弃（DELETE → supersede）。成员校验 fail-closed。"""

    async def patch(self, request, project_id, memory_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        if not await ProjectMemory.objects.filter(
            pk=memory_id, project_id=project_id
        ).aexists():
            return Response({"detail": "记忆不存在"}, status=status.HTTP_404_NOT_FOUND)
        serializer = ProjectMemoryEditSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        try:
            await MemoryService().edit(
                memory_id=memory_id,
                content=serializer.validated_data["content"],
                editor=request.user,
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except MemoryPermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except MemoryError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        memory = await ProjectMemory.objects.aget(pk=memory_id)
        body = await sync_to_async(lambda: ProjectMemorySerializer(memory).data)()
        return Response(body)

    async def delete(self, request, project_id, memory_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        if not await ProjectMemory.objects.filter(
            pk=memory_id, project_id=project_id
        ).aexists():
            return Response({"detail": "记忆不存在"}, status=status.HTTP_404_NOT_FOUND)
        try:
            await MemoryService().supersede(
                memory_id=memory_id,
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except MemoryPermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectMemoryDraftListView(APIView):
    """记忆草稿列表（GET，pending+）+ 从会话蒸馏（POST，MEM-04）。"""

    async def get(self, request, project_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        drafts = await sync_to_async(
            lambda: list(ProjectMemoryDraft.objects.filter(project_id=project_id))
        )()
        data = await sync_to_async(
            lambda: ProjectMemoryDraftSerializer(drafts, many=True).data
        )()
        return Response(data)

    async def post(self, request, project_id):
        """从成员会话蒸馏一条 pending 记忆草稿（绝不自动写 active，MEM-04）。"""
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        serializer = ProjectMemoryDistillSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        conversation_id = serializer.validated_data["conversation_id"]
        conversation_text = await _gather_conversation_text(conversation_id)
        try:
            draft = await MemoryDistiller().distill_to_draft(
                project_id=project_id,
                conversation_text=conversation_text,
                proposed_by=request.user,
                source_conversation_id=conversation_id,
                initiated_by_user_id=request.user.id,
            )
        except MemoryPermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        if draft is None:
            return Response(
                {"detail": "未从会话提炼出可沉淀的记忆草稿"},
                status=status.HTTP_204_NO_CONTENT,
            )
        body = await sync_to_async(lambda: ProjectMemoryDraftSerializer(draft).data)()
        return Response(body, status=status.HTTP_201_CREATED)


class ProjectMemoryDraftConfirmView(APIView):
    """确认草稿入库（POST，MEM-04）。成员校验 fail-closed。"""

    async def post(self, request, project_id, draft_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        if not await ProjectMemoryDraft.objects.filter(
            pk=draft_id, project_id=project_id
        ).aexists():
            return Response({"detail": "草稿不存在"}, status=status.HTTP_404_NOT_FOUND)
        try:
            memory = await MemoryService().confirm_draft(
                draft_id=draft_id,
                confirmer=request.user,
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except MemoryPermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except MemoryError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        memory = await ProjectMemory.objects.aget(pk=memory.id)
        body = await sync_to_async(lambda: ProjectMemorySerializer(memory).data)()
        return Response(body, status=status.HTTP_201_CREATED)


class ProjectMemoryDraftRejectView(APIView):
    """拒绝草稿（POST，MEM-04）。成员校验 fail-closed。"""

    async def post(self, request, project_id, draft_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        if not await ProjectMemoryDraft.objects.filter(
            pk=draft_id, project_id=project_id
        ).aexists():
            return Response({"detail": "草稿不存在"}, status=status.HTTP_404_NOT_FOUND)
        try:
            draft = await MemoryService().reject_draft(
                draft_id=draft_id,
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except MemoryPermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except MemoryError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        body = await sync_to_async(lambda: ProjectMemoryDraftSerializer(draft).data)()
        return Response(body)


async def _gather_conversation_text(conversation_id) -> str:
    """拼接会话最近消息为文本（供记忆蒸馏；best-effort）。"""
    try:
        from chat.models import Message

        rows = [
            m
            async for m in Message.objects.filter(conversation_id=conversation_id)
            .order_by("-created_at")[:40]
        ]
    except Exception:  # noqa: BLE001
        return ""
    rows.reverse()
    parts = [f"{m.role}: {m.content}" for m in rows if getattr(m, "content", "")]
    return "\n".join(parts)


# ============================ MergeRequest（MR-01）============================


class ProjectMergeRequestListView(APIView):
    """项目 MR 列表（GET，项目内可见，MR-01/02）。"""

    async def get(self, request, project_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        mrs = await sync_to_async(
            lambda: list(MergeRequest.objects.filter(project_id=project_id))
        )()
        data = await sync_to_async(lambda: MergeRequestSerializer(mrs, many=True).data)()
        return Response(data)


# ============================ Cursor rules 模板（CURSOR-02）============================


class ProjectCursorRulesView(APIView):
    """项目专属 Cursor rules 模板（GET，CURSOR-02；读权限）。

    返回 ``{filename, content}``，前端「概览」Tab 提供复制/下载。
    """

    async def get(self, request, project_id):
        project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        from initiatives.services.cursor_rules import (
            build_project_cursor_rules,
            cursor_rules_filename,
        )

        content = await sync_to_async(build_project_cursor_rules)(project)
        filename = cursor_rules_filename(project)
        return Response({"filename": filename, "content": content})


# ============================ IDE hook 资产下发（HOOK-01）============================


class ProjectIdeHookAssetsView(APIView):
    """按 runtime 下发读路径 IDE hook 资产 bundle（GET，HOOK-01；项目读权限）。

    ``GET /api/projects/<id>/ide-hook-assets/?runtime=cursor|claude_code|codex&kind=read``

    ``kind=read``（默认）返回三家 always-on 规则（强制「先反查项目 + 召回再编码」），
    Claude Code 额外含 ``UserPromptSubmit`` 注入脚本 + ``settings.json`` 片段；
    ``kind=write`` 返回三家 stop hook 写路径资产（会话结束默认开启 + 静默 active 回写 +
    STATE 结构化回写，HOOK-02/03）。写路径资产仅是「告诉用户怎么装 hook」的安装说明文本、
    不执行写，故读权限口径不变（``_aget_project_for_read`` fail-closed，非成员不泄漏资产正文）。
    """

    async def get(self, request, project_id):
        project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        from initiatives.serializers import IdeHookAssetsQuerySerializer
        from initiatives.services.ide_hook_assets import (
            build_read_path_assets,
            build_write_path_assets,
        )

        serializer = IdeHookAssetsQuerySerializer(data=request.query_params)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        runtime = serializer.validated_data["runtime"]
        kind = serializer.validated_data["kind"]
        builder = build_write_path_assets if kind == "write" else build_read_path_assets
        bundle = await sync_to_async(builder)(project, runtime)
        bundle["kind"] = kind
        return Response(bundle)


# ============================ 项目工作项组合（COMPOSE-01/02）============================


def _serialize_work_item_links(project_id) -> list[dict]:
    """项目关联工作项摘要列表（经 link 派生）。"""
    from initiatives.models import ProjectWorkItemLink

    rows = (
        ProjectWorkItemLink.objects.filter(project_id=project_id)
        .select_related("work_item")
        .order_by("-created_at")
    )
    out: list[dict] = []
    for link in rows:
        wi = link.work_item
        out.append(
            {
                "id": str(wi.id),
                "feishu_work_item_id": wi.work_item_id,
                "work_item_type": wi.work_item_type,
                "title": wi.title,
                "feishu_project_key": wi.feishu_project_key,
                "provenance": link.provenance,
                "attached_at": link.created_at,
                # WorkItem 状态镜像字段（84-01）：供前端进度灯/里程碑映射。
                "status_state_key": wi.status_state_key,
                "status_display_name": wi.status_display_name,
                "module_normalized": wi.module_normalized,
            }
        )
    return out


class ProjectWorkItemListView(APIView):
    """项目工作项列表（GET）+ 手动并入（POST，COMPOSE-01）。"""

    async def get(self, request, project_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        data = await sync_to_async(_serialize_work_item_links)(project_id)
        return Response(data)

    async def post(self, request, project_id):
        from initiatives.serializers import ProjectWorkItemAttachSerializer

        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        serializer = ProjectWorkItemAttachSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)

        from delivery.models import WorkItem

        work_item = await WorkItem.objects.filter(
            pk=serializer.validated_data["work_item_id"]
        ).afirst()
        if work_item is None:
            return Response({"detail": "工作项不存在"}, status=status.HTTP_404_NOT_FOUND)

        _link, created = await ProjectService().attach_work_item(
            project_id=project_id,
            work_item=work_item,
            actor=request.user,
            initiated_by_user_id=request.user.id,
        )
        if not created:
            return Response(
                {"detail": "该工作项已并入项目"}, status=status.HTTP_409_CONFLICT
            )
        return Response({"attached": True}, status=status.HTTP_201_CREATED)


class ProjectWorkItemDetailView(APIView):
    """从项目移除工作项（DELETE，COMPOSE-01）。"""

    async def delete(self, request, project_id, work_item_id):
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        removed = await ProjectService().detach_work_item(
            project_id=project_id,
            work_item_id=work_item_id,
            actor=request.user,
            initiated_by_user_id=request.user.id,
        )
        if not removed:
            return Response({"detail": "工作项未关联此项目"}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ============================ 分支↔项目绑定（BIND-01）============================


class ProjectBranchListCreateView(APIView):
    """项目分支绑定列表（GET，读权限）+ 绑定（POST，BIND-01；写仅成员 fail-closed）。"""

    async def get(self, request, project_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        bindings = await ProjectBranchService().list_for_project(project_id=project_id)
        data = await sync_to_async(
            lambda: ProjectBranchSerializer(bindings, many=True).data
        )()
        return Response(data)

    async def post(self, request, project_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        serializer = ProjectBranchBindRequestSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        d = serializer.validated_data
        from repositories.models import Repository

        if not await Repository.objects.filter(pk=d["repository_id"]).aexists():
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)
        try:
            binding = await ProjectBranchService().bind(
                project_id=project_id,
                repository_id=d["repository_id"],
                branch_name=d["branch_name"],
                source=d.get("source"),
                feishu_board_id=d.get("feishu_board_id", ""),
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except ProjectBranchPermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ProjectBranchError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        binding = await ProjectBranch.objects.select_related("repository").aget(
            pk=binding.id
        )
        body = await sync_to_async(lambda: ProjectBranchSerializer(binding).data)()
        return Response(body, status=status.HTTP_201_CREATED)


class ProjectBranchDetailView(APIView):
    """解绑分支（DELETE，BIND-01；写仅成员 fail-closed）。"""

    async def delete(self, request, project_id, branch_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        binding = await ProjectBranch.objects.filter(
            pk=branch_id, project_id=project_id
        ).afirst()
        if binding is None:
            return Response({"detail": "分支绑定不存在"}, status=status.HTTP_404_NOT_FOUND)
        try:
            await ProjectBranchService().unbind(
                project_id=project_id,
                repository_id=binding.repository_id,
                branch_name=binding.branch_name,
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except ProjectBranchPermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ============================ 项目工作区（WS-03/04 + DOC-02）============================


class ProjectWorkspaceDocsView(APIView):
    """项目工作区 5 文件容器列表（GET，DOC-01~05；读权限）。"""

    async def get(self, request, project_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        docs = await sync_to_async(
            lambda: list(ProjectDoc.objects.filter(project_id=project_id))
        )()
        data = await sync_to_async(lambda: ProjectDocSerializer(docs, many=True).data)()
        return Response(data)


class ProjectWorkspaceRebuildView(APIView):
    """工作区一键重建（POST，WS-04 兜底飞书首建失败的 broken；写权限 Space admin+）。"""

    async def post(self, request, project_id):
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        await ProjectDocService().rebuild_workspace(
            project_id=project_id,
            initiated_by_user_id=request.user.id,
        )
        return Response({"rebuilding": True}, status=status.HTTP_202_ACCEPTED)


class ProjectRehomeView(APIView):
    """项目改归到其他空间（POST，WS-03；写权限 Space admin+）。"""

    async def post(self, request, project_id):
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        serializer = ProjectRehomeSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        new_space_id = serializer.validated_data["new_space_id"]
        if await _aget_space(new_space_id) is None:
            return Response({"detail": "目标空间不存在"}, status=status.HTTP_404_NOT_FOUND)
        try:
            updated = await ProjectService().rehome_space(
                project_id=project_id,
                new_space_id=new_space_id,
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except ProjectRehomeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        updated = await Project.objects.select_related("space").aget(pk=updated.id)
        body = await sync_to_async(lambda: ProjectSerializer(updated).data)()
        return Response(body)


class ProjectStateApiListCreateView(APIView):
    """项目结构化 API 清单列表（GET，读权限）+ 手动新增（POST，写权限，DOC-02）。"""

    async def get(self, request, project_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        apis = await sync_to_async(
            lambda: list(ProjectStateApi.objects.filter(project_id=project_id))
        )()
        data = await sync_to_async(
            lambda: ProjectStateApiSerializer(apis, many=True).data
        )()
        return Response(data)

    async def post(self, request, project_id):
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        serializer = ProjectStateApiCreateSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        d = serializer.validated_data
        api, created = await ProjectDocService().upsert_state_api(
            project_id=project_id,
            method=d["method"],
            path=d["path"],
            params=d.get("params") or {},
            description=d.get("description") or "",
            request_fields=d.get("request_fields") or [],
            response_fields=d.get("response_fields") or [],
            status=d["status"],
            actor=request.user,
            initiated_by_user_id=request.user.id,
        )
        api = await ProjectStateApi.objects.aget(pk=api.id)
        body = await sync_to_async(lambda: ProjectStateApiSerializer(api).data)()
        return Response(
            body,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ProjectStateApiDetailView(APIView):
    """更新（PATCH）/ 移除（DELETE）结构化 API 清单条目（写权限，DOC-02）。"""

    async def patch(self, request, project_id, api_id):
        """更新单条 API 清单条目的 method/path/params/status（DOC-02，84-01）。"""
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        serializer = ProjectStateApiUpdateSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        updated = await ProjectDocService().update_state_api(
            project_id=project_id,
            api_id=api_id,
            fields=serializer.validated_data,
            actor=request.user,
            initiated_by_user_id=request.user.id,
        )
        if updated is None:
            return Response(
                {"detail": "API 清单条目不存在"}, status=status.HTTP_404_NOT_FOUND
            )
        updated = await ProjectStateApi.objects.aget(pk=updated.id)
        body = await sync_to_async(lambda: ProjectStateApiSerializer(updated).data)()
        return Response(body)

    async def delete(self, request, project_id, api_id):
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        removed = await ProjectDocService().remove_state_api(
            project_id=project_id,
            api_id=api_id,
            actor=request.user,
            initiated_by_user_id=request.user.id,
        )
        if not removed:
            return Response(
                {"detail": "API 清单条目不存在"}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ============================ 工作台后端支撑（WB-02/03/05，84-01）============================


class ProjectWorkspaceDocContentView(APIView):
    """单文档渲染内容 + block 分区读取（GET，WB-03；读权限）。

    路由 ``projects/<project_id>/workspace/docs/<doc_type>/``；``doc_type`` 闭集校验
    （memory/state/milestones/research/preflight），非法 400；文件不存在 404。
    """

    async def get(self, request, project_id, doc_type):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        if doc_type not in ALLOWED_DOC_TYPES:
            return Response(
                {"detail": f"非法 doc_type：{doc_type}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        content = await DocContentService().get_doc_render(
            project_id=project_id, doc_type=doc_type
        )
        if content is None:
            return Response(
                {"detail": "工作区文件不存在"}, status=status.HTTP_404_NOT_FOUND
            )
        body = await sync_to_async(
            lambda: ProjectDocContentSerializer(content).data
        )()
        return Response(body)


class ProjectWorkspaceDocHumanBlocksView(APIView):
    """人工区 block 写回（PUT/PATCH，WB-03；写操作仅项目成员，WS-02 fail-closed）。

    路由 ``projects/<project_id>/workspace/docs/<doc_type>/human-blocks/``；触发 Phase 83
    ``DocSyncService`` block 级回灌（永不整篇覆盖）；系统区只读（写 system block → 409）。
    """

    async def put(self, request, project_id, doc_type):
        return await self._write(request, project_id, doc_type)

    async def patch(self, request, project_id, doc_type):
        return await self._write(request, project_id, doc_type)

    async def _write(self, request, project_id, doc_type):
        # 读权限作为入口前置（项目可见），成员写权限在 service 层 fail-closed 校验。
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        if doc_type not in ALLOWED_DOC_TYPES:
            return Response(
                {"detail": f"非法 doc_type：{doc_type}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = ProjectDocHumanBlocksWriteSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        try:
            result = await DocContentService().update_human_blocks(
                project_id=project_id,
                doc_type=doc_type,
                blocks=serializer.validated_data["blocks"],
                user=request.user,
            )
        except HumanWriteForbidden as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except SystemReadOnlyError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except DocContentNotFound as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except DocContentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class ProjectFeatureListView(APIView):
    """feature list 树 + 进度灯（GET，WB-02；读权限）。

    路由 ``projects/<project_id>/feature-list/``；返回 模块→功能点→验收项 三层树，每个功能点
    带四态进度灯；空 feature_list 工件返回空树不报错。
    """

    async def get(self, request, project_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        from initiatives.services.feature_list_service import to_feature_node_tree

        tree = await FeatureListService().build_tree(project_id)
        # 转为前端 FeatureNode 树（kind/name/children/state）——前端各组件统一按此契约消费。
        return Response(to_feature_node_tree(tree))

    async def post(self, request, project_id):
        """设置/更新 feature list（#5）：手动录入 或 飞书多维表格链接（写权限 Space admin+）。"""
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        mode = request.data.get("mode")
        if mode not in ("manual", "feishu", "gitlab", "paste"):
            return Response(
                {"detail": "mode 必须为 manual / feishu / gitlab / paste"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        kwargs: dict = {"mode": mode}
        if mode == "manual":
            modules = request.data.get("modules")
            if not isinstance(modules, list):
                return Response(
                    {"detail": "manual 模式需提供 modules 数组"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            kwargs["modules"] = modules
        elif mode in ("feishu", "gitlab"):
            url = (request.data.get("url") or "").strip()
            if not url:
                return Response(
                    {"detail": f"{mode} 模式需提供 url"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            kwargs["url"] = url
        else:  # paste
            paste_text = request.data.get("text") or ""
            if not str(paste_text).strip():
                return Response(
                    {"detail": "paste 模式需提供 text"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            kwargs["paste_text"] = paste_text
        title = (request.data.get("title") or "").strip()
        if title:
            kwargs["title"] = title
        try:
            await FeatureListService().aset_feature_list(
                project_id,
                actor=request.user,
                initiated_by_user_id=getattr(request.user, "id", None),
                **kwargs,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"ok": True})


class ProjectFeatureListParseView(APIView):
    """把粘贴的文档 AI 解析为结构化 feature 模块（只解析、不落库；#4 录入填充）。

    路由 ``projects/<project_id>/feature-list/parse/``；body ``{text}``。返回
    ``{modules: [{module, features: [{name, acceptance: [...]}]}]}``，供前端「手动录入」
    编辑器自动填入后人工确认再保存。强约束：内容逐字保留原文（见 feature_list_import）。
    """

    async def post(self, request, project_id):
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        text = request.data.get("text") or ""
        if not str(text).strip():
            return Response(
                {"detail": "需提供 text"}, status=status.HTTP_400_BAD_REQUEST
            )
        from initiatives.services.feature_list_import import (
            FeatureListParseError,
            agenerate_feature_modules_from_text,
        )

        try:
            modules = await agenerate_feature_modules_from_text(project_id, str(text))
        except FeatureListParseError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )
        return Response({"modules": modules})


class ProjectFeatureListParseModulesView(APIView):
    """Step 0：只解析**模块层级**（POST；写权限）。

    路由 ``projects/<project_id>/feature-list/parse-modules/``；body ``{text}``。返回
    ``{modules: [{module, line_start, line_end}]}``——输出极小、模块再多也不截断。前端据
    行区间切片后逐模块调用 parse-module-features，实现「先出模块、再逐步填功能点」。
    """

    async def post(self, request, project_id):
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        text = request.data.get("text") or ""
        if not str(text).strip():
            return Response({"detail": "需提供 text"}, status=status.HTTP_400_BAD_REQUEST)
        from initiatives.services.feature_list_import import (
            FeatureListParseError,
            agenerate_module_outline,
        )

        try:
            modules = await agenerate_module_outline(project_id, str(text))
        except FeatureListParseError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )
        return Response({"modules": modules})


class ProjectFeatureListParseModuleFeaturesView(APIView):
    """Step 1：解析**单个模块切片**下的功能点（POST；写权限）。

    路由 ``projects/<project_id>/feature-list/parse-module-features/``；body ``{text}``
    （单个模块的原文切片）。返回 ``{features: [{name, acceptance, source}]}``——输入受单模块
    体量约束、输出不截断。逐字保留原文。
    """

    async def post(self, request, project_id):
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        text = request.data.get("text") or ""
        if not str(text).strip():
            return Response({"features": []})
        from initiatives.services.feature_list_import import (
            FeatureListParseError,
            agenerate_module_features,
        )

        try:
            features = await agenerate_module_features(project_id, str(text))
        except FeatureListParseError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )
        return Response({"features": features})


class ProjectFeatureListParseConfigView(APIView):
    """粘贴文档 AI 解析的额度配置（GET，读权限）。

    路由 ``projects/<project_id>/feature-list/parse-config/``；返回
    ``{model, max_input_tokens, max_output_tokens, max_input_chars}``：前端据
    ``max_input_chars`` 限制单次粘贴字数（已扣除 system prompt / 输出 / 安全余量），
    避免因 prompt 撑爆上下文导致上游 400。无 Provider 时给兜底字数，不报错。
    """

    async def get(self, request, project_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        from initiatives.services.feature_list_import import aget_parse_budget

        return Response(await aget_parse_budget(project_id))


class ProjectFeatureListFeatureDetailView(APIView):
    """把单个功能点/模块的原文结构化为柔性 sections（POST，按需；读权限）。

    路由 ``projects/<project_id>/feature-list/feature-detail/``；body ``{source}``（功能点
    整段原文，取自 feature 树节点的 ``source``）。返回 ``{sections: [{title,type,content}]}``，
    type∈text/list/mermaid。Step 2 单功能点单独请求，体积小、绝不超限；best-effort，
    失败返回空 sections（前端回退展示原文）。
    """

    async def post(self, request, project_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        source = request.data.get("source") or ""
        if not str(source).strip():
            return Response({"sections": []})
        from initiatives.services.feature_detail_service import feature_detail_service

        # 缓存优先：命中直接返回；未命中生成并写缓存（此后不再重算）。
        sections = await feature_detail_service.aget_or_generate(project_id, str(source))
        return Response({"sections": sections})


class ProjectFeatureListDraftView(APIView):
    """feature list 解析草稿：GET 取回（含进度/状态/部分结果） + PUT 保存手工编辑。

    路由 ``projects/<project_id>/feature-list/draft/``。刷新/重开弹窗按项目取回草稿续看
    （异步解析进度落库、每项目一份）。PUT 保存用户手工编辑的草稿（``{modules}``）。
    """

    async def get(self, request, project_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        from initiatives.services.feature_list_draft_service import (
            feature_list_draft_service,
        )

        data = await feature_list_draft_service.aget_serialized(project_id)
        return Response(data)

    async def put(self, request, project_id):
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        modules = request.data.get("modules")
        if not isinstance(modules, list):
            return Response(
                {"detail": "需提供 modules 数组"}, status=status.HTTP_400_BAD_REQUEST
            )
        from initiatives.services.feature_list_draft_service import (
            feature_list_draft_service,
        )

        data = await feature_list_draft_service.asave_manual(
            project_id, modules, actor_id=getattr(request.user, "id", None)
        )
        return Response(data)


class ProjectFeatureListDraftParseView(APIView):
    """发起 feature list 异步解析（POST，写权限）。

    路由 ``projects/<project_id>/feature-list/draft/parse/``；body ``{text}``。写草稿 +
    defer 后台作业立即返回草稿快照（不阻塞请求），进度经 WS ``feature_list_draft`` 推送。
    """

    async def post(self, request, project_id):
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        text = request.data.get("text") or ""
        if not str(text).strip():
            return Response({"detail": "需提供 text"}, status=status.HTTP_400_BAD_REQUEST)
        from initiatives.services.feature_list_draft_service import (
            feature_list_draft_service,
        )

        data = await feature_list_draft_service.astart_parse(
            project_id, str(text), actor_id=getattr(request.user, "id", None)
        )
        return Response(data, status=status.HTTP_202_ACCEPTED)


class ProjectFeatureListDraftCommitView(APIView):
    """把 feature list 草稿确认为正式工件（POST，写权限），成功后删除草稿。

    路由 ``projects/<project_id>/feature-list/draft/commit/``；可选 body ``{modules}``
    （前端确认时提交最终编辑；缺省则用草稿当前 tree）。
    """

    async def post(self, request, project_id):
        _project, err = await _aget_project_for_write(request, project_id)
        if err is not None:
            return err
        from initiatives.services.feature_list_draft_service import (
            feature_list_draft_service,
        )

        modules = request.data.get("modules")
        modules = modules if isinstance(modules, list) else None
        try:
            await feature_list_draft_service.acommit(
                project_id,
                modules=modules,
                actor=request.user,
                actor_id=getattr(request.user, "id", None),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"ok": True})


def _serialize_project_repositories(project_id: Any) -> list[dict[str, Any]]:
    """项目「关联仓库」= 业务关联（RepoAssociation 非 rejected）∪ 分支绑定（ProjectBranch），去重。

    新空项目两者皆空 → 返回 []，不再误把整个空间的仓库池当作项目关联仓库。
    """
    from initiatives.models import ProjectBranch
    from initiatives.models.repo_association import (
        RepoAssociation,
        RepoAssociationStatus,
    )

    rows: dict[str, dict[str, Any]] = {}
    associations = (
        RepoAssociation.objects.filter(project_id=project_id)
        .exclude(status=RepoAssociationStatus.REJECTED)
        .select_related("repository")
    )
    for assoc in associations:
        repo = assoc.repository
        rows.setdefault(
            str(repo.id),
            {
                "id": str(assoc.id),
                "repository_id": str(repo.id),
                "repository_name": repo.name,
                "git_url": repo.git_url,
                "source": "association",
                "status": assoc.status,
            },
        )
    branches = ProjectBranch.objects.filter(project_id=project_id).select_related(
        "repository"
    )
    for branch in branches:
        repo = branch.repository
        if str(repo.id) in rows:
            continue
        rows[str(repo.id)] = {
            "id": str(branch.id),
            "repository_id": str(repo.id),
            "repository_name": repo.name,
            "git_url": repo.git_url,
            "source": "branch",
            "status": "",
        }
    return list(rows.values())


class ProjectRepositoryListView(APIView):
    """项目「关联仓库」列表（GET，读权限）。

    返回该项目业务级关联（``RepoAssociation``）∪ 分支绑定（``ProjectBranch``）涉及的仓库，
    去重。**不是**所属空间的仓库池——新空项目应返回空列表（修 #4：避免误显示全部仓库）。
    """

    async def get(self, request, project_id):
        _project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        data = await sync_to_async(_serialize_project_repositories)(project_id)
        return Response(data)


class ProjectSearchView(APIView):
    """项目基础模糊搜索（GET，WB-05；读权限，召回链路写 RetrievalTrace）。

    路由 ``projects/<project_id>/search/?q=``；本期接基础关键词 + 复用知识检索做项目域兜底，
    结果项带 ``locator``（属哪个 repo/project）。深度项目域 RAG 标注留 Phase 85。
    """

    async def get(self, request, project_id):
        project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        q = (request.query_params.get("q") or "").strip()
        if not q:
            return Response({"query": "", "results": []})
        try:
            top_k = int(request.query_params.get("top_k", "10"))
        except ValueError:
            return Response(
                {"detail": "top_k 必须为整数"}, status=status.HTTP_400_BAD_REQUEST
            )
        results = await ProjectSearchService().search(
            project=project, query=q, user=request.user, top_k=top_k
        )
        body = await sync_to_async(
            lambda: ProjectSearchResultSerializer(results, many=True).data
        )()
        return Response({"query": q, "results": body})


_ARTIFACT_RELATIONS = frozenset({"HAS_ARTIFACT", "ARTIFACT_REPO", "ARTIFACT_CAPABILITY"})


def _build_project_galaxy(
    project, tree: dict, *, artifact_assocs: dict | None = None, max_nodes: int = 300
) -> dict:
    """项目作战室 P4：聚合项目关系星图（sync，供 sync_to_async 包裹）。

    节点类型：project / feature / work_item / repository / merge_request /
    artifact / capability（KDEP-10）。
    边：project 为枢纽（HAS_FEATURE / HAS_WORK_ITEM / HAS_MR / USES_REPO），
    叠加 MR→repo、MR→work_item 关联；工件侧叠加 HAS_ARTIFACT（project→artifact）、
    ARTIFACT_REPO（artifact→repo）、ARTIFACT_CAPABILITY（artifact→capability）。
    项目↔仓库关联来源并入 verified ``RepoAssociation``（不再仅来自 MR）。
    超 max_nodes 截断（meta.truncated=True）。

    ``artifact_assocs``：``{artifact_id: {repositories:[{repository_id, repo_name, ...}],
    capabilities:[node_path]}}``——由 ``_agather_artifact_assocs`` 异步预取（复用 Phase 98
    ``ArtifactAssociationService``，不在本 sync 函数内重复图遍历）；None 视为 {}。

    工件/关联分支整体 best-effort：异常被吞掉，既有 project/feature/work_item/MR/repo
    星图完整返回（read-only 只读展示，绝不反噬既有星图）。
    """
    import uuid as _uuid

    from initiatives.models import MergeRequest, ProjectWorkItemLink

    nodes: list[dict] = []
    edges: list[dict] = []
    seen: set[str] = set()
    edge_seen: set[tuple[str, str, str]] = set()

    def repo_node_id(raw) -> str:
        """归一化仓库 id 到唯一 canonical 串形。

        仓库节点跨三来源（MR / verified RepoAssociation / 工件 ARTIFACT_REPO）拼装，
        去重依赖节点 id 逐字符一致。``source_id`` 是 ``CharField``，一旦上游写入格式漂移
        （大小写/带不带 dash/前缀），裸 ``f"repository:{raw}"`` 会产生重复节点与重复边。
        此处统一归一化为 ``str(uuid.UUID(...))``（无法解析为 UUID 时回退原值），锁死不变量。
        """
        try:
            return f"repository:{_uuid.UUID(str(raw))}"
        except (ValueError, AttributeError, TypeError):
            return f"repository:{raw}"

    def add_node(nid: str, ntype: str, label: str, **extra) -> None:
        if nid in seen:
            return
        seen.add(nid)
        nodes.append({"id": nid, "type": ntype, "label": label, **extra})

    def add_edge(source: str, target: str, relation: str, **extra) -> None:
        key = (source, target, relation)
        if key in edge_seen:
            return
        edge_seen.add(key)
        edges.append({"source": source, "target": target, "relation": relation, **extra})

    pid = str(project.id)
    proj_node = f"project:{pid}"
    add_node(proj_node, "project", project.name or "项目", ref_id=pid)

    # feature 节点（来自 feature 树：模块 → 功能点）
    for module in tree.get("modules") or []:
        module_name = module.get("name", "")
        for feat in module.get("features") or []:
            fname = feat.get("name", "")
            fid = f"feature:{module_name}/{fname}"
            add_node(
                fid, "feature", fname,
                state=feat.get("state"), module=module_name,
            )
            add_edge(proj_node, fid, "HAS_FEATURE")

    # 工作项节点
    wi_node_by_id: dict[str, str] = {}
    for link in (
        ProjectWorkItemLink.objects.filter(project_id=pid).select_related("work_item")
    ):
        wi = link.work_item
        nid = f"work_item:{wi.id}"
        wi_node_by_id[str(wi.id)] = nid
        add_node(
            nid, "work_item", wi.title or f"工作项 {wi.work_item_id}",
            work_item_type=wi.work_item_type, ref_id=str(wi.id),
        )
        add_edge(proj_node, nid, "HAS_WORK_ITEM")

    # MR + 仓库节点
    for mr in (
        MergeRequest.objects.filter(project_id=pid).select_related("repository", "work_item")
    ):
        mr_nid = f"mr:{mr.id}"
        add_node(
            mr_nid, "merge_request", mr.title or mr.external_id or "MR",
            status=mr.status, url=mr.url, ref_id=str(mr.id),
        )
        add_edge(proj_node, mr_nid, "HAS_MR")
        if mr.repository_id:
            repo_nid = repo_node_id(mr.repository_id)
            repo_name = mr.repository.name if mr.repository else str(mr.repository_id)
            add_node(repo_nid, "repository", repo_name, ref_id=str(mr.repository_id))
            # USES_REPO 纳入统一去重集：与下方 verified RepoAssociation 来源去重（同 repo 一条）。
            add_edge(proj_node, repo_nid, "USES_REPO")
            add_edge(mr_nid, repo_nid, "MR_REPO")
        if mr.work_item_id and str(mr.work_item_id) in wi_node_by_id:
            add_edge(mr_nid, wi_node_by_id[str(mr.work_item_id)], "MR_WORK_ITEM")

    # 工件 / 关联分支（KDEP-10）——best-effort，异常绝不反噬既有星图。
    try:
        from initiatives.models.repo_association import (
            RepoAssociation,
            RepoAssociationStatus,
        )

        assocs = artifact_assocs or {}
        for a in Artifact.objects.filter(project_id=pid).select_related("type"):
            art_nid = f"artifact:{a.id}"
            add_node(
                art_nid, "artifact", a.title or "工件",
                type_key=a.type.key, carrier=a.carrier, ref_id=str(a.id),
            )
            add_edge(proj_node, art_nid, "HAS_ARTIFACT")
            assoc = assocs.get(str(a.id)) or {}
            for repo in assoc.get("repositories") or []:
                rid = repo.get("repository_id")
                if not rid:
                    continue
                repo_nid = repo_node_id(rid)
                add_node(
                    repo_nid, "repository", repo.get("repo_name") or str(rid),
                    ref_id=str(rid),
                )
                add_edge(art_nid, repo_nid, "ARTIFACT_REPO")
            for path in assoc.get("capabilities") or []:
                if not path:
                    continue
                cap_nid = f"capability:{path}"
                label = str(path).rsplit("/", 1)[-1] or str(path)
                add_node(cap_nid, "capability", label, path=str(path))
                add_edge(art_nid, cap_nid, "ARTIFACT_CAPABILITY")

        # 项目↔仓库关联来源并入 verified RepoAssociation（与 Phase 98 派生边一致）。
        for assoc in (
            RepoAssociation.objects.filter(
                project_id=pid, status=RepoAssociationStatus.VERIFIED
            ).select_related("repository")
        ):
            repo = assoc.repository
            repo_nid = repo_node_id(repo.id)
            add_node(repo_nid, "repository", repo.name, ref_id=str(repo.id))
            add_edge(proj_node, repo_nid, "USES_REPO")
    except Exception as exc:  # noqa: BLE001 — best-effort，绝不反噬既有星图
        from common.logging import redact_secrets_in_text

        logger.warning(
            "project_galaxy_artifact_branch_failed",
            project_id=pid,
            error=redact_secrets_in_text(str(exc)),
            error_type=type(exc).__name__,
            component="initiatives.galaxy",
            category="sampling",
        )

    truncated = False
    if len(nodes) > max_nodes:
        nodes = nodes[:max_nodes]
        kept = {n["id"] for n in nodes}
        edges = [e for e in edges if e["source"] in kept and e["target"] in kept]
        truncated = True

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "truncated": truncated,
            "artifact_nodes": sum(1 for n in nodes if n["type"] == "artifact"),
            "artifact_edges": sum(1 for e in edges if e["relation"] in _ARTIFACT_RELATIONS),
        },
    }


async def _agather_artifact_assocs(project, user) -> dict:
    """异步预取本项目所有可见工件的关联（复用 Phase 98 ``ArtifactAssociationService``）。

    产出 ``{artifact_id: {repositories:[...], capabilities:[...]}}`` 传入 sync builder。
    逐工件走正向查询（天然 access_scope fail-closed，不可见/无关联返回 None → 跳过）。
    整体 best-effort：异常返回 {} 并记 warning——绝不反噬星图。
    """
    from knowledge.artifact_associations import ArtifactAssociationService

    try:
        artifact_ids = await sync_to_async(
            lambda: list(
                Artifact.objects.filter(project_id=project.id).values_list(
                    "id", flat=True
                )
            )
        )()
        service = ArtifactAssociationService()
        result: dict[str, dict] = {}
        for aid in artifact_ids:
            assoc = await service.get_artifact_associations(aid, user=user)
            if assoc is None:
                continue
            result[str(aid)] = {
                "repositories": assoc.get("repositories", []),
                "capabilities": assoc.get("capabilities", []),
            }
        return result
    except Exception as exc:  # noqa: BLE001 — best-effort，绝不反噬星图
        from common.logging import redact_secrets_in_text

        logger.warning(
            "project_galaxy_artifact_assoc_failed",
            project_id=str(project.id),
            error=redact_secrets_in_text(str(exc)),
            error_type=type(exc).__name__,
            component="initiatives.galaxy",
            category="sampling",
        )
        return {}


class ProjectGalaxyView(APIView):
    """项目级关系星图（GET，读权限；项目作战室 P4）。

    路由 ``projects/<project_id>/galaxy/``；聚合 项目/feature/工作项/仓库/MR/工件/能力
    节点与关联边，前端用力导图呈现「某 feature/工件关联了什么」。按项目成员 fail-closed。
    """

    async def get(self, request, project_id):
        import time

        project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        started = time.monotonic()
        tree = await FeatureListService().build_tree(project_id)
        artifact_assocs = await _agather_artifact_assocs(project, request.user)
        payload = await sync_to_async(_build_project_galaxy)(
            project, tree, artifact_assocs=artifact_assocs
        )
        logger.info(
            "project_galaxy_built",
            project_id=str(project_id),
            nodes=payload["meta"]["total_nodes"],
            edges=payload["meta"]["total_edges"],
            artifact_nodes=payload["meta"].get("artifact_nodes"),
            artifact_edges=payload["meta"].get("artifact_edges"),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            component="initiatives.galaxy",
            category="caller",
        )
        return Response(payload)


# ============================ 项目上下文关联（「生成知识关联」）============================


async def _aget_project_for_link_edit(request, project_id):
    """取项目 + 校验关联编辑权限（Space admin+ 或项目成员）。返回 (project, error_response)。

    作战室「成员就地编辑」语义：项目成员即可审阅/编辑关联，Space viewer 只读。
    """
    project = await aget_object_or_404(
        Project.objects.select_related("space"), pk=project_id
    )
    allowed = await auser_can_access_project(request.user, project, SpaceRole.ADMIN)
    if not allowed:
        allowed = await auser_is_project_member(request.user, project_id)
    if not allowed:
        return None, Response(
            {"detail": "仅项目成员可编辑关联"}, status=status.HTTP_403_FORBIDDEN
        )
    return project, None


async def _aserialize_context_links(payload: dict[str, Any]) -> dict[str, Any]:
    """列表载荷序列化（links 走 serializer，repos 已是 dict）。"""
    links = await sync_to_async(
        lambda: ProjectContextLinkSerializer(payload["links"], many=True).data
    )()
    return {"links": links, "repos": payload["repos"]}


class ProjectContextLinkListCreateView(APIView):
    """上下文关联列表（GET，读权限）+ 人工添加（POST，成员）。"""

    async def get(self, request, project_id):
        project, err = await _aget_project_for_read(request, project_id)
        if err is not None:
            return err
        payload = await ContextLinkService().list_links(project)
        return Response(await _aserialize_context_links(payload))

    async def post(self, request, project_id):
        project, err = await _aget_project_for_link_edit(request, project_id)
        if err is not None:
            return err
        serializer = ContextLinkManualCreateSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        data = serializer.validated_data
        try:
            link = await ContextLinkService().aadd_manual(
                project,
                target_kind=data["target_kind"],
                target_id=data.get("target_id"),
                title=data.get("title") or "",
                url=data.get("url") or "",
                reason=data.get("reason") or "",
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except ContextLinkError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        body = await sync_to_async(lambda: ProjectContextLinkSerializer(link).data)()
        return Response(body, status=status.HTTP_201_CREATED)


class ProjectContextLinkGenerateView(APIView):
    """一键「生成知识关联」（POST，成员）：仓库/知识/工件/MR 四类候选统一编排。"""

    async def post(self, request, project_id):
        project, err = await _aget_project_for_link_edit(request, project_id)
        if err is not None:
            return err
        summary = await ContextLinkService().agenerate(
            project, user=request.user, initiated_by_user_id=request.user.id
        )
        payload = await ContextLinkService().list_links(project)
        body = await _aserialize_context_links(payload)
        body["summary"] = summary
        return Response(body)


class ProjectContextLinkDecisionView(APIView):
    """候选裁决（POST .../<link_id>/<action>/，action=accept|reject，成员）。"""

    async def post(self, request, project_id, link_id, action):
        project, err = await _aget_project_for_link_edit(request, project_id)
        if err is not None:
            return err
        try:
            link = await ContextLinkService().adecide(
                project,
                link_id,
                action=action,
                actor=request.user,
                initiated_by_user_id=request.user.id,
            )
        except ContextLinkError as exc:
            not_found = "不存在" in str(exc)
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_404_NOT_FOUND if not_found else status.HTTP_400_BAD_REQUEST,
            )
        body = await sync_to_async(lambda: ProjectContextLinkSerializer(link).data)()
        return Response(body)


class ProjectContextLinkDetailView(APIView):
    """删除一条关联记录（DELETE，成员；人工编辑的移除分支）。"""

    async def delete(self, request, project_id, link_id):
        project, err = await _aget_project_for_link_edit(request, project_id)
        if err is not None:
            return err
        deleted = await ContextLinkService().aremove(
            project, link_id, initiated_by_user_id=request.user.id
        )
        if not deleted:
            return Response({"detail": "关联记录不存在"}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectContextLinkRepoDecisionView(APIView):
    """仓库候选裁决（POST，成员）：accept → confirm_repos；reject → reject_candidates。"""

    async def post(self, request, project_id):
        project, err = await _aget_project_for_link_edit(request, project_id)
        if err is not None:
            return err
        serializer = ContextLinkRepoDecisionSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        data = serializer.validated_data
        try:
            applied = await ContextLinkService().adecide_repo(
                project,
                data["repository_id"],
                action=data["action"],
                initiated_by_user_id=request.user.id,
            )
        except ContextLinkError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if not applied:
            return Response(
                {"detail": "无可裁决的候选（可能已流转或不存在）"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"applied": True, "action": data["action"]})
