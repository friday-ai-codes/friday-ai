"""Built-in lifecycle hooks."""

from datetime import timedelta
from typing import Any

import structlog

from workflows.hooks.base import BaseHook
from workflows.models.execution import NodeExecution, WorkflowExecution

logger = structlog.get_logger()


class LoggingHook(BaseHook):
    """日志钩子"""

    priority = 1  # 最先执行

    async def execute(self, event: str, **kwargs) -> None:
        execution = kwargs.get("execution")
        node_execution = kwargs.get("node_execution")

        log_data = {"workflow_event_type": event}

        if execution:
            log_data["execution_id"] = str(execution.id)
            exe = await WorkflowExecution.objects.select_related("workflow").aget(id=execution.id)
            log_data["workflow"] = exe.workflow.name

        if node_execution:
            ne = await NodeExecution.objects.select_related("node").aget(id=node_execution.id)
            log_data["node_id"] = str(ne.node.id)
            log_data["node_name"] = ne.node.name

        logger.info("工作流事件", **log_data)


class WebSocketBroadcastHook(BaseHook):
    """WebSocket 广播钩子"""

    priority = 10

    async def execute(self, event: str, **kwargs) -> None:
        execution = kwargs.get("execution")
        if not execution:
            return

        try:
            from channels.layers import get_channel_layer

            channel_layer = get_channel_layer()
            if not channel_layer:
                return

            message = {
                "type": "workflow.event",
                "event": event,
                "execution_id": str(execution.id),
                "status": execution.status,
            }

            node_execution = kwargs.get("node_execution")
            if node_execution:
                message["node_id"] = str(node_execution.node_id)
                message["node_status"] = node_execution.status

                # 调试暂停事件：附带节点输入输出数据供前端展示
                if event == "node_debug_paused":
                    message["node_input"] = node_execution.input_data or {}
                    message["node_output"] = node_execution.output_data or {}

                # OBS-01 / D-04 / Pitfall 5：仅失败/超时态追加可选 error 键，
                # 前端无需 full fetch 即见失败原因；成功态不写入这些键以保持
                # 现有消费方（AlertRuleHook 读 DB 对象，不受影响）向后兼容。
                # error_message 由 Phase 17/18 已产出「摘要+末行 JSON」，此处直接
                # 透传不二次拼接敏感数据，并截断 2000 字符防止超大 payload。
                if node_execution.status in ("failed", "timeout"):
                    message["error_message"] = (node_execution.error_message or "")[:2000]
                    message["error_code"] = node_execution.error_code or ""

            await channel_layer.group_send(
                f"execution_{execution.id}",
                message,
            )
        except ImportError:
            # channels not installed
            pass


class NotificationHook(BaseHook):
    """通知钩子"""

    priority = 50

    NOTIFY_EVENTS = [
        "execution_completed",
        "execution_failed",
        "node_waiting_approval",
    ]

    async def execute(self, event: str, **kwargs) -> None:
        if event not in self.NOTIFY_EVENTS:
            return

        execution = kwargs.get("execution")
        if not execution:
            logger.info("notification_skipped", workflow_event=event, reason="missing_execution")
            return

        execution_id = str(getattr(execution, "id", "unknown"))
        if getattr(execution, "is_debug", False):
            logger.info(
                "notification_skipped",
                workflow_event=event,
                execution_id=execution_id,
                reason="debug_execution",
            )
            return

        chat_id = self._get_chat_id(execution)
        if not chat_id:
            logger.info(
                "notification_skipped",
                workflow_event=event,
                execution_id=execution_id,
                reason="missing_chat_id",
            )
            return

        try:
            from services.feishu_im import FeishuIMService

            project = self._get_project(execution)
            im_service = await FeishuIMService.create(project)
            card = self._build_card(event, execution=execution, node_execution=kwargs.get("node_execution"))
            message_id = await im_service.send_card(
                receive_id=chat_id,
                receive_id_type="chat_id",
                card=card,
            )
            if message_id:
                execution.feishu_message_id = message_id
                await execution.asave(update_fields=["feishu_message_id"])

            logger.info(
                "notification_sent",
                workflow_event=event,
                execution_id=execution_id,
                message_id=message_id,
            )
        except Exception:
            logger.warning(
                "notification_failed",
                workflow_event=event,
                execution_id=execution_id,
                exc_info=True,
            )

    def _get_chat_id(self, execution: WorkflowExecution | Any) -> str | None:
        context = getattr(execution, "context", None) or {}
        chat_id = context.get("chat_id") if isinstance(context, dict) else None
        if chat_id:
            return chat_id

        input_data = getattr(execution, "input_data", None) or {}
        return input_data.get("chat_id") if isinstance(input_data, dict) else None

    def _get_project(self, execution: WorkflowExecution | Any) -> Any:
        workflow = getattr(execution, "workflow", None)
        workflow_project = getattr(workflow, "space", None)
        if workflow_project is not None:
            return workflow_project
        return getattr(execution, "space", None)

    def _build_card(
        self,
        event: str,
        *,
        execution: WorkflowExecution | Any,
        node_execution: NodeExecution | Any | None = None,
    ) -> dict[str, Any]:
        if event == "execution_completed":
            color = "green"
            content = "工作流执行完成"
        elif event == "execution_failed":
            color = "red"
            error_message = getattr(execution, "error_message", "") or "未知错误"
            content = f"工作流执行失败\n错误: {str(error_message)[:500]}"
        else:
            color = "orange"
            node_name = "审批节点"
            description = "请审批"
            if node_execution is not None:
                node = getattr(node_execution, "node", None)
                node_name = getattr(node, "name", node_name) or node_name
                node_config = getattr(node, "config", None) or {}
                if isinstance(node_config, dict):
                    description = node_config.get("description_template") or description

            content = (
                f"等待审批: {node_name}\n\n"
                f"{description}\n\n"
                "回复「通过」或「驳回」进行审批"
            )

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "工作流通知"},
                "template": color,
            },
            "elements": [{"tag": "markdown", "content": content}],
        }


class AlertRuleHook(BaseHook):
    """告警规则钩子 — 在 execution_failed / execution_timeout / execution_completed / node_failed 事件触发规则评估。"""

    priority = 30

    EVENT_TO_CONDITION = {
        "execution_failed": "execution_failed",
        "execution_timeout": "execution_timeout",
        "execution_completed": "cost_threshold",
        "node_failed": "node_error_code",
    }

    async def execute(self, event: str, **kwargs: Any) -> None:
        condition_type = self.EVENT_TO_CONDITION.get(event)
        if not condition_type:
            return

        execution = kwargs.get("execution")
        if not execution:
            return

        # 跳过调试执行（per contract）
        if getattr(execution, "is_debug", False):
            return

        # 查询匹配规则（全局 + 本工作流）
        rules = await self._get_matching_rules(execution, condition_type)

        for rule in rules:
            if await self._check_cooldown(rule, execution):
                continue
            if await self._evaluate_condition(rule, execution, kwargs.get("node_execution")):
                # 后台执行动作，不阻塞 Hook 链（Pitfall 1）
                import asyncio

                asyncio.create_task(self._execute_action(rule, execution, event))

    async def _get_matching_rules(self, execution: Any, condition_type: str) -> list[Any]:
        from django.db import models
        from workflows.models import AlertRule

        workflow_id = getattr(execution, "workflow_id", None)
        project_id = getattr(execution, "space_id", None)

        return [
            r async for r in AlertRule.objects.filter(
                models.Q(workflow_id=workflow_id) | models.Q(workflow__isnull=True),
                space_id=project_id,
                condition_type=condition_type,
                enabled=True,
            )
        ]

    async def _check_cooldown(self, rule: Any, execution: Any) -> bool:
        from django.utils import timezone
        from workflows.models import AlertRuleExecution

        # 无条件去重：同一规则 + 同一执行只能触发一次
        exists = await AlertRuleExecution.objects.filter(
            alert_rule=rule,
            workflow_execution=execution,
        ).aexists()
        if exists:
            return True

        # cooldown_seconds 额外窗口（若配置）
        cooldown_seconds = rule.cooldown_seconds or 0
        if cooldown_seconds > 0:
            cutoff = timezone.now() - timedelta(seconds=cooldown_seconds)
            recent_exists = await AlertRuleExecution.objects.filter(
                alert_rule=rule,
                workflow_execution=execution,
                triggered_at__gte=cutoff,
            ).aexists()
            return recent_exists

        return False

    async def _evaluate_condition(
        self, rule: Any, execution: Any, node_execution: Any | None = None
    ) -> bool:
        condition_type = rule.condition_type
        config = rule.condition_config or {}

        if condition_type == "execution_failed":
            return execution.status in ("failed", "timeout")

        if condition_type == "execution_timeout":
            return execution.status == "timeout"

        if condition_type == "cost_threshold":
            from decimal import Decimal
            from django.db.models import Sum

            threshold = Decimal(str(config.get("threshold_value", "0")))
            total_cost = Decimal("0")

            async for ne in execution.node_executions.all():
                async for session in ne.subagent_sessions.all():
                    cost_agg = await session.token_usages.all().aaggregate(
                        total=Sum("total_cost_usd")
                    )
                    total_cost += cost_agg["total"] or Decimal("0")

            return total_cost > threshold

        if condition_type == "node_error_code":
            if not node_execution:
                return False
            target_code = config.get("error_code")
            return node_execution.error_code == target_code

        return False

    async def _execute_action(self, rule: Any, execution: Any, triggered_event: str) -> None:
        from workflows.models import AlertRuleExecution

        try:
            if rule.action_type == "feishu_notification":
                await self._send_feishu(rule, execution)
            elif rule.action_type == "webhook":
                await self._send_webhook(rule, execution)

            await AlertRuleExecution.objects.acreate(
                alert_rule=rule,
                workflow_execution=execution,
                status="delivered",
                triggered_event=triggered_event,
            )
            logger.info(
                "alert_rule_delivered",
                rule_id=str(rule.id),
                execution_id=str(execution.id),
                action_type=rule.action_type,
            )
        except Exception as e:
            logger.error(
                "alert_rule_action_failed",
                rule_id=str(rule.id),
                execution_id=str(execution.id),
                error=str(e),
            )
            await AlertRuleExecution.objects.acreate(
                alert_rule=rule,
                workflow_execution=execution,
                status="failed",
                error_message=str(e)[:500],
                triggered_event=triggered_event,
            )

    async def _send_feishu(self, rule: Any, execution: Any) -> None:
        from django.utils import timezone
        from services.feishu_im import FeishuIMService

        config = rule.action_config or {}
        chat_id = config.get("chat_id")
        if not chat_id:
            raise ValueError("飞书通知动作缺少 chat_id")

        project = getattr(execution, "space", None)
        im_service = await FeishuIMService.create(project)

        workflow_name = ""
        if execution.workflow:
            workflow_name = execution.workflow.name

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"工作流告警：{rule.name}"},
                "template": "red",
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"**触发条件：** {rule.get_condition_type_display()}\n"
                        f"**工作流：** {workflow_name or '未知'}\n"
                        f"**执行 ID：** {execution.id}\n"
                        f"**触发时间：** {timezone.now().isoformat()}"
                    ),
                }
            ],
        }

        await im_service.send_card(
            receive_id=chat_id,
            receive_id_type="chat_id",
            card=card,
        )

    async def _send_webhook(self, rule: Any, execution: Any) -> None:
        import json
        from urllib.parse import urlparse

        import httpx
        from django.utils import timezone
        from prompts.engine import get_jinja_env

        config = rule.action_config or {}
        url = config.get("url")
        if not url:
            raise ValueError("Webhook 动作缺少 URL")

        # SSRF 防护：协议白名单 + 内网地址拦截（security mitigation）
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"不支持的协议: {parsed.scheme}")
        hostname = parsed.hostname or ""
        if self._is_internal_host(hostname):
            raise ValueError("禁止访问内网地址")

        headers = config.get("headers", {})
        template_str = config.get("payload_template", "")

        workflow_name = ""
        if execution.workflow:
            workflow_name = execution.workflow.name

        context = {
            "event": "workflow_alert",
            "rule_name": rule.name,
            "condition_type": rule.condition_type,
            "workflow_execution": {
                "id": str(execution.id),
                "status": execution.status,
                "workflow_name": workflow_name,
            },
            "triggered_at": timezone.now().isoformat(),
        }

        if template_str:
            env = get_jinja_env()
            template = env.from_string(template_str)
            payload = template.render(**context)
        else:
            payload = json.dumps(context, ensure_ascii=False)

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, headers=headers, content=payload)
            if response.status_code >= 400:
                raise RuntimeError(f"Webhook 返回错误状态码: {response.status_code}")

    @staticmethod
    def _is_internal_host(hostname: str) -> bool:
        import ipaddress

        try:
            ip = ipaddress.ip_address(hostname)
            return ip.is_private or ip.is_loopback or ip.is_link_local
        except ValueError:
            return hostname in ("localhost",) or hostname.endswith(".local")
