"""多维分面服务（PageIndex 化）。

分面分两类，治理方式不同：

- **语义分面**（业务线/服务对象/技术形态）：repo_summary 任务由 LLM 从
  FacetVocabulary 受控词表选值，callback 写入 Repository.facets；本服务不碰。
- **事实分面**（活跃度/技术栈/关键程度/团队归属）：本服务从既有数据自动计算，
  随索引完成刷新，永不漂移、零 LLM。

人工 pin：facets["_pinned"] 为维度名列表，刷新时跳过这些维度。
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from urllib.parse import urlparse

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

logger = structlog.get_logger(__name__)

# 事实分面维度名（与语义分面共用 facets JSONField，键不冲突）
DIM_ACTIVITY = "活跃度"
DIM_CRITICALITY = "关键程度"
DIM_TEAM = "团队归属"
DIM_TECH_STACK = "技术栈"

_EXT_LANGUAGE_MAP = {
    "py": "Python", "go": "Go", "ts": "TypeScript", "tsx": "TypeScript",
    "js": "JavaScript", "jsx": "JavaScript", "vue": "Vue", "java": "Java",
    "kt": "Kotlin", "rs": "Rust", "rb": "Ruby", "php": "PHP", "cs": "C#",
    "cpp": "C++", "c": "C", "swift": "Swift", "m": "Objective-C",
    "scala": "Scala", "sql": "SQL", "sh": "Shell",
}


class FacetService:
    """事实分面计算与刷新——纯 @classmethod async 服务类。"""

    @classmethod
    async def refresh_fact_facets(cls, repository_id: str) -> dict[str, str]:
        """重算并写回事实分面；返回最终 facets dict。"""
        from repositories.models import Repository

        repo = await Repository.objects.filter(id=repository_id).afirst()
        if repo is None:
            return {}

        computed = await sync_to_async(
            cls._compute_fact_facets, thread_sensitive=False
        )(repository_id, repo.git_url)

        facets = dict(repo.facets or {})
        pinned = set(facets.get("_pinned", []))
        for dim, value in computed.items():
            if dim in pinned:
                continue
            if value:
                facets[dim] = value

        repo.facets = facets
        await repo.asave(update_fields=["facets", "updated_at"])
        logger.info(
            "fact_facets_refreshed",
            repository_id=repository_id,
            facets={k: v for k, v in computed.items() if v},
        )
        return facets

    # ------------------------------------------------------------------
    # 计算逻辑（sync，跑在线程池）
    # ------------------------------------------------------------------

    @classmethod
    def _compute_fact_facets(cls, repository_id: str, git_url: str) -> dict[str, str]:
        return {
            DIM_ACTIVITY: cls._compute_activity(repository_id),
            DIM_CRITICALITY: cls._compute_criticality(repository_id),
            DIM_TEAM: cls._compute_team(git_url),
            DIM_TECH_STACK: cls._compute_tech_stack(repository_id),
        }

    @classmethod
    def _compute_activity(cls, repository_id: str) -> str:
        """活跃度：FileIndex 文件级最近提交时间 → 四档。"""
        from django.db.models import Max

        from repositories.models import FileIndex

        latest = FileIndex.objects.filter(repository_id=repository_id).aggregate(
            latest=Max("last_commit_authored_at")
        )["latest"]
        if latest is None:
            return ""
        age = timezone.now() - latest
        if age <= timedelta(days=14):
            return "活跃开发"
        if age <= timedelta(days=90):
            return "维护中"
        if age <= timedelta(days=365):
            return "低频"
        return "疑似废弃"

    @classmethod
    def _compute_criticality(cls, repository_id: str) -> str:
        """关键程度：跨仓 API 调用入度（被依赖越多越核心）。"""
        try:
            from codegraph.models import CrossRepoApiCall

            in_degree = CrossRepoApiCall.objects.filter(
                endpoint__repository_id=repository_id
            ).count()
        except Exception:  # noqa: BLE001 — codegraph 未启用时静默
            return ""
        if in_degree >= 10:
            return "核心"
        if in_degree >= 1:
            return "重要"
        return "边缘"

    @classmethod
    def _compute_team(cls, git_url: str) -> str:
        """团队归属：git URL 的 group/namespace 段。"""
        if not git_url:
            return ""
        try:
            if git_url.startswith("git@"):
                # git@host:group/sub/repo.git
                path = git_url.split(":", 1)[1]
            else:
                path = urlparse(git_url).path
            segments = [s for s in path.strip("/").split("/") if s]
            if len(segments) >= 2:
                # 去掉末段 repo 名，剩余即 namespace 链
                return "/".join(segments[:-1])
        except Exception:  # noqa: BLE001
            return ""
        return ""

    @classmethod
    def _compute_tech_stack(cls, repository_id: str) -> str:
        """技术栈：FileIndex 扩展名分布 Top-3 映射为语言名。"""
        from repositories.models import FileIndex

        paths = FileIndex.objects.filter(repository_id=repository_id).values_list(
            "file_path", flat=True
        )
        counter: Counter[str] = Counter()
        for fp in paths:
            ext = fp.rsplit(".", 1)[-1].lower() if "." in fp else ""
            lang = _EXT_LANGUAGE_MAP.get(ext)
            if lang:
                counter[lang] += 1
        if not counter:
            return ""
        return "/".join(lang for lang, _ in counter.most_common(3))


__all__ = ["FacetService", "DIM_ACTIVITY", "DIM_CRITICALITY", "DIM_TEAM", "DIM_TECH_STACK"]
