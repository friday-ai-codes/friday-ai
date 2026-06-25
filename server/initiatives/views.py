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

from initiatives.models import Project, ProjectMember
from initiatives.permissions import (
    auser_can_access_project,
    auser_is_project_member,
)
from initiatives.serializers import (
    ProjectCreateSerializer,
    ProjectMemberAddSerializer,
    ProjectMemberSerializer,
    ProjectMemberUpdateSerializer,
    ProjectOwnerTransferSerializer,
    ProjectSerializer,
    ProjectTransitionSerializer,
    ProjectUpdateSerializer,
)
from initiatives.services import (
    ProjectMemberError,
    ProjectService,
    ProjectTransitionError,
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
