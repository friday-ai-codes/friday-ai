"""CompletionWritebackService 公共回写服务单测（LOOP-01 / Phase 101）。

覆盖三路语义：
- skip：三元组缺失（work_item_id=None）/ space 反查不到 → 双 skipped 且不触飞书客户端；
- 成功：文档 append + 工作项评论双写，入参与文案断言（含 "Friday 已更新执行结果："）；
- 失败：评论抛异常 → comment error 且不上抛，document 分支不受影响。

另断言 ``render_results_markdown`` 模板与 MCP ``_execution_results_markdown``
现状逐字一致（标题/表头/行格式/反引号——零回归前提）。

服务经异步 ORM 反查 Space——DB 用例须 transaction=True（跨线程连接写入）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from asgiref.sync import sync_to_async

from delivery.models import Artifact, ArtifactVersion, WorkItem, WorkItemOrigin
from delivery.services.coding_completion import (
    CompletionWritebackService,
    RepoResult,
    aresolve_triple_for_coding_session,
    aresolve_triple_from_plan_version,
    render_comment_lines,
    render_results_markdown,
)
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)


class _FakeDocClient:
    def __init__(self) -> None:
        self.appended: list[dict[str, str]] = []

    async def append_markdown(self, document_id: str, content: str) -> dict[str, Any]:
        self.appended.append({"document_id": document_id, "content": content})
        return {"document_id": document_id, "appended_blocks": 3}


class _FakeFeishuClient:
    def __init__(self, ok: bool = True, exc: Exception | None = None) -> None:
        self.ok = ok
        self.exc = exc
        self.comments: list[dict[str, Any]] = []

    async def add_comment(
        self,
        project_key: str,
        work_item_id: int,
        work_item_type: str,
        content: str,
    ) -> bool:
        if self.exc is not None:
            raise self.exc
        self.comments.append(
            {
                "project_key": project_key,
                "work_item_id": work_item_id,
                "work_item_type": work_item_type,
                "content": content,
            }
        )
        return self.ok


def _results() -> list[RepoResult]:
    return [
        RepoResult(
            repo_name="web",
            status="completed",
            branch_name="feat/login",
            commit_sha="a" * 40,
            mr_url="https://example.com/mr/1",
        )
    ]


@pytest.mark.asyncio
async def test_missing_work_item_id_skips_without_feishu_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """三元组缺失（work_item_id=None）：双 skipped 且飞书客户端零调用。"""
    doc_factory = AsyncMock()
    comment_factory = MagicMock()
    monkeypatch.setattr(
        "delivery.services.coding_completion.create_feishu_doc_client_for_project",
        doc_factory,
    )
    monkeypatch.setattr(
        "delivery.services.coding_completion.create_feishu_client_for_project",
        comment_factory,
    )

    document_update, comment = await CompletionWritebackService().awrite_back(
        feishu_project_key="proj-key",
        work_item_type="story",
        work_item_id=None,
        title="登录改造",
        results=_results(),
        space=MagicMock(),
        feishu_document_id="doxcnPlan",
        doc_markdown="## 执行结果\n",
    )

    assert document_update == {"status": "skipped"}
    assert comment == {"status": "skipped"}
    doc_factory.assert_not_called()
    comment_factory.assert_not_called()


@pytest.mark.asyncio
async def test_space_not_found_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    """space=None 且 feishu_project_key 查无 Space：双 skipped。"""
    doc_factory = AsyncMock()
    comment_factory = MagicMock()
    monkeypatch.setattr(
        "delivery.services.coding_completion.create_feishu_doc_client_for_project",
        doc_factory,
    )
    monkeypatch.setattr(
        "delivery.services.coding_completion.create_feishu_client_for_project",
        comment_factory,
    )

    document_update, comment = await CompletionWritebackService().awrite_back(
        feishu_project_key="no-such-project-key",
        work_item_type="story",
        work_item_id=88,
        title="登录改造",
        results=_results(),
        space=None,
        feishu_document_id="doxcnPlan",
        doc_markdown="## 执行结果\n",
    )

    assert document_update == {"status": "skipped"}
    assert comment == {"status": "skipped"}
    doc_factory.assert_not_called()
    comment_factory.assert_not_called()


@pytest.mark.asyncio
async def test_success_path_appends_doc_and_writes_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功路径：文档 append + 评论双写，入参三元组与文案断言。"""
    space = await sync_to_async(Space.objects.create)(
        name="writeback-space",
        feishu_project_key="wb-key",
    )
    doc_client = _FakeDocClient()
    feishu_client = _FakeFeishuClient()

    async def _doc_factory(_space):
        return doc_client

    monkeypatch.setattr(
        "delivery.services.coding_completion.create_feishu_doc_client_for_project",
        _doc_factory,
    )
    monkeypatch.setattr(
        "delivery.services.coding_completion.create_feishu_client_for_project",
        lambda _space: feishu_client,
    )

    document_update, comment = await CompletionWritebackService().awrite_back(
        feishu_project_key="wb-key",
        work_item_type="story",
        work_item_id=88,
        title="多仓登录链路改造",
        results=_results(),
        space=space,
        feishu_document_id="doxcnPlan",
        doc_markdown="## 执行结果\n",
        initiated_by_user_id="u-1",
    )

    assert document_update["status"] == "appended"
    assert document_update["appended_blocks"] == 3
    assert comment == {"status": "written"}
    assert doc_client.appended == [{"document_id": "doxcnPlan", "content": "## 执行结果\n"}]

    posted = feishu_client.comments[0]
    assert posted["project_key"] == "wb-key"
    assert posted["work_item_id"] == 88
    assert posted["work_item_type"] == "story"
    assert posted["content"].startswith("Friday 已更新执行结果：多仓登录链路改造")
    assert "- web: completed, branch `feat/login`, MR https://example.com/mr/1" in posted["content"]


@pytest.mark.asyncio
async def test_comment_error_does_not_raise_and_doc_unaffected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """评论抛异常：comment error 且不上抛，document 分支照常 append。"""
    space = await sync_to_async(Space.objects.create)(
        name="writeback-space-err",
        feishu_project_key="wb-key-err",
    )
    doc_client = _FakeDocClient()

    async def _doc_factory(_space):
        return doc_client

    monkeypatch.setattr(
        "delivery.services.coding_completion.create_feishu_doc_client_for_project",
        _doc_factory,
    )
    monkeypatch.setattr(
        "delivery.services.coding_completion.create_feishu_client_for_project",
        lambda _space: _FakeFeishuClient(exc=RuntimeError("feishu comment down")),
    )

    document_update, comment = await CompletionWritebackService().awrite_back(
        feishu_project_key="wb-key-err",
        work_item_type="story",
        work_item_id=88,
        title="多仓登录链路改造",
        results=_results(),
        space=space,
        feishu_document_id="doxcnPlan",
        doc_markdown="## 执行结果\n",
    )

    assert document_update["status"] == "appended"
    assert comment == {"status": "error", "error": "feishu comment down"}
    assert len(doc_client.appended) == 1


@pytest.mark.asyncio
async def test_upstream_exception_text_redacted_before_persistable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """凭证泄漏守卫（101 WR-02）：上游异常文本含密钥 → 返回 error 字段已脱敏。

    返回 dict 会被 MCP 薄包装持久化到 ``technical_plan.error`` / ``comment_result``
    （DB 直写无 processor/ledger 兜底），故 ``awrite_back`` 出口必须已脱敏。
    """
    secret = "sk-ant-api03-verysecretcredential1234567890"
    space = await sync_to_async(Space.objects.create)(
        name="writeback-space-secret",
        feishu_project_key="wb-key-secret",
    )

    async def _doc_factory(_space):
        raise RuntimeError(f"upstream 401: Authorization: Bearer {secret}")

    monkeypatch.setattr(
        "delivery.services.coding_completion.create_feishu_doc_client_for_project",
        _doc_factory,
    )
    monkeypatch.setattr(
        "delivery.services.coding_completion.create_feishu_client_for_project",
        lambda _space: _FakeFeishuClient(exc=RuntimeError(f"comment failed with key {secret}")),
    )

    document_update, comment = await CompletionWritebackService().awrite_back(
        feishu_project_key="wb-key-secret",
        work_item_type="story",
        work_item_id=88,
        title="登录改造",
        results=_results(),
        space=space,
        feishu_document_id="doxcnPlan",
        doc_markdown="## 执行结果\n",
    )

    assert document_update["status"] == "error"
    assert comment["status"] == "error"
    assert secret not in document_update["error"]
    assert secret not in comment["error"]
    assert "REDACTED" in document_update["error"]
    assert "REDACTED" in comment["error"]


def test_render_results_markdown_matches_mcp_template() -> None:
    """渲染模板与 MCP ``_execution_results_markdown`` 现状逐字一致。"""
    result = RepoResult(
        repo_name="web",
        status="completed",
        branch_name="feat/login",
        commit_sha="abc123",
        mr_url="https://example.com/mr/1",
        error="",
    )
    markdown = render_results_markdown([result])
    lines = markdown.split("\n")

    assert lines[0] == "## 执行结果"
    assert lines[1] == ""
    assert lines[2].startswith("更新时间：")
    assert lines[3] == ""
    assert lines[4] == "| 仓库 | 状态 | 分支 | Commit | PR/MR | 错误 |"
    assert lines[5] == "|---|---|---|---|---|---|"
    assert lines[6] == "| web | completed | `feat/login` | `abc123` | https://example.com/mr/1 |  |"
    assert markdown.endswith("|\n")


# ---------------------------------------------------------------------------
# 三元组反查器（LOOP-02 / 101-03）
# ---------------------------------------------------------------------------


async def _make_work_item_chain(*, content: dict | None = None) -> tuple[WorkItem, ArtifactVersion]:
    """构造 WorkItem → Artifact → ArtifactVersion 链（正向反查用）。"""
    space = await Space.objects.acreate(
        name="triple-space",
        feishu_project_key="triple-key",
    )
    work_item = await WorkItem.objects.acreate(
        feishu_project_key="triple-key",
        work_item_type="story",
        work_item_id=88,
        title="多仓登录链路改造",
        space=space,
        origin=WorkItemOrigin.MANUAL,
    )
    artifact = await Artifact.objects.acreate(
        artifact_type="technical_plan",
        work_item=work_item,
    )
    version = await ArtifactVersion.objects.acreate(
        artifact=artifact,
        version_no=1,
        content=content or {},
    )
    return work_item, version


@pytest.mark.asyncio
async def test_resolve_triple_from_plan_version_hits_work_item() -> None:
    """workflow 链正向：plan_version_id → ArtifactVersion → artifact.work_item 命中三元组。"""
    work_item, version = await _make_work_item_chain()

    triple = await aresolve_triple_from_plan_version(str(version.id))

    assert triple is not None
    assert triple.feishu_project_key == "triple-key"
    assert triple.work_item_type == "story"
    assert triple.work_item_id == 88
    assert triple.title == "多仓登录链路改造"
    assert triple.space_id == str(work_item.space_id)


@pytest.mark.asyncio
async def test_resolve_triple_from_plan_version_broken_chain_returns_none() -> None:
    """断链：Artifact 未绑定 work_item → None（fail-soft，无异常）。"""
    artifact = await Artifact.objects.acreate(artifact_type="technical_plan", work_item=None)
    version = await ArtifactVersion.objects.acreate(artifact=artifact, version_no=1)

    assert await aresolve_triple_from_plan_version(str(version.id)) is None
    assert await aresolve_triple_from_plan_version(None) is None
    assert await aresolve_triple_from_plan_version("not-a-uuid") is None


@pytest.mark.asyncio
async def test_resolve_triple_for_coding_session_via_json_key() -> None:
    """chat 链正向：ArtifactVersion.content 埋 chat_coding_plan_id → 命中三元组。"""
    plan_id = "11111111-2222-3333-4444-555555555555"
    _work_item, _version = await _make_work_item_chain(
        content={"chat_coding_plan_id": plan_id},
    )
    coding_session = MagicMock()
    coding_session.coding_plan_id = plan_id

    triple = await aresolve_triple_for_coding_session(coding_session)

    assert triple is not None
    assert triple.work_item_id == 88
    assert triple.feishu_project_key == "triple-key"


@pytest.mark.asyncio
async def test_resolve_triple_for_coding_session_current_state_returns_none() -> None:
    """现状路径：普通 coding_plan（无 ArtifactVersion 埋键）→ None（零行为变化）。"""
    coding_session = MagicMock()
    coding_session.coding_plan_id = "99999999-8888-7777-6666-555555555555"

    assert await aresolve_triple_for_coding_session(coding_session) is None

    # coding_plan 未绑定 → 直接 None（不触 DB）。
    coding_session.coding_plan_id = None
    assert await aresolve_triple_for_coding_session(coding_session) is None


def test_render_comment_lines_matches_mcp_wording() -> None:
    """评论文案逐字一致：标题行 + 空行 + 仓库状态 + 逐仓行（未生成兜底）。"""
    content = render_comment_lines(
        "多仓登录链路改造",
        [RepoResult(repo_name="server", status="partial", branch_name="feat/x")],
    )
    assert content == (
        "Friday 已更新执行结果：多仓登录链路改造\n"
        "\n"
        "仓库状态：\n"
        "- server: partial, branch `feat/x`, MR 未生成"
    )
