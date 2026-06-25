"""implementation + implementation Wave（task）：plan_generation prompt 迁移。

implementation 原 6 测试验证 Prompt Center render_prompt 三态行为 + `.replace` 字节级等价，
**不触及** LLM 调用（迁移前老 SDK 客户端 / httpx-level mock 均无，node.execute 链路也不跑）。

implementation Wave（work item / contract）补强：新增 `_CapturingFake` seam 经
``fake_chat_model_factory`` 共用 fixture 注入到 ``build_chat_model``，驱动真实
AIPlanGenerationNode.execute() 跑到 LangChainAgentRunner.stream 首轮 invoke，
捕获 ``SystemMessage.content`` 做字节级 sha256 断言（contract）。

关键守护（work item 强化）：
- 本 plan 执行前文件内无任何硬编码 expected sha 值（Ground truth = None）
- 新增字节级测试**动态计算** expected hash（从相同 Prompt Center 渲染路径 +
  fixture 固定的 execution_id / node_id / 空 system_prompt 配置得到），而非硬编码
- 任何 Prompt 渲染路径漂移（Jinja2 sandbox / _enhance_system_prompt 注入 /
  AIPlanGenerationNode._precomputed_base_prompt replace 口径变化）都会让
  actual/expected 同步漂移；真正守护的是"execute 捕获的 SystemMessage.content
  == 预计算 enhanced_prompt（包含 schema_json + session_id 注入）"契约
- 若未来改成硬编码 sha（Wave/5），此测试 expected_sha 仍由
  `fixture 固定 execution_id="test-exec-id-12345"` + `node_id="plan-gen-n1"`
  保证跨环境稳定
"""
from __future__ import annotations

import hashlib
import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from prompts.keys import PromptSlugs
from prompts.models import Prompt, PromptScope, PromptVersion
from prompts.services import render_prompt
from tests.helpers.fake_chat_model import FakeChatModel
from workflows.nodes.ai.plan_generation import (
    _PLAN_GENERATION_BASE_PROMPT,
    TECHNICAL_PLAN_JSON_SCHEMA,
    AIPlanGenerationNode,
)


@pytest.mark.django_db(transaction=True)
class TestPlanGenerationMigration:

    @pytest.fixture(autouse=True)
    def _ensure_seed(self, db: Any) -> None:
        """每个测试开始前确保 AI_NODE_PLAN_GENERATION seed 存在。"""
        if not Prompt.objects.filter(
            slug=PromptSlugs.AI_NODE_PLAN_GENERATION,
            scope=PromptScope.SYSTEM,
        ).exists():
            prompt = Prompt.objects.create(
                slug=PromptSlugs.AI_NODE_PLAN_GENERATION,
                scope=PromptScope.SYSTEM,
                space=None,
                category="ai_node",
                title="AI 节点 - 方案生成",
                description="implementation test re-seed",
                is_builtin=True,
            )
            version = PromptVersion.objects.create(
                prompt=prompt,
                version=1,
                body=_PLAN_GENERATION_BASE_PROMPT,
                variables_schema={},
                change_note="test re-seed",
            )
            prompt.active_version = version
            prompt.save(update_fields=["active_version", "updated_at"])

    @pytest.mark.asyncio
    async def test_render_prompt_db_hit_xml_wraps_schema_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """implementation 行为参考：render_prompt DB 命中路径会 XML 包裹变量 & 触发截断。

        本测试记录 implementation services.render_prompt 的行为。implementation 的
        plan_generation.execute() **不**走此路径（contract retreat），而是手工读取
        get_active_prompt + str.replace，见
        test_execute_schema_json_not_truncated_by_retreat_path。
        """
        monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
        result = await render_prompt(
            PromptSlugs.AI_NODE_PLAN_GENERATION,
            project_id=None,
            variables={"schema_json": "MY_SCHEMA_PLACEHOLDER"},
            fallback=_PLAN_GENERATION_BASE_PROMPT,
        )
        # DB 命中路径变量被 _sanitize_variables XML tag 包裹
        assert "<schema_json>MY_SCHEMA_PLACEHOLDER</schema_json>" in result

    @pytest.mark.asyncio
    async def test_execute_schema_json_not_truncated_by_retreat_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """contract retreat（work item regression fix）：schema_json 4KB+ 在 execute() 预渲染后
        必须保留完整内容，不被 implementation _sanitize_variables 的 1024 字符截断。

        implementation code review work item 发现：schema_json 实测 4432 字符，走 render_prompt
        会被截到 1024 → 切在中间产生残缺 JSON → LLM 看到 garbage。
        修复策略：plan_generation.execute() 改为手工 get_active_prompt + str.replace，
        绕过 Jinja2 sandbox + 清洗流程（符合 work-item contract 的 retreat 机制）。
        """
        from prompts.services import get_active_prompt

        monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)

        schema_json = json.dumps(TECHNICAL_PLAN_JSON_SCHEMA, ensure_ascii=False, indent=2)
        # 前置假设：schema_json 必须 > 1024 字符才能真正触发 work item regression
        assert len(schema_json) > 1024, (
            f"TECHNICAL_PLAN_JSON_SCHEMA 必须 > 1024 字符才能验证 work item 修复 "
            f"(实测 {len(schema_json)})"
        )

        # 模拟 execute() 的 retreat 逻辑
        version = await get_active_prompt(
            PromptSlugs.AI_NODE_PLAN_GENERATION, project_id=None
        )
        assert version is not None, "fixture 应已种入 seed"
        body_template = version.body
        rendered = body_template.replace("{{schema_json}}", schema_json)

        # work item 回归断言：
        # 1. 完整 schema_json 必须出现在 rendered 里（未被截到 1024）
        assert schema_json in rendered, (
            "work item regression: schema_json 被截断或未完整替换"
        )
        # 2. 没有 XML tag 包裹（contract retreat 绕过了 _sanitize_variables）
        assert "<schema_json>" not in rendered, (
            "work item regression: 预渲染不应使用 XML tag 包裹路径"
        )
        # 3. rendered 长度应大致 = base_prompt 长度 - 占位符长度 + schema_json 长度
        expected_len = len(body_template) - len("{{schema_json}}") + len(schema_json)
        assert len(rendered) == expected_len, (
            f"长度不匹配: expected {expected_len}, got {len(rendered)}"
        )

    @pytest.mark.asyncio
    async def test_db_empty_fallback_byte_equivalent(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """DB 空路径：走 _render_fallback regex 替换 — 与直接 str.replace 字节级等价。"""
        monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
        await Prompt.objects.filter(
            slug=PromptSlugs.AI_NODE_PLAN_GENERATION,
            scope=PromptScope.SYSTEM,
        ).adelete()
        schema_json = json.dumps(TECHNICAL_PLAN_JSON_SCHEMA, ensure_ascii=False, indent=2)
        result = await render_prompt(
            PromptSlugs.AI_NODE_PLAN_GENERATION,
            project_id=None,
            variables={"schema_json": schema_json},
            fallback=_PLAN_GENERATION_BASE_PROMPT,
        )
        expected = _PLAN_GENERATION_BASE_PROMPT.replace("{{schema_json}}", schema_json)
        assert result == expected

    @pytest.mark.asyncio
    async def test_flag_disabled_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """flag 禁用：走 fallback 路径。"""
        monkeypatch.setenv("PROMPT_CENTER_DISABLED_KEYS", "ai_node.plan_generation.system")
        schema_json = json.dumps(TECHNICAL_PLAN_JSON_SCHEMA, ensure_ascii=False, indent=2)
        result = await render_prompt(
            PromptSlugs.AI_NODE_PLAN_GENERATION,
            project_id=None,
            variables={"schema_json": schema_json},
            fallback=_PLAN_GENERATION_BASE_PROMPT,
        )
        assert "<schema_json>" not in result  # 证明未走 DB 清洗
        assert schema_json in result  # 证明 fallback 替换成功

    def test_hook_uses_precomputed_when_set(self) -> None:
        """get_system_prompt 在 _precomputed_base_prompt 被预填时优先返回它。"""
        node = AIPlanGenerationNode()
        node._precomputed_base_prompt = "PRECOMPUTED_SENTINEL"
        ctx = MagicMock()
        ctx.node_config = {}
        result = node.get_system_prompt(ctx)
        assert result == "PRECOMPUTED_SENTINEL"

    def test_hook_falls_back_to_f_string_when_not_set(self) -> None:
        """get_system_prompt 在 _precomputed_base_prompt 为 None 时走降级路径(与迁移前字节级等价)。"""
        node = AIPlanGenerationNode()
        # 默认 __init__ 里已设为 None
        node._precomputed_base_prompt = None
        ctx = MagicMock()
        ctx.node_config = {}
        result = node.get_system_prompt(ctx)
        schema_json = json.dumps(TECHNICAL_PLAN_JSON_SCHEMA, ensure_ascii=False, indent=2)
        expected = _PLAN_GENERATION_BASE_PROMPT.replace("{{schema_json}}", schema_json)
        assert result == expected

    # ================================================================
    # implementation Wave（task）：`_CapturingFake` + execute()
    # 链路字节级 hash 守护（work item / contract / Pattern 8）
    # ================================================================

    @pytest.mark.asyncio
    async def test_execute_system_prompt_byte_equal_via_capturing_fake(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_chat_model_factory: Any,
        mock_aresolve_ok: Any,
        make_minimal_context: Any,
    ) -> None:
        """``_CapturingFake`` 捕获 ``SystemMessage.content`` 做字节级 sha256 断言。

        work item 强化：
        - ``expected_sha`` 由同一 Prompt Center 渲染路径 + 固定 ``execution_id`` /
          ``node_id`` 动态计算（无硬编码）
        - 固定 ``make_minimal_context`` 默认 ``execution_id="test-exec-id-12345"`` /
          ``node_id="n1"``，使 ``_enhance_system_prompt`` 注入的
          ``session_id=wf-{exec}-{node}`` 稳定；修改这两个常量即触发
          expected ↔ actual 双向漂移，守护"execute 路径 Prompt 构造契约不变"。
        """
        # 1. `_CapturingFake` —— 在 `fake_chat_model_factory` 注入的 fake 前再裹一层
        captured: dict[str, Any] = {}

        def _capture(messages: list[Any]) -> None:
            """Capture SystemMessage / HumanMessage contents from runner messages。"""
            if captured:
                return  # 仅捕获首次（第一 turn），避免后续 ToolMessage 覆盖
            captured["all_contents"] = [
                getattr(m, "content", "") or str(m) for m in messages
            ]
            captured["system_content"] = next(
                (
                    getattr(m, "content", "")
                    for m in messages
                    if isinstance(m, SystemMessage)
                ),
                "",
            )
            captured["human_content"] = next(
                (
                    getattr(m, "content", "")
                    for m in messages
                    if isinstance(m, HumanMessage)
                ),
                "",
            )

        class _CapturingFake(FakeChatModel):
            async def ainvoke(
                self, input_: Any, config: Any = None, **kwargs: Any
            ) -> Any:
                if isinstance(input_, list):
                    _capture(input_)
                return await super().ainvoke(input_, config, **kwargs)

            async def _astream(  # type: ignore[override]
                self,
                messages: list[Any],
                stop: list[str] | None = None,
                run_manager: Any = None,
                **kwargs: Any,
            ) -> Any:
                if isinstance(messages, list):
                    _capture(messages)
                async for chunk in super()._astream(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                ):
                    yield chunk

        capturing = _CapturingFake(responses=["方案生成完成"])
        # 先用 factory 注入 5 路 seam（含 workflows.nodes.ai.base_agent.build_chat_model），
        # 再用 _CapturingFake 覆盖 agents.llm_factory 与 agents.langchain_runner 两个权威入口
        fake_chat_model_factory(responses=["sentinel"])
        monkeypatch.setattr(
            "agents.llm_factory.build_chat_model",
            lambda *a, **kw: capturing,
        )
        monkeypatch.setattr(
            "agents.langchain_runner.build_chat_model",
            lambda *a, **kw: capturing,
            raising=False,
        )
        mock_aresolve_ok(source="system", provider_type="anthropic")

        # 2. Stub project / user / AgentSession：避免真实 DB 外键
        async def _stub_get_project(self: Any, context: Any) -> Any:
            mock_project = MagicMock()
            mock_project.id = "00000000-0000-0000-0000-000000000001"
            mock_project.feishu_doc_folder_token = "folder_token_123"
            return mock_project

        async def _stub_get_user(self: Any, context: Any) -> Any:
            return MagicMock(id=1)

        async def _stub_ensure_session(
            self: Any, session_id: str, project: Any, user: Any, chat_id: str
        ) -> None:
            return None

        monkeypatch.setattr(
            "workflows.nodes.ai.base_agent.AIAgentBaseNode._get_project",
            _stub_get_project,
        )
        monkeypatch.setattr(
            "workflows.nodes.ai.base_agent.AIAgentBaseNode._get_user",
            _stub_get_user,
        )
        monkeypatch.setattr(
            "workflows.nodes.ai.base_agent.AIAgentBaseNode._ensure_agent_session",
            _stub_ensure_session,
        )

        # 3. 固定 execution_id / node_id 使 session_id 稳定（work item 强化）
        exec_id = "test-exec-id-12345"
        node_id_val = "plan-gen-n1"
        ctx = make_minimal_context(
            execution_id=exec_id,
            node_id=node_id_val,
            node_config={
                "user_prompt": "实现用户认证模块",
                "model": "claude-sonnet-4-20250514",
                "chat_id": "",  # 空 chat_id → _ensure_agent_session 即便不 stub 也跳过 DB
            },
        )
        node = AIPlanGenerationNode()
        result = await node.execute(ctx)
        assert result.status in ("completed", "failed"), (
            f"执行应走到 ainvoke（不论结果如何），实际 result={result!r}"
        )

        # 4. 动态计算 expected system prompt（与 execute() 内完全相同的渲染路径）
        schema_json = json.dumps(
            TECHNICAL_PLAN_JSON_SCHEMA, ensure_ascii=False, indent=2
        )
        base_prompt = _PLAN_GENERATION_BASE_PROMPT.replace(
            "{{schema_json}}", schema_json
        )
        # DB 命中路径：execute() 会用 Prompt Center DB body（_ensure_seed 已种入 _PLAN_GENERATION_BASE_PROMPT）
        # 故 body_template == _PLAN_GENERATION_BASE_PROMPT，字节级等价
        session_id = f"wf-{exec_id}-{node_id_val}"
        expected_enhanced = (
            f"{base_prompt}\n\n"
            f"[System Info]\n"
            f"- session_id: {session_id}\n"
            f"When calling tools that require session_id, always use: {session_id}"
        )

        # 5. 字节级 sha256 断言
        assert "system_content" in captured, (
            "`_CapturingFake.ainvoke` 未捕获到 input messages —— seam 脱靶"
        )
        actual_system = captured["system_content"]
        actual_sha = hashlib.sha256(actual_system.encode("utf-8")).hexdigest()
        expected_sha = hashlib.sha256(
            expected_enhanced.encode("utf-8")
        ).hexdigest()

        assert actual_sha == expected_sha, (
            f"Plan generation system prompt 字节级漂移：\n"
            f"  actual_sha   = {actual_sha}\n"
            f"  expected_sha = {expected_sha}\n"
            f"  actual(prefix 200) = {actual_system[:200]!r}\n"
            f"  expected(prefix 200) = {expected_enhanced[:200]!r}\n"
            f"work item 守护：禁止更新 expected hash；若语义确变，修 Prompt 路径"
            f"或 fixture 固定的 execution_id（当前 {exec_id}）而非 hash。"
        )
