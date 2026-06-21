"""飞书群聊操作节点。

FetchGroupChatNode: 获取群聊 ID（从配置或工作项 API）
JoinGroupChatNode: 将 Bot 加入指定群聊（幂等）
CreateGroupChatNode: 创建飞书群并拉入成员，输出 chat_id 供下游使用（可选 writeback）
CreateWorkItemChatNode: 触发飞书原生自动建群并绑定到工作项，输出 chat_id
"""

import asyncio
import json
import time

import structlog
from asgiref.sync import sync_to_async

from services.feishu_im import FeishuIMError, FeishuIMService
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


async def _resolve_project(context: ExecutionContext):
    """异步安全地解析工作流关联的空间（Project）。

    直接在异步上下文里访问 ``context.workflow_execution.workflow.project`` 会触发
    Django 同步 ORM 外键懒加载，抛 ``SynchronousOnlyOperation``（"You cannot call
    this from an async context - use a thread or sync_to_async."）。这里用
    ``sync_to_async`` 把懒加载放到线程中执行，规避该限制。

    Returns:
        关联的 Project 实例；无 workflow_execution 时返回 None。
    """
    execution = context.workflow_execution
    if execution is None:
        return None
    return await sync_to_async(lambda: execution.workflow.project)()


def _parse_id_list(value: object, context: ExecutionContext) -> list[str]:
    """解析成员 ID 三形态为去空字符串列表。

    支持（镜像 ``normalize_repositories`` 思路）：

    - 模板字符串 ``{{nodes.x.member_ids}}``：经 ``get_template_value`` 解析（保留 list 类型）；
    - JSON 列表字符串 ``["ou_a", "ou_b"]``（兼容单引号）；
    - 逗号分隔字符串 ``"ou_a, ou_b"``；
    - 上游直接注入的 ``list``：逐项 ``str`` 化并 ``strip`` 去空。

    Args:
        value: 节点配置中的 member_ids 原始值（str / list / None）。
        context: 执行上下文，用于模板解析。

    Returns:
        去空后的成员 ID 字符串列表。
    """
    # 模板变量：保留复杂类型（可能解析出 list）
    if isinstance(value, str) and "{{" in value:
        resolved = context.get_template_value(value)
        if resolved is not None and resolved != "":
            value = resolved

    if value is None:
        return []

    # 字符串：优先 JSON 列表，否则逗号分隔
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                parsed = json.loads(s.replace("'", '"'))
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except json.JSONDecodeError:
                pass  # 落到逗号分隔解析
        return [part.strip() for part in s.split(",") if part.strip()]

    # 列表：逐项 str 化去空
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    return []


@register_node
class FetchGroupChatNode(BaseNode):
    """获取群聊 ID 节点。

    优先从配置读取 chat_id，若未配置则通过工作项 API 自动获取。
    """

    node_type = "fetch_group_chat"
    display_name = "获取群聊"
    description = "获取群聊 ID，支持手动配置或从工作项自动获取"
    icon = "message-circle"
    category = NodeCategory.INTEGRATION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "chat_id": {
                "type": "string",
                "title": "群聊 ID",
                "description": "手动指定群聊 ID，留空则从工作项自动获取",
                "default": "",
            },
            "project_key": {
                "type": "string",
                "title": "空间 Key",
                "description": "飞书项目空间 Key（自动获取时需要）",
                "default": "",
            },
            "work_item_id": {
                "type": "string",
                "title": "工作项 ID",
                "description": "工作项 ID（自动获取时需要）",
                "default": "",
            },
            "work_item_type": {
                "type": "string",
                "title": "工作项类型",
                "description": "工作项类型（story, task, bug 等）",
                "default": "story",
            },
        },
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
    outputs = [
        NodePort(name="default", label="成功", port_type=PortType.OBJECT),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config
        log = logger.bind(node_id=context.node_id)

        # 优先从配置读取 chat_id（支持模板变量）
        chat_id = context.render_template(config.get("chat_id", "")).strip()

        if chat_id:
            log.info("chat_id_from_config", chat_id=chat_id)
            return NodeResult(
                status="completed",
                output={"chat_id": chat_id, "source": "config"},
                next_handle="default",
            )

        # 从工作项 API 获取
        project_key = context.render_template(config.get("project_key", "")).strip()
        work_item_id_str = context.render_template(config.get("work_item_id", "")).strip()
        work_item_type = config.get("work_item_type", "story")

        if not project_key or not work_item_id_str:
            log.warning("missing_work_item_params")
            return NodeResult(
                status="failed",
                error="无法获取群聊 ID：未配置 chat_id，且缺少 project_key 或 work_item_id",
                next_handle="error",
            )

        # 获取 FeishuIMService 实例。
        # with_project_client=True：从工作项自动获取群聊依赖飞书项目 API client
        # （get_chat_id_for_work_item 需要 project_client，缺省 False 会导致自动获取恒为空）。
        project = await _resolve_project(context)

        im_service = await FeishuIMService.create(project, with_project_client=True)

        try:
            work_item_id = int(work_item_id_str)
        except ValueError:
            return NodeResult(
                status="failed",
                error=f"work_item_id 格式错误: {work_item_id_str}",
                next_handle="error",
            )

        chat_info = await im_service.get_chat_id_for_work_item(
            project_key=project_key,
            work_item_id=work_item_id,
            work_item_type=work_item_type,
        )

        if chat_info is None:
            log.warning("no_chat_found_for_work_item")
            return NodeResult(
                status="failed",
                error="无法获取群聊 ID：工作项无关联群聊",
                next_handle="error",
            )

        log.info("chat_id_from_work_item", chat_id=chat_info["chat_id"])
        return NodeResult(
            status="completed",
            output=chat_info,
            next_handle="default",
        )


@register_node
class JoinGroupChatNode(BaseNode):
    """加入群聊节点。

    调用 ensure_bot_in_chat 将 Bot 加入指定群聊，幂等操作。
    """

    node_type = "join_group_chat"
    display_name = "加入群聊"
    description = "将 Bot 加入指定群聊，已在群内时幂等成功"
    icon = "user-plus"
    category = NodeCategory.INTEGRATION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "chat_id": {
                "type": "string",
                "title": "群聊 ID",
                "description": "目标群聊 ID，支持模板变量",
            },
        },
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
    outputs = [
        NodePort(name="default", label="成功", port_type=PortType.OBJECT),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config
        log = logger.bind(node_id=context.node_id)

        # 优先从配置获取 chat_id，其次从 input_data
        chat_id = context.render_template(config.get("chat_id", "")).strip()
        if not chat_id:
            chat_id = str(context.input_data.get("chat_id", "")).strip()

        if not chat_id:
            return NodeResult(
                status="failed",
                error="未提供 chat_id",
                next_handle="error",
            )

        # 获取 FeishuIMService 实例
        project = await _resolve_project(context)

        im_service = await FeishuIMService.create(project)

        result = await im_service.ensure_bot_in_chat(chat_id)

        if result["success"]:
            log.info(
                "join_group_chat_success",
                chat_id=chat_id,
                already_member=result["already_member"],
            )
            return NodeResult(
                status="completed",
                output={
                    "chat_id": chat_id,
                    "already_member": result["already_member"],
                },
                next_handle="default",
            )

        log.warning("join_group_chat_failed", chat_id=chat_id, error=result.get("error"))
        return NodeResult(
            status="failed",
            error=result.get("error", "加入群聊失败"),
            next_handle="error",
        )


@register_node
class CreateGroupChatNode(BaseNode):
    """创建群聊节点。

    经 ``FeishuIMService.create_chat`` 单步建群即拉人，输出 ``chat_id`` 一等字段供下游
    （JoinGroupChatNode / 发卡节点）消费。可选 writeback：仅当配置了 work_item 标识时，
    把 ``chat_id`` 写回 WorkItem（经 ``WorkItemService.awriteback_feishu_chat_id`` 单一入口）。

    fail-soft 两类分开（D-7）：

    - 建群失败（缺群名/成员 或 ``FeishuIMError``）→ ``failed`` + ``error`` handle；
    - writeback 失败（WorkItem 不存在 / DB 异常）→ 节点**仍 completed** 返回 chat_id
      （捕获异常 + ``log.warning``，绝不冒泡）。
    """

    node_type = "create_group_chat"
    display_name = "创建群聊"
    description = "创建飞书群并拉入指定成员，输出 chat_id 供下游使用"
    icon = "users"
    category = NodeCategory.INTEGRATION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "title": "群名称",
                "description": "新建群聊的名称，支持模板变量",
                "default": "",
            },
            "description": {
                "type": "string",
                "title": "群描述",
                "description": "新建群聊的描述（可选），支持模板变量",
                "default": "",
            },
            "owner_id": {
                "type": "string",
                "title": "群主 ID",
                "description": "群主 ID（可选），留空则 Bot 为群主；与成员使用同一 user_id_type",
                "default": "",
            },
            "member_ids": {
                "type": "string",
                "title": "成员 ID",
                "description": (
                    "拉入群聊的成员 ID，支持逗号分隔、JSON 列表或模板变量 "
                    "{{nodes.x.member_ids}}；与群主使用同一 user_id_type"
                ),
                "default": "",
            },
            "user_id_type": {
                "type": "string",
                "title": "用户 ID 类型",
                "description": "成员与群主的 ID 类型",
                "enum": ["open_id", "union_id", "user_id"],
                "default": "open_id",
            },
            "project_key": {
                "type": "string",
                "title": "空间 Key",
                "description": "飞书项目空间 Key（配置后才回写 chat_id 到工作项）",
                "default": "",
            },
            "work_item_id": {
                "type": "string",
                "title": "工作项 ID",
                "description": "工作项 ID（配置后才回写 chat_id 到工作项）",
                "default": "",
            },
            "work_item_type": {
                "type": "string",
                "title": "工作项类型",
                "description": "工作项类型（story, task, bug 等）",
                "default": "story",
            },
        },
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
    outputs = [
        NodePort(name="default", label="成功", port_type=PortType.OBJECT),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config
        log = logger.bind(node_id=context.node_id)

        # 解析群名 + 成员（member_ids 三形态）
        name = context.render_template(config.get("name", "")).strip()
        member_ids = _parse_id_list(config.get("member_ids", ""), context)

        # 缺参：群名为空 或 成员为空 → 建群+拉人无意义（D-4）
        if not name or not member_ids:
            log.warning("missing_create_chat_params", has_name=bool(name), members=len(member_ids))
            return NodeResult(
                status="failed",
                error="缺少群名或成员",
                next_handle="error",
            )

        # 获取 FeishuIMService 实例
        project = await _resolve_project(context)

        im_service = await FeishuIMService.create(project)

        user_id_type = config.get("user_id_type", "open_id")
        owner_id = context.render_template(config.get("owner_id", "")).strip()
        description = context.render_template(config.get("description", "")).strip()

        # work_item 锚解析上移：建群前 fence 查询 + 建群后 writeback 复用同一组解析值
        project_key = context.render_template(config.get("project_key", "")).strip()
        work_item_id_str = context.render_template(config.get("work_item_id", "")).strip()
        work_item_type = config.get("work_item_type", "story")
        work_item_id: int | None = None
        if project_key and work_item_id_str:
            try:
                work_item_id = int(work_item_id_str)
            except ValueError:
                log.warning("writeback_skipped_invalid_work_item_id", value=work_item_id_str)

        # IDEMP-02：建群前查 WorkItem.feishu_chat_id，命中则复用既有群跳过 create_chat。
        # 仅当 work_item 锚（project_key + 可解析 work_item_id）齐备时才查；
        # 无锚 → 不查、照常建群（fence 退化 no-op）。查询 fail-soft，绝不阻断建群。
        if project_key and work_item_id is not None:
            from delivery.services.work_item_service import WorkItemService

            try:
                existing_chat_id = await WorkItemService().aget_feishu_chat_id(
                    project_key, work_item_type, work_item_id
                )
            except Exception as e:  # noqa: BLE001 — fence 查询 fail-soft，绝不冒泡
                log.warning("create_chat_fence_failed", error=str(e))
                existing_chat_id = None

            if existing_chat_id:
                log.info("create_chat_dedup_reuse", chat_id=existing_chat_id)
                return NodeResult(
                    status="completed",
                    output={
                        "chat_id": existing_chat_id,
                        "chat_name": name,
                        "owner_id": "",
                        "source": "create_group_chat",
                        "deduplicated": True,
                        "writeback": {"attempted": False, "success": False},
                    },
                    next_handle="default",
                )

        # 建群（建群失败走 error handle，D-7）
        try:
            data = await im_service.create_chat(
                name,
                user_id_list=member_ids,
                owner_id=owner_id,
                description=description,
                user_id_type=user_id_type,
            )
        except FeishuIMError as e:
            log.warning("create_chat_failed", error=str(e))
            return NodeResult(
                status="failed",
                error=str(e),
                next_handle="error",
            )

        chat_id = data.get("chat_id", "")
        log.info("create_chat_success", chat_id=chat_id)

        # 可选 writeback（fail-soft，D-7）：复用上面解析好的 work_item 锚
        # （仅当 project_key + 可解析 work_item_id 均齐备才执行）
        writeback = {"attempted": False, "success": False}

        if project_key and work_item_id is not None:
            writeback["attempted"] = True
            try:
                from delivery.services.work_item_service import WorkItemService

                writeback["success"] = await WorkItemService().awriteback_feishu_chat_id(
                    project_key,
                    work_item_type,
                    work_item_id,
                    chat_id,
                )
            except Exception as e:  # noqa: BLE001 — writeback fail-soft，绝不冒泡
                log.warning("writeback_feishu_chat_id_failed", error=str(e))

        return NodeResult(
            status="completed",
            output={
                "chat_id": chat_id,
                "chat_name": data.get("name", ""),
                "owner_id": data.get("owner_id", ""),
                "source": "create_group_chat",
                "writeback": writeback,
            },
            next_handle="default",
        )


@register_node
class CreateWorkItemChatNode(BaseNode):
    """创建工作项群聊节点（飞书原生自动建群并绑定到工作项）。

    机制说明（与 ``create_group_chat`` 的本质区别）：
        飞书项目（Meegle）**没有**独立的"创建群聊 / 绑定群"OpenAPI 接口。原生建群是
        通过把工作项的 ``group_type`` 字段更新为 ``"auto"`` 来触发的——写入后飞书后端会
        **异步**创建群、自动拉入工作项相关人，并把群 ID 原生回填到工作项的
        ``chat_group`` / ``group_id`` 字段（通常数秒内生效）。

        因此本节点产出的是**飞书项目原生绑定群**：群永久挂在工作项上、``chat_group``
        长期可查、跨执行不会重复建群。而 ``create_group_chat`` 走的是开放平台 IM API
        自建群——群 ID 只回写到本地 ``WorkItem.feishu_chat_id``，**不会**回填到飞书工作项
        字段，飞书原生侧查不到。

    执行流程：
        1. 幂等短路：先查工作项是否已绑群（``get_chat_id_for_work_item``）——已绑则直接
           复用现有群（``source=reused``），不重复触发；
        2. 未绑则调 ``update_work_item_fields(group_type="auto")`` 触发飞书原生自动建群；
        3. 轮询查询，直到工作项 ``chat_group`` 出现合法 ``oc_`` 群 ID（``source=created``）
           或达到超时；
        4. 输出 ``chat_id`` 供下游节点（AI 方案 / 通知 / 澄清）经 ``{{input.chat_id}}`` 使用。
    """

    node_type = "create_work_item_chat"
    display_name = "创建工作项群聊"
    description = "触发飞书原生自动建群并绑定到工作项，输出 chat_id 供下游使用"
    icon = "users"
    category = NodeCategory.INTEGRATION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "project_key": {
                "type": "string",
                "title": "空间 Key",
                "description": "飞书项目空间 Key，支持模板变量（如 {{nodes.x.project_key}}）",
                "default": "",
            },
            "work_item_id": {
                "type": "string",
                "title": "工作项 ID",
                "description": "工作项 ID，支持模板变量（如 {{nodes.x.work_item_id}}）",
                "default": "",
            },
            "work_item_type": {
                "type": "string",
                "title": "工作项类型",
                "description": "工作项类型 key（story、issue 或自定义类型 key）",
                "default": "story",
            },
            "poll_timeout_seconds": {
                "type": "integer",
                "title": "轮询超时(秒)",
                "description": "等待飞书异步建群并回填群字段的最长时间",
                "default": 30,
                "minimum": 5,
                "maximum": 120,
            },
            "poll_interval_seconds": {
                "type": "integer",
                "title": "轮询间隔(秒)",
                "description": "两次查询群字段之间的间隔",
                "default": 3,
                "minimum": 1,
                "maximum": 15,
            },
        },
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
    outputs = [
        NodePort(
            name="default",
            label="成功",
            port_type=PortType.OBJECT,
            description="含 chat_id（oc_ 群 ID）、source（reused=复用已有 / created=新建）",
            schema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string"},
                    "source": {"type": "string"},
                },
            },
        ),
        NodePort(
            name="error",
            label="失败",
            port_type=PortType.OBJECT,
            description="缺参 / 触发失败 / 超时未回填等错误信息",
        ),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config
        log = logger.bind(node_id=context.node_id)

        # 解析 work_item 锚点（均支持模板变量）
        project_key = context.render_template(config.get("project_key", "")).strip()
        work_item_id_str = context.render_template(config.get("work_item_id", "")).strip()
        work_item_type = (
            context.render_template(config.get("work_item_type", "story") or "story").strip()
            or "story"
        )

        if not project_key or not work_item_id_str:
            return NodeResult(
                status="failed",
                error="缺少 project_key 或 work_item_id，无法创建工作项群聊",
                next_handle="error",
            )
        try:
            work_item_id = int(work_item_id_str)
        except ValueError:
            return NodeResult(
                status="failed",
                error=f"work_item_id 格式错误: {work_item_id_str}",
                next_handle="error",
            )

        project = await _resolve_project(context)

        # with_project_client=True：触发建群（update）与群字段查询都依赖飞书项目 API client
        im_service = await FeishuIMService.create(project, with_project_client=True)
        if im_service.project_client is None:
            return NodeResult(
                status="failed",
                error="未配置飞书项目 API（plugin token / user key），无法创建工作项群聊",
                next_handle="error",
            )

        # 1) 幂等短路：已绑群直接复用，不重复触发建群
        existing = await im_service.get_chat_id_for_work_item(
            project_key=project_key,
            work_item_id=work_item_id,
            work_item_type=work_item_type,
        )
        if existing and existing.get("chat_id"):
            log.info("work_item_chat_reuse", chat_id=existing["chat_id"])
            return NodeResult(
                status="completed",
                output={**existing, "source": "reused"},
                next_handle="default",
            )

        # 2) 触发飞书原生自动建群：把 group_type 字段写为 auto
        try:
            await im_service.project_client.update_work_item_fields(
                project_key=project_key,
                work_item_id=work_item_id,
                work_item_type=work_item_type,
                fields={"group_type": "auto"},
            )
        except Exception as e:  # noqa: BLE001 — 触发失败走 error handle
            log.warning("set_group_type_auto_failed", error=str(e))
            return NodeResult(
                status="failed",
                error=f"触发飞书自动建群失败: {e}",
                next_handle="error",
            )

        # 3) 轮询等待飞书异步回填 chat_group（建群是异步的，通常数秒内完成）
        timeout_s = int(config.get("poll_timeout_seconds", 30) or 30)
        interval_s = int(config.get("poll_interval_seconds", 3) or 3)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            await asyncio.sleep(interval_s)
            res = await im_service.get_chat_id_for_work_item(
                project_key=project_key,
                work_item_id=work_item_id,
                work_item_type=work_item_type,
            )
            if res and res.get("chat_id"):
                log.info("work_item_chat_created", chat_id=res["chat_id"])
                return NodeResult(
                    status="completed",
                    output={**res, "source": "created"},
                    next_handle="default",
                )

        # 4) 超时：已触发但未在时限内查到回填的群
        log.warning("work_item_chat_timeout", timeout_seconds=timeout_s)
        return NodeResult(
            status="failed",
            error=(
                f"已触发飞书自动建群，但 {timeout_s}s 内未查到回填的群聊"
                "（可能是飞书回填延迟，或该工作项类型/权限不支持自动建群）"
            ),
            next_handle="error",
        )
