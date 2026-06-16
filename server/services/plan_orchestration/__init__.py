"""plan_orchestration —— 可复用方案编排 engine（ORCH-01）。

curated re-export：``PlanOrchestrationEngine``（状态驱动推进器）+ 可注入 stage 协议
与骨架默认实现（38-41 逐步替换）。
"""

from services.plan_orchestration.engine import PlanOrchestrationEngine
from services.plan_orchestration.merged_plan import (
    MERGED_PLAN_FIELDS,
    validate_merged_plan,
)
from services.plan_orchestration.plan_validator import (
    CHECK_NAMES,
    validate_plan,
)
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
from services.plan_orchestration.recall_adapter import DeliveryKnowledgeRecallAdapter
from services.plan_orchestration.repo_router_adapter import RepoRouterV2Adapter
from services.plan_orchestration.research_adapter import ResearchDispatchAdapter
from services.plan_orchestration.research_aggregation import (
    aall_research_tasks_terminal,
    amaybe_complete_research,
    parse_partial_plan_content,
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
    "RepoRouterV2Adapter",
    "DeliveryKnowledgeRecallAdapter",
    "ResearchDispatchAdapter",
    "aall_research_tasks_terminal",
    "amaybe_complete_research",
    "parse_partial_plan_content",
    "MERGED_PLAN_FIELDS",
    "validate_merged_plan",
    "CHECK_NAMES",
    "validate_plan",
]
