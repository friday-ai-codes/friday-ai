"""AICodingNode 单元测试。

覆盖 callback-driven 模式（TaskDispatcher 分发 -> waiting_event）
和 error handling（缺少方案 -> failed、分发失败 -> failed）。

implementation 引入 ProviderConfigService.aresolve_or_error 之后，AICodingNode
执行路径会先解析 Anthropic 凭证再走 _run_repo_coding。本文件用 autouse fixture
统一 stub aresolve_or_error 返回静态 ResolvedProviderConfig，避免单测落入凭证
缺失分支（不破坏 missing-plan / empty-plan 等不依赖凭证的负向用例）。
"""

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog
from asgiref.sync import sync_to_async

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

    def test_build_output_structure(self) -> None:
        """_build_output 返回包含所有必要字段的输出。

        结构已调整：merge_requests / branches / changes_summary / failed_details
        统一收拢到 coding_result 端口内，另有顶层 merge_requests 便捷镜像与 plan 透传。
        """
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

        plan_data = {"execution_plan": [{"repository_id": "repo-1", "name": "Task A"}]}

        output = node._build_output(
            mr_results=mr_results,
            failed_repos=failed_repos,
            branch_name="feat/test",
            base_branch="main",
            plan_data=plan_data,
        )

        # 顶层端口：coding_result（完整结果）+ merge_requests（便捷镜像）+ plan（透传）
        assert set(output) == {"coding_result", "merge_requests", "plan"}
        assert output["plan"] == plan_data

        coding_result = output["coding_result"]
        assert "merge_requests" in coding_result
        assert "branches" in coding_result
        assert "changes_summary" in coding_result
        assert "failed_details" in coding_result

        assert len(coding_result["merge_requests"]) == 1
        mr = coding_result["merge_requests"][0]
        assert mr["repository_id"] == "repo-1"
        assert mr["repository_name"] == "my-repo"
        assert mr["mr_url"] == "https://example.com/mr/1"
        assert mr["mr_id"] == "1"
        assert mr["tasks_completed"] == ["Task A", "Task B"]
        assert mr["files_changed"] == 5
        assert mr["insertions"] == 100
        assert mr["deletions"] == 20

        # 顶层 merge_requests 与 coding_result 内的内容一致
        assert output["merge_requests"] == coding_result["merge_requests"]

        assert coding_result["branches"]["branch_name"] == "feat/test"
        assert coding_result["branches"]["base_branch"] == "main"

        summary = coding_result["changes_summary"]
        assert summary["total_repos"] == 2
        assert summary["succeeded_repos"] == 1
        assert summary["failed_repos"] == 1
        assert summary["total_files_changed"] == 5
        assert summary["total_insertions"] == 100
        assert summary["total_deletions"] == 20

        assert len(coding_result["failed_details"]) == 1
        assert coding_result["failed_details"][0]["repository_name"] == "failed-repo"
        assert coding_result["failed_details"][0]["error"] == "Build failed"


# ---------------------------------------------------------------------------
# PF-06: _run_repo_coding dispatch metadata env 键集合断言（对齐 chat 基线）
# ---------------------------------------------------------------------------

# chat 路径 build_dispatch_metadata 的权威键集合（coding_session_service.py:173-187）
GIT_TOKEN_KEY = "env_FRIDAY_TASK_GIT_ACCESS_TOKEN"
GIT_AUTH_TYPE_KEY = "env_FRIDAY_TASK_GIT_AUTH_TYPE"
GIT_SSL_VERIFY_KEY = "env_FRIDAY_TASK_GIT_SSL_VERIFY"
BRANCH_STRATEGY_KEY = "env_FRIDAY_TASK_BRANCH_STRATEGY"
TARGET_BRANCH_KEY = "env_FRIDAY_TASK_TARGET_BRANCH"

_PF06_TOKEN = "glpat-pf06-controlled-token-xyz"


async def _make_real_repo(git_url: str) -> Any:
    """创建并返回真实 Repository（供 _run_repo_coding 跑真实生产取数路径）。

    WR-01 修复后生产代码不再访问 repository.credential（反向 OneToOne），故此处直接返回
    未 select_related 的实例，如实复现生产异步取数路径——不再用 select_related 重载掩盖。
    """
    from repositories.models import Repository

    return await sync_to_async(Repository.objects.create)(
        name=f"pf06-repo-{uuid.uuid4().hex[:8]}",
        git_url=git_url,
        default_branch="main",
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestRunRepoCodingPF06:
    """PF-06：workflow 编码路径 dispatch metadata 须逐键对齐 chat 基线
    （顶层 env_FRIDAY_TASK_GIT_* + BRANCH_STRATEGY/TARGET_BRANCH + SSH→HTTPS 改写）。

    调用**真实** _run_repo_coding，仅 mock IO 边界：
    - aresolve_git_token（受控 token）
    - runners.dispatcher.get_dispatcher().dispatch（捕获 DispatchTask）
    _create_session 的 ORM 写入跑真实 DB（transaction=True）。
    """

    @pytest.fixture
    def _dispatched(self, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
        captured: list[Any] = []

        class _FakeDispatcher:
            async def dispatch(self, task: Any) -> None:
                captured.append(task)

        monkeypatch.setattr("runners.dispatcher.get_dispatcher", lambda: _FakeDispatcher())
        return captured

    def _patch_token(self, monkeypatch: pytest.MonkeyPatch, token: str) -> None:
        async def _resolve(*args: Any, **kwargs: Any) -> str:
            return token

        monkeypatch.setattr("workflows.nodes.ai.coding.aresolve_git_token", _resolve)

    async def _run(
        self,
        *,
        git_url: str,
        token: str,
        branch_name: str = "feat/pf06-work",
        base_branch: str = "develop",
        monkeypatch: pytest.MonkeyPatch,
    ) -> Any:
        self._patch_token(monkeypatch, token)
        repo = await _make_real_repo(git_url)
        node = AICodingNode()
        await node._run_repo_coding(
            repository=repo,
            tasks=[{"task_description": "do x"}],
            branch_name=branch_name,
            base_branch=base_branch,
            global_context="ctx",
            config={},
        )

    async def test_git_env_injected_when_token_present(
        self, _dispatched: list[Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """token 非空 → metadata 含 GIT_ACCESS_TOKEN==token / AUTH_TYPE=='token' / SSL_VERIFY=='false'。"""
        await self._run(
            git_url="https://gitlab.example.com/org/repo.git",
            token=_PF06_TOKEN,
            monkeypatch=monkeypatch,
        )
        assert len(_dispatched) == 1
        meta = _dispatched[0].metadata
        assert meta[GIT_TOKEN_KEY] == _PF06_TOKEN
        assert meta[GIT_AUTH_TYPE_KEY] == "token"
        assert meta[GIT_SSL_VERIFY_KEY] == "false"

    async def test_branch_strategy_and_target_branch_injected(
        self, _dispatched: list[Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BRANCH_STRATEGY==本仓 branch_name、TARGET_BRANCH==base_branch（无条件注入）。"""
        await self._run(
            git_url="https://gitlab.example.com/org/repo.git",
            token=_PF06_TOKEN,
            branch_name="feat/pf06-mybranch",
            base_branch="release/v1",
            monkeypatch=monkeypatch,
        )
        assert len(_dispatched) == 1
        meta = _dispatched[0].metadata
        assert meta[BRANCH_STRATEGY_KEY] == "feat/pf06-mybranch"
        assert meta[TARGET_BRANCH_KEY] == "release/v1"

    async def test_ssh_https_rewrite_when_token_present(
        self, _dispatched: list[Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """git@host:org/repo.git + token 非空 → DispatchTask.repo_url 改写为 https://host/org/repo.git。"""
        await self._run(
            git_url="git@gitlab.example.com:org/repo.git",
            token=_PF06_TOKEN,
            monkeypatch=monkeypatch,
        )
        assert len(_dispatched) == 1
        assert _dispatched[0].repo_url == "https://gitlab.example.com/org/repo.git"

    async def test_no_token_omits_access_key_and_keeps_repo_url(
        self, _dispatched: list[Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """token 为空 → 不注入 access_token 键且 repo_url 原样不改写（降级不回退）。"""
        await self._run(
            git_url="git@gitlab.example.com:org/repo.git",
            token="",
            monkeypatch=monkeypatch,
        )
        assert len(_dispatched) == 1
        meta = _dispatched[0].metadata
        assert GIT_TOKEN_KEY not in meta
        assert _dispatched[0].repo_url == "git@gitlab.example.com:org/repo.git"

    async def test_no_token_leak_in_dispatch_logs(
        self, _dispatched: list[Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """dispatch 日志绝不含 token 明文，仅记 has_git_token 布尔。"""
        with structlog.testing.capture_logs() as logs:
            await self._run(
                git_url="https://gitlab.example.com/org/repo.git",
                token=_PF06_TOKEN,
                monkeypatch=monkeypatch,
            )
        serialized = json.dumps(logs, default=str)
        assert _PF06_TOKEN not in serialized, "token 明文绝不可进日志"
        dispatch_events = [e for e in logs if e.get("event") == "task_dispatched_to_runner"]
        assert dispatch_events, "应有 task_dispatched_to_runner 日志事件"
        assert dispatch_events[0].get("has_git_token") is True

    async def test_nested_git_credentials_retained(
        self, _dispatched: list[Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """token 非空 → 既有 nested metadata['git_credentials'] dict 原样保留（零回归）。"""
        await self._run(
            git_url="https://gitlab.example.com/org/repo.git",
            token=_PF06_TOKEN,
            monkeypatch=monkeypatch,
        )
        assert len(_dispatched) == 1
        git_credentials = _dispatched[0].metadata["git_credentials"]
        assert isinstance(git_credentials, dict)
        assert git_credentials.get("access_token") == _PF06_TOKEN


# ---------------------------------------------------------------------------
# _build_coding_prompt 上游产物注入 + 零回归（ARTIFACT-02，Phase 45-02）
# ---------------------------------------------------------------------------


def _expected_baseline_prompt(global_context: str, branch_name: str) -> str:
    """直接构造 Phase 44 现行为 prompt 期望字符串（无文件、无上游、单任务）。

    与 ``_build_coding_prompt`` parts 顺序逐字对齐，用于零回归 == 断言。
    """
    parts = [
        f"# 项目背景\n\n{global_context}",
        f"# 分支信息\n\n目标分支: `{branch_name}`",
        "# 编码任务: Task A\n\nDo A",
        (
            "# 要求\n\n"
            "- 确保类型检查通过\n"
            "- 确保单元测试通过\n"
            "- 每个任务至少一个 commit，commit message 清晰描述变更"
        ),
    ]
    return "\n\n---\n\n".join(parts)


_PROMPT_TASKS = [{"name": "Task A", "coding_instruction": "Do A"}]
_UPSTREAM_ARTIFACTS = [
    {
        "repository_id": "r1",
        "repository_name": "backend",
        "branch": "feat/api",
        "mr_url": "https://gitlab.example.com/mr/1",
        "openapi": ["api/openapi.yaml"],
        "api_contracts": ["proto/user.proto"],
        "diff_summary": {"files_changed": 3},
    }
]


class TestBuildCodingPromptUpstreamInjection:
    """``_build_coding_prompt`` 上游产物注入段 + 首发零回归逐字断言。"""

    def test_no_upstream_param_byte_identical_to_phase44(self) -> None:
        """不传 upstream_artifacts（默认）→ prompt 与 Phase 44 现行为逐字一致（零回归命门）。"""
        node = AICodingNode()
        prompt = node._build_coding_prompt(
            _PROMPT_TASKS, "This is a test project.", "feat/x"
        )
        assert prompt == _expected_baseline_prompt("This is a test project.", "feat/x")

    def test_none_and_empty_upstream_byte_identical(self) -> None:
        """upstream_artifacts=None 与 =[] 均与未传该参逐字一致（防空段漂移）。"""
        node = AICodingNode()
        expected = _expected_baseline_prompt("ctx", "br")
        assert (
            node._build_coding_prompt(_PROMPT_TASKS, "ctx", "br", upstream_artifacts=None)
            == expected
        )
        assert (
            node._build_coding_prompt(_PROMPT_TASKS, "ctx", "br", upstream_artifacts=[])
            == expected
        )

    def test_with_upstream_includes_contract_section(self) -> None:
        """带非空 upstream → prompt 含「上游产物」段 + 契约文件名。"""
        node = AICodingNode()
        prompt = node._build_coding_prompt(
            _PROMPT_TASKS,
            "This is a test project.",
            "feat/x",
            upstream_artifacts=_UPSTREAM_ARTIFACTS,
        )
        assert "# 上游产物 / 上游契约" in prompt
        assert "backend" in prompt
        assert "proto/user.proto" in prompt
        assert "api/openapi.yaml" in prompt

    def test_upstream_section_after_global_context_before_branch(self) -> None:
        """上游产物段位于「项目背景」之后、「分支信息」之前（D-08 插入位）。"""
        node = AICodingNode()
        prompt = node._build_coding_prompt(
            _PROMPT_TASKS,
            "This is a test project.",
            "feat/x",
            upstream_artifacts=_UPSTREAM_ARTIFACTS,
        )
        idx_ctx = prompt.index("# 项目背景")
        idx_upstream = prompt.index("# 上游产物 / 上游契约")
        idx_branch = prompt.index("# 分支信息")
        assert idx_ctx < idx_upstream < idx_branch
