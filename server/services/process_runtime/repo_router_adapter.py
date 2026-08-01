"""RepoRouterV2Adapter —— routing stage 真实实现（ROUTE-01）。

把编排 `routing` 阶段的骨架 `SkeletonRouter` 替换为复用既有 `RepoRouterV2`（能力树
+ LLM 两阶段路由，自带 LLM 失败降级 Stage0/v1）的 adapter：从 `session.decomposition`
的 `requirement_text` 路由出候选仓 + confidence，映射为精简 dict 供 engine 经
`ConvergenceSessionService.transition(routing=)` 落 `ConvergenceSession.routing`。

本 adapter **不重写路由逻辑**——只做编排接线（取数 + 候选范围解析 + 结果映射）；
RepoRouterV2 自带的降级链不另加容错。
"""

from __future__ import annotations

from codegraph.services.repo_group_scope import aresolve_grouping_repo_ids
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
        不调 RepoRouterV2、不抛。候选范围 ``repository_ids`` 只在 ``include_repos``
        显式限定时非空（见 ``_resolve_repository_ids``）；项目归属信息走
        ``grouping_repository_ids``（见 ``_resolve_grouping_repository_ids``）。

        ``degraded``（Stage 1 未参与标志，Phase 107 降级 UI 数据底座）随 dict 透传进
        session.routing；``block_order`` / ``degrade_reason`` 同理（前端判定是否启用分组
        呈现与降级提示的唯一依据）。``snapshot``（快照材料）仅供 ``_h_route`` 组
        repo.routing 事件 payload 用——由 ``_h_route`` 在落 session.routing 前 pop
        剔除，**不落库**（session.routing 保持精简，快照细节在 trace 事件里）。
        """
        query = (session.decomposition or {}).get("requirement_text", "")
        if not query:
            return {"candidates": [], "router_version": "skipped", "auto_selected": False}

        repository_ids = await self._resolve_repository_ids(session)
        grouping_repository_ids = await self._resolve_grouping_repository_ids(session)
        result = await RepoRouterV2.route(
            query,
            top_k=self.top_k,
            repository_ids=repository_ids,
            grouping_repository_ids=grouping_repository_ids,
            use_llm=True,
        )
        candidates = [
            {
                "repo_id": c.repo_id,
                "confidence": c.confidence,
                "repository_name": c.repo_name,
                # 呈现层两键 additive-safe：下游 clarify/research/feature_confirm 只读
                # confidence，加键不改任何既有读法。
                "group": c.group,
                "trust": c.trust,
            }
            for c in result.candidates
        ]
        return {
            "candidates": candidates,
            "router_version": result.router_version,
            "auto_selected": result.auto_selected,
            "degraded": result.degraded,
            "block_order": result.block_order,
            "degrade_reason": result.degrade_reason,
            "snapshot": result.snapshot,
        }

    async def _resolve_repository_ids(self, session: ConvergenceSession) -> list[str] | None:
        """候选范围：仅 ``include_repos`` 显式限定时硬过滤，否则 ``None``（全库召回）。

        D-1（107-CONTEXT）：原先的「② work_item.space 仓库」一级已删除——它正是硬过滤
        的来源，会让 ``global`` 分区恒空、ROUTE-01/02 上线即无效果，且从 UI 看不出来
        （只是少一个分区）。空间归属信息现在走 ``grouping_repository_ids``（只标注、
        不过滤、不打分）。硬过滤语义完整保留给 ``include_repos`` 这类明确要限定范围
        的调用方。

        T-107-01 前提：沿用 ``mcp_tools/views.py`` 的 ``RouteRepositoriesView`` 与
        ``repositories/route_views.py`` 两个**已上线**入口的既有判断（二者本来就全库
        路由、只有 ``IsAuthenticated``、无 per-user/per-space 可见性过滤）；Stage 0 侧
        不存在按用户过滤的机制，故本改动**不绕过任何现存权限检查**。

        但透出面不止仓名，别按「仓名不敏感」一句带过：跨组候选的 ``evidence`` 里还有
        命中的**能力树节点路径**、``sub_project`` 子应用名与 LLM 的 ``reasoning``
        （见 ``agents/tools/repository_relevance.py`` 的 evidence 组装）。对空间成员而言，
        这是一个从「空间内仓」放宽到「全库」的新元数据面 —— 与既有全库入口同级，但确实
        比「仓名」更宽。若后续要收窄，现成判据是 ``group == global``，改动面只在
        evidence 映射那一处。
        """
        include = (session.decomposition or {}).get("include_repos")
        if include:
            return [str(r) for r in include]
        return None

    async def _resolve_grouping_repository_ids(
        self, session: ConvergenceSession
    ) -> list[str] | None:
        """分组依据：work_item 所在项目的关联仓宽口径并集（D-2），无上下文返回 ``None``。

        返回排序后的列表而非集合——快照/回放需要确定性的参数序列。
        """
        if session.work_item_id is None:
            return None
        ids = await aresolve_grouping_repo_ids(work_item_id=session.work_item_id)
        return None if ids is None else sorted(ids)
