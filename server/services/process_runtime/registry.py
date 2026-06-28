"""ProcessType / Stage Registry —— 数据化 stage graph 注册表（Chassis v2 · P2）。

把"一个 AI 收敛流程由哪些 stage 组成、每个 stage 跑什么 handler、收到某 outcome event
后转移到哪个 stage"从写死的状态机常量泛化为**可注册的数据**：

- ``StageDef``：单个 stage 的定义（``key`` / ``handler`` / ``transitions`` /
  ``pausable`` / ``wait_status``）。``transitions`` 是 ``{event -> next_stage_key |
  "__done__" | "__failed__"}`` 的数据化转移表（取代写死的 ``_ALLOWED``）。
- ``ProcessDefinition``：一个 ``process_type`` 的完整定义（artifact_type / initial_stage /
  stages / clarification_policy 等）。
- ``ProcessTypeRegistry``：注册 / 查询 ``ProcessDefinition``。

``ConvergenceSessionService.transition`` 据本注册表查转移目标（不再写死 ``_ALLOWED``）；
``ProcessEngine.advance`` 据本注册表取 ``current_stage`` 的 handler 推进。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from services.process_runtime.engine import ProcessEngine, StageOutcome

# stage handler：(session, engine) -> StageOutcome
StageHandler = Callable[[Any, "ProcessEngine"], "Awaitable[StageOutcome]"]

# stage graph 终态 sentinel（transitions 的 value 取这两个值即落终态）
STAGE_DONE = "__done__"
STAGE_FAILED = "__failed__"


@dataclass(frozen=True)
class StageDef:
    """单个 stage 的数据化定义。"""

    key: str
    handler: StageHandler
    # {event -> next_stage_key | STAGE_DONE | STAGE_FAILED}
    transitions: dict[str, str] = field(default_factory=dict)
    # 该 stage 是否可挂起（self-loop 转移命中挂起条件时短路返回）
    pausable: bool = False
    # 挂起时 ConvergenceSession.status 取值（pausable self-loop 命中时）
    wait_status: str = "waiting_event"


@dataclass(frozen=True)
class ProcessDefinition:
    """一个 ``process_type`` 的完整流程定义。"""

    process_type: str
    artifact_type: str
    initial_stage: str
    stages: dict[str, StageDef]
    # 可选：澄清策略 / 其它流程级配置（handler 自取）
    config: dict[str, Any] = field(default_factory=dict)

    def stage(self, key: str) -> StageDef | None:
        return self.stages.get(key)


class ProcessTypeRegistry:
    """``ProcessDefinition`` 注册表（进程类型开放枚举）。"""

    _REGISTRY: dict[str, ProcessDefinition] = {}

    @classmethod
    def register(cls, definition: ProcessDefinition) -> None:
        cls._REGISTRY[definition.process_type] = definition

    @classmethod
    def get(cls, process_type: str) -> ProcessDefinition | None:
        cls._ensure_builtins()
        return cls._REGISTRY.get(process_type)

    @classmethod
    def is_registered(cls, process_type: str) -> bool:
        cls._ensure_builtins()
        return process_type in cls._REGISTRY

    @classmethod
    def registered_types(cls) -> list[str]:
        cls._ensure_builtins()
        return sorted(cls._REGISTRY.keys())

    @classmethod
    def _ensure_builtins(cls) -> None:
        """首次访问时惰性导入内置流程注册（side-effect import，规避 import 环）。"""
        if cls._REGISTRY:
            return
        # 导入即注册（builtin_processes 顶层调用 register）
        import services.process_runtime.builtin_processes  # noqa: F401


def register_process_type(definition: ProcessDefinition) -> None:
    """注册（或覆盖）一种 ``process_type`` 定义。"""
    ProcessTypeRegistry.register(definition)


def get_process_definition(process_type: str) -> ProcessDefinition | None:
    return ProcessTypeRegistry.get(process_type)
