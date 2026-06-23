"""索引全流程端到端集成测试 (work item)。

OBSOLETE — implementation 双轨索引（Qdrant + 图谱）后 clone_and_index_repository 调用链
依赖 Qdrant 真实连接，本测试未 stub 该 seam，因 pytest-socket 隔离失败。
v24.0 应统一抽 conftest fixture 注入 Qdrant mock 后取消 skip。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.skip(
    reason=(
        "OBSOLETE — implementation 双轨索引 + pytest-socket 隔离后，索引主链路触发真实"
        " Qdrant 连接被阻塞。需在 v24.0 重写 fixture 统一 stub Qdrant client。"
    )
)
from django.test import TransactionTestCase

from repositories.models import (
    FileIndex,
    IndexHistory,
    IndexHistoryStatus,
    IndexStatus,
    Repository,
    TriggerType,
)


@pytest.mark.django_db(transaction=True)
class TestManualTriggerFullFlow(TransactionTestCase):
    """work item Test 1: 手动触发索引 → 全量索引 → Qdrant 写入 → 搜索返回结果。"""

    def setUp(self) -> None:
        self.repo = Repository.objects.create(
            name="e2e-test-repo",
            git_url="https://github.com/test/e2e-repo.git",
        )
        self.repo_id = str(self.repo.id)

    def _make_repo_mock(self) -> Repository:
        """预设 credential 缓存避免同步 DB 查询。"""
        self.repo._state.fields_cache["credential"] = None
        return self.repo

    @pytest.mark.asyncio
    async def test_manual_trigger_full_flow(self) -> None:
        """手动触发全流程：clone → full_index → upsert → FileIndex 记录 → 搜索返回结果。"""
        from services.indexer import clone_and_index_repository

        # 追踪 upsert 调用的 points
        upserted_points: list[dict] = []

        def mock_upsert(repo_id: str, points: list[dict]) -> bool:
            upserted_points.extend(points)
            return True

        # 模拟搜索：从 upserted_points 中返回匹配结果
        def mock_search(
            repo_id: str, query_embedding: list, top_k: int = 10, filters: dict | None = None
        ) -> list:
            results = []
            for pt in upserted_points[:top_k]:
                results.append({"score": 0.95, "payload": pt["payload"]})
            return results

        fake_embedding = [0.1] * 128

        with (
            patch(
                "services.indexer._get_head_sha", new_callable=AsyncMock, return_value="abc123head"
            ),
            patch(
                "services.indexer.qdrant_create_collection",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "services.indexer.qdrant_get_stored_file_hashes",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "services.indexer.qdrant_upsert_vectors",
                new_callable=AsyncMock,
                side_effect=mock_upsert,
            ),
            patch(
                "services.indexer.EmbeddingService.generate_embeddings_batch",
                new_callable=AsyncMock,
                return_value=[fake_embedding],
            ),
            patch("services.indexer.scan_directory", return_value=["/tmp/fake_clone/src/main.py"]),
            patch("services.indexer.CodeParser.parse_file_dual") as mock_parse,
            patch("services.indexer.SystemSetting") as mock_setting_cls,
            patch("tempfile.mkdtemp", return_value="/tmp/fake_clone"),
            patch("shutil.rmtree"),
            patch("os.path.exists", return_value=True),
            patch("asyncio.create_subprocess_exec") as mock_proc,
        ):
            # mock SystemSetting 查询
            mock_qs = MagicMock()
            mock_qs.afirst = AsyncMock(return_value=None)
            mock_filter = MagicMock(return_value=mock_qs)
            mock_setting_cls.objects = MagicMock()
            mock_setting_cls.objects.filter = mock_filter

            # mock CodeParser 返回一个 chunk
            from services.code_parser import CodeChunk

            mock_chunk = CodeChunk(
                content="def hello(): pass",
                file_path="src/main.py",
                file_hash="fakehash123",
                language="python",
                node_type="function",
                start_line=1,
                end_line=1,
                context_header="src/main.py::hello",
                imports="",
                module_docstring="",
                sibling_signatures="",
            )
            mock_parse.return_value = ([mock_chunk], None)

            # mock git clone 成功
            process_mock = AsyncMock()
            process_mock.communicate = AsyncMock(return_value=(b"", b""))
            process_mock.returncode = 0
            mock_proc.return_value = process_mock

            with patch.object(Repository.objects, "select_related") as mock_sr:
                mock_qs_repo = MagicMock()
                mock_qs_repo.aget = AsyncMock(return_value=self._make_repo_mock())
                mock_sr.return_value = mock_qs_repo

                with patch("common.encryption.decrypt_value", return_value=None):
                    result = await clone_and_index_repository(self.repo_id)

        # 验证索引成功
        assert result["status"] == "success"
        assert result["chunks_indexed"] >= 1

        # 验证 Qdrant upsert 被调用且包含正确的 payload
        assert len(upserted_points) >= 1
        payload = upserted_points[0]["payload"]
        assert payload["file_path"] == "src/main.py"
        assert payload["content"] == "def hello(): pass"

        # 验证 FileIndex 记录存在
        fi_count = await FileIndex.objects.filter(repository_id=self.repo_id).acount()
        assert fi_count >= 1
        fi = await FileIndex.objects.filter(
            repository_id=self.repo_id, file_path="src/main.py"
        ).afirst()
        assert fi is not None
        assert fi.file_hash == "fakehash123"

        # 验证搜索返回结果（通过 mock_search）
        search_results = mock_search(self.repo_id, fake_embedding, top_k=5)
        assert len(search_results) >= 1
        assert search_results[0]["payload"]["file_path"] == "src/main.py"


@pytest.mark.django_db(transaction=True)
class TestWebhookTriggerFlow(TransactionTestCase):
    """work item Test 2: Webhook 触发 → trigger_auto_index → IndexHistory 状态跟踪。"""

    def setUp(self) -> None:
        self.repo = Repository.objects.create(
            name="webhook-test-repo",
            git_url="https://github.com/test/webhook-repo.git",
            auto_index_enabled=True,
        )
        self.repo_id = str(self.repo.id)

    @pytest.mark.asyncio
    async def test_webhook_trigger_creates_history_and_starts_task(self) -> None:
        """Webhook 触发创建 IndexHistory 并启动后台索引任务。"""
        from tasks.index_trigger_tasks import (
            clear_dedup_cache,
            parse_push_event,
            trigger_auto_index,
        )

        clear_dedup_cache()

        # 验证 parse_push_event 解析 GitHub payload
        payload = {"ref": "refs/heads/main", "after": "commit_sha_abc123"}
        event_data = parse_push_event("github", payload)
        assert event_data["ref"] == "refs/heads/main"
        assert event_data["after"] == "commit_sha_abc123"

        # mock clone_and_index_repository 快速完成
        mock_result = {"status": "success", "added": 3, "updated": 0, "deleted": 0}

        with patch(
            "tasks.index_trigger_tasks.clone_and_index_repository",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await trigger_auto_index(self.repo, "webhook", "commit_sha_abc123")

        assert result["status"] == "triggered"
        history_id = result["history_id"]

        # 验证 IndexHistory 记录已创建
        history = await IndexHistory.objects.aget(id=history_id)
        assert history.trigger_type == TriggerType.WEBHOOK
        assert history.status == IndexHistoryStatus.RUNNING

    @pytest.mark.asyncio
    async def test_webhook_dedup_skips_duplicate(self) -> None:
        """同一 commit SHA 在去重窗口内被跳过。"""
        from tasks.index_trigger_tasks import clear_dedup_cache, trigger_auto_index

        clear_dedup_cache()

        with patch(
            "tasks.index_trigger_tasks.clone_and_index_repository",
            new_callable=AsyncMock,
        ):
            result1 = await trigger_auto_index(self.repo, "webhook", "same_sha_111")
            assert result1["status"] == "triggered"

            # 刷新 repo 状态避免 already_indexing 判断（模拟索引完成）
            await Repository.objects.filter(id=self.repo_id).aupdate(
                index_status=IndexStatus.NOT_INDEXED
            )
            await self.repo.arefresh_from_db()

            result2 = await trigger_auto_index(self.repo, "webhook", "same_sha_111")
            assert result2["status"] == "duplicate"


@pytest.mark.django_db(transaction=True)
class TestIncrementalIndexFlow(TransactionTestCase):
    """work item Test 3: 增量索引验证——仅变更文件被重新索引，FileIndex 正确更新。"""

    def setUp(self) -> None:
        self.repo = Repository.objects.create(
            name="incr-test-repo",
            git_url="https://github.com/test/incr-repo.git",
        )
        self.repo_id = str(self.repo.id)

    @pytest.mark.asyncio
    async def test_incremental_index_updates_only_changed_files(self) -> None:
        """首次全量索引后，增量索引仅处理 hash 变化的文件。"""
        from services.indexer import IndexerService

        indexer = IndexerService(self.repo_id)

        # 预置 2 条 FileIndex 记录（模拟首次全量索引完成后的状态）
        await FileIndex.objects.acreate(
            repository_id=self.repo_id,
            file_path="src/a.py",
            file_hash="hash_a_v1",
        )
        await FileIndex.objects.acreate(
            repository_id=self.repo_id,
            file_path="src/b.py",
            file_hash="hash_b_v1",
        )
        assert await FileIndex.objects.filter(repository_id=self.repo_id).acount() == 2

        # 模拟本地文件：a.py hash 变了，b.py 不变
        fake_embedding = [0.1] * 128
        upserted_points: list[dict] = []

        def mock_upsert(repo_id: str, points: list[dict]) -> bool:
            upserted_points.extend(points)
            return True

        with (
            patch(
                "services.indexer.scan_directory",
                return_value=["/tmp/repo/src/a.py", "/tmp/repo/src/b.py"],
            ),
            patch(
                "services.indexer.compute_file_hash",
                side_effect=lambda fp: "hash_a_v2" if "a.py" in fp else "hash_b_v1",
            ),
            patch(
                "services.indexer.qdrant_delete_by_file_path",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "services.indexer.qdrant_upsert_vectors",
                new_callable=AsyncMock,
                side_effect=mock_upsert,
            ),
            patch(
                "services.indexer.EmbeddingService.generate_embeddings_batch",
                new_callable=AsyncMock,
                return_value=[fake_embedding],
            ),
            patch("services.indexer.update_index_progress", new_callable=AsyncMock),
            patch("services.indexer.update_write_progress", new_callable=AsyncMock),
            patch("services.indexer.CodeParser.parse_file_dual") as mock_parse,
        ):
            from services.code_parser import CodeChunk

            mock_chunk = CodeChunk(
                content="def updated_a(): pass",
                file_path="src/a.py",
                file_hash="hash_a_v2",
                language="python",
                node_type="function",
                start_line=1,
                end_line=1,
                context_header="src/a.py::updated_a",
                imports="",
                module_docstring="",
                sibling_signatures="",
            )
            mock_parse.return_value = ([mock_chunk], None)

            result = await indexer.run_incremental_index("/tmp/repo")

        # 验证：只有 a.py 被更新（updated=1），b.py 被跳过
        assert result["status"] == "success"
        assert result["updated"] == 1
        assert result["skipped"] == 1
        assert result["added"] == 0

        # 验证 FileIndex 记录：a.py 的 hash 已更新为 v2
        fi_a = await FileIndex.objects.aget(repository_id=self.repo_id, file_path="src/a.py")
        assert fi_a.file_hash == "hash_a_v2"

        # b.py 的 hash 保持不变
        fi_b = await FileIndex.objects.aget(repository_id=self.repo_id, file_path="src/b.py")
        assert fi_b.file_hash == "hash_b_v1"

        # 验证 upsert 只处理了 a.py
        assert len(upserted_points) >= 1
        upserted_files = {pt["payload"]["file_path"] for pt in upserted_points}
        assert "src/a.py" in upserted_files
        assert "src/b.py" not in upserted_files


@pytest.mark.django_db(transaction=True)
class TestIndexStatusProgress(TransactionTestCase):
    """work item Test 4: IndexStatusView 返回 overall_progress 且值在 0-100 之间。"""

    def setUp(self) -> None:
        self.repo = Repository.objects.create(
            name="progress-test-repo",
            git_url="https://github.com/test/progress-repo.git",
            index_status=IndexStatus.INDEXING,
            index_total_chunks=100,
            index_processed_chunks=70,
            index_write_total=50,
            index_write_processed=25,
        )
        self.repo_id = str(self.repo.id)

    @pytest.mark.asyncio
    async def test_index_status_includes_overall_progress(self) -> None:
        """IndexStatusView 响应包含 overall_progress 和 overall_stage，值在有效范围内。"""
        from repositories.index_views import IndexStatusView

        view = IndexStatusView()

        # 构造 mock request
        request = MagicMock()

        response = await view.get(request, self.repo_id)

        data = response.data
        assert "overall_progress" in data
        assert "overall_stage" in data
        assert 0 <= data["overall_progress"] <= 100

        # PROG-01 单调阶段进度：chunk 阶段 embed 70/100 + write 25/50 →
        # combined = 0.7*0.7 + 0.5*0.3 = 0.64，映射到 [20,100] → 20 + 0.64*80 = 71.2 → 71
        assert data["overall_progress"] == 71
        assert data["overall_stage"] == "写入向量库..."

    @pytest.mark.asyncio
    async def test_index_status_zero_progress(self) -> None:
        """进度为零时 overall_progress=0 且 stage 为解析文件中。"""
        from repositories.index_views import IndexStatusView

        repo = await Repository.objects.acreate(
            name="zero-progress-repo",
            git_url="https://github.com/test/zero.git",
            index_status=IndexStatus.INDEXING,
            index_total_chunks=0,
            index_processed_chunks=0,
            index_write_total=0,
            index_write_processed=0,
        )

        view = IndexStatusView()
        request = MagicMock()

        response = await view.get(request, str(repo.id))

        assert response.data["overall_progress"] == 0
        assert response.data["overall_stage"] == "解析文件中..."

    @pytest.mark.asyncio
    async def test_index_status_complete_progress(self) -> None:
        """全部完成时 overall_progress=100 且 stage 为完成。"""
        from repositories.index_views import IndexStatusView

        repo = await Repository.objects.acreate(
            name="complete-progress-repo",
            git_url="https://github.com/test/complete.git",
            index_status=IndexStatus.INDEXING,
            index_total_chunks=50,
            index_processed_chunks=50,
            index_write_total=30,
            index_write_processed=30,
        )

        view = IndexStatusView()
        request = MagicMock()

        response = await view.get(request, str(repo.id))

        assert response.data["overall_progress"] == 100
        assert response.data["overall_stage"] == "完成"
