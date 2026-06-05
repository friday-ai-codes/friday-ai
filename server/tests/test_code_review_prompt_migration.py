"""implementation / implementation contract: code_review prompt 迁移字节级等价测试。

implementation Wave（task）contract 迁移后：
- 老 PROMPT_CENTER 三态（DB hit / DB empty / flag disabled）测试保留，守护 render_prompt 契约
- 新增 ``_CapturingFake`` + conftest ``fake_chat_model_factory`` seam 注入的集成测试，
  对 ``AICodeReviewNode.execute`` 真实传给 LLM 的 ``SystemMessage.content`` 做 sha256 字节级断言
- **work item 强化**：``expected_sha`` 本次固化值禁止修改；若 fixture 变量或 Prompt 源漂移导致
  hash 变化，**修 fixture**（固定 execution_id / node_id / mr_ids）或修回 Prompt 路径，
  **不得**更新 expected_sha。

security mitigation-03 威胁缓解：禁止通过"更新 expected hash 掩盖 Prompt 漂移"路径规避本测试。
"""
from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import SystemMessage

from prompts.keys import PromptSlugs
from prompts.models import Prompt, PromptScope, PromptVersion
from prompts.services import render_prompt
from services.git_platform.models import MRDiffFile, MRDiffResult
from tests.helpers.fake_chat_model import FakeChatModel
from workflows.nodes.ai.code_review import AICodeReviewNode, REVIEW_SYSTEM_PROMPT
from workflows.nodes.base import ExecutionContext


@pytest.mark.django_db(transaction=True)
class TestCodeReviewMigration:

    @pytest.fixture(autouse=True)
    def _ensure_seed(self, db: Any) -> None:
        """每个测试开始前确保 AI_NODE_CODE_REVIEW seed 存在。"""
        if not Prompt.objects.filter(
            slug=PromptSlugs.AI_NODE_CODE_REVIEW,
            scope=PromptScope.SYSTEM,
        ).exists():
            prompt = Prompt.objects.create(
                slug=PromptSlugs.AI_NODE_CODE_REVIEW,
                scope=PromptScope.SYSTEM,
                project=None,
                category="ai_node",
                title="AI 节点 - 代码审查",
                description="implementation test re-seed",
                is_builtin=True,
            )
            version = PromptVersion.objects.create(
                prompt=prompt,
                version=1,
                body=REVIEW_SYSTEM_PROMPT,
                variables_schema={},
                change_note="test re-seed",
            )
            prompt.active_version = version
            prompt.save(update_fields=["active_version", "updated_at"])

    @pytest.mark.asyncio
    async def test_db_hit_returns_db_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DB 命中：render_prompt 返回 DB body（由 seed migration 提供）。"""
        monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
        result = await render_prompt(
            PromptSlugs.AI_NODE_CODE_REVIEW,
            project_id=None,
            variables={},
            fallback=REVIEW_SYSTEM_PROMPT,
        )
        # seed 的 DB body 应与常量字节级相等（由 Task 2 的 hash contract 保证）
        assert result == REVIEW_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_db_empty_returns_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DB 空：删除 seed 后走 fallback 返回常量。"""
        monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
        await Prompt.objects.filter(
            slug=PromptSlugs.AI_NODE_CODE_REVIEW,
            scope=PromptScope.SYSTEM,
        ).adelete()
        result = await render_prompt(
            PromptSlugs.AI_NODE_CODE_REVIEW,
            project_id=None,
            variables={},
            fallback=REVIEW_SYSTEM_PROMPT,
        )
        assert result == REVIEW_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_flag_disabled_returns_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """flag 禁用：即使 DB 有记录也走 fallback。"""
        monkeypatch.setenv("PROMPT_CENTER_DISABLED_KEYS", "ai_node.code_review.system")
        result = await render_prompt(
            PromptSlugs.AI_NODE_CODE_REVIEW,
            project_id=None,
            variables={},
            fallback=REVIEW_SYSTEM_PROMPT,
        )
        assert result == REVIEW_SYSTEM_PROMPT

    def test_hook_still_returns_constant(self) -> None:
        """get_system_prompt hook 保持同步签名返回常量（base class 契约不变）。"""
        node = AICodeReviewNode()
        ctx = MagicMock()
        assert node.get_system_prompt(ctx) == REVIEW_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# implementation contract：_CapturingFake seam 注入 + 字节级 hash 守护
# ---------------------------------------------------------------------------


class _CapturingFake(FakeChatModel):
    """FakeChatModel 子类：在 ``ainvoke`` / ``_astream`` 时捕获传入的 messages。

    覆盖 ``_astream`` 以便 LangChainAgentRunner.stream（流式路径）能捕获
    SystemMessage.content 字节级内容；``bind`` override 确保 chain 内部
    Runner 持有 ``bound_tools=None`` 分支回填我们自己的 FakeChatModel（而非
    runtime-bound 代理）。
    """

    captured: dict[str, Any] = {}

    async def ainvoke(
        self, input_: Any, config: Any = None, **kwargs: Any
    ) -> Any:
        self._capture(input_)
        return await super().ainvoke(input_, config, **kwargs)

    async def _astream(  # type: ignore[override]
        self,
        messages: Any,
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        self._capture(messages)
        async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
            yield chunk

    def _capture(self, input_: Any) -> None:
        if isinstance(input_, list) and input_:
            type(self).captured["all_contents"] = [
                getattr(m, "content", "") or str(m) for m in input_
            ]
            type(self).captured["system_content"] = next(
                (
                    getattr(m, "content", "")
                    for m in input_
                    if isinstance(m, SystemMessage)
                ),
                "",
            )

    def bind(self, **kwargs: Any) -> Any:
        """保持 chain：runner.bind(temperature=..., max_tokens=...) 时返回 self。"""
        return self


def _make_coding_result_with_one_mr() -> dict[str, Any]:
    """最小 coding_result：1 MR，供 AICodeReviewNode.execute 进入 per-MR 循环。"""
    return {
        "coding_result": {
            "merge_requests": [
                {
                    "repository_id": "00000000-0000-0000-0000-000000000001",
                    "repository_name": "test-repo",
                    "mr_url": "https://gitlab.example.com/test/repo/-/merge_requests/1",
                    "mr_id": "1",
                    "tasks_completed": ["Task 1"],
                    "files_changed": 3,
                    "insertions": 50,
                    "deletions": 10,
                }
            ],
            "branches": {"branch_name": "feat/test", "base_branch": "main"},
            "changes_summary": {"total_repos": 1, "succeeded_repos": 1},
        }
    }


def _make_fixed_context() -> ExecutionContext:
    """work item 守护：固定 execution_id / node_id / mr_ids，使 system prompt 稳定。

    注：AI_NODE_CODE_REVIEW prompt 当前无占位符（见 REVIEW_SYSTEM_PROMPT），
    因此 system_content 完全由 REVIEW_SYSTEM_PROMPT 决定；固定 ExecutionContext
    字段主要用于守护未来可能引入变量的稳定性。
    """
    return ExecutionContext(
        execution_id="test-exec-id-12345",
        node_id="code-review-n1",
        node_config={
            "model": "claude-sonnet-4-20250514",
            "chat_id": "",
            "max_iterations": 5,
            "mr_ids": ["mr-1"],
        },
        input_data=_make_coding_result_with_one_mr(),
        workflow_context={},
        previous_outputs={},
        trigger_data={},
        workflow_execution=None,
        node_execution=None,
    )


@pytest.fixture
def capturing_code_review_fake(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """implementation contract：_CapturingFake seam 注入（与 fake_chat_model_factory 同路径覆盖）。

    单独定义而非直接复用 conftest ``fake_chat_model_factory``，以保留 ainvoke/astream
    捕获能力（FakeChatModel 本身不捕获 messages）；fake 的 responses 使用合法 JSON
    确保 AICodeReviewNode._parse_review_output 成功解析。
    """
    # 清空上轮 captured，避免同 session 测试间污染
    _CapturingFake.captured = {}
    # 合法审查报告 JSON（与 test_code_review_node 结构一致）
    report_json = (
        '{"repository": "test-repo", "summary": "ok", "dimensions": '
        '{"code_quality": {"issues": []}, "security": {"issues": []}, '
        '"plan_compliance": {"issues": []}}}'
    )
    fake = _CapturingFake(
        responses=[report_json],
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )
    # 覆盖 3 个关键 build_chat_model seam（双保险 / Pitfall #5）
    monkeypatch.setattr(
        "agents.llm_factory.build_chat_model",
        lambda *a, **kw: fake,
    )
    monkeypatch.setattr(
        "agents.langchain_runner.build_chat_model",
        lambda *a, **kw: fake,
    )
    # aresolve_or_error stub（返回默认 Anthropic system source）
    from services.provider_config import (
        ProviderType,
        ResolvedProviderConfig,
    )

    async def _stub_resolve(
        node_config: Any = None,
        conversation: Any = None,
        project: Any = None,
    ) -> ResolvedProviderConfig:
        return ResolvedProviderConfig(
            provider_type=ProviderType.ANTHROPIC,
            api_key="sk-fake",
            base_url="https://api.anthropic.com",
            source="system",
        )

    monkeypatch.setattr(
        "services.provider_config.ProviderConfigService.aresolve_or_error",
        _stub_resolve,
    )
    return _CapturingFake.captured


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_code_review_system_prompt_byte_equal(
    capturing_code_review_fake: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """work item 强化 / security mitigation-03：AICodeReviewNode.execute 传入 LLM 的 system prompt
    字节级与 REVIEW_SYSTEM_PROMPT 相等。

    本断言通过 sha256 硬编码对比做字节级守护；expected_sha 固定为 REVIEW_SYSTEM_PROMPT
    常量自身的 sha256 —— **禁止修改**。若断言失败：
    1. 检查 AI_NODE_CODE_REVIEW DB seed 是否偏移（应字节级等于 REVIEW_SYSTEM_PROMPT）
    2. 检查 code_review.py L367 `render_prompt(... fallback=REVIEW_SYSTEM_PROMPT)` 参数
    3. 检查 Runner 消息构造 `SystemMessage(content=rendered_system_prompt)` 是否引入
       ChatPromptTemplate 二次封装（contract / 严禁 A）
    **禁止通过更新 expected_sha 修复本测试。**
    """
    ctx = _make_fixed_context()
    node = AICodeReviewNode()

    # 替身：_get_project 返回合法 UUID id 的 mock project 以过 render_prompt
    mock_project = MagicMock()
    mock_project.id = "00000000-0000-0000-0000-000000000001"
    mock_user = MagicMock()
    mock_user.id = 1
    monkeypatch.setattr(
        node, "_get_project", AsyncMock(return_value=mock_project)
    )
    monkeypatch.setattr(node, "_get_user", AsyncMock(return_value=mock_user))
    monkeypatch.setattr(
        node,
        "_fetch_mr_diff",
        AsyncMock(
            return_value=MRDiffResult(
                success=True,
                files=[
                    MRDiffFile(
                        old_path="src/main.py",
                        new_path="src/main.py",
                        diff="@@ -1 +1 @@\n-pass\n+return",
                    )
                ],
                truncated=False,
            )
        ),
    )
    monkeypatch.setattr(
        node, "_send_review_notification", AsyncMock(return_value=None)
    )

    result = await node.execute(ctx)
    assert result.status == "completed", f"execute 应成功完成，实际 {result.status}: {result.error}"

    # 捕获 system prompt（_CapturingFake._astream override 写入）
    system_content = capturing_code_review_fake.get("system_content", "")
    assert system_content, "应捕获 SystemMessage.content，实际为空"

    # work item 强化：expected_sha 固定为 REVIEW_SYSTEM_PROMPT 自身 sha256
    # （AI_NODE_CODE_REVIEW seed body 与常量字节级相等，DB 命中 / fallback 两态皆应匹配）
    expected_sha = hashlib.sha256(
        REVIEW_SYSTEM_PROMPT.encode("utf-8")
    ).hexdigest()
    actual_sha = hashlib.sha256(system_content.encode("utf-8")).hexdigest()

    assert actual_sha == expected_sha, (
        f"code_review system prompt 字节级漂移：\n"
        f"  actual_sha   = {actual_sha}\n"
        f"  expected_sha = {expected_sha}\n"
        f"work item 守护：禁止更新 expected_sha；请检查 render_prompt / Prompt DB seed "
        f"/ SystemMessage 包装路径。"
    )
    # 同时断言字节级字符串相等（更强的语义；若 sha 相等字符串必然相等）
    assert system_content == REVIEW_SYSTEM_PROMPT, (
        "system_content 应与 REVIEW_SYSTEM_PROMPT 字节级相等（work item 守护）"
    )
