"""``GET /api/repositories/<id>/file-lines/`` 守护测试（VIEW-02，per 116-07 plan Task 2）。

守十件事：

1. **未认证一律拒**（401/403）。
2. **参数前置 400 五例**：缺 ``path`` / 缺 ``line_start`` / ``line_start`` 非正整数 /
   缺 ``line_end`` / ``line_end < line_start``；⭐ 错误体键是 **``error``**（与 ``chunk_at``
   同口径，⛔ 不是 ``detail``）。
3. ⭐ **三种不可用情形返回逐字相同的 200 空**（本文件头号靶子）：文件被排除规则挡掉 /
   文件不存在 / 仓库无镜像（未建索引）⇒ 三个响应体两两 ``==``，⛔ 不可区分、无存在性预言机。
4. ⭐ **命中排除绝不返回任何 content**（service 级 + 端点级各一条）。
5. **正路**：镜像文件 + 区间 ``10..20`` ⇒ ``lines`` 11 项、``line_no`` 从 **10** 起
   （1-based，与 citation 的 ``line_start`` 同口径）、``truncated is False``。
6. ⭐ **区间上界截断**：请求 ``1..10000`` ⇒ ``len(lines) == _MAX_LINES`` 且
   ``truncated is True``、**状态码仍 200**（⛔ 不 400）。
7. **文件末尾越界**：``line_end`` 超过文件行数 ⇒ 只返回到最后一行、``truncated is False``。
8. ⭐ **双路径复判**（T-22-21）：``requested_path`` 不命中排除但 ``resolved_path`` 命中
   ⇒ 仍返回空，⛔ 不泄露 content。
9. ⭐ **MCP 面契约零漂移**：同一个被排除文件，MCP ``get_repository_file`` 仍返
   **404 ``file_excluded``**、SPA 面返 **200 空** —— 两个口径并列断言（分道且互不污染）。
10. **观测**：caller 事件带 ``path_len`` 而**不带** ``path`` 原文（AST 断言）。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from rest_framework.test import APIClient

from repositories.models import IndexStatus, Repository
from repositories.repo_file_views import _MAX_LINES

pytestmark = pytest.mark.django_db(transaction=True)

FILE_LINES_URL = "/api/repositories/{repo_id}/file-lines/"
EXCLUDED_PATH = ".env"
PLAIN_PATH = "src/main.py"
SECRET_TEXT = "SECRET_TOKEN=filelinesleak\n"


@pytest.fixture(autouse=True)
def _clear_matcher_cache() -> Any:
    """每个用例前后清空排除匹配器缓存，避免跨用例污染。"""
    from services.exclusion import invalidate_matcher_cache

    invalidate_matcher_cache(None)
    yield
    invalidate_matcher_cache(None)


@pytest.fixture(autouse=True)
def _disable_repo_mirror(settings: Any) -> None:
    """默认关闭本地镜像：fixture 仓库的 git_url 是假远端，避免测试触网。"""
    settings.REPO_MIRROR_ENABLED = False


@pytest.fixture
def indexed_repo(repository: Repository) -> Repository:
    repository.index_status = IndexStatus.INDEXED
    repository.last_indexed_commit_sha = "a" * 40
    repository.save(update_fields=["index_status", "last_indexed_commit_sha"])
    return repository


@pytest.fixture
def not_indexed_repo(db: Any) -> Repository:
    """未建索引的仓库 —— 「仓库无镜像可读」那一支（service 记 unavailable）。"""
    return Repository.objects.create(
        name="No Mirror Repo",
        git_url="https://github.com/test/no-mirror.git",
        git_platform="github",
        default_branch="main",
    )


def _snapshot() -> SimpleNamespace:
    return SimpleNamespace(ref="main", commit_sha="b" * 40, matches_index=True)


def _patch_mirror(monkeypatch: pytest.MonkeyPatch, hit: tuple[str, str, Any] | None) -> None:
    monkeypatch.setattr("services.repo_file_read._aread_from_mirror", AsyncMock(return_value=hit))


def _patch_index_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """索引侧全空 ⇒ 走 not_found（⛔ 不触真实 Qdrant）。"""
    monkeypatch.setattr(
        "services.repo_file_read._scroll_file_from_collection", AsyncMock(return_value=[])
    )
    monkeypatch.setattr("services.repo_file_read._list_indexed_paths", AsyncMock(return_value=[]))


def _get(client: APIClient, repo: Repository, **params: Any) -> Any:
    return client.get(FILE_LINES_URL.format(repo_id=repo.id), params)


# === 1. 认证闸 ===


class TestAuthGate:
    def test_unauthenticated_is_rejected(self, api_client, indexed_repo: Repository) -> None:
        resp = _get(api_client, indexed_repo, path=PLAIN_PATH, line_start=1, line_end=3)
        assert resp.status_code in (401, 403)


# === 2. 参数前置 400 五例（错误体键是 error）===


class TestParamValidation:
    def test_missing_path_400(self, authenticated_client, indexed_repo: Repository) -> None:
        resp = _get(authenticated_client, indexed_repo, line_start=1, line_end=3)
        assert resp.status_code == 400
        assert "error" in resp.json()
        assert "detail" not in resp.json()

    def test_missing_line_start_400(self, authenticated_client, indexed_repo: Repository) -> None:
        resp = _get(authenticated_client, indexed_repo, path=PLAIN_PATH, line_end=3)
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_non_integer_line_start_400(
        self, authenticated_client, indexed_repo: Repository
    ) -> None:
        resp = _get(
            authenticated_client, indexed_repo, path=PLAIN_PATH, line_start="abc", line_end=3
        )
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_non_positive_line_start_400(
        self, authenticated_client, indexed_repo: Repository
    ) -> None:
        resp = _get(authenticated_client, indexed_repo, path=PLAIN_PATH, line_start=0, line_end=3)
        assert resp.status_code == 400

    def test_missing_line_end_400(self, authenticated_client, indexed_repo: Repository) -> None:
        resp = _get(authenticated_client, indexed_repo, path=PLAIN_PATH, line_start=1)
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_line_end_before_line_start_400(
        self, authenticated_client, indexed_repo: Repository
    ) -> None:
        resp = _get(authenticated_client, indexed_repo, path=PLAIN_PATH, line_start=9, line_end=3)
        assert resp.status_code == 400
        assert "error" in resp.json()


# === 3 / 4. 中性口径：三种不可用情形逐字相同的 200 空 ===


class TestNeutralFailClosed:
    def test_three_unusable_cases_are_byte_identical(
        self,
        authenticated_client,
        indexed_repo: Repository,
        not_indexed_repo: Repository,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """⭐ 头号靶子：被排除 / 不存在 / 无镜像三者响应体两两相等，⇒ 无存在性预言机。"""
        params = {"line_start": 1, "line_end": 5}

        # (a) 文件被排除规则挡掉（镜像命中 .env）
        _patch_mirror(monkeypatch, (EXCLUDED_PATH, SECRET_TEXT, _snapshot()))
        resp_a = _get(authenticated_client, indexed_repo, path=EXCLUDED_PATH, **params)

        # (b) 文件不存在（镜像未命中 + 索引全空）
        _patch_mirror(monkeypatch, None)
        _patch_index_empty(monkeypatch)
        resp_b = _get(authenticated_client, indexed_repo, path=EXCLUDED_PATH, **params)

        # (c) 仓库无镜像可读（未建索引 ⇒ service 记 unavailable）
        resp_c = _get(authenticated_client, not_indexed_repo, path=EXCLUDED_PATH, **params)

        assert resp_a.status_code == resp_b.status_code == resp_c.status_code == 200
        assert resp_a.json() == resp_b.json()
        assert resp_b.json() == resp_c.json()
        assert resp_a.json()["lines"] == []
        assert resp_a.json()["truncated"] is False

    def test_excluded_endpoint_never_returns_content(
        self,
        authenticated_client,
        indexed_repo: Repository,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """端点级：命中排除时响应体里连一个字节的正文都不能有。"""
        _patch_mirror(monkeypatch, (EXCLUDED_PATH, SECRET_TEXT, _snapshot()))
        resp = _get(
            authenticated_client, indexed_repo, path=EXCLUDED_PATH, line_start=1, line_end=5
        )
        assert resp.status_code == 200
        body = json.dumps(resp.json())
        assert "filelinesleak" not in body
        assert resp.json()["lines"] == []

    @pytest.mark.asyncio
    async def test_excluded_service_never_returns_content(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """service 级：``status == "excluded"`` 时 ``content`` 与 ``lines`` 恒空。"""
        from services.repo_file_read import aread_repository_file

        repo = await Repository.objects.acreate(
            name="svc-repo",
            git_url="https://github.com/test/svc.git",
            git_platform="github",
            default_branch="main",
            index_status=IndexStatus.INDEXED,
        )
        _patch_mirror(monkeypatch, (EXCLUDED_PATH, SECRET_TEXT, _snapshot()))
        result = await aread_repository_file(
            str(repo.id), EXCLUDED_PATH, surface="test", line_start=1, line_end=5
        )
        assert result["status"] == "excluded"
        assert result["content"] == ""
        assert result["lines"] == []

    def test_dual_path_recheck_blocks_suffix_resolution_bypass(
        self,
        authenticated_client,
        indexed_repo: Repository,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """⭐ T-22-21：requested ``env`` 不命中，但 resolved ``.env`` 命中 ⇒ 仍返回空。"""
        _patch_mirror(monkeypatch, (EXCLUDED_PATH, SECRET_TEXT, _snapshot()))
        resp = _get(authenticated_client, indexed_repo, path="env", line_start=1, line_end=5)
        assert resp.status_code == 200
        assert resp.json()["lines"] == []
        assert "filelinesleak" not in json.dumps(resp.json())


# === 5 / 6 / 7. 正路、截断、末尾越界 ===


class TestHappyPathAndTruncation:
    def test_range_returns_numbered_lines_starting_at_line_start(
        self,
        authenticated_client,
        indexed_repo: Repository,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """区间 10..20 ⇒ 11 项，``line_no`` 从 10 起（1-based，与 citation 同口径）。"""
        text = "\n".join(f"line{i}" for i in range(1, 1001))
        _patch_mirror(monkeypatch, (PLAIN_PATH, text, _snapshot()))
        resp = _get(authenticated_client, indexed_repo, path=PLAIN_PATH, line_start=10, line_end=20)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["lines"]) == 11
        assert body["lines"][0]["line_no"] == 10
        assert body["lines"][0]["text"] == "line10"
        assert body["lines"][-1]["line_no"] == 20
        assert body["truncated"] is False

    def test_oversized_range_is_truncated_not_rejected(
        self,
        authenticated_client,
        indexed_repo: Repository,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """⭐ 请求 1..10000 ⇒ 截断到 ``_MAX_LINES`` 且状态码仍 200（⛔ 不 400）。"""
        text = "\n".join(f"line{i}" for i in range(1, 1001))
        _patch_mirror(monkeypatch, (PLAIN_PATH, text, _snapshot()))
        resp = _get(
            authenticated_client, indexed_repo, path=PLAIN_PATH, line_start=1, line_end=10000
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["lines"]) == _MAX_LINES
        assert body["truncated"] is True

    def test_range_past_end_of_file_returns_up_to_last_line(
        self,
        authenticated_client,
        indexed_repo: Repository,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``line_end`` 超过文件行数 ⇒ 只返回到最后一行、``truncated is False``（⛔ 不报错）。"""
        text = "\n".join(f"line{i}" for i in range(1, 6))
        _patch_mirror(monkeypatch, (PLAIN_PATH, text, _snapshot()))
        resp = _get(authenticated_client, indexed_repo, path=PLAIN_PATH, line_start=3, line_end=99)
        assert resp.status_code == 200
        body = resp.json()
        assert [row["line_no"] for row in body["lines"]] == [3, 4, 5]
        assert body["truncated"] is False


# === 9. MCP 面与 SPA 面两个 is_excluded 口径并列 ===


class TestTwoSurfacesDoNotContaminateEachOther:
    @pytest.fixture
    def mcp_pat_client(self, make_access_token: Any) -> APIClient:
        _token, plaintext = make_access_token(name="file-lines-cross-surface")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
        return client

    def test_mcp_says_file_excluded_while_spa_stays_neutral(
        self,
        authenticated_client,
        mcp_pat_client: APIClient,
        indexed_repo: Repository,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """⭐ 同一个被排除文件：MCP 面 404 ``file_excluded``，SPA 面 200 空 —— 分道且互不污染。"""
        _patch_mirror(monkeypatch, (EXCLUDED_PATH, SECRET_TEXT, _snapshot()))

        mcp_resp = mcp_pat_client.post(
            "/api/mcp/tools/get_repository_file/",
            {"repository_id": str(indexed_repo.id), "file_path": EXCLUDED_PATH},
            format="json",
        )
        assert mcp_resp.status_code == 404
        assert mcp_resp.json()["error_code"] == "file_excluded"
        assert "filelinesleak" not in json.dumps(mcp_resp.json())

        spa_resp = _get(
            authenticated_client, indexed_repo, path=EXCLUDED_PATH, line_start=1, line_end=5
        )
        assert spa_resp.status_code == 200
        assert spa_resp.json()["lines"] == []
        assert "file_excluded" not in json.dumps(spa_resp.json())


# === 10. 观测：只记标量，路径原文与正文不进日志 ===


class TestObservability:
    def test_logger_calls_never_take_raw_path_or_content(self) -> None:
        """AST 断言：视图与 service 的日志 kwarg 里没有 ``path`` / ``content`` / ``text`` 原文。"""
        for module in ("repositories/repo_file_views.py", "services/repo_file_read.py"):
            tree = ast.parse(Path(module).read_text())
            bad: list[tuple[str, str]] = []
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("info", "warning", "error", "debug", "exception")
                ):
                    for kw in node.keywords or []:
                        if kw.arg in ("content", "path", "text", "source"):
                            bad.append((kw.arg, ast.unparse(kw.value)))
            assert not bad, (module, bad)

    def test_view_reports_path_len_instead_of_path(self) -> None:
        src = Path("repositories/repo_file_views.py").read_text()
        assert "path_len=" in src
        assert "line_count=" in src
        assert "duration_ms=" in src
        assert 'category="caller"' in src

    def test_view_has_no_404_branch_and_no_mcp_wording(self) -> None:
        """⭐ 中性口径的源码级钉子：本端点不得有 404 分支、不得沿用 MCP 的显式告知。"""
        src = Path("repositories/repo_file_views.py").read_text()
        assert "HTTP_404" not in src
        assert "status=404" not in src
        assert "file_excluded" not in src
