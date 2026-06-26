"""BranchProvisionService 测试（Phase 89 PLAN-04，建分支绑项目，INV-6 + fail-soft）。

覆盖（git/subprocess seam mock，无真实 git/网络/DB）：
- 逐仓建推成功 → ``ProjectBranchService.bind(source=plan, _skip_member_check)`` 被调；
- 单仓建推失败 / bind 失败隔离不阻断其余（succeeded/failed 收集）；
- 分支已存在 → 跳过 create/push 仅 bind（幂等，仅 fetch）；
- push 注入 ``aresolve_git_token``（oauth2:<token>@）+ token 绝不入日志（capture_logs 断言）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from structlog.testing import capture_logs

from initiatives.models import BranchSource
from initiatives.services.branch_provision_service import BranchProvisionService

_MOD = "initiatives.services.branch_provision_service"
_SVC = "initiatives.services.project_branch_service.ProjectBranchService"
_TOKEN_FN = "services.git_credentials.aresolve_git_token"


def _repo(repo_id: str, name: str = "", git_url: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        id=repo_id,
        name=name or f"repo-{repo_id}",
        git_url=git_url or f"https://github.com/test/{repo_id}.git",
    )


def _project() -> SimpleNamespace:
    return SimpleNamespace(id="p1", name="P")


def _bind_service(bind_mock: AsyncMock) -> MagicMock:
    svc = MagicMock()
    svc.bind = bind_mock
    return svc


@pytest.mark.asyncio
async def test_provision_and_bind_source_plan() -> None:
    repos = [_repo("r1"), _repo("r2")]
    bind = AsyncMock(return_value=SimpleNamespace(id="b1"))

    with (
        patch(_TOKEN_FN, AsyncMock(return_value="tok")),
        patch(_SVC, return_value=_bind_service(bind)),
        patch.object(
            BranchProvisionService,
            "_provision_repo",
            AsyncMock(
                return_value={"status": "success", "created": True, "skipped_existing": False}
            ),
        ),
    ):
        result = await BranchProvisionService().provision_and_bind(
            project=_project(),
            repositories=repos,
            branch_names={"r1": "feat/260610.m-1.X", "r2": "fix/260610.m-1.X"},
            initiated_by_user_id="42",
            feishu_board_id="board-9",
        )

    assert len(result["succeeded"]) == 2
    assert result["all_succeeded"] is True
    assert bind.await_count == 2
    kw = bind.await_args.kwargs
    assert kw["source"] == BranchSource.PLAN
    assert kw["_skip_member_check"] is True
    assert kw["feishu_board_id"] == "board-9"


@pytest.mark.asyncio
async def test_per_repo_provision_failure_isolated() -> None:
    repos = [_repo("r1"), _repo("r2")]
    bind = AsyncMock(return_value=SimpleNamespace(id="b1"))

    with (
        patch(_TOKEN_FN, AsyncMock(return_value="tok")),
        patch(_SVC, return_value=_bind_service(bind)),
        patch.object(
            BranchProvisionService,
            "_provision_repo",
            AsyncMock(
                side_effect=[
                    {"status": "error", "error": "仓库本地路径不存在"},
                    {"status": "success", "created": True},
                ]
            ),
        ),
    ):
        result = await BranchProvisionService().provision_and_bind(
            project=_project(),
            repositories=repos,
            branch_names="feat/260610.m-1.X",
        )

    assert len(result["failed"]) == 1
    assert len(result["succeeded"]) == 1
    assert result["all_succeeded"] is False
    # 仅成功仓 bind（失败仓不绑）
    assert bind.await_count == 1


@pytest.mark.asyncio
async def test_bind_exception_isolated_failsoft() -> None:
    repos = [_repo("r1"), _repo("r2")]
    bind = AsyncMock(side_effect=[RuntimeError("db boom"), SimpleNamespace(id="b2")])

    with (
        patch(_TOKEN_FN, AsyncMock(return_value="tok")),
        patch(_SVC, return_value=_bind_service(bind)),
        patch.object(
            BranchProvisionService,
            "_provision_repo",
            AsyncMock(return_value={"status": "success", "created": True}),
        ),
    ):
        result = await BranchProvisionService().provision_and_bind(
            project=_project(),
            repositories=repos,
            branch_names="feat/260610.m-1.X",
        )

    # 第一仓 bind 抛 → failed；第二仓成功 → succeeded（不阻断）
    assert len(result["failed"]) == 1
    assert len(result["succeeded"]) == 1


@pytest.mark.asyncio
async def test_existing_branch_skips_create_only_binds() -> None:
    repos = [_repo("r1")]
    bind = AsyncMock(return_value=SimpleNamespace(id="b1"))
    agit = AsyncMock()

    with (
        patch(_TOKEN_FN, AsyncMock(return_value="tok")),
        patch(_SVC, return_value=_bind_service(bind)),
        patch.object(BranchProvisionService, "_arepo_exists", AsyncMock(return_value=True)),
        patch.object(BranchProvisionService, "_abranch_exists", AsyncMock(return_value=True)),
        patch.object(BranchProvisionService, "_agit", agit),
    ):
        result = await BranchProvisionService().provision_and_bind(
            project=_project(),
            repositories=repos,
            branch_names={"r1": "feat/260610.m-1.X"},
        )

    assert result["succeeded"][0]["skipped_existing"] is True
    bind.assert_awaited_once()
    # 已存在：仅 fetch，无 checkout/create/push
    called_args = [c.args[1] for c in agit.await_args_list]
    assert ["fetch", "origin"] in called_args
    assert all(a[0] != "push" for a in called_args)
    assert all("-b" not in a for a in called_args)


@pytest.mark.asyncio
async def test_token_injected_into_push_and_not_logged() -> None:
    secret = "ghp_secrettoken123"
    repos = [_repo("r1", git_url="git@github.com:test/repo.git")]
    bind = AsyncMock(return_value=SimpleNamespace(id="b1"))
    agit = AsyncMock()

    with (
        patch(_TOKEN_FN, AsyncMock(return_value=secret)),
        patch(_SVC, return_value=_bind_service(bind)),
        patch.object(BranchProvisionService, "_arepo_exists", AsyncMock(return_value=True)),
        patch.object(BranchProvisionService, "_abranch_exists", AsyncMock(return_value=False)),
        patch.object(BranchProvisionService, "_agit", agit),
        capture_logs() as logs,
    ):
        await BranchProvisionService().provision_and_bind(
            project=_project(),
            repositories=repos,
            branch_names={"r1": "feat/260610.m-1.X"},
        )

    # push 命令注入了 oauth2:<token>@（SSH→HTTPS 改写）
    push_calls = [c.args[1] for c in agit.await_args_list if c.args[1][0] == "push"]
    assert push_calls, "push 未被调用"
    push_argv = " ".join(push_calls[0])
    assert f"oauth2:{secret}@github.com" in push_argv

    # token 绝不入日志：所有结构化事件序列化后均不含明文 token
    serialized = "\n".join(str(event) for event in logs)
    assert secret not in serialized
    # 但 has_git_token 布尔已记录
    assert any(event.get("has_git_token") is True for event in logs)
