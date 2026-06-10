"""首页 Dashboard 聚合统计 API。

提供单一端点 `GET /api/system/dashboard/stats/`，一次性返回：

- 累计统计 + 今日新增：仓库数、代码关联（chunk 边）数、完成编码次数、
  技术方案份数、回答问题数、沉淀文档份数
- 进行中状态：正在进行的编码工作（chat CodingSession + workflow CodingTask）

注意：不返回「正在输出中的回答」（running Conversation 列表）——对话是
owner-scoped 数据（ISO-01 用户状态隔离），不能在全局首页暴露其他用户的
会话标题与入口。

统计口径说明：

- 「编码」合并两个来源：chat 发起的 CodingSession 与 workflow 发起的 CodingTask。
- 「技术方案」合并 chat CodingPlan 与飞书 work item 的 McpWorkItemTechnicalPlan。
- 「问题」按 user 角色消息计数（一条用户消息视为一个问题）。
- 「文档」按已生成飞书文档的方案计数（CodingPlan.feishu_doc_token /
  McpWorkItemTechnicalPlan.feishu_document_id 非空）。
"""

from typing import Any

import structlog
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from chat.models import CodingPlan, CodingSession, Message
from code_relations.models import ChunkEdge
from mcp_tools.models import McpWorkItemTechnicalPlan
from repositories.models import Repository
from workflows.models.coding_task import CodingTask, CodingTaskStatus

logger = structlog.get_logger(__name__)

# chat 编码会话的「进行中」状态（draft 仅是方案草稿，不算进行中）
CODING_SESSION_ACTIVE = [
    CodingSession.Status.CONFIRMED,
    CodingSession.Status.RUNNING,
    CodingSession.Status.AWAITING_CONFIRMATION,
]

# workflow 编码任务的「进行中」状态
CODING_TASK_ACTIVE = [
    CodingTaskStatus.PLANNING,
    CodingTaskStatus.PLAN_REVIEW,
    CodingTaskStatus.EXECUTING,
    CodingTaskStatus.CODE_REVIEW,
]

# workflow 编码任务的「完成」状态（partial_success 已产出代码，计入完成）
CODING_TASK_DONE = [
    CodingTaskStatus.MERGED,
    CodingTaskStatus.PARTIAL_SUCCESS,
]

IN_PROGRESS_LIMIT = 10


class DashboardStatsView(APIView):
    """首页统计概览（累计 + 今日新增 + 进行中列表）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        today = timezone.localdate()

        # ---- 仓库 ----
        repo_qs = Repository.objects.all()
        repositories = {
            "total": repo_qs.count(),
            "today": repo_qs.filter(created_at__date=today).count(),
        }

        # ---- 代码关联（chunk 关系边）----
        edge_qs = ChunkEdge.objects.all()
        code_relations = {
            "total": edge_qs.count(),
            "today": edge_qs.filter(created_at__date=today).count(),
        }

        # ---- 完成的编码（chat CodingSession + workflow CodingTask）----
        session_done = CodingSession.objects.filter(status=CodingSession.Status.COMPLETED)
        task_done = CodingTask.objects.filter(status__in=CODING_TASK_DONE)
        codings = {
            "total": session_done.count() + task_done.count(),
            # CodingSession 无 completed_at，用 updated_at 近似「今日完成」
            "today": (
                session_done.filter(updated_at__date=today).count()
                + task_done.filter(completed_at__date=today).count()
            ),
        }

        # ---- 技术方案（chat CodingPlan + work item 技术方案）----
        plan_qs = CodingPlan.objects.all()
        wi_plan_qs = McpWorkItemTechnicalPlan.objects.all()
        tech_plans = {
            "total": plan_qs.count() + wi_plan_qs.count(),
            "today": (
                plan_qs.filter(created_at__date=today).count()
                + wi_plan_qs.filter(created_at__date=today).count()
            ),
        }

        # ---- 回答的问题（user 消息数）----
        question_qs = Message.objects.filter(
            role=Message.Role.USER,
            conversation__is_deleted=False,
        )
        questions = {
            "total": question_qs.count(),
            "today": question_qs.filter(created_at__date=today).count(),
        }

        # ---- 沉淀的文档（已生成飞书文档的方案）----
        doc_plan_qs = CodingPlan.objects.exclude(feishu_doc_token="")
        doc_wi_qs = McpWorkItemTechnicalPlan.objects.exclude(feishu_document_id="")
        documents = {
            "total": doc_plan_qs.count() + doc_wi_qs.count(),
            "today": (
                doc_plan_qs.filter(created_at__date=today).count()
                + doc_wi_qs.filter(created_at__date=today).count()
            ),
        }

        # ---- 进行中的编码工作 ----
        coding_items: list[dict[str, Any]] = []

        active_sessions = (
            CodingSession.objects.filter(status__in=CODING_SESSION_ACTIVE)
            .select_related("repository", "coding_plan")
            .order_by("-updated_at")
        )
        active_sessions_count = active_sessions.count()
        for s in active_sessions[:IN_PROGRESS_LIMIT]:
            title = ""
            if s.coding_plan_id is not None and s.coding_plan is not None:
                title = s.coding_plan.title
            coding_items.append(
                {
                    "id": str(s.id),
                    "title": title or (s.tech_plan[:50] if s.tech_plan else "编码会话"),
                    "repository_name": s.repository.name if s.repository_id else "",
                    "status": s.status,
                    "status_label": s.get_status_display(),
                    "source": "chat",
                    "conversation_id": str(s.conversation_id),
                    "updated_at": s.updated_at.isoformat(),
                }
            )

        active_tasks = (
            CodingTask.objects.filter(status__in=CODING_TASK_ACTIVE)
            .select_related("repository")
            .order_by("-updated_at")
        )
        active_tasks_count = active_tasks.count()
        for t in active_tasks[:IN_PROGRESS_LIMIT]:
            coding_items.append(
                {
                    "id": str(t.id),
                    "title": t.name,
                    "repository_name": t.repository.name if t.repository_id else "",
                    "status": t.status,
                    "status_label": t.get_status_display(),
                    "source": "workflow",
                    "workflow_execution_id": str(t.workflow_execution_id),
                    "updated_at": t.updated_at.isoformat(),
                }
            )

        coding_items.sort(key=lambda item: item["updated_at"], reverse=True)

        logger.info(
            "dashboard.stats_served",
            coding_in_progress=active_sessions_count + active_tasks_count,
        )

        return Response(
            {
                "stats": {
                    "repositories": repositories,
                    "code_relations": code_relations,
                    "codings": codings,
                    "tech_plans": tech_plans,
                    "questions": questions,
                    "documents": documents,
                },
                "in_progress": {
                    "coding": {
                        "count": active_sessions_count + active_tasks_count,
                        "items": coding_items[:IN_PROGRESS_LIMIT],
                    },
                },
            }
        )
