"""delivery services 包 —— 操作态脊柱写入入口与派生纯函数。

re-export ``WorkItemService`` / ``WorkItemIdentity``（WorkItem 单一写入入口，INV-6）
+ ``CommentEventService`` / ``classify_approval_semantic``（评论事件单一写入入口，CMT-01）
+ ``DocumentService`` / ``derive_feishu_tenant``（Document 单一写入入口，DOC-01/INV-6）
+ ``ReleaseService``（Release 账本单一写入入口，REL-01/INV-6）
+ ``BitableReleaseAdapter``（Bitable 行 → ReleaseService 落库骨架，REL-02）。
"""

from delivery.services.bitable_release_adapter import BitableReleaseAdapter
from delivery.services.clarification_service import ClarificationService
from delivery.services.comment_event_service import (
    CommentEventService,
    classify_approval_semantic,
)
from delivery.services.comment_projection import (
    aproject_comment_tree,
    project_comment_tree,
)
from delivery.services.document_service import DocumentService, derive_feishu_tenant
from delivery.services.event_taxonomy import ALL_EVENTS, RESERVED_EVENTS, build_envelope
from delivery.services.ingest_orchestrator import StepResult, ingest_from_urls
from delivery.services.ingest_parsing import (
    BoardRef,
    MRRef,
    aresolve_repo_and_mr,
    parse_board_url,
    parse_mr_url,
)
from delivery.services.plan_session_service import PlanSessionService
from delivery.services.release_service import ReleaseService
from delivery.services.repo_coding_task_service import RepoCodingTaskService
from delivery.services.research_service import ResearchService
from delivery.services.sdd_spec_service import SddSpecService, SddSpecTransitionError
from delivery.services.technical_plan_service import (
    PlanContentInvalid,
    PlanNotFound,
    PlanRef,
    TechnicalPlanService,
    chat_codingplan_to_content,
    mcp_plan_to_content,
)
from delivery.services.work_item_service import WorkItemIdentity, WorkItemService

__all__ = [
    "WorkItemService",
    "WorkItemIdentity",
    "CommentEventService",
    "classify_approval_semantic",
    "project_comment_tree",
    "aproject_comment_tree",
    "DocumentService",
    "derive_feishu_tenant",
    "ALL_EVENTS",
    "RESERVED_EVENTS",
    "build_envelope",
    "ReleaseService",
    "BitableReleaseAdapter",
    "BoardRef",
    "MRRef",
    "parse_board_url",
    "parse_mr_url",
    "aresolve_repo_and_mr",
    "ingest_from_urls",
    "StepResult",
    "PlanSessionService",
    "ResearchService",
    "RepoCodingTaskService",
    "ClarificationService",
    "SddSpecService",
    "SddSpecTransitionError",
    "TechnicalPlanService",
    "PlanRef",
    "PlanContentInvalid",
    "PlanNotFound",
    "chat_codingplan_to_content",
    "mcp_plan_to_content",
]
