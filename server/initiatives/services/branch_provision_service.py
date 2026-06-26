"""BranchProvisionService —— 逐仓建分支推送 + 绑 仓库↔分支↔项目（Phase 89 PLAN-04，INV-6）。

方案确认后的「建分支绑项目」单一编排收口：逐仓复用 ``CreateBranchNode`` 的 server-local git
逻辑（``DATA_DIR/repos/{repo_id}`` fetch/checkout base/create/push），push URL 经
``aresolve_git_token`` 注入鉴权（SSH→HTTPS 改写 + ``oauth2:<token>@`` 密码位），建成功后经
``ProjectBranchService.bind(source=BranchSource.PLAN)`` 绑定（**绝不旁路写 ``ProjectBranch``**，
INV-6，Phase 85 ``_skip_member_check`` seam）。

设计要点（CONTEXT/RESEARCH 锁定）：

- **单仓 fail-soft 隔离**：每仓 try/except，失败入 ``failed`` 不阻断其余（未克隆/push 失败标失败）。
- **分支已存在幂等**：建前 ``branch_exists`` 判定，已存在跳过 create/push 仅 bind；
  ``ProjectBranchService.bind`` 本身 get_or_create 幂等。
- **观测/安全**：``branch_provision_started`` / ``branch_pushed`` / ``branch_bound`` /
  ``branch_provision_failed``（caller, component=initiatives, +duration_ms + initiated_by_user_id）；
  **git token 绝不入日志**（仅记 ``has_git_token`` 布尔）；分支名/异常经 ``redact_secrets_in_text`` 脱敏。
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from time import perf_counter
from typing import Any

import structlog

from friday.settings import DATA_DIR

logger = structlog.get_logger(__name__)

__all__ = ["BranchProvisionService"]

_COMPONENT = "initiatives"


class BranchProvisionService:
    """逐仓建分支推送 + 绑项目的单一编排收口（无状态，fail-soft，写收口 INV-6）。"""

    async def provision_and_bind(
        self,
        *,
        project: Any,
        repositories: list[Any],
        branch_names: Any,
        actor: Any = None,
        initiated_by_user_id: str = "system",
        base_branch: str = "main",
        feishu_board_id: str = "",
    ) -> dict[str, Any]:
        """逐仓建分支推送 + ``ProjectBranchService.bind(source=plan)`` 绑定（单仓 fail-soft）。

        Args:
            project: 绑定目标项目（需含 ``id``）。
            repositories: ``repositories.models.Repository`` 实例列表（需含 ``id`` / ``name`` /
                ``git_url``）。
            branch_names: ``{repository_id: branch_name}`` 映射，或单一 str（应用到所有仓）。
            actor / initiated_by_user_id: 审计/可观测归因（缺记 system）。
            base_branch: 基础分支（默认 main）。
            feishu_board_id: 冗余项目飞书看板 id（绑定时携带，便于 branch↔board 反查）。

        Returns:
            ``{succeeded: [...], failed: [...], all_succeeded: bool, total: int}``。
        """
        from common.logging import redact_secrets_in_text

        started = perf_counter()
        log = logger.bind(
            component=_COMPONENT,
            category="caller",
            initiated_by_user_id=str(initiated_by_user_id or "system"),
            project_id=str(getattr(project, "id", "") or ""),
        )
        log.info("branch_provision_started", repo_count=len(repositories or []))

        succeeded: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        for repo in repositories or []:
            repo_id = str(getattr(repo, "id", "") or "")
            repo_name = getattr(repo, "name", "") or repo_id
            branch_name = self._resolve_branch_name(branch_names, repo_id)
            has_token = False
            if not branch_name:
                failed.append(
                    {
                        "repository_id": repo_id,
                        "repository_name": repo_name,
                        "error": "缺少分支名",
                    }
                )
                continue
            try:
                from services.git_credentials import aresolve_git_token

                token = await aresolve_git_token(repo)
                has_token = bool(token)
                provision = await self._provision_repo(
                    repo=repo,
                    branch_name=branch_name,
                    base_branch=base_branch,
                    token=token,
                )
                if provision.get("status") != "success":
                    failed.append(
                        {
                            "repository_id": repo_id,
                            "repository_name": repo_name,
                            "branch_name": branch_name,
                            "error": provision.get("error", "建分支失败"),
                        }
                    )
                    log.warning(
                        "branch_provision_failed",
                        repository_id=repo_id,
                        branch_name=branch_name,
                        reason=redact_secrets_in_text(str(provision.get("error", ""))),
                        has_git_token=has_token,
                    )
                    continue

                log.info(
                    "branch_pushed",
                    repository_id=repo_id,
                    branch_name=branch_name,
                    created=provision.get("created", True),
                    skipped_existing=provision.get("skipped_existing", False),
                    has_git_token=has_token,
                )

                # 建/推成功 → 经 ProjectBranchService 绑定（source=plan，INV-6，幂等）。
                from initiatives.models import BranchSource
                from initiatives.services.project_branch_service import (
                    ProjectBranchService,
                )

                binding = await ProjectBranchService().bind(
                    project_id=getattr(project, "id", None),
                    repository_id=getattr(repo, "id", None),
                    branch_name=branch_name,
                    source=BranchSource.PLAN,
                    actor=actor,
                    initiated_by_user_id=initiated_by_user_id,
                    feishu_board_id=feishu_board_id,
                    _skip_member_check=True,
                )
                succeeded.append(
                    {
                        "repository_id": repo_id,
                        "repository_name": repo_name,
                        "branch_name": branch_name,
                        "binding_id": str(getattr(binding, "id", "") or ""),
                        "skipped_existing": provision.get("skipped_existing", False),
                    }
                )
                log.info(
                    "branch_bound",
                    repository_id=repo_id,
                    branch_name=branch_name,
                )
            except Exception as exc:  # noqa: BLE001 — 单仓 fail-soft，绝不阻断其余仓
                failed.append(
                    {
                        "repository_id": repo_id,
                        "repository_name": repo_name,
                        "branch_name": branch_name,
                        "error": redact_secrets_in_text(str(exc)),
                    }
                )
                log.error(
                    "branch_provision_failed",
                    repository_id=repo_id,
                    branch_name=branch_name,
                    error_type=type(exc).__name__,
                    reason=redact_secrets_in_text(str(exc)),
                    has_git_token=has_token,
                )

        log.info(
            "branch_provision_completed",
            succeeded_count=len(succeeded),
            failed_count=len(failed),
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
        return {
            "succeeded": succeeded,
            "failed": failed,
            "all_succeeded": len(failed) == 0,
            "total": len(repositories or []),
        }

    @staticmethod
    def _resolve_branch_name(branch_names: Any, repo_id: str) -> str:
        """从 ``branch_names``（dict 或单一 str）解析本仓分支名。"""
        if isinstance(branch_names, dict):
            return str(branch_names.get(repo_id) or branch_names.get(str(repo_id)) or "")
        if isinstance(branch_names, str):
            return branch_names
        return ""

    # ------------------------------------------------------------------
    # 逐仓 git 建分支推送（复用 CreateBranchNode server-local 逻辑 + token 注入）
    # ------------------------------------------------------------------

    async def _provision_repo(
        self,
        *,
        repo: Any,
        branch_name: str,
        base_branch: str,
        token: str | None,
    ) -> dict[str, Any]:
        """单仓建分支推送：未克隆/git 失败标 error；分支已存在跳过 create/push（幂等）。"""
        repo_id = str(getattr(repo, "id", "") or "")
        repo_path = Path(DATA_DIR) / "repos" / repo_id

        if not await self._arepo_exists(repo_path):
            return {
                "status": "error",
                "error": "仓库本地路径不存在，请先克隆仓库",
                "branch_name": branch_name,
            }

        repo_path_str = str(repo_path)
        try:
            await self._agit(repo_path_str, ["fetch", "origin"])

            # 幂等：分支已存在 → 跳过 create/push，仅交由上层 bind。
            if await self._abranch_exists(repo_path_str, branch_name):
                return {
                    "status": "success",
                    "branch_name": branch_name,
                    "created": False,
                    "skipped_existing": True,
                }

            await self._agit(repo_path_str, ["checkout", base_branch])
            await self._agit(repo_path_str, ["pull", "origin", base_branch])
            await self._agit(repo_path_str, ["checkout", "-b", branch_name])

            # push URL 注入 token（SSH→HTTPS 改写 + oauth2 密码位）；token 绝不入日志。
            push_url = self._build_push_url(getattr(repo, "git_url", ""), token)
            await self._agit(
                repo_path_str,
                ["push", "-u", push_url, f"HEAD:refs/heads/{branch_name}"],
            )
            return {
                "status": "success",
                "branch_name": branch_name,
                "created": True,
                "skipped_existing": False,
            }
        except subprocess.CalledProcessError as exc:
            from common.logging import redact_secrets_in_text

            stderr = exc.stderr.decode() if getattr(exc, "stderr", None) else str(exc)
            return {
                "status": "error",
                "error": f"Git 操作失败: {redact_secrets_in_text(stderr)}",
                "branch_name": branch_name,
            }

    @staticmethod
    def _build_push_url(git_url: str, token: str | None) -> str:
        """构建鉴权 push URL（SSH→HTTPS 改写 + token 注入；无 token 原样 HTTPS）。"""
        from repositories.serializers import ssh_git_url_to_https
        from repositories.views import build_authenticated_git_url

        https_url = ssh_git_url_to_https(str(git_url or ""))
        return build_authenticated_git_url(https_url, token)

    @staticmethod
    async def _arepo_exists(repo_path: Path) -> bool:
        """仓库本地路径是否存在（线程化 fs 探测）。"""
        return await asyncio.to_thread(repo_path.exists)

    @staticmethod
    async def _abranch_exists(repo_path_str: str, branch_name: str) -> bool:
        """本地分支是否已存在（``git rev-parse --verify``，returncode 判定）。"""
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch_name}"],
            cwd=repo_path_str,
            capture_output=True,
        )
        return result.returncode == 0

    @staticmethod
    async def _agit(repo_path_str: str, args: list[str]) -> None:
        """执行单条 git 命令（check=True，失败抛 CalledProcessError）。"""
        await asyncio.to_thread(
            subprocess.run,
            ["git", *args],
            cwd=repo_path_str,
            check=True,
            capture_output=True,
        )
