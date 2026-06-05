"""repositories.services 子包：仓库领域内可复用的服务模块。

当前模块：
- ``index_cleanup``：``cleanup_index(repo_id) -> CleanupReport`` 级联清理一仓全部
  Symbol / ImportEdge / Endpoint / FileIndex / ChunkEdge / ChunkRegistry +
  Qdrant collection。供 ``IndexDeleteView`` 与未来的运维脚本复用。
"""
