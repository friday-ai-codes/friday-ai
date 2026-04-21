"""Phase Wave — stub 测试文件。Plan 的 task 08-02 将把真实 assertion 填入。
Scope: v8.1 遗留字段硬删 migration up/down 对称性 + 数据保留契约。覆盖 验收项：
 alembic/Django migration `remove_v81_legacy_fields` up/down 对称
 + 数据保留（Conversation.provider_type → provider_credential_id 双向映射）。
Consumer: Plan Wave Task 08-02。
"""
from __future__ import annotations
import pytest
# TODO(Plan Task 08-02)：填入以下用例
# - test_migration_up_removes_v81_fields
# - test_migration_up_preserves_data_via_mapping
# - test_migration_down_restores_v81_fields
# - test_migration_down_backfills_from_provider_credential_id
# - test_migration_idempotent_up_up
# - test_migration_idempotent_down_down
# - test_migrate_plan_shows_expected_operations
def test_placeholder -> None:
 """Phase Wave stub — Plan fill real assertion."""
 pytest.skip("Phase Wave stub — Plan fill real assertion")
