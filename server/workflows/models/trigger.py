"""WorkflowTrigger model for event-based workflow triggering."""

import re
import secrets
import uuid

import structlog
from django.db import models

logger = structlog.get_logger()


def generate_trigger_token() -> str:
    """生成飞书触发器专属端点 token（URL 安全，作为路由标识 + 鉴权凭证）。"""
    return secrets.token_urlsafe(24)


class TriggerEventType(models.TextChoices):
    """飞书 Webhook 事件类型"""

    WORKITEM_CREATE = "WorkitemCreateEvent", "工作项创建"
    WORKITEM_STATUS = "WorkitemStatusEvent", "状态变更"
    WORKITEM_COMMENT = "WorkitemCommentEvent", "评论事件"
    WORKITEM_UPDATE = "WorkitemUpdateEvent", "字段更新"
    WORKFLOW_NODE_STATUS = "WorkFlowNodeStatusEvent", "节点流转"
    WORKITEM_FINISH = "WorkitemFinishEvent", "工作项完成"
    WORKITEM_DELETE = "WorkitemDeleteEvent", "工作项删除"
    WORKITEM_ABORTED = "WorkitemAbortedEvent", "工作项终止"
    WORKITEM_RESTORE = "WorkitemRestoreEvent", "工作项恢复"
    TASK_CREATE = "TaskCreateEvent", "任务创建"
    TASK_STATUS = "TaskStatusEvent", "任务状态变更"
    TASK_UPDATE = "TaskUpdateEvent", "任务修改"


class WorkflowTrigger(models.Model):
    """工作流触发器配置

    定义哪些飞书事件可以自动触发工作流执行。
    支持事件过滤和输入数据校验。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.CASCADE,
        related_name="triggers",
        verbose_name="工作流",
    )

    # 关联的画布触发节点 ID（同步稳定键：保证 token 跨保存不变，区分同一工作流的多个触发节点）
    node_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="触发节点 ID",
        help_text="关联的 feishu_event_trigger 画布节点 ID",
    )

    # 专属 Webhook 端点 token（URL 路径段，既是路由标识又是鉴权凭证）
    # 飞书侧自动化规则把 Webhook 动作指向 /api/feishu/webhook/<token>/ 即可直达本工作流。
    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=generate_trigger_token,
        verbose_name="端点 Token",
        help_text="飞书 Webhook 专属端点标识，命中即直接触发对应工作流",
    )

    # 事件配置（可选）
    # 飞书侧自动化规则已决定"何时触发"，此处不再用于路由匹配；
    # 仅作旧版共享端点（无 token）的向后兼容字段与可读展示保留。
    event_type = models.CharField(
        max_length=50,
        choices=TriggerEventType.choices,
        blank=True,
        default="",
        verbose_name="事件类型",
        help_text="（旧版）监听的飞书 Webhook 事件类型；新版按 token 路由，不再依赖此字段",
    )

    # 过滤条件
    filter_config = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="过滤条件",
        help_text="JSON 格式的过滤条件，如 project_key, work_item_type, status 等",
    )

    # 输入 Schema 校验
    input_schema = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="输入参数 Schema",
        help_text="JSON Schema 格式，用于校验触发器输入数据",
    )

    # 状态
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否启用",
    )

    # 触发器名称和描述（可选）
    name = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="触发器名称",
    )
    description = models.TextField(
        blank=True,
        default="",
        verbose_name="描述",
    )

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workflow_triggers"
        verbose_name = "工作流触发器"
        verbose_name_plural = "工作流触发器"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workflow", "is_active"]),
            models.Index(fields=["event_type", "is_active"]),
        ]
        # 同一工作流不能有重复的事件类型触发器（可根据需求移除）
        # unique_together = [("workflow", "event_type")]

    def __str__(self) -> str:
        name = self.name or self.get_event_type_display() or "飞书触发器"
        return f"{name} ({self.workflow.name})"

    @property
    def endpoint_path(self) -> str:
        """专属 Webhook 端点的相对路径（前端拼 origin 即得完整 URL）。"""
        return f"/api/feishu/webhook/{self.token}/"

    def matches_event(self, event_type: str, payload: dict) -> bool:
        """检查事件是否匹配此触发器

        Args:
            event_type: 事件类型
            payload: Webhook payload

        Returns:
            是否匹配
        """
        # 事件类型必须匹配
        if self.event_type != event_type:
            return False

        # 触发器必须启用
        if not self.is_active:
            return False

        # 检查过滤条件
        return self._matches_filter(payload)

    def _matches_filter(self, payload: dict) -> bool:
        """检查 payload 是否满足过滤条件

        filter_config 结构（向后兼容）：
        - 普通键（如 ``project_key`` / ``cur_work_item_status.state_key``）：正向 AND
          匹配，list 值走成员匹配、标量走相等匹配。
        - ``_include`` / ``_exclude`` 两个以 ``_`` 开头的特殊子结构：负向 / 白名单过滤，
          正向遍历时必须跳过，避免被当作普通字段路径误匹配。

        匹配顺序：先跑正向 AND；再跑 ``_exclude``（命中任一即返回 False）；最后跑
        ``_include.project_keys`` 白名单（非空时要求 payload.project_key 在其中）。

        Args:
            payload: Webhook payload

        Returns:
            是否匹配
        """
        if not self.filter_config:
            return True

        # 正向 AND：跳过 _include / _exclude 等以 _ 开头的特殊键
        for key, expected_value in self.filter_config.items():
            if key.startswith("_"):
                continue
            actual_value = self._get_nested_value(payload, key)

            if isinstance(expected_value, list):
                # 列表匹配：actual_value 在 expected_value 中
                if actual_value not in expected_value:
                    return False
            elif actual_value != expected_value:
                return False

        # 负向 _exclude：命中任一规则即不匹配
        exclude = self.filter_config.get("_exclude") or {}
        if exclude and not self._passes_exclude(payload, exclude):
            return False

        # 白名单 _include.project_keys：非空时要求 project_key 在白名单内
        include = self.filter_config.get("_include") or {}
        include_project_keys = include.get("project_keys") or []
        if include_project_keys and payload.get("project_key") not in include_project_keys:
            return False

        return True

    def _passes_exclude(self, payload: dict, exclude: dict) -> bool:
        """检查 payload 是否通过 _exclude 黑名单（True=通过，未命中任何排除规则）。

        排除规则（命中任一 → 返回 False）：
        - ``project_keys``：payload.project_key 在黑名单中；
        - ``work_item_pattern``：payload.name 含该子串；
        - ``work_item_regex``：payload.name 匹配该正则（非法正则记 warning 并视为
          未命中该规则，绝不抛异常打断匹配）。
        """
        project_key = payload.get("project_key")
        exclude_project_keys = exclude.get("project_keys") or []
        if project_key is not None and project_key in exclude_project_keys:
            return False

        name = payload.get("name") or ""

        pattern = exclude.get("work_item_pattern")
        if pattern and pattern in name:
            return False

        regex = exclude.get("work_item_regex")
        if regex:
            try:
                if re.search(regex, name):
                    return False
            except re.error:
                logger.warning(
                    "trigger_exclude_regex_invalid",
                    trigger_id=str(self.id),
                    regex=regex,
                )

        return True

    def _get_nested_value(self, data: dict, key: str):
        """获取嵌套字典中的值，支持点分隔路径

        Args:
            data: 数据字典
            key: 键路径，如 "cur_work_item_status.state_key"

        Returns:
            对应的值，不存在则返回 None
        """
        keys = key.split(".")
        current = data
        for k in keys:
            if isinstance(current, dict):
                current = current.get(k)
            else:
                return None
        return current

    def validate_input(self, payload: dict) -> list[str]:
        """使用 JSON Schema 校验输入数据

        Args:
            payload: 输入数据

        Returns:
            错误列表，为空表示校验通过
        """
        if not self.input_schema:
            return []

        import jsonschema

        errors = []
        try:
            jsonschema.validate(payload, self.input_schema)
        except jsonschema.ValidationError as e:
            errors.append(str(e.message))
        except jsonschema.SchemaError as e:
            errors.append(f"Schema 错误: {e.message}")

        return errors
