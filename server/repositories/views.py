"""Repositories views."""

import os
import secrets
import subprocess
import tempfile
from urllib.parse import quote

import structlog
from adrf.views import APIView
from adrf.viewsets import ModelViewSet
from asgiref.sync import sync_to_async
from django.db import IntegrityError
from django.shortcuts import aget_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from audit.services import taxonomy
from audit.services.audit_service import AuditService
from common.encryption import encrypt_value
from permissions.api_permissions import IsSuperUser
from services.background_runner import run_in_background
from services.dependency_cache import DependencyCacheManager
from services.exclusion import get_global_default_specs, invalidate_matcher_cache
from services.git_credentials import aresolve_git_token
from services.purge_reconcile import compute_reconciliation, run_cleanup
from services.repo_cache_manager import RepoCacheManager
from tasks.cache_tasks import prune_cache_volumes, warmup_repo_cache

from .models import (
    AISummaryStatus,
    AuthType,
    CleanupRun,
    GitCredential,
    GitInstanceCredential,
    GitPlatform,
    IndexHistory,
    IndexHistoryStatus,
    IndexStatus,
    RepoExclusionRule,
    Repository,
    RepositoryBranchIndex,
    SensitiveFileSuggestion,
    TriggerType,
)
from .serializers import (
    CleanupRequestSerializer,
    CleanupRunSerializer,
    GitCredentialSerializer,
    GitInstanceCredentialSerializer,
    GitInstanceCredentialWriteSerializer,
    ReconcileReportSerializer,
    RepoExclusionRuleSerializer,
    RepositoryCreateSerializer,
    RepositorySerializer,
    RepositoryWithSpacesSerializer,
    SensitiveFileSuggestionSerializer,
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
    env = os.environ.copy()
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
    text = (stderr or "").strip()
    if not text:
        return "连接失败，请检查仓库 URL 和访问令牌"

    lowered = text.lower()

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

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower_line = line.lower()
        if "vscode-git" in lower_line or "econnrefused" in lower_line:
            continue
        if line.startswith("remote:"):
            line = line[len("remote:") :].strip()
        if line.lower().startswith("fatal:"):
            line = line[len("fatal:") :].strip()
        if line.startswith("致命错误"):
            line = line.split("：", 1)[-1].strip()
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
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        return bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, Exception):
        logger.warning("base_branch_validation_failed", branch=base_branch, git_url=git_url)
        return False


def _parse_ls_remote_refs(stdout: str) -> tuple[list[str], str | None]:
    """解析 ``git ls-remote --symref <url> HEAD refs/heads/*`` 输出。

    返回 ``(branches, head_branch)``。head_branch 优先取 symref 行
    （``ref: refs/heads/<name>\\tHEAD``）；部分 git 服务器不回传 symref 时，
    退化为用 HEAD sha 反查同 sha 的分支（多个命中时偏向 main/master）。
    """
    branches: list[str] = []
    head_branch: str | None = None
    head_sha: str | None = None
    sha_by_branch: dict[str, str] = {}
    for line in stdout.strip().splitlines():
        if not line or "\t" not in line:
            continue
        left, ref = line.split("\t", 1)
        ref = ref.strip()
        if left.startswith("ref: refs/heads/") and ref == "HEAD":
            head_branch = left[len("ref: refs/heads/") :].strip()
        elif ref == "HEAD":
            head_sha = left.strip()
        elif ref.startswith("refs/heads/"):
            name = ref[len("refs/heads/") :]
            branches.append(name)
            sha_by_branch[name] = left.strip()
    if head_branch is None and head_sha:
        matched = [name for name, sha in sha_by_branch.items() if sha == head_sha]
        for preferred in ("main", "master"):
            if preferred in matched:
                head_branch = preferred
                break
        else:
            head_branch = matched[0] if matched else None
    return branches, head_branch


async def _probe_branch_activity(
    auth_url: str,
    proxy_url: str | None = None,
    *,
    timeout: int = 20,
) -> dict[str, int]:
    """best-effort 获取各远端分支最近一次提交时间（unix 秒）。

    ``git ls-remote`` 只给 sha 不给时间，这里在临时 bare 仓库里做
    ``fetch --depth=1 --filter=tree:0``（每分支只拉一个 commit 对象，无
    tree/blob，流量极小），再用 for-each-ref 读 committerdate。服务器不支持
    partial clone 或超时一律返回空 dict，调用方排序退化为字典序。
    """

    def _probe() -> dict[str, int]:
        env = _build_git_env(proxy_url)
        with tempfile.TemporaryDirectory(prefix="friday-branch-probe-") as tmp:
            init = subprocess.run(
                ["git", "init", "--bare", "--quiet", tmp],
                capture_output=True,
                text=True,
                timeout=10,
                env=env,
            )
            if init.returncode != 0:
                return {}
            fetch = subprocess.run(
                [
                    "git",
                    "-C",
                    tmp,
                    "fetch",
                    "--quiet",
                    "--depth=1",
                    "--filter=tree:0",
                    auth_url,
                    "+refs/heads/*:refs/heads/*",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            if fetch.returncode != 0:
                return {}
            refs = subprocess.run(
                [
                    "git",
                    "-C",
                    tmp,
                    "for-each-ref",
                    "--format=%(committerdate:unix)\t%(refname:short)",
                    "refs/heads",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                env=env,
            )
            if refs.returncode != 0:
                return {}
            activity: dict[str, int] = {}
            for line in refs.stdout.splitlines():
                if "\t" not in line:
                    continue
                ts, name = line.split("\t", 1)
                try:
                    activity[name] = int(ts)
                except ValueError:
                    continue
            return activity

    try:
        return await sync_to_async(_probe)()
    except (subprocess.TimeoutExpired, Exception):
        logger.info("branch_activity_probe_failed", auth_url_host=auth_url.split("@")[-1])
        return {}


def _sort_branches(
    branches: list[str],
    head_branch: str | None,
    activity: dict[str, int] | None = None,
) -> list[str]:
    """分支排序：HEAD 所在分支 > main/master > 最近活跃 > 字典序。"""
    activity = activity or {}

    def sort_key(name: str) -> tuple[int, int, str]:
        if name == head_branch:
            group = 0
        elif name in ("main", "master"):
            group = 1
        else:
            group = 2
        return (group, -activity.get(name, 0), name)

    return sorted(branches, key=sort_key)


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
        started_at=timezone.now(),
    )

    # durable 入队 + deterministic key 去重（index:{repo_id}）；IndexHistory 仍为进度真相源，
    # FileIndex checkpoint 在任务体内复用，重复投递/执行不产生重复数据。
    from durable import QUEUE_INDEX, DurableTaskService

    await DurableTaskService.defer(
        "durable_index",
        {
            "repository_id": repo_id,
            "history_id": str(history.id),
            "branch": None,
            "trigger": "manual",
        },
        queue=QUEUE_INDEX,
        idempotency_key=f"index:{repo_id}",
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
            return RepositoryWithSpacesSerializer
        return RepositorySerializer

    async def aretrieve(self, request, *args, **kwargs):
        """显式覆盖 aretrieve 确保使用包含 spaces 字段的详情 serializer。

        adrf 的 aretrieve 默认走 get_serializer_class，但 action 判断在 async
        上下文中可能不正确，导致使用了基础 RepositorySerializer 而非
        RepositoryWithSpacesSerializer。此处显式指定 serializer 以确保正确性。
        """
        instance = await self.aget_object()
        serializer = RepositoryWithSpacesSerializer(instance)
        data = await sync_to_async(lambda: serializer.data)()
        return Response(data)

    async def acreate(self, request, *args, **kwargs):
        serializer = RepositoryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        access_token = data.pop("access_token")
        git_user_name = data.pop("git_user_name", "Friday Codes AI Agent")
        git_user_email = data.pop("git_user_email", "ai@friday.codes")
        space_ids = [str(sid) for sid in data.pop("space_ids")]

        if not access_token.strip():
            return Response(
                {"detail": "Access Token 不能为空"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 校验关联空间存在（所有仓库都必须至少关联一个空间）
        from projects.models import Project, ProjectRepository

        spaces = [s async for s in Project.objects.filter(id__in=space_ids)]
        if len(spaces) != len(set(space_ids)):
            return Response(
                {"space_ids": ["部分空间不存在"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # HEAD 分支由前端从 test-connection 结果带入（创建前必须测连拿分支列表）；
        # 未显式选默认分支时自动采用 HEAD 分支
        head_branch = data.get("remote_head_branch")
        if head_branch and not data.get("default_branch"):
            data["default_branch"] = head_branch

        base_branch = data.get("base_branch")
        if base_branch and "default_branch" not in data:
            data["default_branch"] = base_branch
        if base_branch:
            is_valid = await _validate_base_branch(
                git_url=data["git_url"],
                token=access_token,
                base_branch=base_branch,
                proxy_url=data.get("proxy_url"),
            )
            if not is_valid:
                return Response(
                    {"base_branch": [f"所选分支 '{base_branch}' 在远端仓库中不存在"]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Create repository
        repository = await Repository.objects.acreate(**data)

        # 建立空间关联
        await ProjectRepository.objects.abulk_create(
            [ProjectRepository(project=space, repository=repository) for space in spaces]
        )

        # Create credential
        await GitCredential.objects.acreate(
            repository=repository,
            auth_type=AuthType.ACCESS_TOKEN,
            encrypted_token=encrypt_value(access_token),
            git_user_name=git_user_name,
            git_user_email=git_user_email,
        )

        # 审计：建仓附带 per-repo Git 凭证创建（token 密文绝不入载荷，仅记 provided 布尔）
        await AuditService.aemit(
            action=taxonomy.ACTION_CREDENTIAL_CREATED,
            actor=self.request.user,
            target_type="git_credential",
            target_id=repository.id,
            target_repr=repository.name,
            after={"provided": True, "git_user_name": git_user_name},
            source="api",
        )

        # 建仓即自动生成「AI 描述 + PageIndex 索引」（best-effort：
        # Runner 离线 / AI 凭证未配置等失败只记日志，不阻塞建仓响应）。
        self._schedule_auto_summary(str(repository.id))

        # KEEP: RepositorySerializer.get_has_credential 触发 credential FK 访问
        resp_data = await sync_to_async(lambda: RepositorySerializer(repository).data)()
        return Response(resp_data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _schedule_auto_summary(repository_id: str) -> None:
        """仓库创建后后台自动派发 repo_summary（AI 描述 + PageIndex 能力树）。"""
        from services.background_runner import run_in_background

        async def _auto_dispatch() -> None:
            from repositories.summary_service import dispatch_repo_summary

            repo = await Repository.objects.filter(id=repository_id, is_deleted=False).afirst()
            if repo is None or repo.ai_summary_status in (
                AISummaryStatus.PENDING,
                AISummaryStatus.RUNNING,
            ):
                return
            try:
                session_id = await dispatch_repo_summary(repo)
                logger.info(
                    "auto_repo_summary_dispatched",
                    repository_id=repository_id,
                    session_id=session_id,
                )
            except Exception:  # noqa: BLE001 — 自动触发失败不影响建仓
                logger.warning(
                    "auto_repo_summary_dispatch_failed",
                    repository_id=repository_id,
                    exc_info=True,
                )

        run_in_background(_auto_dispatch, name=f"auto_repo_summary_{repository_id}")

    async def perform_aupdate(self, serializer):
        base_branch = serializer.validated_data.get("base_branch")
        if base_branch and "default_branch" not in serializer.validated_data:
            serializer.validated_data["default_branch"] = base_branch
        default_branch = serializer.validated_data.get("default_branch")
        instance = serializer.instance
        old_default_branch = instance.default_branch
        old_index_status = instance.index_status
        old_last_indexed_commit_sha = instance.last_indexed_commit_sha

        default_branch_changed = default_branch is not None and default_branch != old_default_branch
        if default_branch_changed and old_index_status == IndexStatus.INDEXING:
            raise serializers.ValidationError(
                {"default_branch": ["当前索引正在运行，请先停止索引后再切换默认分支"]}
            )

        if base_branch:
            # 经统一解析器取 token（per-repo 显式 token 优先 → host 实例凭证池 fallback），
            # 使「无 per-repo token、仅靠实例池」的仓库也能做 base-branch 校验（Plan 26-04）。
            token = await aresolve_git_token(instance)
            if token:
                is_valid = await _validate_base_branch(
                    git_url=instance.git_url,
                    token=token,
                    base_branch=base_branch,
                    proxy_url=instance.proxy_url,
                )
                if not is_valid:
                    raise serializers.ValidationError(
                        {"base_branch": [f"所选分支 '{base_branch}' 在远端仓库中不存在"]}
                    )
        # KEEP: RepositorySerializer 继承自 rest_framework，不支持 asave()
        await sync_to_async(serializer.save)()
        if default_branch_changed and old_index_status != IndexStatus.NOT_INDEXED:
            await _schedule_default_branch_rolling_index(
                serializer.instance,
                from_sha=old_last_indexed_commit_sha,
            )

    @action(detail=True, methods=["get", "delete"], url_path="credential")
    async def credential(self, request, pk=None):
        """Get or delete credential for repository."""
        repository = await self.aget_object()

        if request.method == "GET":
            credential = await GitCredential.objects.filter(repository=repository).afirst()
            if credential:
                return Response(GitCredentialSerializer(credential).data)
            return Response(None)

        elif request.method == "DELETE":
            credential = await GitCredential.objects.filter(repository=repository).afirst()
            if credential:
                await credential.adelete()
                # 审计：per-repo Git 凭证删除
                await AuditService.aemit(
                    action=taxonomy.ACTION_CREDENTIAL_DELETED,
                    actor=request.user,
                    target_type="git_credential",
                    target_id=repository.id,
                    target_repr=repository.name,
                    before={"provided": True},
                    source="api",
                )
            return Response(status=status.HTTP_204_NO_CONTENT)
        else:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    async def destroy(self, request, *args, **kwargs):
        """Soft delete the repository instead of hard delete."""
        repository = await self.aget_object()
        await repository.asoft_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    async def warmup_cache(self, request, pk=None):
        """预热仓库缓存卷。

        POST /api/repositories/{id}/warmup_cache/
        """
        repository = await self.aget_object()
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
        repository = await self.aget_object()
        manager = RepoCacheManager()
        volume_name = manager.get_volume_name(repository.git_url)

        try:
            # KEEP: Docker SDK 同步客户端限制
            await sync_to_async(manager.client.volumes.get)(volume_name)
            return Response(
                {
                    "cached": True,
                    "volume": volume_name,
                }
            )
        except Exception:
            return Response({"cached": False})

    @action(detail=True, methods=["post"], url_path="generate-summary")
    async def generate_summary(self, request, pk=None):
        """POST /api/repositories/{id}/generate-summary/

        触发仓库 AI 描述生成。幂等检查：status=running/pending 时返回 409。
        """
        repository = await self.aget_object()
        from .summary_service import dispatch_repo_summary, reconcile_ai_summary_status

        repository = await reconcile_ai_summary_status(repository)
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

        session_id = await dispatch_repo_summary(repository)
        return Response({"dispatch_task_id": session_id, "status": "pending"})

    @action(detail=True, methods=["get"], url_path="summary-status")
    async def summary_status(self, request, pk=None):
        """GET /api/repositories/{id}/summary-status/

        返回仓库 AI 描述生成状态 + Claude Code 调用细节（recent_logs）。
        """
        repository = await self.aget_object()
        from .summary_service import reconcile_ai_summary_status

        repository = await reconcile_ai_summary_status(repository)

        # PageIndex 能力树状态：节点数统计（递归）
        def _count_nodes(nodes: list) -> int:
            total = 0
            stack = list(nodes or [])
            while stack:
                node = stack.pop()
                total += 1
                stack.extend(node.get("children", []) if isinstance(node, dict) else [])
            return total

        # 调用细节：Runner 实时回传的容器日志（[task:text]/[task:tool]/[task:result]）
        # 由 runners.consumers._append_runtime_log 写入最近一次 REPO_SUMMARY 会话的
        # last_output["logs"]，这里取尾部 30 条供前端展示进度活动流。
        from subagent.models import SubAgentSession

        recent_logs: list[dict] = []
        session = await (
            SubAgentSession.objects.filter(
                task_type=SubAgentSession.TaskType.REPO_SUMMARY,
                last_output__repository_id=str(repository.id),
            )
            .order_by("-created_at")
            .afirst()
        )
        if session is not None:
            logs = (session.last_output or {}).get("logs")
            if isinstance(logs, list):
                recent_logs = logs[-30:]

        tree = repository.ai_summary_tree or []
        return Response(
            {
                "status": repository.ai_summary_status,
                "progress": None,
                "summary": repository.ai_summary,
                "generated_at": repository.ai_summary_generated_at,
                "error": repository.ai_summary_error or None,
                "has_tree": bool(tree),
                "is_monorepo": repository.is_monorepo,
                "tree_node_count": _count_nodes(tree),
                "recent_logs": recent_logs,
            }
        )

    @action(detail=True, methods=["post"], url_path="generate-webhook-secret")
    async def generate_webhook_secret(self, request, pk=None):
        """POST /api/repositories/{id}/generate-webhook-secret/

        生成随机 webhook secret 并保存到仓库。
        """
        repository = await self.aget_object()
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

        existing_credential = await GitCredential.objects.filter(repository=repository).afirst()

        if existing_credential:
            existing_credential.auth_type = AuthType.ACCESS_TOKEN
            existing_credential.encrypted_token = encrypt_value(token)
            existing_credential.git_user_name = git_user_name
            existing_credential.git_user_email = git_user_email
            await existing_credential.asave()
            # 审计：per-repo Git 凭证更新（token 密文绝不入载荷）
            await AuditService.aemit(
                action=taxonomy.ACTION_CREDENTIAL_UPDATED,
                actor=request.user,
                target_type="git_credential",
                target_id=repository.id,
                target_repr=repository.name,
                after={"provided": True, "git_user_name": git_user_name},
                source="api",
            )
            return Response(GitCredentialSerializer(existing_credential).data)
        else:
            credential = await GitCredential.objects.acreate(
                repository=repository,
                auth_type=AuthType.ACCESS_TOKEN,
                encrypted_token=encrypt_value(token),
                git_user_name=git_user_name,
                git_user_email=git_user_email,
            )
            # 审计：per-repo Git 凭证创建
            await AuditService.aemit(
                action=taxonomy.ACTION_CREDENTIAL_CREATED,
                actor=request.user,
                target_type="git_credential",
                target_id=repository.id,
                target_repr=repository.name,
                after={"provided": True, "git_user_name": git_user_name},
                source="api",
            )
            return Response(
                GitCredentialSerializer(credential).data, status=status.HTTP_201_CREATED
            )


class RepositorySpacesView(APIView):
    """仓库侧的「关联空间」管理。

    GET  /repositories/{id}/spaces/  -> [{id, name}]
    PUT  /repositories/{id}/spaces/  body: {"space_ids": [...]}（全量设置，至少一个）
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request, repository_id):
        repository = await aget_object_or_404(Repository, id=repository_id, is_deleted=False)
        spaces = [{"id": str(p.id), "name": p.name} async for p in repository.projects.all()]
        return Response(spaces)

    async def put(self, request, repository_id):
        repository = await aget_object_or_404(Repository, id=repository_id, is_deleted=False)

        space_ids = request.data.get("space_ids")
        if not isinstance(space_ids, list) or not space_ids:
            return Response(
                {"space_ids": ["仓库必须至少关联一个空间"]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        space_ids = [str(sid) for sid in space_ids]

        from projects.models import Project, ProjectRepository

        spaces = [s async for s in Project.objects.filter(id__in=space_ids)]
        if len(spaces) != len(set(space_ids)):
            return Response(
                {"space_ids": ["部分空间不存在"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        target_ids = {str(s.id) for s in spaces}
        existing = [
            link
            async for link in ProjectRepository.objects.filter(
                repository=repository
            ).select_related("project")
        ]
        existing_ids = {str(link.project_id) for link in existing}

        # 删除不再关联的，新增缺失的（保留已存在关联的 permission_level）
        to_remove = [link.pk for link in existing if str(link.project_id) not in target_ids]
        if to_remove:
            await ProjectRepository.objects.filter(pk__in=to_remove).adelete()
        to_add = [s for s in spaces if str(s.id) not in existing_ids]
        if to_add:
            await ProjectRepository.objects.abulk_create(
                [ProjectRepository(project=space, repository=repository) for space in to_add]
            )

        spaces_sorted = sorted(spaces, key=lambda s: s.name)
        return Response([{"id": str(s.id), "name": s.name} for s in spaces_sorted])


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

            # 既有仓库：经统一解析器取 token（per-repo 优先 → host 实例池 fallback，D-02）
            token = await aresolve_git_token(repository)
            if not token:
                return Response(
                    {"success": False, "error": "仓库未配置访问凭证"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
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

        # SSH 地址自动转换为 HTTPS（任务容器内没有 ssh，token 认证也只支持 HTTPS）
        from .serializers import ssh_git_url_to_https

        git_url = ssh_git_url_to_https(git_url)
        if not is_https_git_url(git_url):
            return Response(
                {
                    "success": False,
                    "error": "当前仅支持 HTTPS 仓库 URL（SSH 地址会自动转换为 HTTPS）。",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Build authenticated URL（GitLab project token 必须把 token 放在密码位置）
        auth_url = build_authenticated_git_url(git_url, token)

        # Test connection using git ls-remote（--symref 顺带探测 HEAD 所在分支）
        try:
            cmd = ["git", "ls-remote", "--symref", auth_url, "HEAD", "refs/heads/*"]
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
                branches, head_branch = _parse_ls_remote_refs(result.stdout)

                # best-effort 分支活跃度（失败时排序退化为字典序）
                activity = await _probe_branch_activity(auth_url, proxy_url)
                branches = _sort_branches(branches, head_branch, activity)

                # 推荐分支：HEAD 所在分支优先，退化到 main/master/develop
                recommended_branch = head_branch
                if recommended_branch is None:
                    for candidate in ("main", "master", "develop"):
                        if candidate in branches:
                            recommended_branch = candidate
                            break

                # 已有仓库测连时顺手缓存 HEAD 分支，供详情页展示 HEAD 标签
                if repository_id and head_branch:
                    await Repository.objects.filter(id=repository_id).aupdate(
                        remote_head_branch=head_branch,
                    )

                return Response(
                    {
                        "success": True,
                        "message": "连接成功",
                        "branches": branches,
                        "head_branch": head_branch,
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
        repo_manager = RepoCacheManager()
        deps_manager = DependencyCacheManager()

        repo_volumes = await repo_manager.list_cache_volumes()
        deps_volumes = await deps_manager.list_deps_volumes()

        return Response(
            {
                "repo_caches": repo_volumes,
                "deps_caches": deps_volumes,
            }
        )

    async def delete(self, request):
        """清理缓存卷。

        DELETE /api/repositories/cache/?older_than_days=7&dry_run=true
        """
        older_than_days = int(request.query_params.get("older_than_days", 7))
        dry_run = request.query_params.get("dry_run", "false").lower() == "true"

        pruned = await prune_cache_volumes(older_than_days, dry_run)
        return Response(
            {
                "pruned": pruned,
                "dry_run": dry_run,
            }
        )


class RepositoryExclusionRulesView(APIView):
    """per-repo 排除规则列表 / 新增（Plan 22-05，EXCL-01）。

    GET  /api/repositories/{id}/exclusions/
        -> {global_defaults: [{pattern, rule_type, source:"global", enabled, override_id}],
            rules: [per-repo RepoExclusionRule 序列化]}
        global_defaults 来自 services.exclusion（builtin ∪ 全局设置），每条 ``enabled``
        反映是否被 per-repo override 关闭；``override_id`` 指向关闭它的 override 行（用于再次启用）。

    POST /api/repositories/{id}/exclusions/   body: {pattern, rule_type, enabled?, source?}
        新增 per-repo 规则；rule_type=regex 时 re.compile 校验，非法 → 400（fail-loud，不写库）。
        「关闭某条全局默认」= POST source="global" + enabled=False 的 override 行。
        写成功后 invalidate_matcher_cache 使所有读取面即时读到新规则（T-22-18）。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request, repository_id):
        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        repo_rules = [
            r
            async for r in RepoExclusionRule.objects.filter(repository_id=repository_id).order_by(
                "created_at"
            )
        ]
        # per-repo 关闭的全局默认 override：(rule_type, pattern) -> 该 override 行
        disabled_overrides = {
            (r.rule_type, r.pattern): r
            for r in repo_rules
            if r.source == RepoExclusionRule.Source.GLOBAL and not r.enabled
        }

        global_specs = await sync_to_async(get_global_default_specs)()
        global_defaults = []
        for spec in global_specs:
            override = disabled_overrides.get((spec.rule_type, spec.pattern))
            global_defaults.append(
                {
                    "pattern": spec.pattern,
                    "rule_type": spec.rule_type,
                    "source": "global",
                    "enabled": override is None,
                    "override_id": str(override.id) if override else None,
                }
            )

        # rules 仅列 per-repo 实际规则（user / ai_suggested）；global override 标记不展示在此
        user_rules = [r for r in repo_rules if r.source != RepoExclusionRule.Source.GLOBAL]
        rules = await sync_to_async(
            lambda: RepoExclusionRuleSerializer(user_rules, many=True).data
        )()

        return Response({"global_defaults": global_defaults, "rules": rules})

    async def post(self, request, repository_id):
        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        serializer = RepoExclusionRuleSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        data = dict(serializer.validated_data)

        try:
            rule = await RepoExclusionRule.objects.acreate(repository_id=repository_id, **data)
        except IntegrityError:
            return Response(
                {"detail": "该排除规则已存在"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 规则变更后失效匹配器缓存，使各读取面即时读到新规则（T-22-18）
        invalidate_matcher_cache(str(repository_id))

        # 审计：排除规则新增
        await AuditService.aemit(
            action=taxonomy.ACTION_EXCLUSION_RULE_CHANGED,
            actor=request.user,
            target_type="repo_exclusion_rule",
            target_id=rule.id,
            target_repr=f"{repository_id}:{rule.pattern}",
            after={
                "pattern": rule.pattern,
                "rule_type": rule.rule_type,
                "enabled": rule.enabled,
                "source": rule.source,
            },
            metadata={"op": "created"},
            source="api",
        )

        out = await sync_to_async(lambda: RepoExclusionRuleSerializer(rule).data)()
        return Response(out, status=status.HTTP_201_CREATED)


class RepositoryExclusionRuleDetailView(APIView):
    """删除单条 per-repo 排除规则（Plan 22-05）。

    DELETE /api/repositories/{id}/exclusions/{rule_id}/
        删除该 per-repo 规则（含「关闭全局默认」的 override 行——删除即再次启用该全局默认）。
        仅能删除属于本仓库的规则（越仓 → 404，T-22-19）。写成功后失效匹配器缓存。
    """

    permission_classes = [IsAuthenticated]

    async def delete(self, request, repository_id, rule_id):
        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        rule = await RepoExclusionRule.objects.filter(
            id=rule_id, repository_id=repository_id
        ).afirst()
        if rule is None:
            return Response({"detail": "排除规则不存在"}, status=status.HTTP_404_NOT_FOUND)

        rule_pk = rule.id
        snapshot = {"pattern": rule.pattern, "rule_type": rule.rule_type}
        await rule.adelete()
        invalidate_matcher_cache(str(repository_id))

        # 审计：排除规则删除（删前快照）
        await AuditService.aemit(
            action=taxonomy.ACTION_EXCLUSION_RULE_CHANGED,
            actor=request.user,
            target_type="repo_exclusion_rule",
            target_id=rule_pk,
            target_repr=f"{repository_id}:{snapshot['pattern']}",
            before=snapshot,
            metadata={"op": "deleted"},
            source="api",
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class GitInstanceCredentialsView(APIView):
    """实例级 Git 凭证列表 / 新建（Plan 26-04，REPO-01，D-01/D-04）。

    GET  /api/repositories/git-instance-credentials/
        -> [{id, host, provider, label, has_token, created_at, updated_at}]
        响应统一经只读序列化器，**绝不**含明文 token（威胁 T-26-13）。

    POST /api/repositories/git-instance-credentials/
        body: {host, access_token, provider?, label?}
        host 归一小写、access_token 经 encrypt_value 加密存 encrypted_token
        （威胁 T-26-14）；host 重复 → 400 中文报错。

    权限：仅 ``IsSuperUser`` 可访问（威胁 T-26-16）。日志绝不含 token（威胁 T-26-17）。
    """

    permission_classes = [IsSuperUser]

    async def get(self, request):
        creds = [c async for c in GitInstanceCredential.objects.all().order_by("host")]
        data = await sync_to_async(lambda: GitInstanceCredentialSerializer(creds, many=True).data)()
        return Response(data)

    async def post(self, request):
        serializer = GitInstanceCredentialWriteSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        data = dict(serializer.validated_data)

        host = data.get("host")
        access_token = data.get("access_token")
        if not host:
            return Response(
                {"host": ["Git 实例 host 不能为空"]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not access_token:
            return Response(
                {"access_token": ["创建实例凭证时 access_token 必填"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if await GitInstanceCredential.objects.filter(host=host).aexists():
            return Response(
                {"host": [f"实例 '{host}' 的凭证已存在，请编辑既有凭证"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            credential = await GitInstanceCredential.objects.acreate(
                host=host,
                provider=data.get("provider") or GitPlatform.GITLAB,
                label=data.get("label", ""),
                encrypted_token=encrypt_value(access_token),
            )
        except IntegrityError:
            return Response(
                {"host": [f"实例 '{host}' 的凭证已存在，请编辑既有凭证"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 日志仅记 host / has_token 布尔，绝不含 token 明文（威胁 T-26-17）。
        logger.info(
            "git_instance_credential_created",
            host=host,
            provider=credential.provider,
            has_token=True,
        )
        # 审计：Git 实例凭证创建（token 密文绝不入载荷，仅记 provided 布尔）
        await AuditService.aemit(
            action=taxonomy.ACTION_CREDENTIAL_CREATED,
            actor=request.user,
            target_type="git_instance_credential",
            target_id=credential.id,
            target_repr=host,
            after={"host": host, "provider": credential.provider, "provided": True},
            source="api",
        )
        out = await sync_to_async(lambda: GitInstanceCredentialSerializer(credential).data)()
        return Response(out, status=status.HTTP_201_CREATED)


class GitInstanceCredentialDetailView(APIView):
    """实例级 Git 凭证详情 / 更新 / 删除（Plan 26-04，REPO-01）。

    GET    /api/repositories/git-instance-credentials/{credential_id}/  -> 只读序列化
    PATCH  /  PUT  同 URL：更新 host/provider/label；``access_token`` 留空表示
           **不修改既有 token**，非空则 encrypt_value 加密覆盖（威胁 T-26-14/15）。
    DELETE /  同 URL：删除该实例凭证。

    权限：仅 ``IsSuperUser`` 可访问（威胁 T-26-16）。响应绝不含明文 token。
    """

    permission_classes = [IsSuperUser]

    async def get(self, request, credential_id):
        credential = await GitInstanceCredential.objects.filter(id=credential_id).afirst()
        if credential is None:
            return Response({"detail": "实例凭证不存在"}, status=status.HTTP_404_NOT_FOUND)
        out = await sync_to_async(lambda: GitInstanceCredentialSerializer(credential).data)()
        return Response(out)

    async def put(self, request, credential_id):
        return await self._update(request, credential_id)

    async def patch(self, request, credential_id):
        return await self._update(request, credential_id)

    async def _update(self, request, credential_id):
        credential = await GitInstanceCredential.objects.filter(id=credential_id).afirst()
        if credential is None:
            return Response({"detail": "实例凭证不存在"}, status=status.HTTP_404_NOT_FOUND)

        serializer = GitInstanceCredentialWriteSerializer(data=request.data, partial=True)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        data = dict(serializer.validated_data)

        new_host = data.get("host")
        if new_host and new_host != credential.host:
            if await GitInstanceCredential.objects.filter(host=new_host).aexists():
                return Response(
                    {"host": [f"实例 '{new_host}' 的凭证已存在，请编辑既有凭证"]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            credential.host = new_host
        if "provider" in data and data.get("provider"):
            credential.provider = data["provider"]
        if "label" in data:
            credential.label = data.get("label", "")

        token_changed = False
        access_token = data.get("access_token")
        if access_token:
            # 仅非空 token 才覆盖；留空保留既有 token（威胁 T-26-15）。
            credential.encrypted_token = encrypt_value(access_token)
            token_changed = True

        try:
            await credential.asave()
        except IntegrityError:
            return Response(
                {"host": [f"实例 '{credential.host}' 的凭证已存在，请编辑既有凭证"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info(
            "git_instance_credential_updated",
            host=credential.host,
            provider=credential.provider,
            token_changed=token_changed,
        )
        # 审计：Git 实例凭证更新（token_changed 标识是否换密钥，密文不入载荷）
        await AuditService.aemit(
            action=taxonomy.ACTION_CREDENTIAL_UPDATED,
            actor=request.user,
            target_type="git_instance_credential",
            target_id=credential.id,
            target_repr=credential.host,
            after={
                "host": credential.host,
                "provider": credential.provider,
                # 键名避开脱敏关键词（"token" 会被入口脱敏）：用 rotated 表「是否换密钥」
                "rotated": token_changed,
            },
            source="api",
        )
        out = await sync_to_async(lambda: GitInstanceCredentialSerializer(credential).data)()
        return Response(out)

    async def delete(self, request, credential_id):
        credential = await GitInstanceCredential.objects.filter(id=credential_id).afirst()
        if credential is None:
            return Response({"detail": "实例凭证不存在"}, status=status.HTTP_404_NOT_FOUND)
        host = credential.host
        provider = credential.provider
        cred_pk = credential.id
        await credential.adelete()
        logger.info("git_instance_credential_deleted", host=host)
        # 审计：Git 实例凭证删除（删前快照）
        await AuditService.aemit(
            action=taxonomy.ACTION_CREDENTIAL_DELETED,
            actor=request.user,
            target_type="git_instance_credential",
            target_id=cred_pk,
            target_repr=host,
            before={"host": host, "provider": provider},
            source="api",
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# 严重级别排序权重：real_secret 优先 > likely_sensitive > config_review（DOMAIN §9 D-02）。
_SENSITIVE_SEVERITY_ORDER = {
    SensitiveFileSuggestion.Severity.REAL_SECRET: 0,
    SensitiveFileSuggestion.Severity.LIKELY_SENSITIVE: 1,
    SensitiveFileSuggestion.Severity.CONFIG_REVIEW: 2,
}


class RepositorySensitiveSuggestionsView(APIView):
    """列出某仓库的 AI 敏感文件建议（Plan 24-03，EXCL-03）。

    GET /api/repositories/{id}/sensitive-suggestions/?status=pending|accepted|dismissed|all
        -> {suggestions: [SensitiveFileSuggestionSerializer ...]}
        默认仅返回 ``status=pending`` 的建议；``?status=all`` 返回全部。
        排序：severity real_secret > likely_sensitive > config_review，同级按
        detected_at desc（最新优先）。仅以 repository_id 限定查询，不泄漏越仓建议
        （T-24-09）。建议为只读视图，状态变更走专用 action 端点（T-24-10）。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request, repository_id):
        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        status_filter = request.query_params.get("status", "pending")
        qs = SensitiveFileSuggestion.objects.filter(repository_id=repository_id)
        if status_filter != "all":
            qs = qs.filter(status=status_filter)

        rows = [row async for row in qs]
        # severity 优先 + detected_at desc：Python 侧稳定排序（建议规模有限，无需 DB 注解）。
        rows.sort(
            key=lambda r: (
                _SENSITIVE_SEVERITY_ORDER.get(r.severity, 99),
                -(r.detected_at.timestamp() if r.detected_at else 0),
            )
        )

        suggestions = await sync_to_async(
            lambda: SensitiveFileSuggestionSerializer(rows, many=True).data
        )()
        return Response({"suggestions": suggestions})


class RepositorySensitiveSuggestionActionView(APIView):
    """接受 / 忽略单条敏感文件建议（Plan 24-03，EXCL-03，D-03）。

    POST /api/repositories/{id}/sensitive-suggestions/{suggestion_id}/action/
        body: {action: "accept" | "dismiss"}

    - ``accept``：幂等创建 ``RepoExclusionRule(source=ai_suggested, rule_type=glob,
      pattern=suggestion.path)`` 并把建议标 ``accepted``，随后 ``invalidate_matcher_cache``
      使各读取面即时生效。**绝不**在此路径触发任何删除 / 清理——已索引/派生数据的删除
      仍由既有 Phase 23 reconcile/cleanup 由用户显式发起（NEVER silent-delete，T-24-10）。
      重复 accept 不报错（``aget_or_create`` 幂等，T-24-12）。
    - ``dismiss``：仅置建议 ``status=dismissed``，不建规则、不删数据。
    - 越仓 / 不存在的 suggestion_id → 404（不泄漏存在性，T-24-09）；非法 action → 400。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request, repository_id, suggestion_id):
        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        action_name = (request.data.get("action") or "").strip().lower()
        if action_name not in ("accept", "dismiss"):
            return Response(
                {"detail": "action 必须为 accept 或 dismiss"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        suggestion = await SensitiveFileSuggestion.objects.filter(
            id=suggestion_id, repository_id=repository_id
        ).afirst()
        if suggestion is None:
            return Response({"detail": "敏感文件建议不存在"}, status=status.HTTP_404_NOT_FOUND)

        if action_name == "dismiss":
            suggestion.status = SensitiveFileSuggestion.Status.DISMISSED
            await suggestion.asave(update_fields=["status", "updated_at"])
            out = await sync_to_async(lambda: SensitiveFileSuggestionSerializer(suggestion).data)()
            return Response({"suggestion": out})

        # accept：幂等建 ai_suggested 排除规则（绝不删数据）
        rule, _created = await RepoExclusionRule.objects.aget_or_create(
            repository_id=repository_id,
            rule_type=RepoExclusionRule.RuleType.GLOB,
            pattern=suggestion.path,
            source=RepoExclusionRule.Source.AI_SUGGESTED,
            defaults={"enabled": True},
        )
        suggestion.status = SensitiveFileSuggestion.Status.ACCEPTED
        await suggestion.asave(update_fields=["status", "updated_at"])

        # 规则变更后失效匹配器缓存，使各读取面即时读到新规则（T-22-18）
        invalidate_matcher_cache(str(repository_id))

        suggestion_out = await sync_to_async(
            lambda: SensitiveFileSuggestionSerializer(suggestion).data
        )()
        rule_out = await sync_to_async(lambda: RepoExclusionRuleSerializer(rule).data)()
        return Response(
            {
                "suggestion": suggestion_out,
                "rule": rule_out,
                # 删除已索引/派生数据由既有 reconcile/cleanup 显式发起，前端可据此引导，
                # 但此 accept 路径**不**自动派发任何清理（NEVER silent-delete）。
                "cleanup_available": True,
            }
        )


class RepositoryReconcileView(APIView):
    """对账（GET）/ 派发清理（POST）（Plan 23-02，EXCL-04 / EXCL-06）。

    GET  /api/repositories/{id}/reconcile/
        -> {indexed_count, excluded_paths, match_count, suggested_mode, degraded, error}
        列出「已索引但现命中排除」的差异文件；匹配器构造失败时 ``degraded=true``（W3，
        不谎报「已一致」假干净）。

    POST /api/repositories/{id}/reconcile/   body: {mode?: "normal"|"sensitive"}
        先建一条 ``CleanupRun(status=running)`` 拿 ``run_id``，再经 ``run_in_background``
        派发后台 ``run_cleanup``（D-04，避免大仓清理阻塞请求线程，T-23-08），立即返回
        202 + {mode, match_count, dispatched, run_id}。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request, repository_id):
        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        report = await compute_reconciliation(str(repository_id))
        data = await sync_to_async(lambda: ReconcileReportSerializer(report).data)()
        return Response(data)

    async def post(self, request, repository_id):
        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        serializer = CleanupRequestSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        mode = serializer.validated_data["mode"]

        # 命中数（供客户端即时展示将清理多少文件）；degraded 时为 0。
        report = await compute_reconciliation(str(repository_id))

        # BL-01：对账诊断不可信（匹配器构造失败）时后端必须 fail-closed 拒绝派发——
        # 不建 running 行、不派发后台清理，绝不依赖前端 TOCTOU 禁用（GET 与本次 POST
        # 之间匹配器构造状态可能漂移）。返回 409 让前端显式展示 degraded + error。
        if report.degraded:
            return Response(
                {
                    "detail": "对账诊断不可信（排除匹配器构造失败），已拒绝派发清理（fail-closed）",
                    "degraded": True,
                    "error": report.error,
                },
                status=status.HTTP_409_CONFLICT,
            )

        # 先落 running 行拿 run_id，后台 run_cleanup 据此更新（结果可经状态端点回流，W1/W2）
        run = await CleanupRun.objects.acreate(
            repository_id=repository_id,
            mode=mode,
            status=CleanupRun.Status.RUNNING,
        )
        run_id = str(run.id)
        repo_id = str(repository_id)

        run_in_background(
            lambda: run_cleanup(repo_id, mode, cleanup_run_id=run_id),
            name=f"cleanup:{repo_id}:{run_id}",
        )

        return Response(
            {
                "mode": mode,
                "match_count": report.match_count,
                "dispatched": True,
                "run_id": run_id,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class RepositoryCleanupStatusView(APIView):
    """最近一次清理运行状态（Plan 23-02，W1/W2）。

    GET /api/repositories/{id}/reconcile/status/
        -> 最近一条 ``CleanupRun`` 序列化（含 sensitive 的 unscrubbed/caveat 原样透传，
           使后台敏感清理「哪些面未清」如实回流前端，不靠静态文案）；无记录 → {status: "none"}。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request, repository_id):
        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        run = (
            await CleanupRun.objects.filter(repository_id=repository_id)
            .order_by("-started_at")
            .afirst()
        )
        if run is None:
            return Response({"status": "none"})

        data = await sync_to_async(lambda: CleanupRunSerializer(run).data)()
        return Response(data)
