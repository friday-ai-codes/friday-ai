"""Project members views: 项目成员 CRUD 端点。"""
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.response import Response
from adrf.views import APIView
from permissions.models import ProjectMembership, ProjectRole
from permissions.services import PermissionService
from projects.models import Project
from .members_serializers import (
 MemberAddSerializer,
 MemberUpdateSerializer,
 ProjectMembershipSerializer,
)
User = get_user_model
async def _get_project_or_404(project_id: str) -> Project:
 """获取项目对象，不存在时返回 404 响应数据（内部辅助）。"""
 try:
 return await sync_to_async(Project.objects.get)(pk=project_id)
 except Project.DoesNotExist:
 return None # type: ignore[return-value]
class ProjectMemberListView(APIView):
 """项目成员列表：GET 查看 / POST 添加。"""
 async def get(self, request, project_id: str):
 """获取项目成员列表。项目成员（任何角色）可查看。"""
 project = await _get_project_or_404(project_id)
 if project is None:
 return Response({"detail": "项目不存在"}, status=status.HTTP_404_NOT_FOUND)
 # 权限校验：必须是项目成员或超级管理员
 has_access = await sync_to_async(PermissionService.has_project_access)(
 request.user, project
 )
 if not has_access:
 return Response({"detail": "无权访问此项目"}, status=status.HTTP_403_FORBIDDEN)
 qs = ProjectMembership.objects.filter(project=project).select_related("user").order_by("joined_at")
 memberships = await sync_to_async(lambda: list(qs))
 return Response(ProjectMembershipSerializer(memberships, many=True).data)
 async def post(self, request, project_id: str):
 """添加项目成员。仅项目 Admin 或超级管理员可操作。"""
 project = await _get_project_or_404(project_id)
 if project is None:
 return Response({"detail": "项目不存在"}, status=status.HTTP_404_NOT_FOUND)
 # 权限校验：需要 Admin 角色
 has_admin = await sync_to_async(PermissionService.has_project_access)(
 request.user, project, min_role=ProjectRole.ADMIN
 )
 if not has_admin:
 return Response({"detail": "仅项目管理员可添加成员"}, status=status.HTTP_403_FORBIDDEN)
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
 )
 if already_member:
 return Response({"detail": "该用户已是项目成员"}, status=status.HTTP_409_CONFLICT)
 membership = await sync_to_async(ProjectMembership.objects.create)(
 user=target_user,
 project=project,
 role=role,
 invited_by=request.user,
 )
 # select_related 用于序列化
 membership = await sync_to_async(
 ProjectMembership.objects.select_related("user").get
 )(pk=membership.pk)
 return Response(
 ProjectMembershipSerializer(membership).data,
 status=status.HTTP_201_CREATED,
 )
class ProjectMemberDetailView(APIView):
 """项目成员详情：PATCH 变更角色 / DELETE 移除成员。"""
 async def _get_membership(self, project_id: str, user_id: str):
 """获取项目成员关系，不存在返回 None。"""
 try:
 return await sync_to_async(
 ProjectMembership.objects.select_related("user", "project").get
 )(project__pk=project_id, user__pk=user_id)
 except ProjectMembership.DoesNotExist:
 return None
 async def patch(self, request, project_id: str, user_id: str):
 """变更项目成员角色。仅项目 Admin 或超级管理员可操作。"""
 project = await _get_project_or_404(project_id)
 if project is None:
 return Response({"detail": "项目不存在"}, status=status.HTTP_404_NOT_FOUND)
 has_admin = await sync_to_async(PermissionService.has_project_access)(
 request.user, project, min_role=ProjectRole.ADMIN
 )
 if not has_admin:
 return Response({"detail": "仅项目管理员可修改成员角色"}, status=status.HTTP_403_FORBIDDEN)
 membership = await self._get_membership(project_id, user_id)
 if membership is None:
 return Response({"detail": "成员关系不存在"}, status=status.HTTP_404_NOT_FOUND)
 serializer = MemberUpdateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 membership.role = serializer.validated_data["role"]
 await sync_to_async(membership.save)(update_fields=["role"])
 return Response(ProjectMembershipSerializer(membership).data)
 async def delete(self, request, project_id: str, user_id: str):
 """移除项目成员。仅项目 Admin 或超级管理员可操作。"""
 project = await _get_project_or_404(project_id)
 if project is None:
 return Response({"detail": "项目不存在"}, status=status.HTTP_404_NOT_FOUND)
 has_admin = await sync_to_async(PermissionService.has_project_access)(
 request.user, project, min_role=ProjectRole.ADMIN
 )
 if not has_admin:
 return Response({"detail": "仅项目管理员可移除成员"}, status=status.HTTP_403_FORBIDDEN)
 membership = await self._get_membership(project_id, user_id)
 if membership is None:
 return Response({"detail": "成员关系不存在"}, status=status.HTTP_404_NOT_FOUND)
 await sync_to_async(membership.delete)
 return Response(status=status.HTTP_204_NO_CONTENT)
