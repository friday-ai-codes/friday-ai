"""plan_orchestration —— 可复用方案编排 engine（ORCH-01）。

curated re-export：``PlanOrchestrationEngine``（状态驱动推进器）+ 可注入 stage 协议
与骨架默认实现（38-41 逐步替换）。
"""

from services.plan_orchestration.engine import PlanOrchestrationEngine
from services.plan_orchestration.protocols import (
    MergeProtocol,
    RecallProtocol,
    ResearchProtocol,
    RouterProtocol,
    SkeletonMerge,
    SkeletonRecall,
    SkeletonResearch,
    SkeletonRouter,
)

__all__ = [
    "PlanOrchestrationEngine",
    "RouterProtocol",
    "RecallProtocol",
    "ResearchProtocol",
    "MergeProtocol",
    "SkeletonRouter",
    "SkeletonRecall",
    "SkeletonResearch",
    "SkeletonMerge",
]
