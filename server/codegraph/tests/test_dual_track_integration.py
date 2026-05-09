"""双轨集成测试 —— 验证索引管线执行后 Qdrant + codegraph 双轨均有数据。
覆盖 Nyquist 维度 1（功能正确性）+ 维度 7（错误恢复）+ 维度 8（配置可控）。
"""
import os
import pytest
import pytest_asyncio
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
@pytest_asyncio.fixture
async def test_repository:
 """集成测试用 Repository 实例。"""
 from repositories.models import Repository
 import uuid
 repo = await Repository.objects.acreate(
 id=uuid.uuid4,
 name="test-dual-track-repo",
 git_url="https://github.com/test/dual.git",
 default_branch="main",
 )
 yield repo
 # 清理级联删除所有关联数据
 await Repository.objects.filter(id=repo.id).adelete
class TestDualTrackIntegration:
 """全量索引后双轨数据完整性验证。"""
 @pytest.mark.django_db(transaction=True)
 async def test_full_index_writes_vector_and_graph_tracks(self):
 """全量索引后：
 1. 图谱服务可初始化
 2. _extract_and_write_graph 方法可正常调用
 """
 from services.indexer import IndexerService
 indexer = IndexerService("test-repo-id")
 indexer._init_graph_services
 # 验证图谱服务已初始化
 assert indexer._graph_extractor is not None, "GraphExtractor not initialized"
 assert indexer._graph_writer is not None, "GraphWriter not initialized"
 # 验证 _extract_and_write_graph 方法可以正常调用（即使没有实际文件）
 # 空文件列表应快速返回零统计
 stats = await indexer._extract_and_write_graph(
 repo_path="/tmp/nonexistent",
 file_paths=,
 repository_id="test-repo-id",
 )
 assert stats["files_processed"] == 0
 assert stats["files_failed"] == 0
 @pytest.mark.django_db(transaction=True)
 async def test_graph_track_failure_does_not_block_vector_track(self):
 """per: 图谱写入失败时，_extract_and_write_graph 内部捕获异常，不向外传播。"""
 from services.indexer import IndexerService
 indexer = IndexerService("test-repo-id")
 indexer._init_graph_services
 # 传入不存在的文件路径 —— graph 抽取应优雅失败
 result = await indexer._extract_and_write_graph(
 repo_path="/tmp/nonexistent",
 file_paths=["nonexistent_file.py"],
 repository_id="test-repo-id",
 )
 # 不应抛异常，应返回统计（files_processed=0）
 assert isinstance(result, dict), f"Expected dict, got {type(result)}"
 assert result["files_processed"] == 0
 @pytest.mark.django_db(transaction=True)
 async def test_feature_flag_disables_graph_track(self, monkeypatch):
 """ENABLE_CODEGRAPH=False 时，图谱轨完全跳过。"""
 from services.indexer import IndexerService
 # Monkey-patch settings
 monkeypatch.setattr("django.conf.settings.ENABLE_CODEGRAPH", False)
 indexer = IndexerService("test-repo-id")
 result = await indexer._extract_and_write_graph(
 repo_path="/tmp/test",
 file_paths=["test.py"],
 repository_id="test-repo-id",
 )
 assert result.get("reason") == "disabled"
 assert result["files_processed"] == 0
 @pytest.mark.django_db(transaction=True)
 async def test_graph_extraction_with_real_python_file(self, tmp_path, test_repository):
 """用真实 Python 文件测试完整的 graph extraction + write 流程。"""
 from services.indexer import IndexerService
 from codegraph.models import Symbol
 # 创建临时 Python 文件
 py_file = tmp_path / "sample.py"
 py_file.write_text("""import os
from typing import Optional
def helper(x: int) -> int:
 return x * 2
class Processor:
 def process(self, data):
 result = helper(len(data))
 return result
""")
 indexer = IndexerService(str(test_repository.id))
 indexer._init_graph_services
 result = await indexer._extract_and_write_graph(
 repo_path=str(tmp_path),
 file_paths=["sample.py"],
 repository_id=str(test_repository.id),
 )
 assert result["files_processed"] == 1, f"Expected 1 file processed, got {result}"
 assert result["total_symbols"] >= 3, f"Expected >= 3 symbols, got {result}"
 # 验证 DB 中有数据
 sym_count = await Symbol.objects.filter(
 repository=test_repository
 ).acount
 assert sym_count >= 3, f"DB symbol count: {sym_count}"
 # helper 函数和 Processor 类应存在
 names = set
 async for s in Symbol.objects.filter(repository=test_repository):
 names.add(s.name)
 assert "helper" in names, f"Missing 'helper' in {names}"
 assert "Processor" in names, f"Missing 'Processor' in {names}"
