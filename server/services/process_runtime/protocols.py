"""编排 engine 的可注入 stage 依赖协议 + 骨架默认实现（ORCH-01）。

engine 设计为入口无关 + 可注入依赖：四个 stage 依赖（路由/召回/调研/融合）以
``typing.Protocol`` 声明窄接口（runtime 不强制），使 Phase 38-41 逐步替换真实实现
且单测可 mock。本 phase 的默认注入为 ``Skeleton*`` 骨架：对应方法显式
``raise NotImplementedError``（带接入 phase TODO），而非静默 pass —— 让「未接入
stage」在开发期显式暴露（T-36-03-02）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from delivery.models import ConvergenceSession

__all__ = [
    "RouterProtocol",
    "RecallProtocol",
    "ResearchProtocol",
    "MergeProtocol",
    "ClarifyProtocol",
    "SkeletonRouter",
    "SkeletonRecall",
    "SkeletonResearch",
    "SkeletonMerge",
    "SkeletonClarify",
]


@runtime_checkable
class RouterProtocol(Protocol):
    """仓库路由 stage 依赖（Phase 38 RepoRouterV2 实现，返回候选仓 + confidence）。"""

    async def route(self, session: ConvergenceSession) -> dict: ...


@runtime_checkable
class RecallProtocol(Protocol):
    """历史/相似召回 stage 依赖（Phase 38 DeliveryKnowledgeSearchService 召回）。"""

    async def recall(self, session: ConvergenceSession) -> dict: ...


@runtime_checkable
class ResearchProtocol(Protocol):
    """并行调研 stage 依赖（Phase 39 filter_then_container fan-out）。"""

    async def dispatch(self, session: ConvergenceSession) -> dict: ...


@runtime_checkable
class MergeProtocol(Protocol):
    """架构师融合 stage 依赖（Phase 40 融合 + PlanValidator）。"""

    async def merge(self, session: ConvergenceSession) -> dict: ...


@runtime_checkable
class ClarifyProtocol(Protocol):
    """澄清 stage 依赖（Phase 41 HITL 澄清回路，needs-clarification policy 判定）。

    返回 ``{"needs_clarification": bool, ...}``：True → engine 保持 clarifying 挂起
    （建 pending Clarification + emit clarification.asked）；False → engine 转移 clarified
    （clarifying→researching）。
    """

    async def clarify(self, session: ConvergenceSession) -> dict: ...


class SkeletonRouter:
    """路由骨架默认实现：显式 NotImplementedError（Phase 38 接入）。"""

    async def route(self, session: ConvergenceSession) -> dict:
        raise NotImplementedError("RouterProtocol.route 未实现 —— Phase 38 RepoRouterV2 接入")


class SkeletonRecall:
    """召回骨架默认实现：显式 NotImplementedError（Phase 38 接入）。"""

    async def recall(self, session: ConvergenceSession) -> dict:
        raise NotImplementedError(
            "RecallProtocol.recall 未实现 —— Phase 38 DeliveryKnowledgeSearchService 接入"
        )


class SkeletonResearch:
    """调研骨架默认实现：显式 NotImplementedError（Phase 39 接入）。"""

    async def dispatch(self, session: ConvergenceSession) -> dict:
        raise NotImplementedError(
            "ResearchProtocol.dispatch 未实现 —— Phase 39 filter_then_container fan-out 接入"
        )


class SkeletonMerge:
    """融合骨架默认实现：显式 NotImplementedError（Phase 40 接入）。"""

    async def merge(self, session: ConvergenceSession) -> dict:
        raise NotImplementedError(
            "MergeProtocol.merge 未实现 —— Phase 40 架构师融合 + PlanValidator 接入"
        )


class SkeletonClarify:
    """澄清骨架默认实现：显式 NotImplementedError（Phase 41 接入）。"""

    async def clarify(self, session: ConvergenceSession) -> dict:
        raise NotImplementedError(
            "ClarifyProtocol.clarify 未实现 —— Phase 41 HITL 澄清回路接入"
        )
