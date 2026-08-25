"""旧结构化渠道收口门禁（260818-pt8 Task 3，D-01/D-02/D-04）。

守三件事（AST 精确定位函数体，禁止裸字符串扫全文件，避免误伤 docstring 与 repo_verify 链）：

1. **task/core 生产代码零残留私有 repo-summary 提交 server**：三场景统一走共享工厂
   ``agent_submit_mcp``，不得再引用旧的 ``mcp__repo-summary__`` 全名。
2. **三场景 parser 函数体不再走文本 JSON 兜底**：``_parse_blueprint_fitness`` /
   ``_parse_blueprint_repo_plan`` / ``_update_repository_on_summary_complete`` 的**代码**里
   不得调用 ``_parse_summary_json(...)`` 或读取 ``output["text"]``（docstring 里提到旧渠道被删
   属正常，不算违规）。
3. **repo_verify 链不被误伤**：``parse_verify_verdict`` 仍保留 ``_parse_summary_json`` 文本解析
   （本次改动明确不动 verify 链）——门禁若把它一起清了就是过度收口。
"""

from __future__ import annotations

import ast
from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _SERVER_ROOT.parent
_CALLBACKS = _SERVER_ROOT / "subagent" / "api" / "callbacks.py"
_TASK_CORE = _REPO_ROOT / "task" / "core"

_THREE_SCENARIO_PARSERS = (
    "_parse_blueprint_fitness",
    "_parse_blueprint_repo_plan",
    "_update_repository_on_summary_complete",
)


def _find_func(tree: ast.AST, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"未找到函数 {name}")


def _calls_parse_summary_json(func: ast.AST) -> bool:
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_parse_summary_json"
        for n in ast.walk(func)
    )


def _reads_output_text(func: ast.AST) -> bool:
    for n in ast.walk(func):
        # output["text"]
        if (
            isinstance(n, ast.Subscript)
            and isinstance(n.value, ast.Name)
            and n.value.id == "output"
            and isinstance(n.slice, ast.Constant)
            and n.slice.value == "text"
        ):
            return True
        # output.get("text")
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "output"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and n.args[0].value == "text"
        ):
            return True
    return False


def test_task_core_has_no_private_repo_summary_submit_server() -> None:
    offenders = [
        p.name
        for p in _TASK_CORE.glob("*.py")
        if "mcp__repo-summary__" in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"task/core 仍引用旧私有提交 server: {offenders}"


def test_three_scenario_parsers_drop_text_json_fallback() -> None:
    tree = ast.parse(_CALLBACKS.read_text(encoding="utf-8"))
    for name in _THREE_SCENARIO_PARSERS:
        func = _find_func(tree, name)
        assert not _calls_parse_summary_json(func), f"{name} 仍调用 _parse_summary_json（应只认 mcp_result）"
        assert not _reads_output_text(func), f"{name} 仍读取 output['text']（应只认 mcp_result）"


def test_repo_verify_chain_is_not_over_collected() -> None:
    """反向断言：verify 链仍用文本解析——门禁不得把它一起清掉（D-04 scoped）。"""
    tree = ast.parse(_CALLBACKS.read_text(encoding="utf-8"))
    func = _find_func(tree, "parse_verify_verdict")
    assert _calls_parse_summary_json(func), "parse_verify_verdict 的文本解析被误删（越界收口）"
