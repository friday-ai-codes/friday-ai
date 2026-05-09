"""仓库摘要索引构建服务 —— per //。"""
from __future__ import annotations
import structlog
logger = structlog.get_logger(__name__)
class RepoSummaryBuilder:
 """仓库摘要索引构建服务 —— 从 codegraph 四模型提取摘要并写入 Qdrant。"""
 @classmethod
 async def build(cls, repository_id: str) -> bool:
 """构建或刷新仓库摘要索引，upsert 到 Qdrant repo_summaries collection。"""
 raise NotImplementedError
