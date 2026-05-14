"""代码关系图谱工具函数 —— chunk_id 同源稳定生成入口。"""
from __future__ import annotations
import uuid
from code_relations.constants import NAMESPACE_REPO
__all__ = ["generate_chunk_id"]
def generate_chunk_id(repo_id: str, file_path: str, chunk_index: int) -> uuid.UUID:
 """根据 (repo_id, file_path, chunk_index) 三元组生成确定性 chunk_id。
 本函数是 chunk_id 生成的**唯一入口**：indexer / ChunkRegistry 写入 / 测试 fixture
 全部走此函数，禁止散落复刻 `uuid5(NAMESPACE_REPO, ...)`，否则 Pitfall 1 全量漂移。
 拼接格式锁定 `f"{repo_id}:{file_path}:{chunk_index}"`（per ）；任何顺序 /
 分隔符变更都构成 chunk_id 漂移破坏 Qdrant point_id ↔ ChunkRegistry 同源约定。
 Args:
 repo_id: Repository UUID 的字符串形式（调用方传 `str(repo.id)`）。
 file_path: 相对仓库根的路径字符串（与 indexer 现有规范一致，不再做归一化）。
 chunk_index: ≥0 的整数（同一 file_path 内 chunk 出现次序，从 0 起递增）。
 Returns:
 uuid.UUID 实例（不是 str；调用方按需 `str(cid)` 自行转字符串）。
 """
 return uuid.uuid5(NAMESPACE_REPO, f"{repo_id}:{file_path}:{chunk_index}")
