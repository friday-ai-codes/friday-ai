"""initiatives app views（项目/成员 REST API，adrf 异步）。

权限按所属 Space 成员权限 fail-closed（复用 ``PermissionService``）：
- 读（list/retrieve/members list）= Space viewer+ 或项目成员；
- 写（create/update/transition/member 增删改/transfer）= Space admin+ 或 superuser。

所有写入收口于 ``ProjectService``（INV-6）；状态非法流转 / 成员非法操作 fail-loud → 400。
新增 REST 入口经统一中间件自动纳入 QPS/错误率/时长指标。
"""

from __future__ import annotations

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
    ProjectMember,
    ProjectMemory,
    ProjectMemoryDraft,
    ProjectMemoryStatus,
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
    MergeRequestSerializer,
    ProjectCreateSerializer,
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
    ProjectSerializer,
    ProjectTransitionSerializer,
    ProjectUpdateSerializer,
)
from initiatives.services import (
    ArtifactError,
    ArtifactService,
    MemoryDistiller,
    MemoryError,
    MemoryPermissionError,
    MemoryService,
    ProjectMemberError,
    ProjectService,
    ProjectTransitionError,
)
from initiatives.services.artifact_view import aget_artifact_view
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
        """列出对当前用户可见的项目（Space 成员可见 + 项目成员可见）。"""
        user = request.user
        projects = await self._list_visible(user)
        data = await sync_to_async(
            lambda: ProjectSerializer(projects, many=True).data
        )()
        return Response(data)

    @sync_to_async
    def _list_visible(self, user) -> list[Project]:
        qs = Project.objects.select_related("space").prefetch_related("members")
        if not user.is_authenticated:
            return []
        if user.is_superuser:
            return list(qs)
        # Space 成员可见 OR 项目成员可见
        from django.db.models import Q

        return list(
            qs.filter(
                Q(space__memberships__user=user) | Q(members__user=user)
            ).distinct()
        )

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
