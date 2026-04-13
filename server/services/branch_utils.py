"""分支命名工具与 overlay collection 保护常量。"""
import hashlib
import re
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
 hash_suffix = hashlib.md5(branch_name.encode).hexdigest[:8]
 return f"{sanitized}_{hash_suffix}"
def get_overlay_collection_name(repository_id: str, branch_name: str) -> str:
 """生成功能分支 overlay collection 名称。"""
 return f"code_index_{repository_id}_br_{sanitize_branch_name(branch_name)}"
def get_effective_collection_name(
 repository_id: str, branch_name: str | None = None
) -> str:
 """获取查询时使用的有效 collection 名称。
 当仓库有 RepositoryBranchIndex 记录时按分支路由，否则降级到旧 collection。
 此函数为 Phase 检索合并预留接口。
 """
 from repositories.models import RepositoryBranchIndex
 from services.qdrant_service import QdrantService
 base_index = RepositoryBranchIndex.objects.filter(
 repository_id=repository_id, is_base_branch=True
 ).first
 if not base_index:
 return QdrantService.get_collection_name(repository_id)
 if not branch_name or branch_name == base_index.branch_name:
 return QdrantService.get_collection_name(repository_id)
 overlay_index = RepositoryBranchIndex.objects.filter(
 repository_id=repository_id, branch_name=branch_name
 ).first
 if overlay_index and overlay_index.collection_name:
 return overlay_index.collection_name
 return QdrantService.get_collection_name(repository_id)
def is_branch_index_enabled(repository_id: str) -> bool:
 """检查仓库是否已迁移到分支索引模型。"""
 from repositories.models import RepositoryBranchIndex
 return RepositoryBranchIndex.objects.filter(
 repository_id=repository_id, is_base_branch=True
 ).exists
