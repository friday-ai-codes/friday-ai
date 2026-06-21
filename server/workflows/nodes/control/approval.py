"""人工审批节点（统一通用审批与方案+飞书卡片审批）。

通过 ``mode`` 区分两种审批形态：

- ``generic``（默认）：通用控制台审批。暂停工作流，等待用户在前端面板点击通过/拒绝。
- ``plan_feishu``：方案+飞书卡片审批。吸收原 ``ai_plan_approval`` 节点能力——把上游
  技术方案落为飞书云文档、向配置的飞书群推送交互审批卡片，再进入挂起态。用户在
  飞书卡片或控制台点击通过/驳回后，经 ``approval_callback`` 桥接到 ``approve_node`` /
  ``reject_node`` 恢复工作流（C2 决策：飞书卡片审批统一走 ``waiting_approval`` 通道，
  淘汰旧 ``waiting_event`` 审批分支）。

两种模式都返回 ``waiting_approval``，挂起-恢复链路完全收口到调度器审批通道。
"""

from datetime import datetime, timezone
from typing import Any

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
class HumanApprovalNode(BaseNode):
    """人工审批节点

    暂停工作流执行，等待人工审批。``mode=plan_feishu`` 时额外生成飞书方案文档并推送
    审批卡片（吸收原 ``ai_plan_approval`` 能力）。
    """

    node_type = "human_approval"
    display_name = "人工审批"
    description = "暂停执行，等待人工审批通过后继续（支持方案+飞书卡片审批）"
    icon = "user-check"
    category = NodeCategory.CONTROL
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "title": "审批模式",
                "description": "generic=通用控制台审批；plan_feishu=方案+飞书卡片审批",
                "enum": ["generic", "plan_feishu"],
                "default": "generic",
            },
            "chat_id": {
                "type": "string",
                "title": "飞书群 ID",
                "description": "plan_feishu 模式下用于发送审批卡片的飞书群 ID，留空则使用上游传递的 chat_id",
                "default": "",
            },
            "title": {
                "type": "string",
                "title": "审批标题",
                "default": "请审批",
            },
            "description": {
                "type": "string",
                "title": "审批说明",
                "default": "",
            },
            "approvers": {
                "type": "array",
                "title": "审批人",
                "description": "指定审批人的用户 ID 列表，为空则空间成员均可审批",
                "items": {"type": "string"},
                "default": [],
            },
            "require_all": {
                "type": "boolean",
                "title": "需要所有人审批",
                "description": "是否需要所有指定审批人都通过",
                "default": False,
            },
            "timeout_hours": {
                "type": "integer",
                "title": "超时时间(小时)",
                "description": "超时后自动拒绝，0 表示不超时",
                "default": 0,
            },
            "notification": {
                "type": "object",
                "title": "通知配置",
                "properties": {
                    "enabled": {"type": "boolean", "default": True},
                    "channels": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["feishu", "email"]},
                        "default": ["feishu"],
                    },
                },
            },
            "show_data": {
                "type": "array",
                "title": "展示数据",
                "description": "在审批页面展示的输入数据字段",
                "items": {"type": "string"},
                "default": [],
            },
        },
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
    outputs = [
        NodePort(name="approved", label="通过", port_type=PortType.OBJECT),
        NodePort(name="rejected", label="拒绝", port_type=PortType.OBJECT),
    ]

    is_blocking = True

    async def execute(self, context: ExecutionContext) -> NodeResult:
        mode = context.get_config("mode", "generic") or "generic"
        if mode == "plan_feishu":
            return await self._execute_plan_feishu(context)
        return await self._execute_generic(context)

    # ------------------------------------------------------------------
    # 通用控制台审批
    # ------------------------------------------------------------------

    async def _execute_generic(self, context: ExecutionContext) -> NodeResult:
        """通用审批：构建审批请求、发通知、进入 waiting_approval。"""
        config = context.node_config

        approval_request = {
            "title": context.render_template(config.get("title", "请审批")),
            "description": context.render_template(config.get("description", "")),
            "approvers": config.get("approvers", []),
            "require_all": config.get("require_all", False),
            "timeout_hours": config.get("timeout_hours", 0),
            "display_data": self._extract_display_data(
                context.input_data,
                config.get("show_data", []),
            ),
            "requested_at": context.workflow_context.get("started_at"),
        }

        notification_config = config.get("notification", {})
        if notification_config.get("enabled", True):
            await self._send_notifications(
                context,
                approval_request,
                notification_config.get("channels", ["feishu"]),
            )

        return NodeResult(
            status="waiting_approval",
            output=approval_request,
        )

    def _extract_display_data(self, input_data: dict, fields: list) -> dict:
        """提取要展示的数据"""
        if not fields:
            return input_data
        return {k: input_data.get(k) for k in fields if k in input_data}

    async def _send_notifications(
        self,
        context: ExecutionContext,
        approval_request: dict,
        channels: list[str],
    ) -> None:
        """发送审批通知"""
        logger.warning(
            "approval_notification_not_implemented",
            channels=channels,
            node_name=context.node_config.get("title", ""),
        )

    # ------------------------------------------------------------------
    # 方案 + 飞书卡片审批（原 ai_plan_approval 能力）
    # ------------------------------------------------------------------

    async def _execute_plan_feishu(self, context: ExecutionContext) -> NodeResult:
        """方案审批：落飞书文档 + 推送审批卡片，进入 waiting_approval。

        1. 提取上游技术方案数据
        2. 生成飞书技术方案文档
        3. 构建审批卡片推送到飞书群
        4. 返回 waiting_approval，等待用户审批（统一审批通道）
        """
        log = logger.bind(
            execution_id=context.execution_id,
            node_id=context.node_id,
        )

        plan_data = context.get_input("plan")
        if not plan_data:
            # 兜底：上游可能把方案平铺在 input_data 顶层
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

        document_url = await self._create_plan_document(context, plan_data, plan_title, log)

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

        return NodeResult(
            status="waiting_approval",
            output={
                "title": plan_title,
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
        """从方案数据生成飞书云文档，返回文档 URL（失败返回空串，非阻塞）。"""
        try:
            if not context.workflow_execution:
                log.warning("plan_approval_no_workflow_execution")
                return ""

            from workflows.models import WorkflowExecution

            we = await WorkflowExecution.objects.select_related("workflow__project").aget(
                id=context.workflow_execution.id
            )
            project = we.workflow.project if we.workflow else None

            if not project:
                log.warning("plan_approval_no_project")
                return ""

            from agents.tools.feishu_doc_tools import (
                create_feishu_doc_client_for_project,
            )

            client = await create_feishu_doc_client_for_project(project)

            content = self._build_document_content(plan_data, plan_title)

            folder_token = getattr(project, "feishu_doc_folder_token", None) or ""
            if not folder_token:
                log.warning("plan_approval_no_folder_token")
                return ""

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
            # 文档生成失败不阻断审批
            log.warning("plan_document_creation_failed", error=str(e))
            return ""

    def _build_document_content(
        self,
        plan_data: dict[str, Any],
        plan_title: str,
    ) -> str:
        """把方案数据拼成 Markdown 文档内容。"""
        sections: list[str] = []

        sections.append(f"# {plan_title}")
        sections.append(
            f"**创建时间:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )

        summary = plan_data.get("summary", "")
        if summary:
            sections.append("## 方案概要")
            sections.append(summary)

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
                            "**涉及文件:**\n" + "\n".join(f"- {f}" for f in files_list)
                        )
                    if coding_instruction:
                        sections.append(f"**编码指令:**\n{coding_instruction}")

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

        assumptions = plan_data.get("assumptions", [])
        if assumptions:
            sections.append("## 假设前提")
            for assumption in assumptions:
                if isinstance(assumption, str):
                    sections.append(f"- {assumption}")
                elif isinstance(assumption, dict):
                    sections.append(f"- {assumption.get('description', '')}")

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
        """构建审批卡片并推送到飞书群（失败非阻塞，用户仍可经控制台审批）。"""
        try:
            from feishu.cards.approval_card import build_approval_card

            card = build_approval_card(
                plan_title=plan_title,
                plan_summary=plan_summary,
                document_url=document_url,
                execution_id=context.execution_id,
                node_id=context.node_id,
            )

            if not context.workflow_execution:
                log.warning("plan_approval_no_workflow_execution_for_card")
                return

            from workflows.models import WorkflowExecution as WE2

            we = await WE2.objects.select_related("workflow__project").aget(
                id=context.workflow_execution.id
            )
            project = we.workflow.project if we.workflow else None

            if not project:
                log.warning("plan_approval_no_project_for_card")
                return

            from agents.tools.feishu_doc_tools import (
                create_feishu_doc_client_for_project,
            )
            from services.feishu_im import FeishuIMClient

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

            log.info("approval_card_sent", chat_id=chat_id, message_id=message_id)

        except Exception as e:
            # 卡片发送失败非阻塞（用户仍可经控制台审批）
            log.warning("approval_card_send_failed", chat_id=chat_id, error=str(e))
