"""Projects app views."""
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from common.encryption import encrypt_value
from .models import (
 AuthType,
 GitCredential,
 Project,
 ProjectRepository,
 Repository,
 generate_webhook_token,
)
from .serializers import (
 ClaudeConfigCreateSerializer,
 ClaudeConfigSerializer,
 FeishuConfigCreateSerializer,
 FeishuConfigSerializer,
 GitCredentialSerializer,
 ProjectCreateSerializer,
 ProjectSerializer,
 ProjectUpdateSerializer,
 RepositoryCreateSerializer,
 RepositorySerializer,
 RepositoryWithProjectsSerializer,
 WebhookTokenSerializer,
 WebhookTokenUpdateSerializer,
)
class ProjectViewSet(ModelViewSet):
 """ViewSet for Project CRUD operations."""
 queryset = Project.objects.prefetch_related("repositories__credential").all
 serializer_class = ProjectSerializer
 def get_serializer_class(self):
 if self.action == "create":
 return ProjectCreateSerializer
 if self.action in ["update", "partial_update"]:
 return ProjectUpdateSerializer
 return ProjectSerializer
 def create(self, request, *args, **kwargs):
 serializer = self.get_serializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 project = Project.objects.create(**serializer.validated_data)
 return Response(
 ProjectSerializer(project).data,
 status=status.HTTP_201_CREATED,
 )
 # === Repository association ===
 @action(detail=True, methods=["get"], url_path="repositories")
 def list_repositories(self, request, pk=None):
 """List repositories associated with the project."""
 project = self.get_object
 repositories = project.repositories.filter(is_deleted=False)
 serializer = RepositorySerializer(repositories, many=True)
 return Response(serializer.data)
 @action(detail=True, methods=["post"], url_path=r"repositories/(?P<repository_id>[^/.]+)")
 def link_repository(self, request, pk=None, repository_id=None):
 """Link a repository to the project."""
 project = self.get_object
 repository = get_object_or_404(Repository, id=repository_id, is_deleted=False)
 _, created = ProjectRepository.objects.get_or_create(
 project=project,
 repository=repository,
 )
 if not created:
 return Response({"message": "Already linked"})
 return Response({"message": "Linked successfully"}, status=status.HTTP_201_CREATED)
 @link_repository.mapping.delete
 def unlink_repository(self, request, pk=None, repository_id=None):
 """Unlink a repository from the project."""
 project = self.get_object
 link = get_object_or_404(
 ProjectRepository,
 project=project,
 repository_id=repository_id,
 )
 link.delete
 return Response(status=status.HTTP_204_NO_CONTENT)
 # === Feishu configuration ===
 @action(detail=True, methods=["get", "put", "delete"], url_path="feishu-config")
 def feishu_config(self, request, pk=None):
 """Manage Feishu configuration."""
 project = self.get_object
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
 project.save
 return Response(FeishuConfigSerializer(project).data)
 # DELETE
 project.feishu_plugin_id = None
 project.feishu_plugin_secret_encrypted = None
 project.feishu_user_key = None
 project.save
 return Response(status=status.HTTP_204_NO_CONTENT)
 @action(detail=True, methods=["post"], url_path="feishu-config/test")
 def test_feishu_config(self, request, pk=None):
 """Test Feishu configuration."""
 project = self.get_object
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
 import asyncio
 from feishu.client import FeishuClient
 client = FeishuClient(
 plugin_id=plugin_id,
 plugin_secret=plugin_secret,
 project_key=project.feishu_project_key,
 user_key=user_key,
 )
 # 使用 asyncio.run 执行异步测试
 test_result = asyncio.run(client.test_connection(project.feishu_project_key))
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
 def refresh_webhook_token(self, request, pk=None):
 """Refresh webhook token."""
 project = self.get_object
 project.feishu_webhook_token = generate_webhook_token
 project.save
 return Response(
 WebhookTokenSerializer({"webhook_token": project.feishu_webhook_token}).data
 )
 @action(detail=True, methods=["put"], url_path="webhook-token")
 def update_webhook_token(self, request, pk=None):
 """Update webhook token with custom value."""
 project = self.get_object
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
 project.save
 return Response(
 WebhookTokenSerializer({"webhook_token": project.feishu_webhook_token}).data
 )
 # === Claude configuration ===
 @action(detail=True, methods=["get", "put", "delete"], url_path="claude-config")
 def claude_config(self, request, pk=None):
 """Manage Claude configuration."""
 project = self.get_object
 if request.method == "GET":
 has_api_key = bool(project.claude_api_key_encrypted)
 source = "project" if has_api_key else "system"
 return Response(
 ClaudeConfigSerializer(
 {
 "has_api_key": has_api_key,
 "base_url": project.claude_base_url,
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
 project.save
 return Response(
 ClaudeConfigSerializer(
 {
 "has_api_key": bool(project.claude_api_key_encrypted),
 "base_url": project.claude_base_url,
 "source": "project" if project.claude_api_key_encrypted else "system",
 }
 ).data
 )
 # DELETE
 project.claude_api_key_encrypted = None
 project.claude_base_url = None
 project.save
 return Response(status=status.HTTP_204_NO_CONTENT)
class RepositoryViewSet(ModelViewSet):
 """ViewSet for Repository CRUD operations."""
 queryset = Repository.objects.filter(is_deleted=False).select_related("credential").prefetch_related("projects")
 serializer_class = RepositorySerializer
 def get_serializer_class(self):
 if self.action == "create":
 return RepositoryCreateSerializer
 if self.action == "retrieve":
 return RepositoryWithProjectsSerializer
 return RepositorySerializer
 def create(self, request, *args, **kwargs):
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
 repository = Repository.objects.create(**data)
 # Create credential
 GitCredential.objects.create(
 repository=repository,
 auth_type=AuthType.ACCESS_TOKEN,
 encrypted_token=encrypt_value(access_token),
 git_user_name=git_user_name,
 git_user_email=git_user_email,
 )
 return Response(
 RepositorySerializer(repository).data,
 status=status.HTTP_201_CREATED,
 )
 @action(detail=True, methods=["get", "delete"], url_path="credential")
 def credential(self, request, pk=None):
 """Get or delete credential for repository."""
 repository = self.get_object
 if request.method == "GET":
 # 凭证不存在时返回 null 而不是 404
 credential = GitCredential.objects.filter(repository=repository).first
 if credential:
 return Response(GitCredentialSerializer(credential).data)
 return Response(None)
 elif request.method == "DELETE":
 credential = GitCredential.objects.filter(repository=repository).first
 if credential:
 credential.delete
 return Response(status=status.HTTP_204_NO_CONTENT)
 else:
 return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
class SetAccessTokenView(APIView):
 """View for setting or updating access token.
 支持创建新凭证或更新已有凭证。
 """
 def post(self, request, repository_id):
 repository = get_object_or_404(Repository, id=repository_id, is_deleted=False)
 token = request.data.get("token")
 if not token:
 return Response(
 {"detail": "Token 不能为空"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 git_user_name = request.data.get("git_user_name", "Friday Codes AI Agent")
 git_user_email = request.data.get("git_user_email", "ai@friday.codes")
 # 检查凭证是否已存在，存在则更新，不存在则创建
 existing_credential = GitCredential.objects.filter(repository=repository).first
 if existing_credential:
 # 更新现有凭证
 existing_credential.auth_type = AuthType.ACCESS_TOKEN
 existing_credential.encrypted_token = encrypt_value(token)
 existing_credential.git_user_name = git_user_name
 existing_credential.git_user_email = git_user_email
 existing_credential.save
 return Response(GitCredentialSerializer(existing_credential).data)
 else:
 # 创建新凭证
 credential = GitCredential.objects.create(
 repository=repository,
 auth_type=AuthType.ACCESS_TOKEN,
 encrypted_token=encrypt_value(token),
 git_user_name=git_user_name,
 git_user_email=git_user_email,
 )
 return Response(
 GitCredentialSerializer(credential).data, status=status.HTTP_201_CREATED
 )
