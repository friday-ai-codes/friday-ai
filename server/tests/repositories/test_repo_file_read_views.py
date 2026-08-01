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


# === 11. 索引回退路径的行号坐标系（116-REVIEW MJ-01 的复现固化）===


class TestIndexFallbackLineNumbers:
    """⭐ 索引回退路径的 ``line_no`` **必须来自每个 chunk 自身的 ``start_line``**。

    ⛔ 不许「从首个 chunk 的 ``start_line`` 连续数下去」—— 本仓 chunker 的两条真实形态都会
    让那个假定失效：``symbol_chunker._split_large`` 默认 ``overlap_lines=5``（相邻子 chunk
    **重叠**），``_merge_small_adjacent`` 允许 ``gap <= 2`` 的合并组（组内**留空洞**）。
    连续编号会把**别的行的源码**贴上被引行的行号，而前端 ``CitationCodePreview`` 逐字渲染
    ``line_no`` 并据它判高亮 ⇒ 高亮框框住的不是被引用的那几行。
    """

    @staticmethod
    def _chunk(index: int, start: int, end: int, prefix: str) -> dict[str, Any]:
        """造一个正文与行号自洽的 chunk：第 ``n`` 行的正文恰为 ``f"{prefix}{n}"``。"""
        return {
            "chunk_index": index,
            "content": "\n".join(f"{prefix}{n}" for n in range(start, end + 1)),
            "start_line": start,
            "end_line": end,
            "language": "python",
        }

    async def _aread(
        self,
        monkeypatch: pytest.MonkeyPatch,
        chunks: list[dict[str, Any]],
        *,
        line_start: int | None,
        line_end: int | None,
        max_lines: int | None = None,
    ) -> dict[str, Any]:
        from services.repo_file_read import aread_repository_file

        repo = await Repository.objects.acreate(
            name="idx-repo",
            git_url="https://github.com/test/idx.git",
            git_platform="github",
            default_branch="main",
            index_status=IndexStatus.INDEXED,
        )
        _patch_mirror(monkeypatch, None)  # ⇒ 强制走 ② Qdrant 索引 chunk 回退
        monkeypatch.setattr(
            "services.repo_file_read._scroll_file_from_collection",
            AsyncMock(return_value=list(chunks)),
        )
        monkeypatch.setattr(
            "services.repo_file_read._list_indexed_paths", AsyncMock(return_value=[])
        )
        return await aread_repository_file(
            str(repo.id),
            PLAIN_PATH,
            surface="test",
            line_start=line_start,
            line_end=line_end,
            max_lines=max_lines,
        )

    @pytest.mark.asyncio
    async def test_overlapping_chunks_do_not_renumber_or_duplicate_lines(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """形态 A（重叠）：一个大符号被 ``overlap_lines=5`` 切成 100..150 与 146..196。

        请求 148..155 ⇒ 每个 ``line_no`` **只出现一次**且正文恰为 ``f"L{line_no}"``。
        （回退前实测：151..155 贴的是 L146..L150 的正文，且 L148/L149/L150 被渲染两次。）
        """
        result = await self._aread(
            monkeypatch,
            [self._chunk(0, 100, 150, "L"), self._chunk(1, 146, 196, "L")],
            line_start=148,
            line_end=155,
        )

        assert result["status"] == "ok"
        rows = result["lines"]
        line_nos = [row["line_no"] for row in rows]
        assert line_nos == sorted(line_nos), "行号必须单调递增"
        assert len(line_nos) == len(set(line_nos)), f"重叠行未去重：{line_nos}"
        assert line_nos == list(range(148, 156))
        for row in rows:
            assert row["text"] == f"L{row['line_no']}", (
                f"第 {row['line_no']} 行贴的是 {row['text']!r} 的正文（坐标系错位）"
            )

    @pytest.mark.asyncio
    async def test_gap_between_chunks_is_reported_honestly_not_renumbered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """形态 B（空洞）：chunk 1..5 与 40..44 之间有空洞，请求 3..42。

        ⇒ 行号集合恰为 ``{3,4,5,40,41,42}``：空洞由**行号跳变**如实表达，
        ⛔ 第 40..42 行的源码绝不能被贴上第 6..8 行的号。
        （回退前实测：返回 8 行、行号 3..10，第 40..44 行被贴成第 6..10 行。）
        """
        result = await self._aread(
            monkeypatch,
            [self._chunk(0, 1, 5, "G"), self._chunk(1, 40, 44, "G")],
            line_start=3,
            line_end=42,
        )

        assert result["status"] == "ok"
        rows = result["lines"]
        assert [row["line_no"] for row in rows] == [3, 4, 5, 40, 41, 42]
        assert [row["text"] for row in rows] == ["G3", "G4", "G5", "G40", "G41", "G42"]
        # ⛔ 空洞里的行号一个都不许凭空出现
        assert not [row for row in rows if 6 <= row["line_no"] <= 39]

    @pytest.mark.asyncio
    async def test_single_chunk_covering_range_is_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """⭐ 非恒真对照：单 chunk 覆盖整个区间时，结果与修改前逐字相同（镜像路径同款恒等映射）。"""
        result = await self._aread(
            monkeypatch,
            [self._chunk(0, 1, 20, "S")],
            line_start=5,
            line_end=8,
        )

        assert result["lines"] == [
            {"line_no": 5, "text": "S5"},
            {"line_no": 6, "text": "S6"},
            {"line_no": 7, "text": "S7"},
            {"line_no": 8, "text": "S8"},
        ]
        assert result["truncated"] is False

    @pytest.mark.asyncio
    async def test_range_in_tail_survives_max_lines_truncation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """次生形态：区间落在超 ``max_lines`` 的 chunk 尾部时，⛔ 不许过滤成空。

        截断必须**发生在区间过滤之后** —— 否则「明明能读到」会表现成「读不到」而落 quote 快照。
        （回退前实测：``lines`` 为空、``status`` 仍是 ``"ok"``。）
        """
        result = await self._aread(
            monkeypatch,
            [self._chunk(0, 1, 1000, "T")],
            line_start=900,
            line_end=905,
            max_lines=400,
        )

        assert result["status"] == "ok"
        assert [row["line_no"] for row in result["lines"]] == [900, 901, 902, 903, 904, 905]
        assert [row["text"] for row in result["lines"]] == [f"T{n}" for n in range(900, 906)]

    @pytest.mark.asyncio
    async def test_mcp_content_concatenation_is_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """⭐ MCP 契约锁：``content`` 仍是 chunk 正文**首尾相接后按 ``max_lines`` 截断**的老口径。

        两份产出共存：``content`` 走旧拼接（``get_repository_file`` 的对外契约不漂移），
        ``lines`` 走新编号。``truncated`` / ``returned_lines`` / ``total_lines`` 同样描述 ``content``。
        """
        chunks = [self._chunk(0, 100, 150, "L"), self._chunk(1, 146, 196, "L")]
        expected_texts = [line for chunk in chunks for line in str(chunk["content"]).splitlines()]

        result = await self._aread(monkeypatch, chunks, line_start=148, line_end=155, max_lines=60)

        assert result["content"] == "\n".join(expected_texts[:60])
        assert result["truncated"] is True  # 102 行正文 > 60 行上界
        assert result["returned_lines"] == 60
        assert result["total_lines"] == 102


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
