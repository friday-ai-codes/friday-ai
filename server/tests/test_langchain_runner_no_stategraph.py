"""静态断言：langchain_runner.py 不得嵌入 LangGraph 子图执行器。
依据：
- REQUIREMENTS "不嵌入 LangGraph 子图执行器（保持朴素 ReAct loop）"
- project-docs/research/PITFALLS.md §Pitfall 9 三层 await 死锁
- v21.0 Out of Scope "AI 节点内嵌 LangGraph 子图"
- Pitfall 8：runner 必须用 llm.astream 而非事件流 v2
若未来需要子图嵌入，必须另起里程碑 + 反转 决策 + 重评 Pitfall 9 缓解。
任何违反 的 commit 会立即 CI fail。
"""
from __future__ import annotations
import ast
from pathlib import Path
RUNNER_FILE = Path(__file__).parent.parent / "agents" / "langchain_runner.py"
# 禁止 from 这些 module 做任何 import
FORBIDDEN_IMPORT_MODULES = {
 "langgraph.graph",
 "langgraph.prebuilt",
 "langgraph.pregel",
}
# 禁止在源码里出现的类 / 函数 / API 名（含 import 或引用）
FORBIDDEN_SYMBOLS = {"StateGraph", "MessageGraph", "create_react_agent"}
def test_no_langgraph_imports -> None:
 """langchain_runner.py 不得 import 任何 langgraph.* 符号（ 禁线）。"""
 src = RUNNER_FILE.read_text(encoding="utf-8")
 tree = ast.parse(src)
 for node in ast.walk(tree):
 if isinstance(node, ast.ImportFrom):
 mod = node.module or ""
 assert mod not in FORBIDDEN_IMPORT_MODULES, (
 f"langchain_runner.py 禁止 from {mod} import（ + Pitfall 9）"
 )
 # 兜底：也禁止 langgraph.* 全前缀（例如将来 langgraph.new_subpkg）
 assert not mod.startswith("langgraph."), (
 f"langchain_runner.py 禁止 from {mod} import（ 禁线）"
 )
 elif isinstance(node, ast.Import):
 for alias in node.names:
 assert not alias.name.startswith("langgraph."), (
 f"langchain_runner.py 禁止 import {alias.name}（ 禁线）"
 )
 assert alias.name != "langgraph", (
 "langchain_runner.py 禁止 import langgraph（ 禁线）"
 )
def test_no_forbidden_symbols_in_source -> None:
 """源码不得引用 StateGraph / MessageGraph / create_react_agent 任一符号。"""
 src = RUNNER_FILE.read_text(encoding="utf-8")
 for sym in FORBIDDEN_SYMBOLS:
 assert sym not in src, (
 f"langchain_runner.py 不得引用 {sym}（ 禁止嵌 LangGraph 子图执行器）"
 )
def test_no_astream_events_v2 -> None:
 """Pitfall 8：runner 必须用 llm.astream 而非事件流 v2 API。"""
 src = RUNNER_FILE.read_text(encoding="utf-8")
 assert "astream_events" not in src, (
 "langchain_runner.py 不得使用 astream_events（Pitfall 8：保持 AIMessageChunk 累加）"
 )
