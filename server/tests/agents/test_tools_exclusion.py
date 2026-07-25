"""Agent 工具读取面 fail-closed 排除守护测试（Phase 22 Plan 03，EXCL-02）。

覆盖进程内 chat/agent 工具：
- ``browse_file_content``：命中排除路径 → 拒读（chunks=[] + error 含 "excluded"，无明文）；
  fuzzy 解析到被排除真实路径同样拒读（防后缀绕过）；surface="browse_file_content" 审计。
- ``list_space_structure``：文件树过滤被排除文件。
- ``search_repository_code``：底层强行返回被排除项时由兜底过滤剔除（防御未来旁路回流）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from asgiref.sync import sync_to_async

from agents.tools.chat_tools import browse_file_content, list_space_structure
from agents.tools.space_tools import search_repository_code
from services.exclusion import ExclusionMatcher, ExclusionRuleSpec


def _env_matcher() -> ExclusionMatcher:
    return ExclusionMatcher([ExclusionRuleSpec(pattern=".env", rule_type="glob", source="global")])


# ============================================================================
# browse_file_content
# ============================================================================


async def test_browse_file_content_rejects_excluded_no_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """命中排除 file_path → chunks=[]、error 含 excluded、绝不返回明文。"""
    monkeypatch.setattr(
        "agents.tools.chat_tools.build_matcher_for_repo",
        AsyncMock(return_value=_env_matcher()),
    )
    # 即使底层 scroll 能返回明文，也不应被调用到（入口即拒）。
    scroll_mock = AsyncMock(return_value=[{"content": "SECRET=supersecret", "chunk_index": 0}])
    monkeypatch.setattr("agents.tools.chat_tools._scroll_file_from_collection", scroll_mock)
    log_mock = MagicMock()
    monkeypatch.setattr("agents.tools.chat_tools.log_exclusion_blocked", log_mock)

    res = await browse_file_content("repo-a", ".env")

    data = res.output["data"]
    assert data["chunks"] == []
    assert data["total_chunks"] == 0
    assert "excluded" in res.output["error"].lower()
    assert "supersecret" not in str(res.output)
    assert log_mock.call_args.kwargs["surface"] == "browse_file_content"


async def test_browse_file_content_fuzzy_resolved_excluded_cannot_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """requested 'env' 不命中，但 fuzzy 解析到真实 '.env' 命中 → 仍拒读（防绕过 T-22-09）。"""
    monkeypatch.setattr(
        "agents.tools.chat_tools.build_matcher_for_repo",
        AsyncMock(return_value=_env_matcher()),
    )
    # 首次严格匹配返回空 → 触发 fuzzy；fuzzy 解析出 .env。
    monkeypatch.setattr(
        "agents.tools.chat_tools._scroll_file_from_collection",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "agents.tools.chat_tools._list_indexed_paths",
        AsyncMock(return_value=[".env"]),
    )

    res = await browse_file_content("repo-a", "env")

    data = res.output["data"]
    assert data["chunks"] == []
    assert "excluded" in res.output["error"].lower()


async def test_browse_file_content_failclosed_on_matcher_build_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """匹配器构造异常 → fail-closed 拒读，不降级返回明文。"""
    monkeypatch.setattr(
        "agents.tools.chat_tools.build_matcher_for_repo",
        AsyncMock(side_effect=RuntimeError("db down")),
    )
    monkeypatch.setattr(
        "agents.tools.chat_tools._scroll_file_from_collection",
        AsyncMock(return_value=[{"content": "SECRET=failopen", "chunk_index": 0}]),
    )

    res = await browse_file_content("repo-a", "src/main.py")

    assert res.output["data"]["chunks"] == []
    assert "excluded" in res.output["error"].lower()
    assert "failopen" not in str(res.output)


async def test_browse_file_content_non_excluded_still_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非排除文件不受影响，正常返回内容（防止过度拦截）。"""
    monkeypatch.setattr(
        "agents.tools.chat_tools.build_matcher_for_repo",
        AsyncMock(return_value=_env_matcher()),
    )
    monkeypatch.setattr(
        "agents.tools.chat_tools._scroll_file_from_collection",
        AsyncMock(
            return_value=[
                {
                    "content": "print('hi')",
                    "chunk_index": 0,
                    "start_line": 1,
                    "end_line": 1,
                    "language": "python",
                }
            ]
        ),
    )

    res = await browse_file_content("repo-a", "src/main.py")

    assert res.output["data"]["total_chunks"] == 1
    assert "hi" in res.output["data"]["chunks"][0]["content"]


# ============================================================================
# list_space_structure
# ============================================================================


def _fake_qdrant_client(points: list[Any]) -> Any:
    class _FakeClient:
        def scroll(self, **_kw: Any) -> tuple[list[Any], None]:
            return (points, None)

    return _FakeClient()


@pytest.mark.django_db(transaction=True)
async def test_list_space_structure_filters_excluded(
    monkeypatch: pytest.MonkeyPatch, project: Any, repository: Any
) -> None:
    """文件树不展示被排除文件。

    ``list_space_structure`` 契约已收紧为 repository_id 必填（不再支持全空间 dump），
    故必须显式限定仓库，否则只会拿到引导文案 + 空树。
    """
    repository.index_status = "indexed"
    await sync_to_async(repository.save)(update_fields=["index_status"])

    points = [
        SimpleNamespace(payload={"file_path": "src/main.py", "language": "python"}),
        SimpleNamespace(payload={"file_path": ".env", "language": ""}),
    ]
    monkeypatch.setattr(
        "agents.tools.chat_tools.QdrantService.get_client",
        lambda: _fake_qdrant_client(points),
    )
    monkeypatch.setattr(
        "agents.tools.chat_tools.build_matcher_for_repo",
        AsyncMock(return_value=_env_matcher()),
    )

    res = await list_space_structure(str(project.id), repository_id=str(repository.id))

    structure = res.output["data"]["structure"]
    assert ".env" not in structure
    assert "main.py" in structure


# ============================================================================
# search_repository_code 兜底过滤
# ============================================================================


@pytest.mark.django_db(transaction=True)
async def test_search_repository_code_backstop_filters_excluded(
    monkeypatch: pytest.MonkeyPatch, repository: Any
) -> None:
    """即便底层强行返回被排除项，也由兜底过滤剔除（防御未来旁路回流）。"""
    from services.exclusion import invalidate_matcher_cache
    from services.retrieval.types import LayerSnapshot, RagSearchResult

    invalidate_matcher_cache(str(repository.id))

    forced = RagSearchResult(
        query="q",
        repository_ids=[str(repository.id)],
        layers=[
            LayerSnapshot(
                layer="L3",
                status="ok",
                result_count=2,
                items=[
                    {
                        "score": 0.9,
                        "repository_id": str(repository.id),
                        "payload": {
                            "file_path": "src/app.py",
                            "content": "ok",
                            "language": "python",
                        },
                    },
                    {
                        "score": 0.95,
                        "repository_id": str(repository.id),
                        "payload": {
                            "file_path": ".env",
                            "content": "SECRET=leak",
                            "language": "text",
                        },
                    },
                ],
            )
        ],
        final_context="ctx",
        total_tokens=10,
    )
    monkeypatch.setattr(
        "services.retrieval.hybrid_search.HybridSearchService.search",
        AsyncMock(return_value=forced),
    )

    res = await search_repository_code("q", repository_id=str(repository.id), min_score=0.5)

    paths = {r["file_path"] for r in res.output["data"]["results"]}
    assert ".env" not in paths
    assert "src/app.py" in paths
    assert "leak" not in str(res.output["data"]["results"])
