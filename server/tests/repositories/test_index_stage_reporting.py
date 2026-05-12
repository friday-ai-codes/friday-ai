"""验证 indexer 各阶段会主动写 Repository.index_stage 字段，
SSE / IndexStatusView 才能展示更细的"克隆中 / 对比 hash / 解析中 / 写入中 / 图谱"等阶段。
这里只测 update_index_stage helper 本身的语义（是否真的把字段写到 DB），
indexer 内部多个阶段调用 update_index_stage 由更上层的端到端测试 + 手测覆盖。
"""
from __future__ import annotations
import pytest
from repositories.models import IndexStatus, Repository
from services.indexer import IndexStage, update_index_stage
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]
class TestUpdateIndexStage:
 async def test_update_writes_stage_to_db(self) -> None:
 repo = await Repository.objects.acreate(
 name="stage-test",
 git_url="https://github.com/test/stage.git",
 git_platform="github",
 default_branch="main",
 index_status=IndexStatus.INDEXING,
 )
 await update_index_stage(str(repo.id), IndexStage.CLONING)
 await repo.arefresh_from_db
 assert repo.index_stage == IndexStage.CLONING
 await update_index_stage(str(repo.id), IndexStage.EMBEDDING)
 await repo.arefresh_from_db
 assert repo.index_stage == IndexStage.EMBEDDING
 async def test_clear_stage_with_empty_string(self) -> None:
 """失败 / 完成清理路径：传空字符串可清空 stage。"""
 repo = await Repository.objects.acreate(
 name="stage-clear",
 git_url="https://github.com/test/clear.git",
 git_platform="github",
 default_branch="main",
 index_status=IndexStatus.INDEXING,
 index_stage=IndexStage.WRITING_VECTORS,
 )
 await update_index_stage(str(repo.id), "")
 await repo.arefresh_from_db
 assert repo.index_stage == ""
 async def test_index_stage_constants_are_distinct_chinese_strings(self) -> None:
 """常量值必须是非空中文，作为 SSE overall_stage 直接给前端渲染。"""
 stages = [
 IndexStage.CLONING,
 IndexStage.COMPARING_HEAD,
 IndexStage.LOADING_HASHES,
 IndexStage.COMPUTING_DIFF,
 IndexStage.SCANNING_FILES,
 IndexStage.PARSING_FILES,
 IndexStage.EMBEDDING,
 IndexStage.WRITING_VECTORS,
 IndexStage.BUILDING_GRAPH,
 IndexStage.FINALIZING,
 IndexStage.COMPLETED,
 ]
 for s in stages:
 assert isinstance(s, str) and s.strip, s
 assert len(set(stages)) == len(stages), "stage 文案必须互不重复"
