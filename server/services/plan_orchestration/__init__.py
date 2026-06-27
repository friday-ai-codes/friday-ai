"""plan_orchestration —— 可复用方案编排 engine（ORCH-01）。

curated re-export：``PlanOrchestrationEngine``（状态驱动推进器）+ 可注入 stage 协议
与骨架默认实现（38-41 逐步替换）。
"""

from services.plan_orchestration.answer_resume import aanswer_round_and_resume
from services.plan_orchestration.architect_merge_adapter import (
    ArchitectMergeAdapter,
    LLMMergedPlanSynthesizer,
    MergedPlanSynthesizer,
)
from services.plan_orchestration.artifact_extraction import (
    build_produced_artifacts,
    classify_modified_files,
)
from services.plan_orchestration.artifact_injection import (
    acollect_upstream_artifacts,
    render_upstream_artifacts_section,
)
from services.plan_orchestration.ask_clarification import ask_clarification
from services.plan_orchestration.clarify_adapter import (
    ClarifyAdapter,
    default_needs_clarification,
)
from services.plan_orchestration.engine import PlanOrchestrationEngine
from services.plan_orchestration.entrypoint import (
    build_orchestration_engine,
    start_orchestration,
)
from services.plan_orchestration.merged_plan import (
    MERGED_PLAN_FIELDS,
    validate_merged_plan,
)
from services.plan_orchestration.plan_validator import (
    CHECK_NAMES,
    validate_plan,
)
from services.plan_orchestration.protocols import (
    ClarifyProtocol,
    MergeProtocol,
    RecallProtocol,
    ResearchProtocol,
    RouterProtocol,
    SkeletonClarify,
    SkeletonMerge,
    SkeletonRecall,
    SkeletonResearch,
    SkeletonRouter,
)
from services.plan_orchestration.recall_adapter import DeliveryKnowledgeRecallAdapter
from services.plan_orchestration.render import render_merged_plan_markdown
from services.plan_orchestration.repo_router_adapter import RepoRouterV2Adapter
from services.plan_orchestration.research_adapter import ResearchDispatchAdapter
from services.plan_orchestration.research_aggregation import (
    aall_research_tasks_terminal,
    amaybe_complete_research,
    parse_partial_plan_content,
)
from services.plan_orchestration.resume import (
    adrive_plan_session_to_pause_or_terminal,
)
from services.plan_orchestration.spec_generation import (
    LLMSddSpecSynthesizer,
    SddSpecSynthesizer,
    agenerate_specs_for_plan,
)
from services.plan_orchestration.wave_layering import (
    build_repo_dep_edges,
    build_repo_waves,
)
from services.plan_orchestration.wave_progression import (
    aadvance_coding_waves,
    acurrent_wave_all_terminal,
)

__all__ = [
    "PlanOrchestrationEngine",
    "start_orchestration",
    "build_orchestration_engine",
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
    "ClarifyAdapter",
    "default_needs_clarification",
    "RepoRouterV2Adapter",
    "DeliveryKnowledgeRecallAdapter",
    "ResearchDispatchAdapter",
    "aall_research_tasks_terminal",
    "amaybe_complete_research",
    "parse_partial_plan_content",
    "adrive_plan_session_to_pause_or_terminal",
    "MERGED_PLAN_FIELDS",
    "validate_merged_plan",
    "CHECK_NAMES",
    "validate_plan",
    "ArchitectMergeAdapter",
    "MergedPlanSynthesizer",
    "LLMMergedPlanSynthesizer",
    "SddSpecSynthesizer",
    "LLMSddSpecSynthesizer",
    "agenerate_specs_for_plan",
    "build_repo_waves",
    "build_repo_dep_edges",
    "acurrent_wave_all_terminal",
    "aadvance_coding_waves",
    "build_produced_artifacts",
    "classify_modified_files",
    "acollect_upstream_artifacts",
    "render_upstream_artifacts_section",
    "ask_clarification",
    "aanswer_round_and_resume",
    "render_merged_plan_markdown",
]
