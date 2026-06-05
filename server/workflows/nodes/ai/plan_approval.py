"""Plan Approval node - reviews and approves/rejects technical plans.

Creates a formal Feishu document from the technical plan, sends an
interactive approval card to the configured chat, and enters
waiting_event state. The workflow resumes when a user clicks
approve or reject on the card.
"""

from datetime import datetime, timezone
from typing import Any, ClassVar

import structlog

from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.registry import register_node

logger = structlog.get_logger(__name__)


@register_node
class PlanApprovalNode(BaseNode):
    """Plan Approval node.

    Reviews technical plans and routes to approved/rejected outputs.
    Uses waiting_event mechanism with Feishu card callbacks.

    Flow:
    1. Extract plan data from input
    2. Create formal Feishu document with plan content
    3. Build and send interactive approval card to chat
    4. Return waiting_event (workflow suspends)
    5. On approve/reject callback -> engine resumes via approved/rejected port
    """

    node_type: ClassVar[str] = "ai_plan_approval"
    display_name: ClassVar[str] = "方案审批"
    description: ClassVar[str] = "审批技术方案"
    icon: ClassVar[str] = "check-circle"
    category: ClassVar[NodeCategory] = NodeCategory.AI
    execution_mode: ClassVar[str] = "server_local"
    is_blocking: ClassVar[bool] = True

    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "chat_id": {
                "type": "string",
                "title": "Chat ID",
                "description": "飞书群 ID，用于发送审批通知",
                "default": "",
            },
        },
        "required": [],
    }

    inputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="default",
            label="方案输入",
            port_type=PortType.OBJECT,
            required=True,
            description="待审批的技术方案",
        ),
    ]

    outputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="approved",
            label="通过",
            port_type=PortType.OBJECT,
            description="审批通过后的输出",
        ),
        NodePort(
            name="rejected",
            label="驳回",
            port_type=PortType.OBJECT,
            description="审批驳回后的输出",
        ),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """Execute plan approval node.

        1. Extract plan data from input
        2. Create formal Feishu technical plan document
        3. Build approval card and send to Feishu chat
        4. Return waiting_event, waiting for user action
        """
        log = logger.bind(
            execution_id=context.execution_id,
            node_id=context.node_id,
        )

        # 1. Extract input data
        plan_data = context.get_input("plan")
        if not plan_data:
            # Fallback: try to get plan from the entire input_data
            # (upstream node may output plan at top level)
            if isinstance(context.input_data, dict) and "summary" in context.input_data:
                plan_data = context.input_data
            else:
                return NodeResult(
                    status="failed",
                    error="缺少技术方案数据（plan）",
                )

        if not isinstance(plan_data, dict):
            return NodeResult(
                status="failed",
                error="技术方案数据格式错误，期望 dict",
            )

        final_answer = context.get_input("final_answer", "")
        usage = context.get_input("usage", {})
        plan_title = plan_data.get("title", "技术方案")
        plan_summary = plan_data.get("summary", "")

        log.info(
            "plan_approval_start",
            plan_title=plan_title,
            summary_length=len(plan_summary),
        )

        # 2. Create formal Feishu document
        document_url = ""
        document_url = await self._create_plan_document(
            context, plan_data, plan_title, log
        )

        # 3. Build and send approval card
        chat_id = context.get_config("chat_id", "")
        if chat_id:
            await self._send_approval_card(
                context=context,
                plan_title=plan_title,
                plan_summary=plan_summary,
                document_url=document_url,
                chat_id=chat_id,
                log=log,
            )
        else:
            log.warning("plan_approval_no_chat_id", node_id=context.node_id)

        # 4. Return waiting_event
        return NodeResult(
            status="waiting_event",
            output={
                "plan": plan_data,
                "final_answer": final_answer,
                "usage": usage,
                "document_url": document_url,
                "approval_status": "pending",
            },
        )

    async def _create_plan_document(
        self,
        context: ExecutionContext,
        plan_data: dict[str, Any],
        plan_title: str,
        log: Any,
    ) -> str:
        """Create a formal Feishu document from plan data.

        Args:
            context: Execution context
            plan_data: Technical plan data dict
            plan_title: Document title
            log: Bound logger

        Returns:
            Document URL, or empty string if creation failed
        """
        try:
            # Get project from workflow execution
            if not context.workflow_execution:
                log.warning("plan_approval_no_workflow_execution")
                return ""

            from workflows.models import WorkflowExecution

            we = await WorkflowExecution.objects.select_related(
                "workflow__project"
            ).aget(id=context.workflow_execution.id)
            project = we.workflow.project if we.workflow else None

            if not project:
                log.warning("plan_approval_no_project")
                return ""

            from agents.tools.feishu_doc_tools import (
                create_feishu_doc_client_for_project,
            )

            client = await create_feishu_doc_client_for_project(project)

            # Build document content in Markdown
            content = self._build_document_content(plan_data, plan_title)

            # Get folder token from project config
            folder_token = getattr(project, "feishu_doc_folder_token", None) or ""
            if not folder_token:
                log.warning("plan_approval_no_folder_token")
                return ""

            # Create document
            result = await client.create_document(
                title=f"[技术方案] {plan_title}",
                folder_token=folder_token,
                content=content,
            )

            document_url: str = result.get("url", "")
            log.info(
                "plan_document_created",
                document_id=result.get("document_id"),
                url=document_url,
            )
            return document_url

        except Exception as e:
            # Document creation failure is non-blocking
            log.warning(
                "plan_document_creation_failed",
                error=str(e),
            )
            return ""

    def _build_document_content(
        self,
        plan_data: dict[str, Any],
        plan_title: str,
    ) -> str:
        """Build Markdown content for the plan document.

        Args:
            plan_data: Technical plan data dict
            plan_title: Plan title

        Returns:
            Markdown formatted document content
        """
        sections: list[str] = []

        # Title and metadata
        sections.append(f"# {plan_title}")
        sections.append(
            f"**创建时间:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )

        # Summary
        summary = plan_data.get("summary", "")
        if summary:
            sections.append("## 方案概要")
            sections.append(summary)

        # Execution plan (tasks)
        execution_plan = plan_data.get("execution_plan", [])
        if execution_plan:
            sections.append("## 执行任务")
            for i, task in enumerate(execution_plan, 1):
                if isinstance(task, dict):
                    task_name = task.get("name", f"任务 {i}")
                    task_desc = task.get("description", "")
                    repository = task.get("repository", "")
                    files = task.get("files", [])
                    coding_instruction = task.get("coding_instruction", "")

                    sections.append(f"### {i}. {task_name}")
                    if task_desc:
                        sections.append(task_desc)
                    if repository:
                        sections.append(f"**仓库:** {repository}")
                    if files:
                        files_list = files if isinstance(files, list) else [files]
                        sections.append(
                            "**涉及文件:**\n"
                            + "\n".join(f"- {f}" for f in files_list)
                        )
                    if coding_instruction:
                        sections.append(f"**编码指令:**\n{coding_instruction}")

        # Risks
        risks = plan_data.get("risks", [])
        if risks:
            sections.append("## 风险评估")
            for risk in risks:
                if isinstance(risk, str):
                    sections.append(f"- {risk}")
                elif isinstance(risk, dict):
                    sections.append(
                        f"- **{risk.get('name', '风险')}**: {risk.get('description', '')}"
                    )

        # Assumptions
        assumptions = plan_data.get("assumptions", [])
        if assumptions:
            sections.append("## 假设前提")
            for assumption in assumptions:
                if isinstance(assumption, str):
                    sections.append(f"- {assumption}")
                elif isinstance(assumption, dict):
                    sections.append(f"- {assumption.get('description', '')}")

        # Decision process
        document_url = plan_data.get("document_url", "")
        if document_url:
            sections.append("## 决策过程")
            sections.append(f"参考方案文档: [{document_url}]({document_url})")
        else:
            sections.append("## 决策过程")
            sections.append("方案由 AI 自动生成")

        return "\n\n".join(sections)

    async def _send_approval_card(
        self,
        context: ExecutionContext,
        plan_title: str,
        plan_summary: str,
        document_url: str,
        chat_id: str,
        log: Any,
    ) -> None:
        """Build and send approval card to Feishu chat.

        Args:
            context: Execution context
            plan_title: Plan title for card header
            plan_summary: Plan summary for card body
            document_url: URL to full plan document
            chat_id: Feishu chat ID to send card to
            log: Bound logger
        """
        try:
            from feishu.cards.approval_card import build_approval_card

            # Get node_id (WorkflowNode UUID, not NodeExecution UUID)
            card = build_approval_card(
                plan_title=plan_title,
                plan_summary=plan_summary,
                document_url=document_url,
                execution_id=context.execution_id,
                node_id=context.node_id,
            )

            # Get project for Feishu credentials
            if not context.workflow_execution:
                log.warning("plan_approval_no_workflow_execution_for_card")
                return

            from workflows.models import WorkflowExecution as WE2

            we = await WE2.objects.select_related(
                "workflow__project"
            ).aget(id=context.workflow_execution.id)
            project = we.workflow.project if we.workflow else None

            if not project:
                log.warning("plan_approval_no_project_for_card")
                return

            from agents.tools.feishu_doc_tools import (
                create_feishu_doc_client_for_project,
            )
            from services.feishu_im import FeishuIMClient

            # Use same credentials as doc client
            doc_client = await create_feishu_doc_client_for_project(project)
            im_client = FeishuIMClient(
                app_id=doc_client.app_id,
                app_secret=doc_client.app_secret,
            )

            message_id = await im_client.send_card(
                receive_id=chat_id,
                receive_id_type="chat_id",
                card=card,
            )

            log.info(
                "approval_card_sent",
                chat_id=chat_id,
                message_id=message_id,
            )

        except Exception as e:
            # Card sending failure is non-blocking (user can still use API to approve)
            log.warning(
                "approval_card_send_failed",
                chat_id=chat_id,
                error=str(e),
            )
