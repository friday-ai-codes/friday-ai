"""Repositories views."""
import secrets
import subprocess
from adrf.views import APIView
from adrf.viewsets import ModelViewSet
from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from common.encryption import decrypt_value, encrypt_value
from permissions.api_permissions import IsSuperUser
from services.dependency_cache import DependencyCacheManager
from services.repo_cache_manager import RepoCacheManager
from tasks.cache_tasks import prune_cache_volumes, warmup_repo_cache
from .models import AuthType, GitCredential, Repository
from .serializers import (
 GitCredentialSerializer,
 RepositoryCreateSerializer,
 RepositorySerializer,
 RepositoryWithProjectsSerializer,
)
def is_https_git_url(git_url: str) -> bool:
 """当前 Access Token 流程只支持 HTTPS 仓库地址。"""
 return git_url.startswith(("http://", "https://"))
class RepositoryViewSet(ModelViewSet):
 """ViewSet for Repository CRUD operations."""
 permission_classes = [IsAuthenticated]
 serializer_class = RepositorySerializer
 def get_queryset(self):
 """Filter out soft-deleted repositories."""
 return (
 Repository.objects.filter(is_deleted=False)
 .select_related("credential")
 .prefetch_related("projects")
 )
 def get_serializer_class(self):
 if self.action == "create":
 return RepositoryCreateSerializer
 if self.action == "retrieve":
 return RepositoryWithProjectsSerializer
 return RepositorySerializer
 async def aretrieve(self, request, *args, **kwargs):
 """显式覆盖 aretrieve 确保使用包含 projects 字段的详情 serializer。
 adrf 的 aretrieve 默认走 get_serializer_class，但 action 判断在 async
 上下文中可能不正确，导致使用了基础 RepositorySerializer 而非
 RepositoryWithProjectsSerializer。此处显式指定 serializer 以确保正确性。
 """
 instance = await self.aget_object
 serializer = RepositoryWithProjectsSerializer(instance)
 data = await sync_to_async(lambda: serializer.data)
 return Response(data)
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
 async def perform_aupdate(self, serializer):
 # KEEP: RepositorySerializer 继承自 rest_framework，不支持 asave
 await sync_to_async(serializer.save)
 @action(detail=True, methods=["get", "delete"], url_path="credential")
 async def credential(self, request, pk=None):
 """Get or delete credential for repository."""
 repository = await self.aget_object
 if request.method == "GET":
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
 async def destroy(self, request, *args, **kwargs):
 """Soft delete the repository instead of hard delete."""
 repository = await self.aget_object
 await repository.asoft_delete
 return Response(status=status.HTTP_204_NO_CONTENT)
 @action(detail=True, methods=["post"])
 async def warmup_cache(self, request, pk=None):
 """预热仓库缓存卷。
 POST /api/repositories/{id}/warmup_cache/
 """
 repository = await self.aget_object
 volume_name = await warmup_repo_cache(
 repo_url=repository.git_url,
 repo_id=str(repository.id),
 )
 if volume_name:
 return Response({"volume": volume_name, "status": "created"})
 return Response(
 {"error": "Cache creation failed"},
 status=status.HTTP_500_INTERNAL_SERVER_ERROR,
 )
 @action(detail=True, methods=["get"])
 async def cache_status(self, request, pk=None):
 """获取仓库缓存状态。
 GET /api/repositories/{id}/cache_status/
 """
 repository = await self.aget_object
 manager = RepoCacheManager
 volume_name = manager.get_volume_name(repository.git_url)
 try:
 # KEEP: Docker SDK 同步客户端限制
 await sync_to_async(manager.client.volumes.get)(volume_name)
 return Response({
 "cached": True,
 "volume": volume_name,
 })
 except Exception:
 return Response({"cached": False})
 @action(detail=True, methods=["post"], url_path="generate-webhook-secret")
 async def generate_webhook_secret(self, request, pk=None):
 """POST /api/repositories/{id}/generate-webhook-secret/
 生成随机 webhook secret 并保存到仓库。
 """
 repository = await self.aget_object
 new_secret = secrets.token_hex(32)
 repository.webhook_secret = new_secret
 await repository.asave(update_fields=["webhook_secret"])
 return Response({"webhook_secret": new_secret})
class SetAccessTokenView(APIView):
 """View for setting or updating access token."""
 permission_classes = [IsAuthenticated]
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
 existing_credential = await GitCredential.objects.filter(repository=repository).afirst
 if existing_credential:
 existing_credential.auth_type = AuthType.ACCESS_TOKEN
 existing_credential.encrypted_token = encrypt_value(token)
 existing_credential.git_user_name = git_user_name
 existing_credential.git_user_email = git_user_email
 await existing_credential.asave
 return Response(GitCredentialSerializer(existing_credential).data)
 else:
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
class TestConnectionView(APIView):
 """View for testing Git repository connection."""
 permission_classes = [IsAuthenticated]
 async def post(self, request, repository_id=None):
 """Test connection to a Git repository.
 Can be used in two ways:
 1. With repository_id: Test existing repository's connection
 2. Without repository_id: Test connection with provided git_url and access_token
 """
 if repository_id:
 # Test existing repository
 repository = await aget_object_or_404(Repository, id=repository_id, is_deleted=False)
 git_url = repository.git_url
 proxy_url = repository.proxy_url
 # Get token from credential
 credential = await GitCredential.objects.filter(
 repository=repository
 ).afirst
 if not credential or not credential.encrypted_token:
 return Response(
 {"success": False, "error": "仓库未配置访问凭证"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 token = decrypt_value(credential.encrypted_token)
 else:
 # Test with provided data
 git_url = request.data.get("git_url")
 token = request.data.get("access_token")
 proxy_url = request.data.get("proxy_url")
 if not git_url:
 return Response(
 {"success": False, "error": "请提供仓库 URL"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 if not token:
 return Response(
 {"success": False, "error": "请提供 Access Token"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 if not is_https_git_url(git_url):
 return Response(
 {
 "success": False,
 "error": "当前仅支持 HTTPS 仓库 URL；SSH URL 需要 SSH Key，暂未支持。",
 },
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Build authenticated URL
 auth_url = git_url
 if token and git_url.startswith("https://"):
 auth_url = git_url.replace("https://", f"https://{token}@")
 # Test connection using git ls-remote
 try:
 cmd = ["git", "ls-remote", "--heads", auth_url]
 # Add proxy if configured
 env = None
 if proxy_url:
 import os
 env = os.environ.copy
 env["http_proxy"] = proxy_url
 env["https_proxy"] = proxy_url
 # KEEP: subprocess.run 阻塞系统调用，必须在线程中运行
 result = await sync_to_async(subprocess.run)(
 cmd,
 capture_output=True,
 text=True,
 timeout=30,
 env=env,
 )
 if result.returncode == 0:
 # Parse branches from output
 branches =
 for line in result.stdout.strip.split("\n"):
 if line and "\t" in line:
 ref = line.split("\t")[1]
 if ref.startswith("refs/heads/"):
 branches.append(ref.replace("refs/heads/", ""))
 return Response(
 {
 "success": True,
 "message": "连接成功",
 "branches": branches[:10], # Limit to first 10 branches
 }
 )
 else:
 error_msg = result.stderr.strip
 # Clean up token from error message
 if token:
 error_msg = error_msg.replace(token, "***")
 return Response(
 {
 "success": False,
 "error": f"连接失败: {error_msg}",
 }
 )
 except subprocess.TimeoutExpired:
 return Response(
 {
 "success": False,
 "error": "连接超时，请检查网络或代理配置",
 }
 )
 except Exception as e:
 return Response(
 {
 "success": False,
 "error": f"连接测试失败: {e!s}",
 }
 )
class CacheManagementView(APIView):
 """缓存管理 API。"""
 permission_classes = [IsSuperUser]
 async def get(self, request):
 """列出所有缓存卷。
 GET /api/repositories/cache/
 """
 repo_manager = RepoCacheManager
 deps_manager = DependencyCacheManager
 repo_volumes = await repo_manager.list_cache_volumes
 deps_volumes = await deps_manager.list_deps_volumes
 return Response({
 "repo_caches": repo_volumes,
 "deps_caches": deps_volumes,
 })
 async def delete(self, request):
 """清理缓存卷。
 DELETE /api/repositories/cache/?older_than_days=7&dry_run=true
 """
 older_than_days = int(request.query_params.get("older_than_days", 7))
 dry_run = request.query_params.get("dry_run", "false").lower == "true"
 pruned = await prune_cache_volumes(older_than_days, dry_run)
 return Response({
 "pruned": pruned,
 "dry_run": dry_run,
 })
