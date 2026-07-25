"""分支感知索引管线测试：payload 注入、branch payload index、DB 记录管理、overlay 索引管线。"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.utils import timezone

from services.branch_utils import BranchOverlayLimitExceeded, MAX_OVERLAY_COLLECTIONS_PER_REPO
from services.indexer import DiffAction, FileDiff, IndexerService


class TestBaseBranchMetadata:
    """测试 _build_points 的分支元数据注入。"""

    @staticmethod
    def _make_chunk(**overrides):
        """构造最小化的 CodeChunk mock。"""
        chunk = MagicMock()
        chunk.file_path = overrides.get("file_path", "src/main.py")
        chunk.file_hash = overrides.get("file_hash", "abc123")
        chunk.language = overrides.get("language", "python")
        chunk.node_type = overrides.get("node_type", "function")
        chunk.start_line = overrides.get("start_line", 1)
        chunk.end_line = overrides.get("end_line", 10)
        chunk.content = overrides.get("content", "def hello(): pass")
        chunk.context_header = overrides.get("context_header", "module:main")
        return chunk

    def test_build_points_with_branch_name_includes_metadata(self):
        """传入 branch_name 时，payload 应包含 branch_name 和 is_base_branch。"""
        chunk = self._make_chunk()
        embedding = [0.1] * 3

        points, _ = IndexerService._build_points(
            [chunk],
            [embedding],
            None,
            False,
            repository_id="test-repo-uuid",
            branch_name="main",
            is_base_branch=True,
        )

        assert len(points) == 1
        payload = points[0]["payload"]
        assert payload["branch_name"] == "main"
        assert payload["is_base_branch"] is True

    def test_build_points_without_branch_name_no_metadata(self):
        """不传 branch_name 时，payload 不应包含 branch 相关字段（向后兼容）。"""
        chunk = self._make_chunk()
        embedding = [0.1] * 3

        points, _ = IndexerService._build_points(
            [chunk],
            [embedding],
            None,
            False,
            repository_id="test-repo-uuid",
        )

        assert len(points) == 1
        payload = points[0]["payload"]
        assert "branch_name" not in payload
        assert "is_base_branch" not in payload

    def test_build_points_branch_metadata_with_hybrid(self):
        """hybrid 模式下，branch 元数据同样正确注入。"""
        chunk = self._make_chunk()
        embedding = [0.1] * 3
        sparse = {"indices": [0, 1], "values": [0.5, 0.3]}

        with patch("qdrant_client.http.models.SparseVector") as mock_sv:
            mock_sv.return_value = MagicMock()
            points, _ = IndexerService._build_points(
                [chunk],
                [embedding],
                [sparse],
                True,
                repository_id="test-repo-uuid",
                branch_name="develop",
                is_base_branch=False,
            )

        assert len(points) == 1
        payload = points[0]["payload"]
        assert payload["branch_name"] == "develop"
        assert payload["is_base_branch"] is False

    @patch("services.qdrant_service.QdrantService.get_client")
    def test_create_branch_payload_index_success(self, mock_get_client):
        """create_branch_payload_index 应调用 create_payload_index 创建 keyword index。"""
        from services.qdrant_service import QdrantService

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = QdrantService.create_branch_payload_index("test_collection")

        assert result is True
        mock_client.create_payload_index.assert_called_once()
        call_kwargs = mock_client.create_payload_index.call_args
        assert call_kwargs[1]["collection_name"] == "test_collection"
        assert call_kwargs[1]["field_name"] == "branch_name"

    @patch("services.qdrant_service.QdrantService.get_client")
    def test_create_branch_payload_index_already_exists(self, mock_get_client):
        """index 已存在时应返回 False 而非崩溃。"""
        from qdrant_client.http.exceptions import UnexpectedResponse

        from services.qdrant_service import QdrantService

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        import httpx

        mock_client.create_payload_index.side_effect = UnexpectedResponse(
            status_code=400,
            reason_phrase="Bad Request",
            content=b"already exists",
            headers=httpx.Headers(),
        )

        result = QdrantService.create_branch_payload_index("test_collection")

        assert result is False


@pytest.mark.django_db(transaction=True)
class TestBranchIndexRecord:
    """测试 _update_branch_index_record 创建/更新 DB 记录。"""

    @pytest.fixture
    def repository(self):
        from repositories.models import Repository

        return Repository.objects.create(
            name="test-repo",
            git_url="https://github.com/test/repo.git",
            default_branch="main",
        )

    @pytest.fixture
    def indexer(self, repository):
        return IndexerService(str(repository.id))

    @pytest.mark.asyncio
    @patch(
        "services.indexer._get_head_sha",
        new_callable=AsyncMock,
        return_value="abc1234567890abcdef1234567890abcdef123456",
    )
    async def test_creates_branch_index_record(self, mock_sha, repository, indexer):
        """run_full_index 后应创建 RepositoryBranchIndex 记录。"""
        from repositories.models import BranchIndexStatus, RepositoryBranchIndex

        await indexer._update_branch_index_record(
            repo_path="/tmp/fake",
            branch_name="main",
            is_base_branch=True,
            points_count=42,
        )

        record = await RepositoryBranchIndex.objects.aget(
            repository=repository,
            branch_name="main",
        )
        assert record.is_base_branch is True
        assert record.head_sha == "abc1234567890abcdef1234567890abcdef123456"
        assert record.status == BranchIndexStatus.INDEXED
        assert record.effective_chunks_count == 42
        assert record.is_stale is False

    @pytest.mark.asyncio
    @patch("services.indexer._get_head_sha", new_callable=AsyncMock, return_value="def456")
    async def test_updates_existing_branch_index_record(self, mock_sha, repository, indexer):
        """重新索引时应更新已有记录。"""
        from repositories.models import BranchIndexStatus, RepositoryBranchIndex

        await RepositoryBranchIndex.objects.acreate(
            repository=repository,
            branch_name="main",
            is_base_branch=True,
            status=BranchIndexStatus.INDEXED,
            effective_chunks_count=10,
        )

        await indexer._update_branch_index_record(
            repo_path="/tmp/fake",
            branch_name="main",
            is_base_branch=True,
            points_count=99,
        )

        record = await RepositoryBranchIndex.objects.aget(
            repository=repository,
            branch_name="main",
        )
        assert record.effective_chunks_count == 99
        assert record.head_sha == "def456"


@pytest.mark.django_db(transaction=True)
class TestStalePropagate:
    """测试 base 重索引后 overlay stale 传播。"""

    @pytest.fixture
    def repository(self):
        from repositories.models import Repository

        return Repository.objects.create(
            name="test-repo-stale",
            git_url="https://github.com/test/stale-repo.git",
            default_branch="main",
        )

    @pytest.fixture
    def indexer(self, repository):
        return IndexerService(str(repository.id))

    @pytest.mark.asyncio
    @patch("services.indexer._get_head_sha", new_callable=AsyncMock, return_value="head123")
    async def test_base_reindex_marks_overlays_stale(self, mock_sha, repository, indexer):
        """base 分支重索引后，所有非 base 的 overlay 应标记为 is_stale=True。"""
        from repositories.models import BranchIndexStatus, RepositoryBranchIndex

        overlay1 = await RepositoryBranchIndex.objects.acreate(
            repository=repository,
            branch_name="feature/a",
            is_base_branch=False,
            is_stale=False,
            status=BranchIndexStatus.INDEXED,
        )
        overlay2 = await RepositoryBranchIndex.objects.acreate(
            repository=repository,
            branch_name="feature/b",
            is_base_branch=False,
            is_stale=False,
            status=BranchIndexStatus.INDEXED,
        )

        await indexer._update_branch_index_record(
            repo_path="/tmp/fake",
            branch_name="main",
            is_base_branch=True,
            points_count=50,
        )

        await overlay1.arefresh_from_db()
        await overlay2.arefresh_from_db()
        assert overlay1.is_stale is True
        assert overlay2.is_stale is True

    @pytest.mark.asyncio
    @patch("services.indexer._get_head_sha", new_callable=AsyncMock, return_value="head456")
    async def test_non_base_reindex_does_not_mark_stale(self, mock_sha, repository, indexer):
        """非 base 分支索引不应触发 stale 传播。"""
        from repositories.models import BranchIndexStatus, RepositoryBranchIndex

        overlay = await RepositoryBranchIndex.objects.acreate(
            repository=repository,
            branch_name="feature/c",
            is_base_branch=False,
            is_stale=False,
            status=BranchIndexStatus.INDEXED,
        )

        await indexer._update_branch_index_record(
            repo_path="/tmp/fake",
            branch_name="feature/x",
            is_base_branch=False,
            points_count=10,
        )

        await overlay.arefresh_from_db()
        assert overlay.is_stale is False


@pytest.mark.django_db(transaction=True)
class TestOverlayIndex:
    """测试 run_branch_index 功能分支 overlay 索引。"""

    @pytest.fixture
    def repository(self):
        from repositories.models import Repository

        return Repository.objects.create(
            name="overlay-repo",
            git_url="https://github.com/test/overlay.git",
            default_branch="main",
        )

    @pytest.fixture
    def indexer(self, repository):
        return IndexerService(str(repository.id))

    @pytest.mark.asyncio
    @patch(
        "services.indexer.qdrant_upsert_vectors_by_name", new_callable=AsyncMock, return_value=True
    )
    @patch(
        "services.indexer.qdrant_create_collection_by_name",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch("services.indexer.QdrantService.create_branch_payload_index", return_value=True)
    @patch("services.indexer.EmbeddingService.generate_embeddings_batch", new_callable=AsyncMock)
    @patch("services.indexer._parse_git_diff_output")
    @patch("services.indexer.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @patch(
        "services.indexer._deepen_for_merge_base", new_callable=AsyncMock, return_value="merge111"
    )
    @patch("services.indexer._fetch_branch", new_callable=AsyncMock, return_value=True)
    @patch("services.indexer._is_shallow_clone", new_callable=AsyncMock, return_value=True)
    async def test_run_branch_index_creates_overlay(
        self,
        mock_shallow,
        mock_fetch_br,
        mock_deepen,
        mock_subprocess,
        mock_parse,
        mock_embed,
        mock_branch_idx,
        mock_create_coll,
        mock_upsert,
        repository,
        indexer,
        tmp_path,
    ):
        """有差异的功能分支应创建 overlay collection 并记录 BranchFileIndex。"""
        from repositories.models import BranchIndexStatus, RepositoryBranchIndex
        from services.indexer import DiffAction, FileDiff

        # 用真实临时文件而非 patch os.path.*：管线要 isfile + getsize（大文件预检）
        # 都成立才会解析，打桩单个函数既脆又会污染全局 os.path。
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "new.py").write_text("def new(): pass\n", encoding="utf-8")

        mock_parse.return_value = [FileDiff("src/new.py", DiffAction.ADD)]
        mock_embed.return_value = [[0.1, 0.2, 0.3]]

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"feature_head_sha_abc", b""))
        mock_proc.returncode = 0
        mock_subprocess.return_value = mock_proc

        indexer.parser = MagicMock()
        chunk = MagicMock()
        chunk.file_path = "src/new.py"
        chunk.file_hash = "hash1"
        chunk.language = "python"
        chunk.node_type = "function"
        chunk.start_line = 1
        chunk.end_line = 5
        chunk.content = "def new(): pass"
        chunk.context_header = "module:new"
        chunk.imports = ""
        chunk.module_docstring = ""
        chunk.sibling_signatures = ""
        indexer.parser.parse_file_dual.return_value = ([chunk], None)

        result = await indexer.run_branch_index(str(tmp_path), "feature/x", repository)

        assert result["status"] == "indexed"
        assert result["diff_files"] == 1
        mock_create_coll.assert_called_once()
        mock_upsert.assert_called_once()

        record = await RepositoryBranchIndex.objects.aget(
            repository=repository,
            branch_name="feature/x",
        )
        assert record.status == BranchIndexStatus.INDEXED
        assert record.is_base_branch is False
        assert record.collection_name is not None

    @pytest.mark.asyncio
    @patch(
        "services.indexer.qdrant_upsert_vectors_by_name", new_callable=AsyncMock, return_value=True
    )
    @patch(
        "services.indexer.qdrant_create_collection_by_name",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch("services.indexer.QdrantService.create_branch_payload_index", return_value=True)
    @patch("services.indexer.EmbeddingService.generate_embeddings_batch", new_callable=AsyncMock)
    @patch("services.indexer._parse_git_diff_output")
    @patch("services.indexer.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @patch(
        "services.indexer._deepen_for_merge_base", new_callable=AsyncMock, return_value="merge111"
    )
    @patch("services.indexer._fetch_branch", new_callable=AsyncMock, return_value=True)
    @patch("services.indexer._is_shallow_clone", new_callable=AsyncMock, return_value=True)
    async def test_run_branch_index_skips_excluded_files(
        self,
        mock_shallow,
        mock_fetch_br,
        mock_deepen,
        mock_subprocess,
        mock_parse,
        mock_embed,
        mock_branch_idx,
        mock_create_coll,
        mock_upsert,
        repository,
        indexer,
        tmp_path,
    ):
        """ME-02：被排除文件（server/.env）不进入 overlay 索引，正常文件照常索引。"""
        from services.exclusion import invalidate_matcher_cache

        invalidate_matcher_cache(str(repository.id))

        # 两个文件都真实落盘：证明 .env 是被排除规则剔除的，而不是"文件不存在"蒙对。
        (tmp_path / "server").mkdir()
        (tmp_path / "server" / ".env").write_text("SECRET=x\n", encoding="utf-8")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "new.py").write_text("def new(): pass\n", encoding="utf-8")

        # diff 同时含被排除的 server/.env（builtin 默认）与正常 src/new.py。
        mock_parse.return_value = [
            FileDiff("server/.env", DiffAction.ADD),
            FileDiff("src/new.py", DiffAction.ADD),
        ]
        mock_embed.return_value = [[0.1, 0.2, 0.3]]

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"feature_head_sha_abc", b""))
        mock_proc.returncode = 0
        mock_subprocess.return_value = mock_proc

        indexer.parser = MagicMock()
        chunk = MagicMock()
        chunk.file_path = "src/new.py"
        chunk.file_hash = "hash1"
        chunk.language = "python"
        chunk.node_type = "function"
        chunk.start_line = 1
        chunk.end_line = 5
        chunk.content = "def new(): pass"
        chunk.context_header = "module:new"
        chunk.imports = ""
        chunk.module_docstring = ""
        chunk.sibling_signatures = ""
        indexer.parser.parse_file_dual.return_value = ([chunk], None)

        result = await indexer.run_branch_index(str(tmp_path), "feature/excl", repository)

        assert result["status"] == "indexed"
        # 仅正常文件被解析/索引；被排除文件从源头剔除（不调用 parse_file_dual）。
        assert indexer.parser.parse_file_dual.call_count == 1
        parsed_paths = [call.args[0] for call in indexer.parser.parse_file_dual.call_args_list]
        assert all(".env" not in p for p in parsed_paths)
        assert any(p.endswith("src/new.py") for p in parsed_paths)


@pytest.mark.django_db(transaction=True)
class TestInheritedFromBase:
    """测试无差异分支标记为 inherited_from_base。"""

    @pytest.fixture
    def repository(self):
        from repositories.models import Repository

        return Repository.objects.create(
            name="inherited-repo",
            git_url="https://github.com/test/inherited.git",
            default_branch="main",
        )

    @pytest.fixture
    def indexer(self, repository):
        return IndexerService(str(repository.id))

    @pytest.mark.asyncio
    @patch("services.indexer._parse_git_diff_output", return_value=[])
    @patch("services.indexer.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @patch("services.indexer._get_merge_base", new_callable=AsyncMock, return_value="merge222")
    @patch("services.indexer._fetch_branch", new_callable=AsyncMock, return_value=True)
    @patch("services.indexer._is_shallow_clone", new_callable=AsyncMock, return_value=False)
    async def test_no_diff_marks_inherited(
        self,
        mock_shallow,
        mock_fetch_br,
        mock_merge,
        mock_subprocess,
        mock_parse,
        repository,
        indexer,
    ):
        """diff 为空时应标记 INHERITED，不创建 overlay collection。"""
        from repositories.models import BranchIndexStatus, RepositoryBranchIndex

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"feature_head_sha_def", b""))
        mock_proc.returncode = 0
        mock_subprocess.return_value = mock_proc

        result = await indexer.run_branch_index("/tmp/fake", "feature/same", repository)

        assert result["status"] == "inherited"
        assert result["diff_files"] == 0

        record = await RepositoryBranchIndex.objects.aget(
            repository=repository,
            branch_name="feature/same",
        )
        assert record.status == BranchIndexStatus.INHERITED
        assert record.is_base_branch is False


@pytest.mark.django_db(transaction=True)
class TestOverlayLimit:
    """测试 overlay 硬上限检查。"""

    @pytest.fixture
    def repository(self):
        from repositories.models import Repository

        return Repository.objects.create(
            name="limit-repo",
            git_url="https://github.com/test/limit.git",
            default_branch="main",
        )

    @pytest.fixture
    def indexer(self, repository):
        return IndexerService(str(repository.id))

    @pytest.mark.asyncio
    async def test_overlay_limit_exceeded_raises(self, repository, indexer):
        """overlay 数量达到硬上限时应抛出 BranchOverlayLimitExceeded。"""
        from services.branch_utils import (
            MAX_OVERLAY_COLLECTIONS_PER_REPO,
            BranchOverlayLimitExceeded,
        )

        from repositories.models import BranchIndexStatus, RepositoryBranchIndex

        for i in range(MAX_OVERLAY_COLLECTIONS_PER_REPO):
            await RepositoryBranchIndex.objects.acreate(
                repository=repository,
                branch_name=f"feature/limit-{i}",
                is_base_branch=False,
                status=BranchIndexStatus.INDEXED,
            )

        with pytest.raises(BranchOverlayLimitExceeded):
            await indexer.run_branch_index("/tmp/fake", "feature/over-limit", repository)


@pytest.mark.django_db(transaction=True)
class TestCloneAndIndexBranch:
    """测试 clone_and_index_repository 分支参数路由。"""

    @pytest.fixture
    def repository(self):
        from repositories.models import Repository

        return Repository.objects.create(
            name="clone-branch-repo",
            git_url="https://github.com/test/clone-branch.git",
            default_branch="main",
        )

    @pytest.mark.asyncio
    @patch("services.indexer.IndexerService.run_branch_index", new_callable=AsyncMock)
    @patch("services.indexer.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_branch_param_routes_to_run_branch_index(
        self,
        mock_subprocess,
        mock_run_branch,
        repository,
    ):
        """clone_and_index_repository 传入 branch 时应路由到 run_branch_index。"""
        from services.indexer import clone_and_index_repository

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0
        # _stream_clone_progress 现在直接读 stderr 而不是 communicate()。
        # 必须显式给 mock 一个 stderr stream 让 read() 立刻返回 EOF (b"")。
        mock_stderr = AsyncMock()
        mock_stderr.read = AsyncMock(return_value=b"")
        mock_proc.stderr = mock_stderr
        mock_proc.wait = AsyncMock(return_value=0)
        mock_subprocess.return_value = mock_proc

        mock_run_branch.return_value = {
            "status": "indexed",
            "diff_files": 3,
            "indexed_files": 2,
            "chunks_indexed": 10,
        }

        result = await clone_and_index_repository(
            str(repository.id),
            branch="feature/test",
        )

        assert result["status"] == "indexed"
        mock_run_branch.assert_called_once()
        call_args = mock_run_branch.call_args
        assert call_args[0][1] == "feature/test"
