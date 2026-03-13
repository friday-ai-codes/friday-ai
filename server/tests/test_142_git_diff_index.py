"""Phase: Git Diff 增量索引测试
测试覆盖：
-: git diff 获取变更文件列表 + last_indexed_commit_sha 更新
-: 按变更类型分发处理 + fallback
-: 差异摘要生成
"""
import pytest
from services.indexer import DiffAction, FileDiff
# SQLite 内存数据库 + async 需要 transaction=True 避免跨线程锁冲突
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]
# ============================================================================
# DiffAction 枚举扩展
# ============================================================================
class TestDiffActionEnum:
 """DiffAction 枚举扩展验证。"""
 def test_rename_action_exists(self) -> None:
 assert DiffAction.RENAME.value == "rename"
 def test_all_actions(self) -> None:
 actions = {a.value for a in DiffAction}
 assert actions == {"add", "update", "delete", "skip", "rename"}
# ============================================================================
# FileDiff 数据类扩展
# ============================================================================
class TestFileDiffDataclass:
 """FileDiff 数据类扩展验证。"""
 def test_old_path_default_none(self) -> None:
 diff = FileDiff("new.py", DiffAction.ADD)
 assert diff.old_path is None
 def test_old_path_for_rename(self) -> None:
 diff = FileDiff("new.py", DiffAction.RENAME, old_path="old.py")
 assert diff.old_path == "old.py"
# ============================================================================
# IndexHistory.summary_text 字段
# ============================================================================
class TestIndexHistorySummaryText:
 """IndexHistory.summary_text 字段验证。"""
 def test_summary_text_field_exists(self) -> None:
 from repositories.models import IndexHistory
 field = IndexHistory._meta.get_field("summary_text")
 assert field.null is True
 assert field.blank is True
