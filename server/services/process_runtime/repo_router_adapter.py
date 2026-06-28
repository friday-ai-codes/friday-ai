"""RepoRouterV2Adapter —— routing stage 真实实现（ROUTE-01）。

把编排 `routing` 阶段的骨架 `SkeletonRouter` 替换为复用既有 `RepoRouterV2`（能力树
+ LLM 两阶段路由，自带 LLM 失败降级 Stage0/v1）的 adapter：从 `session.decomposition`
的 `requirement_text` 路由出候选仓 + confidence，映射为精简 dict 供 engine 经
`ConvergenceSessionService.transition(routing=)` 落 `ConvergenceSession.routing`。

本 adapter **不重写路由逻辑**——只做编排接线（取数 + 候选范围解析 + 结果映射）；
RepoRouterV2 自带的降级链不另加容错。
"""

from __future__ import annotations

from asgiref.sync import sync_to_async

from codegraph.services.repo_router_v2 import RepoRouterV2
from delivery.models import ConvergenceSession

__all__ = ["RepoRouterV2Adapter"]


class RepoRouterV2Adapter:
    """仓库路由 stage 依赖的真实实现（满足 RouterProtocol，ROUTE-01）。"""

    def __init__(self, *, top_k: int = 3) -> None:
        # top_k 候选数上限（对齐 38-CONTEXT 默认 3，可配）
        self.top_k = top_k

    async def route(self, session: ConvergenceSession) -> dict:
        """路由出候选仓 + confidence，返回精简 dict（候选 + version + auto_selected）。

        无 requirement_text（空 query）→ 直接返回空候选（router_version="skipped"），
        不调 RepoRouterV2、不抛。候选范围 repository_ids 按 include_repos → work_item
        所属 project 仓库 → 全库 优先级解析（见 ``_resolve_repository_ids``）。
        """
        query = (session.decomposition or {}).get("requirement_text", "")
        if not query:
            return {"candidates": [], "router_version": "skipped", "auto_selected": False}

        repository_ids = await self._resolve_repository_ids(session)
        result = await RepoRouterV2.route(
            query, top_k=self.top_k, repository_ids=repository_ids, use_llm=True
        )
        candidates = [
            {
                "repo_id": c.repo_id,
                "confidence": c.confidence,
                "repository_name": c.repo_name,
            }
            for c in result.candidates
        ]
        return {
            "candidates": candidates,
            "router_version": result.router_version,
            "auto_selected": result.auto_selected,
        }

    async def _resolve_repository_ids(self, session: ConvergenceSession) -> list[str] | None:
        """候选范围优先级解析：① include_repos → ② work_item.space 仓库 → ③ None（全库）。"""
        include = (session.decomposition or {}).get("include_repos")
        if include:
            return [str(r) for r in include]
        if session.work_item_id is not None:
            project_repos = await self._project_repository_ids(session.work_item_id)
            if project_repos:
                return project_repos
        return None

    @sync_to_async
    def _project_repository_ids(self, work_item_id) -> list[str] | None:
        """取 work_item 所属 project 的仓库 id 列表（同步 ORM 经 sync_to_async）。"""
        from delivery.models import WorkItem

        wi = (
            WorkItem.objects.select_related("space")
            .filter(id=work_item_id)
            .first()
        )
        if wi is None or wi.space is None:
            return None
        repo_ids = [str(r) for r in wi.space.repositories.values_list("id", flat=True)]
        return repo_ids or None
