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

from delivery.services.coding_completion import (
    CompletionWritebackService,
    RepoResult,
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
