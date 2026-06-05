"""分支命名工具与 overlay collection 保护常量。"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from repositories.models import RepositoryBranchIndex

logger = structlog.get_logger(__name__)

MAX_OVERLAY_COLLECTIONS_PER_REPO = 20


class BranchOverlayLimitExceeded(Exception):
    """单仓库 overlay collection 数量超过硬上限。"""


def sanitize_branch_name(branch_name: str) -> str:
    """将分支名清洗为 Qdrant collection 名兼容格式。

    替换 / 和特殊字符为 _，截断到 80 字符，附加 MD5 前 8 位保证唯一性。
    """
    sanitized = branch_name.replace("/", "_")
    sanitized = re.sub(r"[^a-zA-Z0-9_\-.]", "_", sanitized)
    sanitized = sanitized[:80]
    hash_suffix = hashlib.md5(branch_name.encode()).hexdigest()[:8]
    return f"{sanitized}_{hash_suffix}"


def get_overlay_collection_name(repository_id: str, branch_name: str) -> str:
    """生成功能分支 overlay collection 名称。"""
    return f"code_index_{repository_id}_br_{sanitize_branch_name(branch_name)}"


def get_effective_collection_name(
    repository_id: str, branch_name: str | None = None
) -> str:
    """获取查询时使用的有效 collection 名称。

    当仓库有 RepositoryBranchIndex 记录时按分支路由，否则降级到旧 collection。
    此函数为 implementation 检索合并预留接口。
    """
    from repositories.models import RepositoryBranchIndex
    from services.qdrant_service import QdrantService

    base_index = RepositoryBranchIndex.objects.filter(
        repository_id=repository_id, is_base_branch=True
    ).first()

    if not base_index:
        return QdrantService.get_collection_name(repository_id)

    if not branch_name or branch_name == base_index.branch_name:
        return QdrantService.get_collection_name(repository_id)

    overlay_index = RepositoryBranchIndex.objects.filter(
        repository_id=repository_id, branch_name=branch_name
    ).first()
    if overlay_index and overlay_index.collection_name:
        return overlay_index.collection_name

    return QdrantService.get_collection_name(repository_id)


def is_branch_index_enabled(repository_id: str) -> bool:
    """检查仓库是否已迁移到分支索引模型。"""
    from repositories.models import RepositoryBranchIndex

    return RepositoryBranchIndex.objects.filter(
        repository_id=repository_id, is_base_branch=True
    ).exists()


async def is_branch_index_enabled_async(repository_id: str) -> bool:
    """检查仓库是否已迁移到分支索引模型（async 版本）。"""
    from repositories.models import RepositoryBranchIndex

    return await RepositoryBranchIndex.objects.filter(
        repository_id=repository_id, is_base_branch=True
    ).aexists()


async def resolve_branch_for_query(
    repository_id: str,
    branch_name: str | None,
) -> tuple[str | None, RepositoryBranchIndex | None]:
    """解析查询时的有效分支。

    回退链: explicit branch → repo.base_branch → repo.default_branch → None（旧路径）
    返回 (effective_branch_name, branch_index_or_none)。
    """
    from repositories.models import Repository, RepositoryBranchIndex

    if not await is_branch_index_enabled_async(repository_id):
        return None, None

    repo = await Repository.objects.filter(id=repository_id).afirst()
    if not repo:
        return None, None

    effective_branch = branch_name or repo.base_branch or repo.default_branch
    if not effective_branch:
        return None, None

    branch_index = await RepositoryBranchIndex.objects.filter(
        repository_id=repository_id,
        branch_name=effective_branch,
    ).afirst()

    return effective_branch, branch_index


async def get_branch_file_changes(
    branch_index: RepositoryBranchIndex,
) -> tuple[set[str], set[str], set[str]]:
    """获取分支的文件变更集。

    Returns:
        (added_files, modified_files, deleted_files) 三个 set
    """
    from repositories.models import BranchFileIndex

    added: set[str] = set()
    modified: set[str] = set()
    deleted: set[str] = set()

    async for fi in BranchFileIndex.objects.filter(branch_index=branch_index):
        if fi.change_type == "added":
            added.add(fi.file_path)
        elif fi.change_type == "modified":
            modified.add(fi.file_path)
        elif fi.change_type == "deleted":
            deleted.add(fi.file_path)

    return added, modified, deleted
