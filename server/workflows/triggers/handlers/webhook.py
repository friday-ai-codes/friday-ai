"""WebhookHandler for generic webhook triggering."""
from typing import TYPE_CHECKING, ClassVar
import structlog
from asgiref.sync import sync_to_async
from workflows.triggers.context import TriggerContext
from workflows.triggers.handlers.base import TriggerHandler
from workflows.triggers.registry import register_handler
if TYPE_CHECKING:
 from workflows.models import Workflow
logger = structlog.get_logger
@register_handler
class WebhookHandler(TriggerHandler):
 """通用 Webhook 触发处理器
 通过 webhook path 查找关联的工作流，并验证请求签名。
 TriggerContext 需要:
 - raw_payload: 原始请求体
 - metadata["webhook_path"]: Webhook 路径
 - metadata["signature"]: 请求签名 (可选，如 X-Signature header)
 - metadata["request_body"]: 原始请求体 bytes (用于签名验证)
 """
 trigger_type: ClassVar[str] = "webhook"
 display_name: ClassVar[str] = "Webhook 触发"
 description: ClassVar[str] = "通过通用 Webhook 触发工作流"
 async def validate(self, context: TriggerContext) -> list[str]:
 """验证 Webhook 触发上下文
 检查:
 1. metadata 中必须有 webhook_path
 2. 查找对应的 WebhookConfig
 3. 验证签名（如果配置了 secret）
 """
 errors =
 webhook_path = context.metadata.get("webhook_path")
 if not webhook_path:
 errors.append("缺少必需字段: metadata.webhook_path")
 return errors
 # 查找 WebhookConfig
 from workflows.models import WebhookConfig
 config = await sync_to_async(
 lambda: WebhookConfig.objects.filter(
 path=webhook_path,
 is_active=True,
 workflow__is_active=True,
 ).select_related("workflow").first
 )
 if not config:
 errors.append(f"未找到有效的 Webhook 配置: {webhook_path}")
 return errors
 # 验证签名
 if config.secret:
 signature = context.metadata.get("signature", "")
 request_body = context.metadata.get("request_body", b"")
 if isinstance(request_body, str):
 request_body = request_body.encode
 if not config.verify_signature(request_body, signature):
 errors.append("Webhook 签名验证失败")
 logger.warning(
 "webhook_signature_invalid",
 webhook_path=webhook_path,
 )
 return errors
 async def find_workflows(self, context: TriggerContext) -> list["Workflow"]:
 """通过 webhook path 查找关联的工作流"""
 webhook_path = context.metadata.get("webhook_path")
 if not webhook_path:
 return
 from workflows.models import WebhookConfig
 configs = await sync_to_async(
 lambda: list(
 WebhookConfig.objects.filter(
 path=webhook_path,
 is_active=True,
 workflow__is_active=True,
 ).select_related("workflow")
 )
 )
 return [config.workflow for config in configs]
 async def prepare_input(
 self,
 context: TriggerContext,
 workflow: "Workflow",
 ) -> dict:
 """准备 Webhook 触发的输入数据"""
 return {
 "trigger_type": context.trigger_type,
 "raw_payload": context.raw_payload,
 "webhook_path": context.metadata.get("webhook_path"),
 }
