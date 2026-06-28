"""process_runtime —— 数据化 stage graph 收敛引擎（Chassis v2 · P2）。

curated re-export：``ProcessEngine`` / ``StageOutcome``（数据化推进器）+ stage/process 注册表
+ 可注入 stage 协议 + technical_plan 真实 adapters + 入口/续驱/作答 helper。
"""

from services.process_runtime.answer_resume import aanswer_round_and_resume
from services.process_runtime.architect_merge_adapter import (
    ArchitectMergeAdapter,
    LLMMergedPlanSynthesizer,
    MergedPlanSynthesizer,
)
from services.process_runtime.artifact_extraction import (
    build_produced_artifacts,
    classify_modified_files,
)
from services.process_runtime.artifact_injection import (
    acollect_upstream_artifacts,
    render_upstream_artifacts_section,
)
from services.process_runtime.ask_clarification import ask_clarification
from services.process_runtime.clarify_adapter import (
    ClarifyAdapter,
    default_needs_clarification,
)
from services.process_runtime.engine import ProcessEngine, StageOutcome
from services.process_runtime.entrypoint import (
    build_orchestration_engine,
    start_orchestration,
)
from services.process_runtime.merged_plan import (
    MERGED_PLAN_FIELDS,
    validate_merged_plan,
)
from services.process_runtime.plan_validator import (
    CHECK_NAMES,
    validate_plan,
)
from services.process_runtime.protocols import (
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
from services.process_runtime.recall_adapter import DeliveryKnowledgeRecallAdapter
from services.process_runtime.registry import (
    STAGE_DONE,
    STAGE_FAILED,
    ProcessDefinition,
    ProcessTypeRegistry,
    StageDef,
    get_process_definition,
    register_process_type,
)
from services.process_runtime.render import render_merged_plan_markdown
from services.process_runtime.repo_router_adapter import RepoRouterV2Adapter
from services.process_runtime.research_adapter import ResearchDispatchAdapter
from services.process_runtime.research_aggregation import (
    aall_research_tasks_terminal,
    amaybe_complete_research,
    parse_partial_plan_content,
)
from services.process_runtime.resume import (
    adrive_convergence_session_to_pause_or_terminal,
)
from services.process_runtime.spec_generation import (
    LLMSddSpecSynthesizer,
    SddSpecSynthesizer,
    agenerate_specs_for_plan,
)
from services.process_runtime.wave_layering import (
    build_repo_dep_edges,
    build_repo_waves,
)
from services.process_runtime.wave_progression import (
    aadvance_coding_waves,
    acurrent_wave_all_terminal,
)

__all__ = [
    "ProcessEngine",
    "StageOutcome",
    "ProcessDefinition",
    "ProcessTypeRegistry",
    "StageDef",
    "STAGE_DONE",
    "STAGE_FAILED",
    "register_process_type",
    "get_process_definition",
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
    "adrive_convergence_session_to_pause_or_terminal",
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
