"""创建项目节点（FSPROJ-03）。

``CreateProjectNode``：以飞书"项目跟踪"看板引用建项目 + 枚举拉人（身份映射带角色）+ 组合子项
WorkItem。镜像 ``feishu_chat.CreateGroupChatNode`` 结构 + 全中文 config_schema；inputs=[default]、
outputs=[default(成功), error(失败)]。

节点**不直接写表**——全经 ``ProjectBoardSyncService.sync_from_board``（与飞书事件 handler 同源
入口，INV-6）。缺看板引用 → ``failed`` + error handle；枚举 fail-soft 降级仍 ``completed``
（输出 ``degraded`` / ``warnings``，子项/成员留待后续 webhook 逐个并入）。
"""

import structlog
from asgiref.sync import sync_to_async

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


async def _resolve_workflow_space(context: ExecutionContext):
    """异步安全地解析工作流绑定的 Space（懒加载经 sync_to_async）。"""
    execution = context.workflow_execution
    if execution is None:
        return None
    return await sync_to_async(lambda: execution.workflow.space)()


@register_node
class CreateProjectNode(BaseNode):
    """创建项目节点。

    以飞书"项目跟踪"看板引用幂等建项目（``(space, feishu_project_key)`` 幂等）、枚举看板拉人
    带身份、组合子项 WorkItem（story/缺陷复用 ``delivery.WorkItem`` 经关系边挂入）。
    """

    node_type = "create_project"
    display_name = "创建项目"
    description = "以飞书项目跟踪看板建项目并拉入成员、组合子项工作项"
    icon = "folder-plus"
    category = NodeCategory.INTEGRATION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "feishu_project_key": {
                "type": "string",
                "title": "飞书项目 Key",
                "description": "飞书'项目跟踪'看板 project_key，支持模板变量；与 Space 构成幂等键",
                "default": "",
            },
            "board_work_item_id": {
                "type": "string",
                "title": "看板工作项 ID",
                "description": "'项目跟踪'看板工作项 ID（枚举子项/人员的锚点），支持模板变量",
                "default": "",
            },
            "board_work_item_type": {
                "type": "string",
                "title": "看板工作项类型",
                "description": "看板工作项类型 key（如 project / story）",
                "default": "story",
            },
            "name": {
                "type": "string",
                "title": "项目名称",
                "description": "项目名称（留空则用'项目-{看板工作项 ID}'），支持模板变量",
                "default": "",
            },
            "space_identifier": {
                "type": "string",
                "title": "空间标识",
                "description": (
                    "空间 ID 或飞书项目 Key（留空则用工作流绑定的空间，或按 feishu_project_key 查找）"
                ),
                "default": "",
            },
            "feishu_board_url": {
                "type": "string",
                "title": "飞书看板链接",
                "description": "飞书看板 URL（可选），支持模板变量",
                "default": "",
            },
            "feishu_board_id": {
                "type": "string",
                "title": "飞书看板 ID",
                "description": "飞书看板 ID（可选），支持模板变量",
                "default": "",
            },
        },
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
    outputs = [
        NodePort(
            name="default",
            label="成功",
            port_type=PortType.OBJECT,
            description="含 project_id / created / degraded / warnings / members_added / work_items_linked",
        ),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config
        log = logger.bind(node_id=context.node_id)

        feishu_project_key = context.render_template(
            config.get("feishu_project_key", "")
        ).strip()
        board_work_item_id_str = context.render_template(
            config.get("board_work_item_id", "")
        ).strip()
        board_work_item_type = (
            context.render_template(config.get("board_work_item_type", "story") or "story").strip()
            or "story"
        )

        # 缺看板引用（feishu_project_key 或 board_work_item_id）→ failed + error handle
        if not feishu_project_key or not board_work_item_id_str:
            log.warning(
                "create_project_missing_board_ref",
                has_project_key=bool(feishu_project_key),
                has_work_item_id=bool(board_work_item_id_str),
            )
            return NodeResult(
                status="failed",
                error="缺少飞书看板引用（feishu_project_key 或 board_work_item_id）",
                next_handle="error",
            )

        try:
            board_work_item_id = int(board_work_item_id_str)
        except ValueError:
            return NodeResult(
                status="failed",
                error=f"board_work_item_id 格式错误: {board_work_item_id_str}",
                next_handle="error",
            )

        name = context.render_template(config.get("name", "")).strip() or (
            f"项目-{board_work_item_id}"
        )
        feishu_board_url = context.render_template(config.get("feishu_board_url", "")).strip()
        feishu_board_id = context.render_template(config.get("feishu_board_id", "")).strip()
        space_identifier = context.render_template(config.get("space_identifier", "")).strip()

        # 解析 Space：space_identifier 显式优先 → 工作流绑定空间 → 按 feishu_project_key 查找
        space = await self._resolve_space(context, space_identifier, feishu_project_key)
        if space is None:
            log.warning("create_project_space_not_found", feishu_project_key=feishu_project_key)
            return NodeResult(
                status="failed",
                error=f"未找到空间（feishu_project_key={feishu_project_key}）",
                next_handle="error",
            )

        from initiatives.services import ProjectBoardSyncService

        result = await ProjectBoardSyncService().sync_from_board(
            space=space,
            feishu_project_key=feishu_project_key,
            board_work_item_id=board_work_item_id,
            board_work_item_type=board_work_item_type,
            name=name,
            feishu_board_url=feishu_board_url,
            feishu_board_id=feishu_board_id,
            initiated_by_user_id="system",
        )

        log.info(
            "create_project_completed",
            project_id=result.get("project_id"),
            created=result.get("created"),
            degraded=result.get("degraded"),
        )
        # 枚举 fail-soft 降级仍视为节点成功（项目已建，子项/成员可后续并入）
        return NodeResult(
            status="completed",
            output={**result, "source": "create_project"},
            next_handle="default",
        )

    async def _resolve_space(
        self, context: ExecutionContext, space_identifier: str, feishu_project_key: str
    ):
        """解析 Space（显式标识 → 工作流绑定空间 → 按 feishu_project_key 查找）。"""
        import uuid as uuid_mod

        from projects.models import Space

        if space_identifier:
            try:
                uuid_mod.UUID(space_identifier)
                space = await Space.objects.filter(id=space_identifier).afirst()
                if space:
                    return space
            except ValueError:
                pass
            space = await Space.objects.filter(
                feishu_project_key=space_identifier
            ).afirst()
            if space:
                return space

        space = await _resolve_workflow_space(context)
        if space is not None:
            return space

        return await Space.objects.filter(feishu_project_key=feishu_project_key).afirst()
