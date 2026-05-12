"""Repositories views."""
import os
import secrets
import subprocess
from urllib.parse import quote
import structlog
from adrf.views import APIView
from adrf.viewsets import ModelViewSet
from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from common.encryption import decrypt_value, encrypt_value
from permissions.api_permissions import IsSuperUser
from services.dependency_cache import DependencyCacheManager
from services.repo_cache_manager import RepoCacheManager
from tasks.cache_tasks import prune_cache_volumes, warmup_repo_cache
from .models import (
 AISummaryStatus,
 AuthType,
 GitCredential,
 IndexHistory,
 IndexHistoryStatus,
 IndexStatus,
 Repository,
 RepositoryBranchIndex,
 TriggerType,
)
from .serializers import (
 GitCredentialSerializer,
 RepositoryCreateSerializer,
 RepositorySerializer,
 RepositoryWithProjectsSerializer,
)
logger = structlog.get_logger(__name__)
DEFAULT_BRANCH_REINDEX_STAGE = "默认分支已变更，准备更新索引..."
def is_https_git_url(git_url: str) -> bool:
 """当前 Access Token 流程只支持 HTTPS 仓库地址。"""
 return git_url.startswith(("http://", "https://"))
def build_authenticated_git_url(git_url: str, token: str | None) -> str:
 """把 token 嵌入 https URL 的密码位置。
 采用 ``https://oauth2:<token>@host/...`` 形式：
 - GitLab 项目/个人访问令牌必须放在 *密码* 位置，仅放在用户名位置（即
 ``https://<token>@host``）会被 git 解析成 ``user=<token>, password=空``，
 触发凭证 prompt 后被 ``GIT_TERMINAL_PROMPT=0`` 中断，报
 ``could not read Password ... terminal prompts disabled``；
 - GitHub PAT、Gitea Token 都接受任意用户名 + token 作为密码，
 因此使用 ``oauth2`` 这一占位用户名能在四大平台上一致工作。
 token 内的特殊字符会被 URL 编码以避免破坏 URL 结构。
 """
 if not token or not git_url.startswith(("http://", "https://")):
 return git_url
 scheme, rest = git_url.split("://", 1)
 encoded_token = quote(token, safe="")
 return f"{scheme}://oauth2:{encoded_token}@{rest}"
def _build_git_env(proxy_url: str | None = None) -> dict[str, str]:
 """构造执行 git 命令的环境变量。
 显式移除外部继承的凭证助手与 askpass 配置（例如 VS Code 注入的
 `GIT_ASKPASS=.../vscode-git-*.sock`），避免 git 在 token 鉴权失败时
 再去连接不存在的 socket，产生 `ECONNREFUSED /var/folders/.../vscode-git-*.sock`
 这类无关噪音污染错误信息。
 """
 env = os.environ.copy
 for key in (
 "GIT_ASKPASS",
 "SSH_ASKPASS",
 "GIT_CREDENTIAL_HELPER",
 "GCM_INTERACTIVE",
 ):
 env.pop(key, None)
 env["GIT_TERMINAL_PROMPT"] = "0"
 env["GIT_CONFIG_COUNT"] = "1"
 env["GIT_CONFIG_KEY_0"] = "credential.helper"
 env["GIT_CONFIG_VALUE_0"] = ""
 if proxy_url:
 env["http_proxy"] = proxy_url
 env["https_proxy"] = proxy_url
 return env
def _parse_git_error(stderr: str) -> str:
 """把 git ls-remote 的 stderr 简化为面向用户的中文错误。
 原始 stderr 通常含有大量与最终原因无关的内容（例如 credential helper
 的 socket 报错、stack trace、URL 等）。这里识别常见模式并返回简短消息，
 原始内容由调用方写日志便于排查。
 """
 text = (stderr or "").strip
 if not text:
 return "连接失败，请检查仓库 URL 和访问令牌"
 lowered = text.lower
 auth_markers = (
 "http basic: access denied",
 "authentication failed",
 "authentication required",
 "could not read username",
 "could not read password",
 "invalid credentials",
 "401 unauthorized",
 "403 forbidden",
 "鉴权失败",
 "认证失败",
 )
 if any(marker in lowered or marker in text for marker in auth_markers):
 return "鉴权失败：Access Token 无效或权限不足"
 not_found_markers = (
 "repository not found",
 "not found",
 "does not exist",
 "no such repository",
 "404",
 )
 if any(marker in lowered for marker in not_found_markers):
 return "仓库不存在或当前 Token 无访问权限"
 if (
 "ssl certificate" in lowered
 or "ssl_error" in lowered
 or "self signed certificate" in lowered
 or "certificate verify" in lowered
 or "unable to get local issuer certificate" in lowered
 ):
 return "SSL 证书校验失败，请检查仓库或代理证书"
 network_markers = (
 "could not resolve host",
 "couldn't resolve host",
 "failed to connect",
 "connection timed out",
 "connection refused",
 "network is unreachable",
 "unable to access",
 "operation timed out",
 )
 if any(marker in lowered for marker in network_markers):
 return "网络连接失败，请检查仓库 URL 或代理配置"
 for raw_line in text.splitlines:
 line = raw_line.strip
 if not line:
 continue
 lower_line = line.lower
 if "vscode-git" in lower_line or "econnrefused" in lower_line:
 continue
 if line.startswith("remote:"):
 line = line[len("remote:"):].strip
 if line.lower.startswith("fatal:"):
 line = line[len("fatal:"):].strip
 if line.startswith("致命错误"):
 line = line.split("：", 1)[-1].strip
 if line:
 return line
 return "连接失败，请检查仓库 URL 和访问令牌"
async def _validate_base_branch(
 git_url: str,
 token: str,
 base_branch: str,
 proxy_url: str | None = None,
) -> bool:
 """通过 git ls-remote 检查分支是否存在于远端。"""
 auth_url = build_authenticated_git_url(git_url, token)
 cmd = ["git", "ls-remote", "--heads", auth_url, f"refs/heads/{base_branch}"]
 env = _build_git_env(proxy_url)
 try:
 result = await sync_to_async(subprocess.run)(
 cmd, capture_output=True, text=True, timeout=15, env=env,
 )
 return bool(result.stdout.strip)
 except (subprocess.TimeoutExpired, Exception):
 logger.warning("base_branch_validation_failed", branch=base_branch, git_url=git_url)
 return False
async def _schedule_default_branch_rolling_index(
 repository: Repository,
 *,
 from_sha: str | None,
) -> None:
 """默认分支变更后，基于旧索引 commit 滚动更新到新默认分支。"""
 repo_id = str(repository.id)
 await Repository.objects.filter(id=repository.id).aupdate(
 index_status=IndexStatus.INDEXING,
 index_error=None,
 index_total_chunks=0,
 index_processed_chunks=0,
 index_write_total=0,
 index_write_processed=0,
 index_stage=DEFAULT_BRANCH_REINDEX_STAGE,
 remote_head_sha="",
 remote_head_checked_at=None,
 behind_commits=None,
 behind_commits_calculated_at=None,
 )
 await RepositoryBranchIndex.objects.filter(repository=repository).aupdate(
 is_stale=True,
 )
 history = await IndexHistory.objects.acreate(
 repository=repository,
 trigger_type=TriggerType.MANUAL,
 status=IndexHistoryStatus.RUNNING,
 from_sha=from_sha,
 started_at=timezone.now,
 )
 from services.background_runner import run_in_background
 from services.indexer import clone_and_index_repository
 run_in_background(
 lambda: clone_and_index_repository(repo_id, history_id=str(history.id)),
 name=f"index-{repo_id}",
 )
 repository.index_status = IndexStatus.INDEXING
 repository.index_error = None
 repository.index_total_chunks = 0
 repository.index_processed_chunks = 0
 repository.index_write_total = 0
 repository.index_write_processed = 0
 repository.index_stage = DEFAULT_BRANCH_REINDEX_STAGE
 repository.remote_head_sha = ""
 repository.remote_head_checked_at = None
 repository.behind_commits = None
 repository.behind_commits_calculated_at = None
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
 if data.get("base_branch") and "default_branch" not in data:
 data["default_branch"] = data["base_branch"]
 data["base_branch"] = None
 default_branch = data.get("default_branch")
 if default_branch:
 is_valid = await _validate_base_branch(
 git_url=data["git_url"],
 token=access_token,
 base_branch=default_branch,
 proxy_url=data.get("proxy_url"),
 )
 if not is_valid:
 return Response(
 {"default_branch": [f"所选分支 '{default_branch}' 在远端仓库中不存在"]},
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
 if serializer.validated_data.get("base_branch") and "default_branch" not in serializer.validated_data:
 serializer.validated_data["default_branch"] = serializer.validated_data["base_branch"]
 serializer.validated_data["base_branch"] = None
 default_branch = serializer.validated_data.get("default_branch")
 instance = serializer.instance
 old_default_branch = instance.default_branch
 old_index_status = instance.index_status
 old_last_indexed_commit_sha = instance.last_indexed_commit_sha
 default_branch_changed = (
 default_branch is not None
 and default_branch != old_default_branch
 )
 if default_branch_changed and old_index_status == IndexStatus.INDEXING:
 raise serializers.ValidationError(
 {"default_branch": ["当前索引正在运行，请先停止索引后再切换默认分支"]}
 )
 if default_branch:
 credential = await GitCredential.objects.filter(repository=instance).afirst
 if credential and credential.encrypted_token:
 token = decrypt_value(credential.encrypted_token)
 is_valid = await _validate_base_branch(
 git_url=instance.git_url,
 token=token,
 base_branch=default_branch,
 proxy_url=instance.proxy_url,
 )
 if not is_valid:
 raise serializers.ValidationError(
 {"default_branch": [f"所选分支 '{default_branch}' 在远端仓库中不存在"]}
 )
 # KEEP: RepositorySerializer 继承自 rest_framework，不支持 asave
 await sync_to_async(serializer.save)
 if default_branch_changed and old_index_status != IndexStatus.NOT_INDEXED:
 await _schedule_default_branch_rolling_index(
 serializer.instance,
 from_sha=old_last_indexed_commit_sha,
 )
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
 @action(detail=True, methods=["post"], url_path="generate-summary")
 async def generate_summary(self, request, pk=None):
 """POST /api/repositories/{id}/generate-summary/
 触发仓库 AI 描述生成。幂等检查：status=running/pending 时返回 409。
 """
 repository = await self.aget_object
 if repository.ai_summary_status in (
 AISummaryStatus.RUNNING,
 AISummaryStatus.PENDING,
 ):
 return Response(
 {
 "detail": "摘要正在生成中，请稍候",
 "status": repository.ai_summary_status,
 },
 status=status.HTTP_409_CONFLICT,
 )
 from .summary_service import dispatch_repo_summary
 session_id = await dispatch_repo_summary(repository)
 return Response({"dispatch_task_id": session_id, "status": "pending"})
 @action(detail=True, methods=["get"], url_path="summary-status")
 async def summary_status(self, request, pk=None):
 """GET /api/repositories/{id}/summary-status/
 返回仓库 AI 描述生成状态。
 """
 repository = await self.aget_object
 return Response({
 "status": repository.ai_summary_status,
 "progress": None,
 "summary": repository.ai_summary,
 "generated_at": repository.ai_summary_generated_at,
 "error": repository.ai_summary_error or None,
 })
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
 # Build authenticated URL（GitLab project token 必须把 token 放在密码位置）
 auth_url = build_authenticated_git_url(git_url, token)
 # Test connection using git ls-remote
 try:
 cmd = ["git", "ls-remote", "--heads", auth_url]
 env = _build_git_env(proxy_url)
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
 recommended_priority = ["main", "master", "develop"]
 recommended_branch = None
 for candidate in recommended_priority:
 if candidate in branches:
 recommended_branch = candidate
 break
 return Response(
 {
 "success": True,
 "message": "连接成功",
 "branches": sorted(branches),
 "recommended_branch": recommended_branch,
 }
 )
 else:
 raw_stderr = result.stderr or ""
 if token:
 raw_stderr = raw_stderr.replace(token, "***")
 logger.warning(
 "git_test_connection_failed",
 git_url=git_url,
 returncode=result.returncode,
 stderr=raw_stderr,
 )
 return Response(
 {
 "success": False,
 "error": _parse_git_error(raw_stderr),
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
 logger.exception("git_test_connection_exception", git_url=git_url)
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
