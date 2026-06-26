"""看板拆分工作流节点（BOARD-01，87-03）。

``BoardSplitNode``：端到端「feature list → 子看板」节点——解析多源输入 → 委托
:class:`BoardSplitService` 抽取拆分提案（``propose_split``）→ 逐 feature 建子看板 +
关联项目跟踪 + 落 link + 父子降级（``create_boards``）。与 AI 会话工具
``split_feature_list_to_boards`` 共用同一服务（单一编排收口，绝不两套实现）。

自动注册：放在 ``workflows/nodes/integrations/`` 下且声明 ``node_type`` 即被
``NodeRegistry`` 自动发现。
"""

from __future__ import annotations

import structlog
from asgiref.sync import sync_to_async

from initiatives.services.board_split_service import BoardSplitService
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
class BoardSplitNode(BaseNode):
    """看板拆分节点：feature list → 逐 feature 子看板（委托 BoardSplitService）。"""

    node_type = "board_split"
    display_name = "看板拆分"
    description = "把 feature list 拆成子看板（每 feature 一条 + 关联项目跟踪 + 父子降级）"
    icon = "layout-grid"
    category = NodeCategory.INTEGRATION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "feature_list_url": {
                "type": "string",
                "title": "飞书文档链接",
                "description": "feature list 飞书文档链接/ID，支持模板变量",
                "default": "",
            },
            "feature_list_text": {
                "type": "string",
                "title": "粘贴文本",
                "description": "粘贴的 feature list 文本，支持模板变量",
                "default": "",
            },
            "uploaded_text": {
                "type": "string",
                "title": "上传文件正文",
                "description": "上传文件（md）正文，支持模板变量",
                "default": "",
            },
            "work_item_type": {
                "type": "string",
                "title": "工作项类型",
                "description": "子看板工作项类型",
                "default": "story",
            },
        },
        "required": [],
    }

    inputs = [
        NodePort(
            name="default",
            label="输入",
            port_type=PortType.OBJECT,
            required=False,
            description="上游输出，可提供 feature list 来源",
        ),
    ]

    outputs = [
        NodePort(
            name="default",
            label="拆分结果",
            port_type=PortType.OBJECT,
            description="建出的子看板列表 + 父子降级标志",
            schema={
                "type": "object",
                "properties": {
                    "created": {"type": "array", "description": "建出的子看板"},
                    "failures": {"type": "array", "description": "建项失败的 feature"},
                    "degraded_parent_child": {
                        "type": "boolean",
                        "description": "父子关系类型缺失而降级",
                    },
                    "hint": {"type": "string", "description": "降级提示（去配置中心）"},
                    "feature_count": {"type": "integer", "description": "提案 feature 总数"},
                },
            },
        ),
        NodePort(
            name="error",
            label="失败",
            port_type=PortType.OBJECT,
            description="无输入源 / 服务异常时的错误信息",
        ),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """端到端拆分：解析空间 → propose_split → create_boards。"""
        config = context.node_config

        feishu_url = context.render_template(config.get("feature_list_url", "") or "")
        pasted_text = context.render_template(config.get("feature_list_text", "") or "")
        uploaded_text = context.render_template(config.get("uploaded_text", "") or "")
        work_item_type = config.get("work_item_type", "") or "story"

        if not (feishu_url.strip() or pasted_text.strip() or uploaded_text.strip()):
            return NodeResult(
                status="failed",
                error="未提供任何 feature list 输入源（飞书链接 / 粘贴文本 / 上传文件）",
                next_handle="error",
            )

        space = await _resolve_project(context)
        if space is None:
            return NodeResult(
                status="failed",
                error="无法获取空间信息，请确保工作流关联了空间",
                next_handle="error",
            )

        initiated_by_user_id = self._resolve_initiator(context)

        try:
            service = BoardSplitService()
            proposal = await service.propose_split(
                space=space,
                uploaded_text=uploaded_text or None,
                feishu_url=feishu_url or None,
                pasted_text=pasted_text or None,
                initiated_by_user_id=initiated_by_user_id,
            )
            result = await service.create_boards(
                space=space,
                proposal=proposal,
                work_item_type=work_item_type,
                initiated_by_user_id=initiated_by_user_id,
            )
        except Exception as exc:
            error_msg = str(exc) or f"{type(exc).__name__}: 看板拆分失败"
            logger.error(
                "board_split_node_failed",
                error=error_msg,
                error_type=type(exc).__name__,
            )
            return NodeResult(status="failed", error=error_msg, next_handle="error")

        return NodeResult(
            status="completed",
            output={
                "created": result["created"],
                "failures": result["failures"],
                "degraded_parent_child": result["degraded_parent_child"],
                "hint": result["hint"],
                "feature_count": result["feature_count"],
            },
            next_handle="default",
        )

    @staticmethod
    def _resolve_initiator(context: ExecutionContext) -> str:
        """取工作流触发用户 id（缺记 system）。"""
        execution = context.workflow_execution
        if execution is not None:
            triggered_by_id = getattr(execution, "triggered_by_id", None)
            if triggered_by_id:
                return str(triggered_by_id)
        return "system"


async def _resolve_project(context: ExecutionContext):
    """异步安全解析工作流关联空间（镜像 feishu_chat._resolve_project，规避同步 ORM 懒加载）。"""
    execution = context.workflow_execution
    if execution is None:
        return None
    return await sync_to_async(lambda: execution.workflow.space)()
