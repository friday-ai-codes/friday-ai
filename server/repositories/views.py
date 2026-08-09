"""Repositories views."""

import os
import secrets
import subprocess
import tempfile
from typing import Any
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
from permissions.services import PermissionService
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
    from durable.concurrency import aindex_lock

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
        # CONC-01：索引槽位锁池（同仓恒定同槽串行，至多 N 仓并发）
        lock=await aindex_lock(str(repo_id)),
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


async def _acreate_repository_core(data: dict, *, actor: Any) -> Repository:
    """建仓核心（单仓 acreate 与批量建仓 BATCH-02 共用）。

    入参为 RepositoryCreateSerializer 已校验的 validated_data（dict 副本）。
    校验失败抛 ``serializers.ValidationError``（由调用方/DRF 渲染 400）；成功返回
    创建的 Repository。包含：access_token 非空校验 → 关联空间存在校验 →
    default/base 分支推断与校验 → 建仓 + 空间关联 + per-repo Git 凭证 + 审计 +
    后台自动 AI 描述派发。
    """
    from projects.models import Space, SpaceRepository
    from repositories.models import GitInstanceCredential
    from services.git_credentials import _extract_git_host

    access_token = data.pop("access_token", "") or ""
    git_user_name = data.pop("git_user_name", "Friday Codes AI Agent")
    git_user_email = data.pop("git_user_email", "ai@friday.codes")
    # #9：space_ids 可选——允许先建仓、后绑定空间（孤儿仓库仅超管可见/管理）
    space_ids = [str(sid) for sid in (data.pop("space_ids", None) or [])]
    instance_credential_id = data.pop("git_instance_credential_id", None)

    # TOKEN-02：token 可选。无 token 时必须可由「密钥提供方」FK 或 host 自动匹配实例池解析，
    # 否则 fail-loud（绝不建无凭证、无法 clone 的仓库）。
    instance_credential = None
    if instance_credential_id:
        instance_credential = await GitInstanceCredential.objects.filter(
            id=instance_credential_id
        ).afirst()
        if instance_credential is None:
            raise serializers.ValidationError(
                {"git_instance_credential_id": ["所选密钥提供方不存在"]}
            )

    # effective_token：用于建仓期 base_branch 校验（运行期 token 由 aresolve_git_token 解析）。
    effective_token = access_token
    has_own_token = bool(access_token.strip())
    if not has_own_token:
        from common.encryption import decrypt_value

        # 无自有 token：FK 优先，其次 host 自动匹配实例池
        resolved_instance = instance_credential
        if resolved_instance is None:
            host = _extract_git_host(data.get("git_url"))
            if host:
                resolved_instance = await GitInstanceCredential.objects.filter(host=host).afirst()
        if resolved_instance is None:
            raise serializers.ValidationError(
                {
                    "access_token": [
                        "未填写 Access Token 且无可用密钥提供方（实例凭证）：请填写 token 或选择/配置密钥提供方"
                    ]
                }
            )
        # 绑定 FK（仅在用户显式选择密钥提供方时写 FK；host 自动匹配场景运行期按 host 命中）
        if instance_credential is not None:
            data["git_instance_credential_id"] = str(instance_credential.id)
        if resolved_instance.encrypted_token:
            effective_token = decrypt_value(resolved_instance.encrypted_token)

    spaces = [s async for s in Space.objects.filter(id__in=space_ids)]
    if len(spaces) != len(set(space_ids)):
        raise serializers.ValidationError({"space_ids": ["部分空间不存在"]})

    # HEAD 分支由前端从 test-connection 结果带入；未显式选默认分支时自动采用 HEAD 分支
    head_branch = data.get("remote_head_branch")
    if head_branch and not data.get("default_branch"):
        data["default_branch"] = head_branch

    base_branch = data.get("base_branch")
    if base_branch and "default_branch" not in data:
        data["default_branch"] = base_branch
    if base_branch:
        is_valid = await _validate_base_branch(
            git_url=data["git_url"],
            token=effective_token,
            base_branch=base_branch,
            proxy_url=data.get("proxy_url"),
        )
        if not is_valid:
            raise serializers.ValidationError(
                {"base_branch": [f"所选分支 '{base_branch}' 在远端仓库中不存在"]}
            )

    repository = await Repository.objects.acreate(**data)

    await SpaceRepository.objects.abulk_create(
        [SpaceRepository(space=space, repository=repository) for space in spaces]
    )

    # TOKEN-02：仅在用户填写自有 token 时建 per-repo GitCredential；否则由密钥提供方
    # FK / host 实例池在运行期解析（不建空 token 凭证）。
    if has_own_token:
        await GitCredential.objects.acreate(
            repository=repository,
            auth_type=AuthType.ACCESS_TOKEN,
            encrypted_token=encrypt_value(access_token),
            git_user_name=git_user_name,
            git_user_email=git_user_email,
        )

    await AuditService.aemit(
        action=taxonomy.ACTION_CREDENTIAL_CREATED,
        actor=actor,
        target_type="git_credential",
        target_id=repository.id,
        target_repr=repository.name,
        after={"provided": has_own_token, "git_user_name": git_user_name},
        source="api",
    )

    # 建仓即自动入队「代码索引(RAG+条件图谱) + AI 描述」（best-effort，失败不阻塞）。
    # 图谱仅当 ENABLE_CODEGRAPH ∧ auto_build_graph_enabled 时由 indexer auto_after_index
    # 内联触发——禁止在此额外入队独立图谱任务（避免双跑）。
    import time as _time

    from common.logging import redact_secrets_in_text
    from repositories.index_enqueue import enqueue_repo_index
    from repositories.summary_service import enqueue_repo_summary

    actor_id = str(getattr(actor, "id", "") or "") or None
    pipeline_started = _time.monotonic()
    index_job = None
    summary_job = None
    try:
        index_job = await enqueue_repo_index(
            str(repository.id), initiated_by_user_id=actor_id, trigger="create"
        )
        if repository.ai_summary_status not in (
            AISummaryStatus.PENDING,
            AISummaryStatus.RUNNING,
        ):
            summary_job = await enqueue_repo_summary(
                str(repository.id), initiated_by_user_id=actor_id
            )
        # 入队可能已把 DB 置为 INDEXING；刷新实例，避免 201 序列化仍报 not_indexed。
        await repository.arefresh_from_db()
        logger.info(
            "repo_create_pipeline_enqueued",
            category="caller",
            component="repositories",
            repository_id=str(repository.id),
            initiated_by_user_id=actor_id or "system",
            index_job=bool(index_job),
            summary_job=bool(summary_job),
            duration_ms=round((_time.monotonic() - pipeline_started) * 1000, 2),
        )
    except Exception as exc:  # noqa: BLE001 — 入队绝不回滚已创建的仓库
        logger.warning(
            "repo_create_pipeline_enqueue_failed",
            category="caller",
            component="repositories",
            repository_id=str(repository.id),
            initiated_by_user_id=actor_id or "system",
            error=redact_secrets_in_text(str(exc)),
            duration_ms=round((_time.monotonic() - pipeline_started) * 1000, 2),
        )
    return repository


class RepositoryViewSet(ModelViewSet):
    """ViewSet for Repository CRUD operations."""

    permission_classes = [IsAuthenticated]
    serializer_class = RepositorySerializer

    def get_queryset(self):
        """仅返回当前用户可见的仓库（并排除软删除）。

        #9 / #11 可见性口径：超管可见全部；普通用户仅可见其所属空间所关联的仓库。
        孤儿仓库（未关联任何空间）因而仅超管可见——与 ``can_admin_repository`` 的孤儿
        规则、以及 ``serializers.py`` / 本文件 #9 注释中「孤儿仓库仅超管可见/管理」的
        既有约定一致。此前只收口了「管理」，可见性未做隔离，任何登录用户都能列出全库
        仓库（含他人空间的仓库名与 git_url）。
        """
        qs = (
            Repository.objects.filter(is_deleted=False)
            .select_related("credential")
            .prefetch_related("spaces")
        )
        user = self.request.user
        if getattr(user, "is_superuser", False):
            return qs
        # 同一仓库可关联多个空间，用户又可能同时是多个空间成员 → join 会放大行数，必须 distinct
        return qs.filter(spaces__memberships__user=user).distinct()

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
        # 单仓创建复用与批量建仓（BATCH-02）同一核心 helper。helper 校验失败抛
        # ValidationError —— 显式 catch 后以 Response 返回 detail，复刻重构前
        # explicit 400 响应体形状（如 {"base_branch": [...]}），与 adrf 异步异常
        # 渲染差异脱钩，保证既有契约零回归。
        try:
            repository = await _acreate_repository_core(
                dict(serializer.validated_data), actor=self.request.user
            )
        except serializers.ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        # KEEP: RepositorySerializer.get_has_credential 触发 credential FK 访问
        resp_data = await sync_to_async(lambda: RepositorySerializer(repository).data)()
        return Response(resp_data, status=status.HTTP_201_CREATED)

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
        if not await sync_to_async(PermissionService.can_admin_repository)(
            request.user, str(repository.id)
        ):
            return Response(
                {"detail": "仅空间管理员可操作此仓库的建立知识"},
                status=status.HTTP_403_FORBIDDEN,
            )
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

    @action(detail=True, methods=["post"], url_path="generate-summary/cancel")
    async def cancel_summary(self, request, pk=None):
        """POST /api/repositories/{id}/generate-summary/cancel/

        终止仓库"建立知识"任务（标记在途 session 为 cancelled，状态回退 NOT_STARTED）。
        """
        repository = await self.aget_object()
        if not await sync_to_async(PermissionService.can_admin_repository)(
            request.user, str(repository.id)
        ):
            return Response(
                {"detail": "仅空间管理员可操作此仓库的建立知识"},
                status=status.HTTP_403_FORBIDDEN,
            )
        from .summary_service import cancel_repo_summary

        cancelled = await cancel_repo_summary(
            str(repository.id),
            initiated_by_user_id=str(getattr(request.user, "id", "")) or None,
        )
        return Response({"cancelled": cancelled, "status": AISummaryStatus.NOT_STARTED})

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

    @action(detail=True, methods=["post"], url_path="setup-webhook")
    async def setup_webhook(self, request, pk=None):
        """POST /api/repositories/{id}/setup-webhook/

        一键在 Git 平台侧自动创建/更新 push webhook（当前仅 GitLab）。

        流程：无 secret 先生成 → aresolve_git_token 解析凭证（per-repo →
        实例凭证池）→ 用「站点 Host」设置（site_host → 请求 Host →
        FRIDAY_BASE_URL）拼回调 URL → GitLab project hooks 幂等创建/更新
        （按 URL 匹配，branch filter 默认 default_branch）。成功后顺手启用
        auto_index_enabled（接收端对未启用仓库 fail-closed 拒绝）。

        需要 token 对应账号在项目中为 Maintainer 及以上且 PAT 具有 api scope，
        权限/网络类失败翻译为中文提示返回 400。
        """
        import time as _time

        from django.conf import settings as dj_settings

        from common.logging import redact_secrets_in_text
        from identity.services import aresolve_site_base_url
        from services.git_platform import (
            GitLabClient,
            extract_gitlab_url,
            extract_project_path,
        )

        started = _time.monotonic()
        repository = await self.aget_object()

        if repository.git_platform != GitPlatform.GITLAB:
            return Response(
                {"detail": "自动配置 Webhook 目前仅支持 GitLab 仓库，其他平台请按面板指引手动配置"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token = await aresolve_git_token(repository)
        if not token:
            return Response(
                {"detail": "仓库未配置 Git 凭证（Access Token 或密钥提供方），无法调用 GitLab API"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 站点外部地址：site_host 设置 → 当前请求 Host → FRIDAY_BASE_URL
        base_url = await aresolve_site_base_url(
            getattr(dj_settings, "FRIDAY_BASE_URL", ""), request=request
        )
        if not base_url:
            return Response(
                {"detail": "无法确定站点外部地址，请在系统设置中配置「站点 Host」"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        webhook_url = f"{base_url.rstrip('/')}/api/repositories/{repository.id}/webhooks/push/"

        # 无 secret 先生成（接收端用它验 X-Gitlab-Token）
        if not repository.webhook_secret:
            repository.webhook_secret = secrets.token_hex(32)
            await repository.asave(update_fields=["webhook_secret"])

        # branch filter 默认只订阅默认分支的 push（可通过 body.branch_filter 覆盖；
        # 显式传空串表示订阅所有分支）
        branch_filter = request.data.get("branch_filter")
        if branch_filter is None:
            branch_filter = repository.default_branch or ""

        logger.info(
            "repository_webhook_setup_started",
            repository_id=str(repository.id),
            branch_filter=branch_filter,
            category="caller",
            component="repositories",
        )

        try:
            client = GitLabClient(
                base_url=extract_gitlab_url(repository.git_url),
                token=token,
                project_path=extract_project_path(repository.git_url),
            )
            result = await client.ensure_push_webhook(
                url=webhook_url,
                secret=repository.webhook_secret,
                branch_filter=branch_filter,
            )
        except Exception as e:  # noqa: BLE001 — URL 解析等意外错误统一翻译返回
            logger.warning(
                "repository_webhook_setup_failed",
                repository_id=str(repository.id),
                error=redact_secrets_in_text(str(e)),
                duration_ms=int((_time.monotonic() - started) * 1000),
                category="caller",
                component="repositories",
            )
            return Response(
                {"detail": f"配置 Webhook 失败: {redact_secrets_in_text(str(e))}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        duration_ms = int((_time.monotonic() - started) * 1000)
        if not result.success:
            logger.warning(
                "repository_webhook_setup_failed",
                repository_id=str(repository.id),
                error=result.error,
                duration_ms=duration_ms,
                category="caller",
                component="repositories",
            )
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        # webhook 接收端对 auto_index_enabled=False 的仓库 fail-closed，
        # 一键配置的目的就是自动更新，顺手启用避免"配完没反应"。
        if not repository.auto_index_enabled:
            repository.auto_index_enabled = True
            await repository.asave(update_fields=["auto_index_enabled"])

        logger.info(
            "repository_webhook_setup_completed",
            repository_id=str(repository.id),
            action=result.action,
            hook_id=result.hook_id,
            branch_filter=branch_filter,
            duration_ms=duration_ms,
            category="caller",
            component="repositories",
        )
        return Response(
            {
                "action": result.action,
                "hook_id": result.hook_id,
                "webhook_url": webhook_url,
                "branch_filter": branch_filter,
                "auto_index_enabled": repository.auto_index_enabled,
            }
        )


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
    PUT  /repositories/{id}/spaces/  body: {"space_ids": [...]}（全量设置，可为空=解绑全部）
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request, repository_id):
        repository = await aget_object_or_404(Repository, id=repository_id, is_deleted=False)
        spaces = [{"id": str(p.id), "name": p.name} async for p in repository.spaces.all()]
        return Response(spaces)

    async def put(self, request, repository_id):
        repository = await aget_object_or_404(Repository, id=repository_id, is_deleted=False)

        # #9：允许置空（解绑全部空间），不再强制"至少一个空间"
        space_ids = request.data.get("space_ids")
        if not isinstance(space_ids, list):
            return Response(
                {"space_ids": ["space_ids 必须为列表"]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        space_ids = [str(sid) for sid in space_ids]

        from projects.models import Space, SpaceRepository

        spaces = [s async for s in Space.objects.filter(id__in=space_ids)]
        if len(spaces) != len(set(space_ids)):
            return Response(
                {"space_ids": ["部分空间不存在"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        target_ids = {str(s.id) for s in spaces}
        existing = [
            link
            async for link in SpaceRepository.objects.filter(repository=repository).select_related(
                "space"
            )
        ]
        existing_ids = {str(link.space_id) for link in existing}

        # 删除不再关联的，新增缺失的（保留已存在关联的 permission_level）
        to_remove = [link.pk for link in existing if str(link.space_id) not in target_ids]
        if to_remove:
            await SpaceRepository.objects.filter(pk__in=to_remove).adelete()
        to_add = [s for s in spaces if str(s.id) not in existing_ids]
        if to_add:
            await SpaceRepository.objects.abulk_create(
                [SpaceRepository(space=space, repository=repository) for space in to_add]
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
                # TOKEN-02：无自有 token → 按密钥提供方 FK / host 自动匹配实例池 fallback 校验
                from common.encryption import decrypt_value
                from repositories.models import GitInstanceCredential
                from services.git_credentials import _extract_git_host

                instance = None
                fk_id = request.data.get("git_instance_credential_id")
                if fk_id:
                    instance = await GitInstanceCredential.objects.filter(id=fk_id).afirst()
                if instance is None:
                    host = _extract_git_host(git_url)
                    if host:
                        instance = await GitInstanceCredential.objects.filter(host=host).afirst()
                if instance and instance.encrypted_token:
                    token = decrypt_value(instance.encrypted_token)
            if not token:
                return Response(
                    {
                        "success": False,
                        "error": "请提供 Access Token 或选择/配置密钥提供方（实例凭证）",
                    },
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

        # #11：敏感信息仅空间管理员/系统管理员可见
        if not await sync_to_async(PermissionService.can_admin_repository)(
            request.user, str(repository_id)
        ):
            return Response(
                {"detail": "仅空间管理员可查看敏感信息"},
                status=status.HTTP_403_FORBIDDEN,
            )

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
    - #11：与列表端点同权限——仅空间管理员/系统管理员可操作。本端点既变更索引范围
      （accept 会建 RepoExclusionRule），响应又回显建议的 path / reason 等敏感字段，
      授权强度必须与 RepositorySensitiveSuggestionsView 一致，否则列表侧的管控会被
      本端点旁路。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request, repository_id, suggestion_id):
        try:
            await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return Response({"detail": "仓库不存在"}, status=status.HTTP_404_NOT_FOUND)

        # #11：敏感信息仅空间管理员/系统管理员可操作（与列表端点同一守卫）
        if not await sync_to_async(PermissionService.can_admin_repository)(
            request.user, str(repository_id)
        ):
            return Response(
                {"detail": "仅空间管理员可操作敏感建议"},
                status=status.HTTP_403_FORBIDDEN,
            )

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


# 批量建仓单次上限（CSV 数百仓库；防一次请求过大）。
_MAX_BATCH_REPOSITORIES = 500


class RepositoryBatchCreateView(APIView):
    """批量建仓（BATCH-02）——接受仓库数组，逐项复用单仓建仓核心。

    POST /api/repositories/batch/  body: {"repositories": [ {<RepositoryCreateSerializer 字段>}, ... ]}
    前端 CSV 导入：解析 CSV → 数组 → 调本接口。逐项独立校验/创建，单项失败不影响其余，
    返回 created / failed（含 index/name/error），支持数百仓库导入。

    权限：仅系统管理员（批量建仓为平台级运维操作）。
    """

    permission_classes = [IsSuperUser]

    async def post(self, request, *args, **kwargs):
        items = request.data.get("repositories")
        if not isinstance(items, list) or not items:
            return Response(
                {"detail": "repositories 必须为非空数组"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(items) > _MAX_BATCH_REPOSITORIES:
            return Response(
                {"detail": f"单次最多导入 {_MAX_BATCH_REPOSITORIES} 个仓库"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created: list[dict[str, str]] = []
        failed: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            name = item.get("name", "") if isinstance(item, dict) else ""
            serializer = RepositoryCreateSerializer(data=item)
            if not await sync_to_async(serializer.is_valid)():
                failed.append({"index": idx, "name": name, "error": serializer.errors})
                continue
            try:
                repo = await _acreate_repository_core(
                    dict(serializer.validated_data), actor=request.user
                )
                created.append({"id": str(repo.id), "name": repo.name})
            except serializers.ValidationError as exc:
                failed.append({"index": idx, "name": name, "error": exc.detail})
            except Exception as exc:  # noqa: BLE001 — 单项失败隔离，不中断批量
                logger.warning("batch_create_repo_failed", index=idx, name=name, error=str(exc))
                failed.append({"index": idx, "name": name, "error": str(exc)})

        return Response(
            {
                "created": created,
                "failed": failed,
                "created_count": len(created),
                "failed_count": len(failed),
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_400_BAD_REQUEST,
        )


class ReindexAllView(APIView):
    """超管「全部更新索引」（BATCH-01）——把全部未删除仓库批量入队重索引。

    POST /api/repositories/reindex-all/  (IsSuperUser fail-closed)
    批量入队的数百仓库受 Phase 67 索引槽位锁池（CONCURRENCY_INDEX_MAX）排队消费，
    不一次性打爆资源。已在索引中的仓库跳过（不重复入队）。返回已排队 / 跳过 / 总数。
    """

    permission_classes = [IsSuperUser]

    async def post(self, request, *args, **kwargs):
        from repositories.index_views import _schedule_index

        repo_ids = [
            str(rid)
            async for rid in Repository.objects.filter(is_deleted=False).values_list(
                "id", flat=True
            )
        ]

        queued = 0
        skipped = 0
        for rid in repo_ids:
            repo = await Repository.objects.filter(id=rid).afirst()
            if repo is None:
                continue
            if repo.index_status == IndexStatus.INDEXING:
                skipped += 1
                continue
            # 重置上轮进度残留 + 建 RUNNING history + 置 INDEXING，再经 durable defer
            # （带 Phase 67 索引槽位锁，超 CONCURRENCY_INDEX_MAX 原生 todo 排队）。
            await Repository.objects.filter(id=rid).aupdate(
                index_total_chunks=0,
                index_processed_chunks=0,
                index_write_total=0,
                index_write_processed=0,
                index_error=None,
                current_indexing_file="",
                indexed_files_processed=0,
                indexed_files_total=0,
            )
            history = await IndexHistory.objects.acreate(
                repository_id=rid,
                trigger_type=TriggerType.MANUAL,
                status=IndexHistoryStatus.RUNNING,
                started_at=timezone.now(),
            )
            await Repository.objects.filter(id=rid).aupdate(
                index_status=IndexStatus.INDEXING,
                index_stage="排队中...",
            )
            try:
                await sync_to_async(_schedule_index)(rid, str(history.id), trigger="manual")
                queued += 1
            except Exception as exc:  # noqa: BLE001 — 单仓入队失败隔离
                logger.warning("reindex_all_enqueue_failed", repository_id=rid, error=str(exc))
                await IndexHistory.objects.filter(id=history.id).aupdate(
                    status=IndexHistoryStatus.FAILED, error_message=str(exc)
                )
                await Repository.objects.filter(id=rid).aupdate(
                    index_status=IndexStatus.FAILED, index_error=str(exc)
                )

        return Response(
            {"queued": queued, "skipped": skipped, "total": len(repo_ids)},
            status=status.HTTP_200_OK,
        )
