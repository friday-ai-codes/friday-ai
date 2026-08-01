"""repositories.services 子包：仓库领域内可复用的服务模块。

当前模块：
- ``index_cleanup``：``cleanup_index(repo_id) -> CleanupReport`` 级联清理一仓全部
  Symbol / ImportEdge / Endpoint / FileIndex / ChunkEdge / ChunkRegistry +
  Qdrant collection。供 ``IndexDeleteView`` 与未来的运维脚本复用。
- ``charter_service``：仓库章程（RepoCharter）唯一写入入口（INV-6）——AI 三源蒸馏
  起草（``adraft_charter``）+ 人工确认收口（``aconfirm_charter``），CHARTER-01。
"""
