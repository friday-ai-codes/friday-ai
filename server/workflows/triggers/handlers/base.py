"""TriggerHandler abstract base class."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

from workflows.triggers.context import TriggerContext

if TYPE_CHECKING:
    from workflows.models import Workflow


class TriggerHandler(ABC):
    """触发处理器基类

    所有触发处理器必须继承此类并实现抽象方法。
    遵循 BaseNode 的设计模式。

    每个处理器负责：
    1. 验证触发上下文的有效性
    2. 查找应该被触发的工作流
    3. 为工作流执行准备输入数据

    ClassVar 属性（子类必须设置）：
        trigger_type: 触发类型标识符（如 "feishu", "webhook", "manual"）
        display_name: 人类可读的显示名称
        description: 可选的描述信息
    """

    # 元数据（子类必须设置）
    trigger_type: ClassVar[str]
    display_name: ClassVar[str]
    description: ClassVar[str] = ""

    @abstractmethod
    async def validate(self, context: TriggerContext) -> list[str]:
        """验证触发上下文

        检查 context 是否包含处理该触发所需的所有数据。
        返回错误消息列表，空列表表示验证通过。

        Args:
            context: 触发上下文

        Returns:
            错误消息列表。空列表表示有效。

        Examples:
            >>> errors = await handler.validate(context)
            >>> if errors:
            ...     print(f"验证失败: {errors}")
        """
        pass

    @abstractmethod
    async def find_workflows(self, context: TriggerContext) -> list["Workflow"]:
        """查找应该被触发的工作流

        根据 context 中的信息，找出所有匹配的、应该被执行的工作流。

        Args:
            context: 触发上下文

        Returns:
            匹配的 Workflow 实例列表
        """
        pass

    @abstractmethod
    async def prepare_input(
        self,
        context: TriggerContext,
        workflow: "Workflow",
    ) -> dict:
        """为工作流执行准备输入数据

        将 context 转换为 WorkflowEngine.start_execution() 所需的 input_data。
        input_data 将包含 raw_payload 供触发节点解析。

        Args:
            context: 触发上下文
            workflow: 目标工作流

        Returns:
            用于 WorkflowEngine.start_execution() 的 input_data 字典
        """
        pass
