"""Loop control nodes: ForEach."""

import asyncio
import json
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

logger = structlog.get_logger()


@register_node
class ForEachNode(BaseNode):
    """ForEach 循环节点：把列表展开成多次迭代并汇总结果。

    **当前实现不执行循环体**——迭代体（``_run_iteration``）把元素原样透传，没有
    子 DAG，也不会去调用画布上的下游节点。所以本节点实际是一个「带串/并发控制与
    错误策略的列表汇总器」：``results`` / ``success_count`` / ``failed_count``
    都是真实产出，下游可以消费；但 ``execution_mode`` 与 ``max_concurrency``
    在迭代体为空转的前提下不产生可观测差异。

    不要按字面理解成「对每个元素跑一段子流程」。需要真正的逐项处理时，当前应在
    下游用其他节点消费 ``results``。补齐子 DAG 执行属未完成工作。
    """

    node_type = "foreach"
    display_name = "ForEach 循环"
    description = "把列表展开并汇总结果（迭代体透传元素，不执行子流程）"
    icon = "repeat"
    category = NodeCategory.CONTROL
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "list_source": {
                "type": "string",
                "title": "列表来源",
                "description": "列表数据来源，支持模板变量如 {{input.items}}",
            },
            "execution_mode": {
                "type": "string",
                "enum": ["sequential", "parallel"],
                "default": "sequential",
                "title": "执行模式",
                "description": "sequential=串行执行, parallel=并发执行",
            },
            "max_concurrency": {
                "type": "integer",
                "default": 5,
                "minimum": 1,
                "maximum": 50,
                "title": "最大并发数",
                "description": "并发模式下的最大并发数（1-50）",
            },
            "on_iteration_error": {
                "type": "string",
                "enum": ["abort", "continue"],
                "default": "abort",
                "title": "迭代错误处理",
                "description": "abort=任一失败终止, continue=记录错误继续",
            },
        },
        "required": ["list_source"],
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT, required=False)]
    outputs = [NodePort(name="default", label="输出", port_type=PortType.OBJECT)]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """执行 ForEach 循环。

        Args:
            context: 执行上下文

        Returns:
            NodeResult: 包含 results、success_count、failed_count 的结果
        """
        config = context.node_config
        list_source = config.get("list_source", "")
        execution_mode = config.get("execution_mode", "sequential")
        max_concurrency = min(config.get("max_concurrency", 5), 50)
        on_error = config.get("on_iteration_error", "abort")

        # 解析列表输入（保留原始类型）
        items = self._resolve_list(context, list_source)

        if not isinstance(items, list):
            # 非列表类型：尝试 JSON 解析，否则包装为单元素列表
            if isinstance(items, str):
                items = self._parse_json_or_wrap(items)
            else:
                items = [items] if items is not None else []

        if not items:
            # 空列表直接返回
            return NodeResult(
                status="completed",
                output={"results": [], "success_count": 0, "failed_count": 0},
            )

        results: list[Any] = []
        success_count = 0
        failed_count = 0

        if execution_mode == "parallel":
            # 并发模式：使用 Semaphore 限制并发数
            semaphore = asyncio.Semaphore(max_concurrency)

            async def _run_with_semaphore(item: Any, index: int) -> dict:
                async with semaphore:
                    return await self._run_iteration(context, item, index)

            tasks = [
                asyncio.create_task(_run_with_semaphore(item, i))
                for i, item in enumerate(items)
            ]

            if on_error == "abort":
                # abort 模式：任一失败立即取消所有未完成任务
                try:
                    for task in asyncio.as_completed(tasks):
                        iteration_result = await task
                        results.append(self._extract_output(iteration_result))
                        if iteration_result.get("status") == "failed":
                            failed_count += 1
                            # 取消所有未完成任务
                            for t in tasks:
                                if not t.done():
                                    t.cancel()
                            # 等待已取消任务完成（忽略 CancelledError）
                            await asyncio.gather(*tasks, return_exceptions=True)
                            return NodeResult(
                                status="failed",
                                output={
                                    "results": results,
                                    "success_count": success_count,
                                    "failed_count": failed_count,
                                    "error": iteration_result.get("error", "迭代失败"),
                                },
                            )
                        else:
                            success_count += 1
                except asyncio.CancelledError:
                    pass
            else:
                # continue 模式：收集所有结果
                iteration_results = await asyncio.gather(*tasks, return_exceptions=True)
                for iteration_result in iteration_results:
                    if isinstance(iteration_result, Exception):
                        failed_count += 1
                        results.append({"status": "failed", "error": str(iteration_result)})
                    elif iteration_result.get("status") == "failed":
                        failed_count += 1
                        results.append(iteration_result)
                    else:
                        success_count += 1
                        results.append(self._extract_output(iteration_result))
        else:
            # 串行模式
            for index, item in enumerate(items):
                iteration_result = await self._run_iteration(context, item, index)

                if iteration_result.get("status") == "failed":
                    failed_count += 1
                    results.append(iteration_result)
                    if on_error == "abort":
                        return NodeResult(
                            status="failed",
                            output={
                                "results": results,
                                "success_count": success_count,
                                "failed_count": failed_count,
                                "error": iteration_result.get("error", "迭代失败"),
                            },
                        )
                else:
                    success_count += 1
                    results.append(self._extract_output(iteration_result))

        return NodeResult(
            status="completed",
            output={
                "results": results,
                "success_count": success_count,
                "failed_count": failed_count,
            },
        )

    def _resolve_list(self, context: ExecutionContext, list_source: str) -> Any:
        """解析列表来源，优先使用 get_template_value 保留原始类型。"""
        if not list_source:
            return []

        # 使用 get_template_value 保留复杂类型（如 list、dict）
        resolved = context.get_template_value(list_source)
        return resolved if resolved != "" else []

    def _parse_json_or_wrap(self, value: str) -> list:
        """尝试 JSON 解析字符串，失败则包装为单元素列表。"""
        value = value.strip()
        if not value:
            return []

        # 尝试 JSON 解析
        if value.startswith("[") or value.startswith("{"):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return parsed
                return [parsed]
            except json.JSONDecodeError:
                pass

        # 包装为单元素列表
        return [value]

    async def _run_iteration(self, context: ExecutionContext, item: Any, index: int) -> dict:
        """执行单次迭代——当前为透传，不执行任何循环体。

        子 DAG 执行尚未实现，这里直接把 item 原样回传。接子流程时，应在此处
        构造 ``{**context.input_data, "item": item, "index": index}`` 作为迭代
        上下文并驱动循环体节点；在那之前不预先构造，避免留下无人使用的变量。

        Args:
            context: 父执行上下文
            item: 当前迭代项
            index: 当前索引

        Returns:
            dict: 迭代结果 {"status": "completed", "output": ...} 或 {"status": "failed", "error": ...}
        """
        try:
            return {
                "status": "completed",
                "output": item,
                "item": item,
                "index": index,
            }
        except Exception as e:
            logger.warning(
                "foreach_iteration_failed",
                item=item,
                index=index,
                error=str(e),
            )
            return {
                "status": "failed",
                "error": str(e),
                "item": item,
                "index": index,
            }

    def _extract_output(self, iteration_result: dict) -> Any:
        """从迭代结果中提取输出值。"""
        if iteration_result.get("status") == "failed":
            return iteration_result
        return iteration_result.get("output")
