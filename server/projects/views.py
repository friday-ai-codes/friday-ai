"""Projects app views."""
from __future__ import annotations
import structlog
from adrf.views import APIView
from adrf.viewsets import ModelViewSet
from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from common.encryption import encrypt_value
from permissions.models import ProjectMembership, ProjectRole
from permissions.services import PermissionService
from repositories.models import AuthType, GitCredential, Repository
from .models import (
 Project,
 ProjectRepository,
 generate_webhook_token,
)
from .serializers import (
 ClaudeConfigCreateSerializer,
 ClaudeConfigSerializer,
 FeishuConfigCreateSerializer,
 FeishuConfigSerializer,
 FeishuIMConfigCreateSerializer,
 FeishuIMConfigSerializer,
 FeishuIMTestSerializer,
 GitCredentialSerializer,
 ProjectCreateSerializer,
 ProjectRepositoryCreateSerializer,
 ProjectRepositorySerializer,
 ProjectRepositoryUpdateSerializer,
 ProjectSerializer,
 ProjectUpdateSerializer,
 RepositoryCreateSerializer,
 RepositorySerializer,
 RepositoryWithProjectsSerializer,
 WebhookTokenSerializer,
 WebhookTokenUpdateSerializer,
)
logger = structlog.get_logger(__name__)
class ProjectViewSet(ModelViewSet):
 """ViewSet for Project CRUD operations."""
 queryset = Project.objects.prefetch_related("repositories__credential").all
 serializer_class = ProjectSerializer
 def get_queryset(self):
 """按用户 membership 过滤项目列表。superuser 看所有。"""
 qs = super.get_queryset
 user = self.request.user
 if not user.is_authenticated:
 return qs.none
 # superuser 看所有
 if user.is_superuser:
 return qs
 # 普通用户按 membership 过滤
 return qs.filter(memberships__user=user).distinct
 def get_serializer_class(self):
 if self.action == "create":
 return ProjectCreateSerializer
 if self.action in ["update", "partial_update"]:
 return ProjectUpdateSerializer
 return ProjectSerializer
 async def acreate(self, request, *args, **kwargs):
 serializer = self.get_serializer(data=request.data)
 # KEEP: ProjectCreateSerializer 含 UniqueValidator (feishu_project_key unique=True)
 await sync_to_async(serializer.is_valid)(raise_exception=True)
 project = await Project.objects.acreate(**serializer.validated_data)
 # 创建项目后自动为创建者添加 admin membership
 await ProjectMembership.objects.acreate(
 user=request.user,
 project=project,
 role=ProjectRole.ADMIN,
 )
 # KEEP: ProjectSerializer.get_repositories 触发 repositories.filter DB 查询
 data = await sync_to_async(lambda: ProjectSerializer(project).data)
 return Response(data, status=status.HTTP_201_CREATED)
 async def perform_aupdate(self, serializer):
 # KEEP: ProjectSerializer 继承自 rest_framework.serializers，不支持 asave
 await sync_to_async(serializer.save)
 # === Repository association ===
 @action(detail=True, methods=["get"], url_path="repositories")
 async def list_repositories(self, request, pk=None):
 """List repositories associated with the project."""
 project = await self.aget_object
 repositories = project.repositories.filter(is_deleted=False).select_related("credential")
 serializer = RepositorySerializer([r async for r in repositories], many=True)
 return Response(serializer.data)
 @action(detail=True, methods=["post"], url_path=r"repositories/(?P<repository_id>[^/.]+)")
 async def link_repository(self, request, pk=None, repository_id=None):
 """Link a repository to the project."""
 project = await self.aget_object
 repository = await aget_object_or_404(Repository, id=repository_id, is_deleted=False)
 _, created = await ProjectRepository.objects.aget_or_create(
 project=project,
 repository=repository,
 )
 if not created:
 return Response({"message": "Already linked"})
 return Response({"message": "Linked successfully"}, status=status.HTTP_201_CREATED)
 @link_repository.mapping.delete
 async def unlink_repository(self, request, pk=None, repository_id=None):
 """Unlink a repository from the project."""
 project = await self.aget_object
 link = await aget_object_or_404(
 ProjectRepository,
 project=project,
 repository_id=repository_id,
 )
 await link.adelete
 return Response(status=status.HTTP_204_NO_CONTENT)
 # === Feishu configuration ===
 @action(detail=True, methods=["get", "put", "delete"], url_path="feishu-config")
 async def feishu_config(self, request, pk=None):
 """Manage Feishu configuration."""
 project = await self.aget_object
 # 写操作需要 admin+ 权限
 if request.method != "GET":
 if not request.user.is_superuser and not PermissionService.has_project_access(
 request.user, project, ProjectRole.ADMIN
 ):
 return Response(
 {"detail": "仅项目管理员可修改配置"},
 status=status.HTTP_403_FORBIDDEN,
 )
 if request.method == "GET":
 return Response(FeishuConfigSerializer(project).data)
 if request.method == "PUT":
 serializer = FeishuConfigCreateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 project.feishu_plugin_id = serializer.validated_data["plugin_id"]
 project.feishu_plugin_secret_encrypted = encrypt_value(
 serializer.validated_data["plugin_secret"]
 )
 project.feishu_user_key = serializer.validated_data.get("user_key", "")
 await project.asave
 return Response(FeishuConfigSerializer(project).data)
 # DELETE
 project.feishu_plugin_id = None
 project.feishu_plugin_secret_encrypted = None
 project.feishu_user_key = None
 await project.asave
 return Response(status=status.HTTP_204_NO_CONTENT)
 @action(detail=True, methods=["post"], url_path="feishu-config/test")
 async def test_feishu_config(self, request, pk=None):
 """Test Feishu configuration."""
 project = await self.aget_object
 # Check if configured
 if not project.has_feishu_config:
 return Response(
 {
 "success": False,
 "message": "飞书配置不完整，请填写插件 ID 和插件 Secret",
 "plugin_token_valid": False,
 "project_accessible": False,
 }
 )
 # 获取测试配置（如果提供）
 test_plugin_id = request.data.get("plugin_id")
 test_plugin_secret = request.data.get("plugin_secret")
 test_user_key = request.data.get("user_key")
 # 使用传入的临时配置或已保存的配置
 plugin_id = test_plugin_id or project.feishu_plugin_id
 plugin_secret = None
 if test_plugin_secret:
 plugin_secret = test_plugin_secret
 elif project.feishu_plugin_secret_encrypted:
 from common.encryption import decrypt_value
 plugin_secret = decrypt_value(project.feishu_plugin_secret_encrypted)
 user_key = test_user_key or project.feishu_user_key
 if not plugin_id or not plugin_secret:
 return Response(
 {
 "success": False,
 "message": "飞书配置不完整，请填写插件 ID 和插件 Secret",
 "plugin_token_valid": False,
 "project_accessible": False,
 }
 )
 # 执行实际的飞书 API 测试
 try:
 from feishu.client import FeishuClient
 client = FeishuClient(
 plugin_id=plugin_id,
 plugin_secret=plugin_secret,
 project_key=project.feishu_project_key,
 user_key=user_key,
 )
 test_result = await client.test_connection(project.feishu_project_key)
 return Response(
 {
 "success": test_result["success"],
 "message": test_result["message"],
 "plugin_token_valid": test_result["plugin_token_valid"],
 "project_accessible": test_result["project_accessible"],
 }
 )
 except Exception as e:
 return Response(
 {
 "success": False,
 "message": f"测试失败: {str(e)}",
 "plugin_token_valid": False,
 "project_accessible": False,
 }
 )
 @action(detail=True, methods=["post"], url_path="refresh-webhook-token")
 async def refresh_webhook_token(self, request, pk=None):
 """Refresh webhook token."""
 project = await self.aget_object
 # admin+ 权限
 if not request.user.is_superuser and not PermissionService.has_project_access(
 request.user, project, ProjectRole.ADMIN
 ):
 return Response(
 {"detail": "仅项目管理员可刷新 webhook token"},
 status=status.HTTP_403_FORBIDDEN,
 )
 project.feishu_webhook_token = generate_webhook_token
 await project.asave
 return Response(
 WebhookTokenSerializer({"webhook_token": project.feishu_webhook_token}).data
 )
 @action(detail=True, methods=["put"], url_path="webhook-token")
 async def update_webhook_token(self, request, pk=None):
 """Update webhook token with custom value."""
 project = await self.aget_object
 # admin+ 权限
 if not request.user.is_superuser and not PermissionService.has_project_access(
 request.user, project, ProjectRole.ADMIN
 ):
 return Response(
 {"detail": "仅项目管理员可修改 webhook token"},
 status=status.HTTP_403_FORBIDDEN,
 )
 serializer = WebhookTokenUpdateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 token = serializer.validated_data["token"]
 if len(token) > 32:
 return Response(
 {"detail": "Token 长度不能超过 32 个字符"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 if len(token) == 0:
 return Response(
 {"detail": "Token 不能为空"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 project.feishu_webhook_token = token
 await project.asave
 return Response(
 WebhookTokenSerializer({"webhook_token": project.feishu_webhook_token}).data
 )
 # === Claude configuration ===
 @action(detail=True, methods=["get", "put", "delete"], url_path="claude-config")
 async def claude_config(self, request, pk=None):
 """Manage Claude configuration."""
 project = await self.aget_object
 # 写操作需要 admin+ 权限
 if request.method != "GET":
 if not request.user.is_superuser and not PermissionService.has_project_access(
 request.user, project, ProjectRole.ADMIN
 ):
 return Response(
 {"detail": "仅项目管理员可修改配置"},
 status=status.HTTP_403_FORBIDDEN,
 )
 if request.method == "GET":
 has_api_key = bool(project.claude_api_key_encrypted)
 source = "project" if has_api_key else "system"
 return Response(
 ClaudeConfigSerializer(
 {
 "has_api_key": has_api_key,
 "base_url": project.claude_base_url,
 "default_model": project.claude_default_model,
 "source": source,
 }
 ).data
 )
 if request.method == "PUT":
 serializer = ClaudeConfigCreateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 api_key = serializer.validated_data.get("api_key")
 if api_key is not None:
 if api_key == "":
 project.claude_api_key_encrypted = None
 else:
 project.claude_api_key_encrypted = encrypt_value(api_key)
 base_url = serializer.validated_data.get("base_url")
 if base_url is not None:
 project.claude_base_url = base_url if base_url else None
 default_model = serializer.validated_data.get("default_model")
 if default_model is not None:
 project.claude_default_model = default_model if default_model else None
 await project.asave
 return Response(
 ClaudeConfigSerializer(
 {
 "has_api_key": bool(project.claude_api_key_encrypted),
 "base_url": project.claude_base_url,
 "default_model": project.claude_default_model,
 "source": "project" if project.claude_api_key_encrypted else "system",
 }
 ).data
 )
 # DELETE
 project.claude_api_key_encrypted = None
 project.claude_base_url = None
 project.claude_default_model = None
 await project.asave
 return Response(status=status.HTTP_204_NO_CONTENT)
 # === Feishu IM App configuration ===
 @action(detail=True, methods=["get", "put", "delete"], url_path="feishu-im-config")
 async def feishu_im_config(self, request, pk=None):
 """Manage Feishu IM App configuration."""
 project = await self.aget_object
 # 写操作需要 admin+ 权限
 if request.method != "GET":
 if not request.user.is_superuser and not PermissionService.has_project_access(
 request.user, project, ProjectRole.ADMIN
 ):
 return Response(
 {"detail": "仅项目管理员可修改配置"},
 status=status.HTTP_403_FORBIDDEN,
 )
 if request.method == "GET":
 return Response(FeishuIMConfigSerializer(project).data)
 if request.method == "PUT":
 serializer = FeishuIMConfigCreateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 project.feishu_app_id = serializer.validated_data["app_id"]
 project.feishu_app_secret_encrypted = encrypt_value(
 serializer.validated_data["app_secret"]
 )
 await project.asave
 return Response(FeishuIMConfigSerializer(project).data)
 # DELETE
 project.feishu_app_id = None
 project.feishu_app_secret_encrypted = None
 await project.asave
 return Response(status=status.HTTP_204_NO_CONTENT)
 @action(detail=True, methods=["post"], url_path="feishu-im-config/test")
 async def test_feishu_im_config(self, request, pk=None):
 """Test Feishu IM configuration by sending a test message."""
 project = await self.aget_object
 serializer = FeishuIMTestSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 user_id = serializer.validated_data["user_id"]
 message = serializer.validated_data["message"]
 # 优先使用请求中的临时配置，否则使用已保存的配置
 app_id = request.data.get("app_id") or project.feishu_app_id
 app_secret = request.data.get("app_secret")
 if not app_secret and project.feishu_app_secret_encrypted:
 from common.encryption import decrypt_value
 app_secret = decrypt_value(project.feishu_app_secret_encrypted)
 if not app_id or not app_secret:
 return Response(
 {
 "success": False,
 "message": "飞书 IM 配置不完整，请填写 App ID 和 App Secret",
 },
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 发送测试消息
 try:
 from services.feishu_im import FeishuIMClient
 client = FeishuIMClient(app_id=app_id, app_secret=app_secret)
 result = await client.send_message(
 receive_id=user_id,
 receive_id_type="open_id",
 msg_type="text",
 content={"text": message},
 )
 message_id = result.get("message_id", "")
 return Response(
 {
 "success": True,
 "message": "测试消息发送成功",
 "message_id": message_id,
 }
 )
 except Exception as e:
 return Response(
 {
 "success": False,
 "message": f"发送失败: {str(e)}",
 }
 )
class RepositoryViewSet(ModelViewSet):
 """ViewSet for Repository CRUD operations."""
 queryset = (
 Repository.objects.filter(is_deleted=False)
 .select_related("credential")
 .prefetch_related("projects")
 )
 serializer_class = RepositorySerializer
 def get_serializer_class(self):
 if self.action == "create":
 return RepositoryCreateSerializer
 if self.action == "retrieve":
 return RepositoryWithProjectsSerializer
 return RepositorySerializer
 async def acreate(self, request, *args, **kwargs):
 serializer = RepositoryCreateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 data = serializer.validated_data
 access_token = data.pop("access_token")
 git_user_name = data.pop("git_user_name", "Friday Codes AI Agent")
 git_user_email = data.pop("git_user_email", "ai@friday.codes")
 if not access_token.strip:
 return Response(
 {"detail": "Access Token 不能为空"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Create repository
 repository = await Repository.objects.acreate(**data)
 # Create credential
 await GitCredential.objects.acreate(
 repository=repository,
 auth_type=AuthType.ACCESS_TOKEN,
 encrypted_token=encrypt_value(access_token),
 git_user_name=git_user_name,
 git_user_email=git_user_email,
 )
 # KEEP: RepositorySerializer.get_has_credential 触发 credential FK 访问
 resp_data = await sync_to_async(lambda: RepositorySerializer(repository).data)
 return Response(resp_data, status=status.HTTP_201_CREATED)
 @action(detail=True, methods=["get", "delete"], url_path="credential")
 async def credential(self, request, pk=None):
 """Get or delete credential for repository."""
 repository = await self.aget_object
 if request.method == "GET":
 # 凭证不存在时返回 null 而不是 404
 credential = await GitCredential.objects.filter(repository=repository).afirst
 if credential:
 return Response(GitCredentialSerializer(credential).data)
 return Response(None)
 elif request.method == "DELETE":
 credential = await GitCredential.objects.filter(repository=repository).afirst
 if credential:
 await credential.adelete
 return Response(status=status.HTTP_204_NO_CONTENT)
 else:
 return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
class SetAccessTokenView(APIView):
 """View for setting or updating access token.
 支持创建新凭证或更新已有凭证。
 """
 async def post(self, request, repository_id):
 repository = await aget_object_or_404(Repository, id=repository_id, is_deleted=False)
 token = request.data.get("token")
 if not token:
 return Response(
 {"detail": "Token 不能为空"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 git_user_name = request.data.get("git_user_name", "Friday Codes AI Agent")
 git_user_email = request.data.get("git_user_email", "ai@friday.codes")
 # 检查凭证是否已存在，存在则更新，不存在则创建
 existing_credential = await GitCredential.objects.filter(repository=repository).afirst
 if existing_credential:
 # 更新现有凭证
 existing_credential.auth_type = AuthType.ACCESS_TOKEN
 existing_credential.encrypted_token = encrypt_value(token)
 existing_credential.git_user_name = git_user_name
 existing_credential.git_user_email = git_user_email
 await existing_credential.asave
 return Response(GitCredentialSerializer(existing_credential).data)
 else:
 # 创建新凭证
 credential = await GitCredential.objects.acreate(
 repository=repository,
 auth_type=AuthType.ACCESS_TOKEN,
 encrypted_token=encrypt_value(token),
 git_user_name=git_user_name,
 git_user_email=git_user_email,
 )
 return Response(
 GitCredentialSerializer(credential).data, status=status.HTTP_201_CREATED
 )
class ProjectRepositoryListCreateView(APIView):
 """项目仓库关联：列表（GET）和批量关联（POST）。
 GET /api/projects/{project_id}/repositories/ — viewer+ 可查看
 POST /api/projects/{project_id}/repositories/ — admin+ 可创建
 """
 async def get(self, request: object, project_id: str) -> Response:
 """返回项目关联的仓库列表。"""
 project = await aget_object_or_404(Project, id=project_id)
 # 权限：viewer+ 可查看
 has_access = await sync_to_async(PermissionService.has_project_access)(
 request.user,
 project,
 ProjectRole.VIEWER,
 )
 if not has_access:
 return Response(
 {"detail": "无权访问此项目"},
 status=status.HTTP_403_FORBIDDEN,
 )
 links = ProjectRepository.objects.filter(
 project=project,
 ).select_related("repository")
 data = await sync_to_async(
 lambda: ProjectRepositorySerializer([link for link in links], many=True).data
 )
 return Response(data)
 async def post(self, request: object, project_id: str) -> Response:
 """批量关联仓库到项目。"""
 project = await aget_object_or_404(Project, id=project_id)
 # 权限：admin+ 可创建
 has_access = await sync_to_async(PermissionService.has_project_access)(
 request.user,
 project,
 ProjectRole.ADMIN,
 )
 if not has_access:
 return Response(
 {"detail": "仅项目管理员可管理仓库关联"},
 status=status.HTTP_403_FORBIDDEN,
 )
 serializer = ProjectRepositoryCreateSerializer(data=request.data)
 await sync_to_async(serializer.is_valid)(raise_exception=True)
 repository_ids: list[str] = serializer.validated_data["repository_ids"]
 created: list[dict[str, object]] =
 skipped: list[str] =
 for repo_id in repository_ids:
 repo = await Repository.objects.filter(
 id=repo_id,
 is_deleted=False,
 ).afirst
 if repo is None:
 logger.warning("repo_not_found_skip", repo_id=str(repo_id))
 continue
 link, was_created = await ProjectRepository.objects.aget_or_create(
 project=project,
 repository=repo,
 )
 if was_created:
 data = await sync_to_async(
 lambda l=link: ProjectRepositorySerializer(l).data # noqa: E741
 )
 created.append(data)
 else:
 skipped.append(str(repo_id))
 logger.info(
 "project_repos_linked",
 project_id=str(project_id),
 created=len(created),
 skipped=len(skipped),
 )
 return Response(
 {"created": created, "skipped": skipped},
 status=status.HTTP_201_CREATED,
 )
class ProjectRepositoryDetailView(APIView):
 """项目仓库关联：更新权限（PATCH）和移除关联（DELETE）。
 PATCH /api/projects/{project_id}/repositories/{pk}/ — admin+ 可修改
 DELETE /api/projects/{project_id}/repositories/{pk}/ — admin+ 可删除
 """
 async def _check_admin(self, request: object, project: Project) -> Response | None:
 """检查 admin 权限，无权返回 403 Response，有权返回 None。"""
 has_access = await sync_to_async(PermissionService.has_project_access)(
 request.user,
 project,
 ProjectRole.ADMIN,
 )
 if not has_access:
 return Response(
 {"detail": "仅项目管理员可管理仓库关联"},
 status=status.HTTP_403_FORBIDDEN,
 )
 return None
 async def patch(self, request: object, project_id: str, pk: str) -> Response:
 """更新关联的权限级别。"""
 project = await aget_object_or_404(Project, id=project_id)
 denied = await self._check_admin(request, project)
 if denied:
 return denied
 link = await aget_object_or_404(ProjectRepository, pk=pk, project=project)
 serializer = ProjectRepositoryUpdateSerializer(data=request.data)
 await sync_to_async(serializer.is_valid)(raise_exception=True)
 link.permission_level = serializer.validated_data["permission_level"]
 await link.asave(update_fields=["permission_level"])
 data = await sync_to_async(lambda: ProjectRepositorySerializer(link).data)
 return Response(data)
 async def delete(self, request: object, project_id: str, pk: str) -> Response:
 """移除仓库关联。"""
 project = await aget_object_or_404(Project, id=project_id)
 denied = await self._check_admin(request, project)
 if denied:
 return denied
 link = await aget_object_or_404(ProjectRepository, pk=pk, project=project)
 await link.adelete
 logger.info(
 "project_repo_unlinked",
 project_id=str(project_id),
 link_id=str(pk),
 )
 return Response(status=status.HTTP_204_NO_CONTENT)
