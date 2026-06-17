"""Space members views: 空间成员 CRUD 端点。"""

from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.response import Response

from audit.services import taxonomy
from audit.services.audit_service import AuditService
from permissions.models import ProjectMembership, ProjectRole
from permissions.services import PermissionService
from projects.models import Project

from .members_serializers import (
    MemberAddSerializer,
    MemberUpdateSerializer,
    ProjectMembershipSerializer,
)

User = get_user_model()


async def _get_space_or_404(space_id: str) -> Project | None:
    """获取空间对象，不存在时返回 404 响应数据（内部辅助）。"""
    try:
        return await sync_to_async(Project.objects.get)(pk=space_id)
    except Project.DoesNotExist:
        return None


class SpaceMemberListView(APIView):
    """空间成员列表：GET 查看 / POST 添加。"""

    async def get(self, request, space_id: str):
        """获取空间成员列表。空间成员（任何角色）可查看。"""
        project = await _get_space_or_404(space_id)
        if project is None:
            return Response({"detail": "空间不存在"}, status=status.HTTP_404_NOT_FOUND)

        # 权限校验：必须是空间成员或超级管理员
        has_access = await sync_to_async(PermissionService.has_project_access)(
            request.user, project
        )
        if not has_access:
            return Response({"detail": "无权访问此空间"}, status=status.HTTP_403_FORBIDDEN)

        qs = (
            ProjectMembership.objects.filter(project=project)
            .select_related("user")
            .order_by("joined_at")
        )
        memberships = await sync_to_async(lambda: list(qs))()
        return Response(ProjectMembershipSerializer(memberships, many=True).data)

    async def post(self, request, space_id: str):
        """添加空间成员。仅空间 Admin 或超级管理员可操作。"""
        project = await _get_space_or_404(space_id)
        if project is None:
            return Response({"detail": "空间不存在"}, status=status.HTTP_404_NOT_FOUND)

        # 权限校验：需要 Admin 角色
        has_admin = await sync_to_async(PermissionService.has_project_access)(
            request.user, project, min_role=ProjectRole.ADMIN
        )
        if not has_admin:
            return Response({"detail": "仅空间管理员可添加成员"}, status=status.HTTP_403_FORBIDDEN)

        serializer = MemberAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_id = serializer.validated_data["user_id"]
        role = serializer.validated_data["role"]

        # 检查目标用户存在
        try:
            target_user = await sync_to_async(User.objects.get)(pk=user_id)
        except User.DoesNotExist:
            return Response({"detail": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)

        # 检查是否已是成员
        already_member = await sync_to_async(
            ProjectMembership.objects.filter(user=target_user, project=project).exists
        )()
        if already_member:
            return Response({"detail": "该用户已是空间成员"}, status=status.HTTP_409_CONFLICT)

        membership = await sync_to_async(ProjectMembership.objects.create)(
            user=target_user,
            project=project,
            role=role,
            invited_by=request.user,
        )
        # select_related 用于序列化
        membership = await sync_to_async(ProjectMembership.objects.select_related("user").get)(
            pk=membership.pk
        )

        # 审计：添加空间成员
        await AuditService.aemit(
            action=taxonomy.ACTION_MEMBER_CREATED,
            actor=request.user,
            target_type="project_membership",
            target_id=membership.id,
            target_repr=f"{target_user.username} @ {project.name}",
            after={
                "user_id": str(target_user.id),
                "project_id": str(project.id),
                "role": role,
            },
            source="api",
        )

        return Response(
            ProjectMembershipSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )


class SpaceMemberDetailView(APIView):
    """空间成员详情：PATCH 变更角色 / DELETE 移除成员。"""

    async def _get_membership(self, space_id: str, user_id: str):
        """获取空间成员关系，不存在返回 None。"""
        try:
            return await sync_to_async(
                ProjectMembership.objects.select_related("user", "project").get
            )(project__pk=space_id, user__pk=user_id)
        except ProjectMembership.DoesNotExist:
            return None

    async def patch(self, request, space_id: str, user_id: str):
        """变更空间成员角色。仅空间 Admin 或超级管理员可操作。"""
        project = await _get_space_or_404(space_id)
        if project is None:
            return Response({"detail": "空间不存在"}, status=status.HTTP_404_NOT_FOUND)

        has_admin = await sync_to_async(PermissionService.has_project_access)(
            request.user, project, min_role=ProjectRole.ADMIN
        )
        if not has_admin:
            return Response(
                {"detail": "仅空间管理员可修改成员角色"}, status=status.HTTP_403_FORBIDDEN
            )

        membership = await self._get_membership(space_id, user_id)
        if membership is None:
            return Response({"detail": "成员关系不存在"}, status=status.HTTP_404_NOT_FOUND)

        serializer = MemberUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        old_role = membership.role
        membership.role = serializer.validated_data["role"]
        await sync_to_async(membership.save)(update_fields=["role"])

        # 审计：成员角色变更，仅在角色真正变化时 emit（值未变不记，SC-4）
        if old_role != membership.role:
            await AuditService.aemit(
                action=taxonomy.ACTION_ROLE_CHANGED,
                actor=request.user,
                target_type="project_membership",
                target_id=membership.id,
                target_repr=f"{membership.user.username} @ {project.name}",
                before={"role": old_role},
                after={"role": membership.role},
                source="api",
            )

        return Response(ProjectMembershipSerializer(membership).data)

    async def delete(self, request, space_id: str, user_id: str):
        """移除空间成员。仅空间 Admin 或超级管理员可操作。"""
        project = await _get_space_or_404(space_id)
        if project is None:
            return Response({"detail": "空间不存在"}, status=status.HTTP_404_NOT_FOUND)

        has_admin = await sync_to_async(PermissionService.has_project_access)(
            request.user, project, min_role=ProjectRole.ADMIN
        )
        if not has_admin:
            return Response({"detail": "仅空间管理员可移除成员"}, status=status.HTTP_403_FORBIDDEN)

        membership = await self._get_membership(space_id, user_id)
        if membership is None:
            return Response({"detail": "成员关系不存在"}, status=status.HTTP_404_NOT_FOUND)

        # delete 前快照（删后对象不存在仍可追溯）
        member_id = membership.id
        member_repr = f"{membership.user.username} @ {project.name}"
        snapshot = {
            "user_id": str(membership.user_id),
            "project_id": str(membership.project_id),
            "role": membership.role,
        }
        await sync_to_async(membership.delete)()

        # 审计：移除空间成员
        await AuditService.aemit(
            action=taxonomy.ACTION_MEMBER_DELETED,
            actor=request.user,
            target_type="project_membership",
            target_id=member_id,
            target_repr=member_repr,
            before=snapshot,
            source="api",
        )

        return Response(status=status.HTTP_204_NO_CONTENT)
