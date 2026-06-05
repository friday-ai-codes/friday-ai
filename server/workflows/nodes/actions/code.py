"""Code sandbox node with AST safety checks and restricted exec environment."""

import ast
import builtins
import json
from typing import Any, ClassVar

import structlog

from workflows.nodes.base import BaseNode, ExecutionContext, NodeCategory, NodeResult
from workflows.nodes.registry import register_node

logger = structlog.get_logger()

# =============================================================================
# AST Safety Configuration
# =============================================================================

UNSAFE_AST_NODES: frozenset[str] = frozenset({
    "Import", "ImportFrom", "ClassDef", "Lambda",
    "Global", "Nonlocal", "Delete",
})

DANGEROUS_BUILTINS: frozenset[str] = frozenset({
    "__import__", "eval", "exec", "compile", "open", "input",
})

DANGEROUS_ATTRS: frozenset[str] = frozenset({
    "system", "popen", "spawn", "kill", "fork", "execv", "execve",
})

SAFE_BUILTINS: list[str] = [
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
    "chr", "complex", "dict", "divmod", "enumerate", "filter", "float",
    "format", "frozenset", "hash", "hex", "int", "isinstance", "issubclass",
    "iter", "len", "list", "map", "max", "min", "next", "oct", "ord",
    "pow", "range", "repr", "reversed", "round", "set", "slice", "sorted",
    "str", "sum", "tuple", "type", "vars", "zip",
]


# =============================================================================
# AST Safety Check
# =============================================================================

def _check_ast_safety(code: str) -> tuple[bool, list[str]]:
    """Parse code and check for unsafe AST nodes and dangerous calls.

    Args:
        code: User-provided Python code string.

    Returns:
        (is_safe, list_of_error_messages)
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, [f"语法错误: {e}"]

    errors: list[str] = []
    for node in ast.walk(tree):
        node_type = type(node).__name__
        if node_type in UNSAFE_AST_NODES:
            errors.append(f"禁止的语法: {node_type}")

        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in DANGEROUS_BUILTINS:
                errors.append(f"禁止的函数: {func.id}")
            elif isinstance(func, ast.Attribute) and func.attr in DANGEROUS_ATTRS:
                errors.append(f"禁止的操作: {func.attr}")

    return len(errors) == 0, errors


# =============================================================================
# Safe Globals Builder
# =============================================================================

def _build_safe_globals() -> dict[str, Any]:
    """Build a restricted globals dict for exec().

    Exposes only safe builtins plus json, math, datetime modules.

    Returns:
        Dict suitable as exec() globals.
    """
    safe_builtins: dict[str, Any] = {}
    for name in SAFE_BUILTINS:
        if hasattr(builtins, name):
            safe_builtins[name] = getattr(builtins, name)
    safe_builtins.update({"True": True, "False": False, "None": None})

    import datetime
    import math

    return {
        "__builtins__": safe_builtins,
        "json": json,
        "math": math,
        "datetime": datetime,
    }


# =============================================================================
# CodeNode
# =============================================================================

@register_node
class CodeNode(BaseNode):
    """代码执行节点 — 在受限沙箱中运行用户提供的 Python 代码。"""

    node_type: ClassVar[str] = "code"
    display_name: ClassVar[str] = "代码执行"
    description: ClassVar[str] = "执行 Python 代码片段"
    icon: ClassVar[str] = "code"
    category: ClassVar[NodeCategory] = NodeCategory.ACTION
    execution_mode: ClassVar[str] = "server_local"
    supports_retry: ClassVar[bool] = True

    config_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "title": "代码",
                "description": "Python 代码片段",
            },
            "timeout_seconds": {
                "type": "integer",
                "default": 30,
                "minimum": 1,
                "maximum": 300,
            },
        },
        "required": ["code"],
    }

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """Execute user code in a restricted sandbox.

        Steps:
        1. Validate code is not empty.
        2. AST safety check.
        3. Build restricted globals + local context.
        4. exec() with safe environment.
        5. Validate output is JSON-serializable.

        Args:
            context: Execution context with input/config/global/trigger data.

        Returns:
            NodeResult with completed status and output, or failed with error.
        """
        code = context.node_config.get("code", "")
        if not code.strip():
            return NodeResult(status="failed", error="代码不能为空")

        # 1. AST 安全检查
        safe, errors = _check_ast_safety(code)
        if not safe:
            error_msg = f"代码安全检查失败: {'; '.join(errors)}"
            logger.warning(
                "code_node.ast_check_failed",
                node_id=context.node_id,
                execution_id=context.execution_id,
                errors=errors,
            )
            return NodeResult(status="failed", error=error_msg)

        # 2. 构建受限执行环境
        safe_globals = _build_safe_globals()
        local_ctx: dict[str, Any] = {
            "context": {
                "input": context.input_data,
                "config": context.node_config,
                "global": context.workflow_context.get("global_params", {}),
                "trigger": context.trigger_data,
            }
        }

        # 3. 执行代码
        try:
            exec(code, safe_globals, local_ctx)  # noqa: S102
        except Exception as e:
            # 仅返回异常类型和消息，不泄露 traceback（per threat model security mitigation）
            error_msg = f"{type(e).__name__}: {e}"
            logger.warning(
                "code_node.execution_error",
                node_id=context.node_id,
                execution_id=context.execution_id,
                exc_type=type(e).__name__,
                exc_msg=str(e),
            )
            return NodeResult(status="failed", error=error_msg)

        # 4. 读取输出并校验 JSON 序列化
        # 用户代码通过 context['output'] = {...} 设置输出，
        # 这修改的是 local_ctx['context'] 字典
        ctx_dict = local_ctx.get("context", {})
        output = ctx_dict.get("output", {})
        try:
            json.dumps(output)
        except (TypeError, ValueError) as e:
            error_msg = f"输出必须是 JSON 可序列化对象: {e}"
            logger.warning(
                "code_node.json_serialization_failed",
                node_id=context.node_id,
                execution_id=context.execution_id,
                output_type=type(output).__name__,
            )
            return NodeResult(status="failed", error=error_msg)

        return NodeResult(status="completed", output=output)
