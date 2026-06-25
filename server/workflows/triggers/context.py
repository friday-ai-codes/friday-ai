"""Trigger context data structure."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from accounts.models import User
    from projects.models import Space
    from workflows.models import Workflow


@dataclass
class TriggerContext:
    """统一触发器上下文

    包含原始 payload，透明传递给触发节点进行解析。
    不做预处理，让节点自行解析所需数据。

    Attributes:
        trigger_type: 触发器类型（如 "feishu", "webhook", "manual"）
        raw_payload: 原始请求数据，不做任何预处理
        event_type: 事件类型（用于飞书等事件源）
        space: 关联的空间
        workflow: 目标工作流（手动触发时指定）
        triggered_by: 触发用户
        idempotency_key: 幂等键，用于去重
        metadata: 附加元数据
    """

    trigger_type: str
    raw_payload: dict

    # 可选字段，带默认值
    event_type: str | None = None
    space: "Space | None" = None
    workflow: "Workflow | None" = None
    triggered_by: "User | None" = None
    idempotency_key: str | None = None
    metadata: dict = field(default_factory=dict)
    # 调试模式标记，仅手动触发时设置
    debug_mode: bool = False
    # 单节点测试：执行到指定节点前停止
    stop_before_node_id: str | None = None

    def get_payload_value(self, key: str, default: Any = None) -> Any:
        """获取 raw_payload 中的嵌套值

        支持点分隔路径访问嵌套数据。

        Args:
            key: 点分隔路径，如 "event.message.content"
            default: 找不到时返回的默认值

        Returns:
            路径对应的值，或默认值

        Examples:
            >>> ctx = TriggerContext(trigger_type="test", raw_payload={"a": {"b": 1}})
            >>> ctx.get_payload_value("a.b")
            1
            >>> ctx.get_payload_value("a.c", "not found")
            'not found'
        """
        keys = key.split(".")
        current: Any = self.raw_payload
        for k in keys:
            if isinstance(current, dict):
                current = current.get(k)
            else:
                return default
            if current is None:
                return default
        return current
