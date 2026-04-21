"""Phase Wave — stub 测试文件。Plan 的 task 04-01 将把真实 assertion 填入。
Scope: 执行级 Provider 快照读写契约。覆盖 验收项：
 ExecutionContext.node_snapshots[node_id] 启动时写入 + Replay 使用快照
 （保证历史执行重放时 Provider 配置不因全局变更而漂移）。
Consumer: Plan Wave Task 04-01。
"""
from __future__ import annotations
import pytest
# TODO(Plan Task 04-01)：填入以下用例
# - test_execution_start_writes_node_snapshot
# - test_snapshot_contains_provider_type_model_source
# - test_replay_reads_snapshot_not_live_config
# - test_snapshot_immutable_after_execution_complete
# - test_multiple_nodes_each_have_own_snapshot
# - test_snapshot_preserved_across_execution_retry
def test_placeholder -> None:
 """Phase Wave stub — Plan fill real assertion."""
 pytest.skip("Phase Wave stub — Plan fill real assertion")
