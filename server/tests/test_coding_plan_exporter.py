"""coding_plan_exporter 单元测试（implementation / work item）。

覆盖：
    1. 文档 markdown 结构 4 段标题 + 生成时间段
    2. 影响文件表格渲染（含缺字段降级）
    3. 多仓状态表格（completed / running 双行）
    4. ``feishu_doc_token`` / ``feishu_doc_url`` 回填到 DB
    5. 创建失败时不静默吞异常 + 不写空 token
    6. 关联 SubAgentSession.task_result.commit_sha 显示前 7 位
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async

from chat.models import CodingPlan, CodingSession, Conversation
from feishu.coding_plan_exporter import export_coding_plan_to_feishu
from projects.models import Space
from repositories.models import Repository
from services.feishu_doc import FeishuDocAPIError


@sync_to_async
def _create_plan(
    *,
    title: str = "示例方案",
    tech_plan: str = "## 概要\n\n说明",
    affected_files: list[dict[str, str]] | None = None,
    provenance: str | None = None,
) -> CodingPlan:
    """异步友好工厂：sync ORM 写入 Space + Conversation + CodingPlan。

    ``provenance`` 缺省走 DB default ``draft``（存量真实形态）；显式传值可覆盖，
    含 choices 之外的未知取值（模型层不做 choices 校验，正是保守分支要防的情形）。
    """
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    project = Space.objects.create(
        name=f"导出测试项目-285-{suffix}",
        feishu_project_key=f"p285-{suffix}",
        feishu_doc_folder_token="fk_test",
        feishu_app_id="cli_test",
        feishu_app_secret_encrypted="enc_test",
    )
    conversation = Conversation.objects.create(space=project, title="对话-285")
    extra: dict[str, str] = {} if provenance is None else {"provenance": provenance}
    return CodingPlan.objects.create(
        conversation=conversation,
        title=title,
        tech_plan=tech_plan,
        affected_files=affected_files or [],
        **extra,
    )


@sync_to_async
def _create_session(
    plan: CodingPlan,
    *,
    repo_name: str,
    branch_name: str = "feat20260520.x",
    status: str = CodingSession.Status.DRAFT,
    pr_url: str = "",
    commit_sha: str = "",
) -> CodingSession:
    """构造 CodingSession + Repository + 可选 SubAgentSession 承载 commit_sha。"""
    from uuid import uuid4

    suffix = uuid4().hex[:6]
    repo = Repository.objects.create(
        name=f"{repo_name}-{suffix}",
        git_url=f"https://gitlab.example.com/ns/{repo_name}-{suffix}.git",
        git_platform="gitlab",
        default_branch="main",
    )
    subagent_session = None
    if commit_sha:
        from agents.models import AgentSession
        from subagent.models import SubAgentSession, TaskResult

        main = AgentSession.objects.create(
            session_id=f"main-{repo_name}-{suffix}",
            status=AgentSession.Status.COMPLETED,
        )
        subagent_session = SubAgentSession.objects.create(
            session_id=f"sa-{repo_name}-{suffix}",
            main_session=main,
            repo_url=repo.git_url,
            task_type=SubAgentSession.TaskType.CODING,
        )
        TaskResult.objects.create(
            session=subagent_session,
            result_type=TaskResult.ResultType.GIT,
            commit_sha=commit_sha,
            branch_name=branch_name,
        )
    return CodingSession.objects.create(
        conversation=plan.conversation,
        coding_plan=plan,
        repository=repo,
        branch_name=branch_name,
        status=status,
        pr_url=pr_url,
        subagent_session=subagent_session,
        tech_plan="",
        affected_files=[],
    )


@sync_to_async
def _refresh_plan(plan: CodingPlan) -> CodingPlan:
    plan.refresh_from_db()
    return plan


def _make_mock_client(
    document_id: str = "doxcnTEST",
    url: str = "https://feishu.cn/docx/doxcnTEST",
    create_side_effect: Any = None,
) -> AsyncMock:
    """构造一个 ``FeishuDocClient`` mock（仅暴露 ``create_document`` async 方法）。"""
    client = AsyncMock()
    if create_side_effect is not None:
        client.create_document = AsyncMock(side_effect=create_side_effect)
    else:
        client.create_document = AsyncMock(
            return_value={"document_id": document_id, "url": url}
        )
    return client


# ---------------------------------------------------------------------------
# Test 1：导出后 markdown 包含 4 段标题 + 生成时间段
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_export_writes_heading_and_sections() -> None:
    plan = await _create_plan(title="标题 X", tech_plan="# A\n\n段落")
    mock_client = _make_mock_client()

    result = await export_coding_plan_to_feishu(
        plan, "folder_T", doc_client=mock_client
    )

    mock_client.create_document.assert_awaited_once()
    kwargs = mock_client.create_document.await_args.kwargs
    content = kwargs["content"]
    assert "# 标题 X" in content
    assert "## 技术方案" in content
    assert "## 影响文件" in content
    assert "## 目标仓库与编码状态" in content
    assert "生成时间：" in content
    assert kwargs["title"] == "标题 X"
    assert kwargs["folder_token"] == "folder_T"
    assert result == {
        "doc_token": "doxcnTEST",
        "doc_url": "https://feishu.cn/docx/doxcnTEST",
    }


# ---------------------------------------------------------------------------
# Test 2：影响文件表格 + 多行
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_affected_files_table() -> None:
    plan = await _create_plan(
        affected_files=[
            {"file_path": "a.py", "change_type": "modify"},
            {"file_path": "b.ts", "change_type": "add"},
        ],
    )
    mock_client = _make_mock_client()
    await export_coding_plan_to_feishu(plan, "folder_T", doc_client=mock_client)
    content = mock_client.create_document.await_args.kwargs["content"]
    assert "| a.py | modify |" in content
    assert "| b.ts | add |" in content


# ---------------------------------------------------------------------------
# Test 3：多仓状态表（含 commit_sha 截取与 PR / commit 空降级）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_repo_status_table_with_completed_and_running() -> None:
    plan = await _create_plan()
    await _create_session(
        plan,
        repo_name="example-app",
        branch_name="fix20260520.alpha",
        status=CodingSession.Status.COMPLETED,
        pr_url="https://gitlab.example.com/ns/example-app/-/merge_requests/123",
        commit_sha="abcdef1234567890",
    )
    await _create_session(
        plan,
        repo_name="friday-server",
        branch_name="fix20260520.beta",
        status=CodingSession.Status.RUNNING,
    )

    mock_client = _make_mock_client()
    await export_coding_plan_to_feishu(plan, "folder_T", doc_client=mock_client)
    content = mock_client.create_document.await_args.kwargs["content"]

    assert "example-app" in content
    assert "✅ 已完成" in content
    assert "abcdef1" in content
    assert "merge_requests/123" in content

    assert "friday-server" in content
    assert "⏳ 进行中" in content
    # running 行 PR 与 commit 双 — 兜底
    running_line = next(
        line
        for line in content.splitlines()
        if "friday-server" in line and "⏳ 进行中" in line
    )
    assert running_line.endswith("| — | — |")


# ---------------------------------------------------------------------------
# Test 4：回填 feishu_doc_token / feishu_doc_url 到 DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_writeback_token_and_url() -> None:
    plan = await _create_plan()
    mock_client = _make_mock_client(
        document_id="doxcnNEW", url="https://feishu.cn/docx/doxcnNEW"
    )

    await export_coding_plan_to_feishu(plan, "folder_T", doc_client=mock_client)

    plan = await _refresh_plan(plan)
    assert plan.feishu_doc_token == "doxcnNEW"
    assert plan.feishu_doc_url == "https://feishu.cn/docx/doxcnNEW"


# ---------------------------------------------------------------------------
# Test 5：create_document 抛 FeishuDocAPIError 时 token 不应被回写
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_create_document_failure_raises_and_does_not_writeback() -> None:
    plan = await _create_plan()
    mock_client = _make_mock_client(create_side_effect=FeishuDocAPIError("boom"))

    with pytest.raises(FeishuDocAPIError):
        await export_coding_plan_to_feishu(plan, "folder_T", doc_client=mock_client)

    plan = await _refresh_plan(plan)
    assert plan.feishu_doc_token == ""
    assert plan.feishu_doc_url == ""


# ---------------------------------------------------------------------------
# Test 6：affected_files 缺 change_type 字段时降级 "—" 不抛异常
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_affected_files_missing_field_falls_back() -> None:
    plan = await _create_plan(
        affected_files=[{"file_path": "x.py"}],
    )
    mock_client = _make_mock_client()

    await export_coding_plan_to_feishu(plan, "folder_T", doc_client=mock_client)
    content = mock_client.create_document.await_args.kwargs["content"]
    assert "| x.py | — |" in content


# ---------------------------------------------------------------------------
# Test 7：title 参数覆盖 coding_plan.title
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_title_param_overrides_plan_title() -> None:
    plan = await _create_plan(title="默认标题")
    mock_client = _make_mock_client()

    await export_coding_plan_to_feishu(
        plan, "folder_T", title="自定义标题", doc_client=mock_client
    )
    kwargs = mock_client.create_document.await_args.kwargs
    assert kwargs["title"] == "自定义标题"
    assert "# 自定义标题" not in kwargs["content"]  # markdown body 仍用 plan.title
    assert "# 默认标题" in kwargs["content"]


# ---------------------------------------------------------------------------
# Test 8：空 sessions 时表格使用 — 占位行，不抛异常
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_empty_sessions_renders_placeholder_row() -> None:
    plan = await _create_plan()
    mock_client = _make_mock_client()

    await export_coding_plan_to_feishu(plan, "folder_T", doc_client=mock_client)
    content = mock_client.create_document.await_args.kwargs["content"]
    # 多仓表标题下应有一行 — 占位
    assert "| — | — | — | — | — |" in content


# ---------------------------------------------------------------------------
# Test 9-13：RELY-01 草稿「未经代码调研」告示（导出侧，第二出口）
# ---------------------------------------------------------------------------

# 界面侧（`TechPlanCard` 草稿横幅）文案，逐字取自 109-UI-SPEC §Copywriting Contract。
# 写成字面量常量而非 import 前端：双侧口径一致性靠这两段字面量锁住 —— 前端常量若变更
# 而未同步导出侧，下方 test_draft_notice_matches_ui_side_copy 会红。
_UI_DRAFT_HEADLINE = "本方案未经代码调研"
_UI_DRAFT_SUBLINE = (
    "由对话直接生成，未经仓库路由、代码召回与并行调研，文件清单与实现步骤可能不准确。"
)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_draft_notice_precedes_tech_plan_body() -> None:
    """provenance=draft → 告示出现且位于技术方案正文之前。"""
    from chat.models import CodingPlanProvenance

    body = "## 我的方案正文\n\n步骤一"
    plan = await _create_plan(tech_plan=body, provenance=CodingPlanProvenance.DRAFT)
    mock_client = _make_mock_client()

    await export_coding_plan_to_feishu(plan, "folder_T", doc_client=mock_client)
    content = mock_client.create_document.await_args.kwargs["content"]

    assert _UI_DRAFT_HEADLINE in content
    # 位置断言：用户读到任何方案内容前先看到「这份东西未经调研」。
    assert content.index(_UI_DRAFT_HEADLINE) < content.index("## 我的方案正文")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_orchestrated_plan_has_no_draft_notice() -> None:
    """provenance=orchestrated → 不含告示主句（唯一免标注的取值）。"""
    from chat.models import CodingPlanProvenance

    plan = await _create_plan(provenance=CodingPlanProvenance.ORCHESTRATED)
    mock_client = _make_mock_client()

    await export_coding_plan_to_feishu(plan, "folder_T", doc_client=mock_client)
    content = mock_client.create_document.await_args.kwargs["content"]

    assert _UI_DRAFT_HEADLINE not in content


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_unknown_provenance_still_gets_draft_notice_and_hides_raw_value() -> None:
    """未知 provenance 取值 → 仍标注（允许清单），且文档不回显原始取值。"""
    plan = await _create_plan(provenance="weird_value")
    mock_client = _make_mock_client()

    await export_coding_plan_to_feishu(plan, "folder_T", doc_client=mock_client)
    content = mock_client.create_document.await_args.kwargs["content"]

    assert _UI_DRAFT_HEADLINE in content
    # 上游非受控取值上屏即泄漏面：判定读它，但绝不把它写进文档。
    assert "weird_value" not in content


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_draft_notice_kept_when_tech_plan_empty() -> None:
    """空 tech_plan + draft → 告示仍在，且既有「（暂无技术方案文本）」兜底不受影响。"""
    from chat.models import CodingPlanProvenance

    plan = await _create_plan(tech_plan="", provenance=CodingPlanProvenance.DRAFT)
    mock_client = _make_mock_client()

    await export_coding_plan_to_feishu(plan, "folder_T", doc_client=mock_client)
    content = mock_client.create_document.await_args.kwargs["content"]

    assert _UI_DRAFT_HEADLINE in content
    assert "（暂无技术方案文本）" in content


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_draft_notice_matches_ui_side_copy() -> None:
    """双侧口径一致：导出文案包含界面侧主句与次行前半段（逐字）。

    导出侧仅在此之上追加一句行动指引 —— 导出物脱离上下文流转，多一句指引值得。
    """
    from chat.models import CodingPlanProvenance

    plan = await _create_plan(provenance=CodingPlanProvenance.DRAFT)
    mock_client = _make_mock_client()

    await export_coding_plan_to_feishu(plan, "folder_T", doc_client=mock_client)
    content = mock_client.create_document.await_args.kwargs["content"]

    assert _UI_DRAFT_HEADLINE in content
    assert _UI_DRAFT_SUBLINE in content
    assert "正式方案请经技术方案编排产出。" in content
