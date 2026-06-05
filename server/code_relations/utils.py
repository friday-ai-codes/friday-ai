"""代码关系图谱工具函数 —— chunk_id 同源稳定生成入口。"""

from __future__ import annotations

import uuid

from code_relations.constants import NAMESPACE_REPO

__all__ = ["generate_chunk_id"]


def generate_chunk_id(
    repo_id: str, file_path: str, chunk_index: int, branch_name: str = ""
) -> uuid.UUID:
    """根据 (repo_id, file_path, chunk_index[, branch_name]) 生成确定性 chunk_id。

    本函数是 chunk_id 生成的**唯一入口**：indexer / ChunkRegistry 写入 / 测试 fixture
    全部走此函数，禁止散落复刻 `uuid5(NAMESPACE_REPO, ...)`，否则 Pitfall 1 全量漂移。

    **分支命名空间（work item）**：

    - base 分支（``branch_name == ""``）：维持 `f"{repo_id}:{file_path}:{chunk_index}"`
      **字节级不变**（零漂移）——`branch_name` 形参放末位 + 默认空串，全部现存三参
      调用方一字不改即走 base 路径，存量 Qdrant point_id ↔ ChunkRegistry 同源约定零
      破坏（存量无需回填）。
    - feature 分支（``branch_name`` 非空）：掺入分支名
      `f"{repo_id}:{branch_name}:{file_path}:{chunk_index}"`，与 base 必然不同。根因
      修复跨分支同文件 chunk_id PK 碰撞（ChunkRegistry PK=chunk_id，feature 命名空间
      使 PK 天然不同，`update_or_create` 不再跨分支覆盖 base 行）。

    本函数是**纯函数、不查库**：「等于 base_branch 视为空串」的归一化**不在此实现**
    （放调用方，由 implementation 写入侧接通），以保函数纯度与 golden 测试可稳定。
    拼接格式锁定（per contract）；任何顺序 / 分隔符变更都构成 chunk_id 漂移。

    Args:
        repo_id: Repository UUID 的字符串形式（调用方传 `str(repo.id)`）。
        file_path: 相对仓库根的路径字符串（与 indexer 现有规范一致，不再做归一化）。
        chunk_index: ≥0 的整数（同一 file_path 内 chunk 出现次序，从 0 起递增）。
        branch_name: 分支名；``""``（默认）= base 字节不变，非空 = feature 掺分支名。
            调用方负责把"等于 base_branch"归一化为 ``""``（implementation 接通）。

    Returns:
        uuid.UUID 实例（不是 str；调用方按需 `str(cid)` 自行转字符串）。
    """
    if branch_name:
        return uuid.uuid5(
            NAMESPACE_REPO, f"{repo_id}:{branch_name}:{file_path}:{chunk_index}"
        )
    return uuid.uuid5(NAMESPACE_REPO, f"{repo_id}:{file_path}:{chunk_index}")
