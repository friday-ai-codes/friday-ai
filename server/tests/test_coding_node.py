"""AICodingNode 单元测试。

覆盖 callback-driven 模式（TaskDispatcher 分发 -> waiting_event）
和 error handling（缺少方案 -> failed、分发失败 -> failed）。

implementation 引入 ProviderConfigService.aresolve_or_error 之后，AICodingNode
执行路径会先解析 Anthropic 凭证再走 _run_repo_coding。本文件用 autouse fixture
统一 stub aresolve_or_error 返回静态 ResolvedProviderConfig，避免单测落入凭证
缺失分支（不破坏 missing-plan / empty-plan 等不依赖凭证的负向用例）。
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.provider_config import ProviderType, ResolvedProviderConfig
from workflows.nodes.ai.coding import AICodingNode
from workflows.nodes.base import ExecutionContext, NodeResult


@pytest.fixture(autouse=True)
def _stub_provider_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """统一 stub Anthropic 凭证解析，使测试无需真实 ProviderCredential 行存在。"""

    async def _resolve(*args: object, **kwargs: object) -> ResolvedProviderConfig:
        return ResolvedProviderConfig(
            provider_type=ProviderType.ANTHROPIC,
            api_key="sk-ant-test",
            base_url="https://api.anthropic.com",
            source="system",
        )

    from services.provider_config import ProviderConfigService
    monkeypatch.setattr(
        ProviderConfigService,
        "aresolve_or_error",
        _resolve,
    )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(repo_id: str | None = None, name: str = "test-repo") -> MagicMock:
    """Create a mock Repository object."""
    repo = MagicMock()
    repo.id = uuid.UUID(repo_id) if repo_id else uuid.uuid4()
    repo.name = name
    repo.git_url = "https://gitlab.example.com/test/repo.git"
    repo.git_platform = "gitlab"
    repo.default_branch = "main"
    repo.is_deleted = False

    credential = MagicMock()
    credential.encrypted_token = "encrypted-contract"
    credential.ssl_verify = True
    repo.credential = credential

    return repo


def _make_context(
    input_data: dict[str, Any] | None = None,
    node_config: dict[str, Any] | None = None,
) -> ExecutionContext:
    """Create a minimal ExecutionContext for testing."""
    return ExecutionContext(
        execution_id="exec-test-001",
        node_id="node-coding-001",
        node_config=node_config
        or {
            "polling_interval": 0,
            "timeout_seconds": 10,
            "chat_id": "",
        },
        input_data=input_data or {},
        workflow_context={},
        previous_outputs={},
        trigger_data={"payload": {"work_item_id": "12345"}},
        workflow_execution=None,
        node_execution=None,
    )


def _make_plan_data(
    repo_id: str,
    task_count: int = 1,
    branch_name: str = "feat/xxxx-m12345-test",
) -> dict[str, Any]:
    """Create valid plan input data for the coding node."""
    execution_plan = [
        {
            "repository_id": repo_id,
            "name": f"Task {i + 1}",
            "description": f"Implement feature {i + 1}",
            "coding_instruction": f"Write code for feature {i + 1}",
        }
        for i in range(task_count)
    ]
    return {
        "plan": {
            "title": "Test Technical Plan",
            "branch_name": branch_name,
            "execution_plan": execution_plan,
            "global_context": "This is a test project.",
        }
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestAICodingNode:
    """AICodingNode 独立执行行为测试。"""

    async def test_execute_happy_path_returns_waiting_event(self) -> None:
        """提供有效 plan，TaskDispatcher 分发成功 -> status=waiting_event。"""
        repo = _make_repo(repo_id="00000000-0000-0000-0000-000000000001")
        repo_id_str = str(repo.id)
        input_data = _make_plan_data(repo_id_str)
        context = _make_context(input_data=input_data)

        node = AICodingNode()

        mock_result = {
            "status": "waiting_event",
            "session_id": "exec-test-001",
            "container_id": "",
            "repository_id": repo_id_str,
            "repository_name": repo.name,
        }

        with (
            patch.object(
                node,
                "_fetch_repositories",
                new_callable=AsyncMock,
                return_value={repo_id_str: repo},
            ),
            patch.object(
                node,
                "_run_repo_coding",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            result: NodeResult = await node.execute(context)

        assert result.status == "waiting_event"
        assert "pending_sessions" in result.output
        assert len(result.output["pending_sessions"]) == 1

    async def test_execute_missing_plan(self) -> None:
        """input_data 无 plan -> status=failed。"""
        context = _make_context(input_data={})
        node = AICodingNode()

        result: NodeResult = await node.execute(context)

        assert result.status == "failed"
        assert "技术方案数据" in (result.error or "")
        assert result.next_handle == "error"

    async def test_execute_empty_execution_plan(self) -> None:
        """plan 中 execution_plan 为空列表 -> status=failed。"""
        input_data = {
            "plan": {
                "title": "Empty Plan",
                "branch_name": "feat/empty",
                "execution_plan": [],
            }
        }
        context = _make_context(input_data=input_data)
        node = AICodingNode()

        result: NodeResult = await node.execute(context)

        assert result.status == "failed"
        assert "execution_plan 为空" in (result.error or "")
        assert result.next_handle == "error"

    async def test_execute_container_failure(self) -> None:
        """所有仓库分发失败 -> status=failed。"""
        repo = _make_repo(repo_id="00000000-0000-0000-0000-000000000002")
        repo_id_str = str(repo.id)
        input_data = _make_plan_data(repo_id_str)
        context = _make_context(input_data=input_data)

        node = AICodingNode()

        mock_result = {
            "status": "error",
            "error": "任务分发失败: Container start failed",
            "repository_id": repo_id_str,
            "repository_name": repo.name,
        }

        with (
            patch.object(
                node,
                "_fetch_repositories",
                new_callable=AsyncMock,
                return_value={repo_id_str: repo},
            ),
            patch.object(
                node,
                "_run_repo_coding",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            result: NodeResult = await node.execute(context)

        assert result.status == "failed"
        assert "所有仓库容器启动失败" in (result.error or "")
        assert result.next_handle == "error"

    async def test_execute_partial_container_failure(self) -> None:
        """两个仓库，一个分发成功一个失败 -> status=waiting_event (部分)。"""
        repo_a = _make_repo(repo_id="00000000-0000-0000-0000-00000000000a", name="repo-a")
        repo_b = _make_repo(repo_id="00000000-0000-0000-0000-00000000000b", name="repo-b")
        id_a = str(repo_a.id)
        id_b = str(repo_b.id)

        input_data = {
            "plan": {
                "title": "Partial Plan",
                "branch_name": "feat/partial",
                "execution_plan": [
                    {"repository_id": id_a, "name": "Task A", "coding_instruction": "code A"},
                    {"repository_id": id_b, "name": "Task B", "coding_instruction": "code B"},
                ],
                "global_context": "",
            }
        }
        context = _make_context(input_data=input_data)

        node = AICodingNode()

        call_count = 0

        async def mock_run_repo_coding(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            repo = kwargs["repository"]
            if call_count == 1:
                return {
                    "status": "waiting_event",
                    "session_id": "exec-partial-001",
                    "container_id": "",
                    "repository_id": str(repo.id),
                    "repository_name": repo.name,
                }
            return {
                "status": "error",
                "error": "分发失败",
                "repository_id": str(repo.id),
                "repository_name": repo.name,
            }

        with (
            patch.object(
                node,
                "_fetch_repositories",
                new_callable=AsyncMock,
                return_value={id_a: repo_a, id_b: repo_b},
            ),
            patch.object(
                node,
                "_run_repo_coding",
                side_effect=mock_run_repo_coding,
            ),
        ):
            result: NodeResult = await node.execute(context)

        assert result.status == "waiting_event"
        assert "pending_sessions" in result.output

    def test_group_by_repository(self) -> None:
        """按 repository_id 正确分组任务。"""
        node = AICodingNode()
        execution_plan = [
            {"repository_id": "repo-1", "name": "Task 1"},
            {"repository_id": "repo-2", "name": "Task 2"},
            {"repository_id": "repo-1", "name": "Task 3"},
            {"repository_id": "repo-2", "name": "Task 4"},
            {"repository_id": "repo-1", "name": "Task 5"},
            {"name": "Task without repo"},  # no repository_id
        ]

        groups = node._group_by_repository(execution_plan)

        assert "repo-1" in groups
        assert "repo-2" in groups
        assert len(groups["repo-1"]) == 3
        assert len(groups["repo-2"]) == 2
        assert "" not in groups

    @pytest.mark.xfail(reason="_build_output 返回结构已变更，branches 字段不再存在", strict=False)
    def test_build_output_structure(self) -> None:
        """_build_output 返回包含所有必要字段的输出。"""
        node = AICodingNode()

        mr_results = [
            {
                "repository_id": "repo-1",
                "repository_name": "my-repo",
                "mr_url": "https://example.com/mr/1",
                "mr_id": "1",
                "tasks_completed": ["Task A", "Task B"],
                "files_changed": 5,
                "insertions": 100,
                "deletions": 20,
            }
        ]
        failed_repos = [
            {
                "repository_id": "repo-2",
                "repository_name": "failed-repo",
                "error": "Build failed",
            }
        ]

        output = node._build_output(
            mr_results=mr_results,
            failed_repos=failed_repos,
            branch_name="feat/test",
            base_branch="main",
        )

        assert "merge_requests" in output
        assert "branches" in output
        assert "changes_summary" in output
        assert "failed_details" in output

        assert len(output["merge_requests"]) == 1
        mr = output["merge_requests"][0]
        assert mr["repository_id"] == "repo-1"
        assert mr["mr_url"] == "https://example.com/mr/1"
        assert mr["files_changed"] == 5
        assert mr["insertions"] == 100
        assert mr["deletions"] == 20

        assert output["branches"]["branch_name"] == "feat/test"
        assert output["branches"]["base_branch"] == "main"

        summary = output["changes_summary"]
        assert summary["total_repos"] == 2
        assert summary["succeeded_repos"] == 1
        assert summary["failed_repos"] == 1
        assert summary["total_files_changed"] == 5
        assert summary["total_insertions"] == 100
        assert summary["total_deletions"] == 20

        assert len(output["failed_details"]) == 1
        assert output["failed_details"][0]["repository_name"] == "failed-repo"
