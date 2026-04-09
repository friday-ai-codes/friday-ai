"""deep_analysis dispatch 模式注入测试。
验证 chat_tools.py 的 deep_analysis 函数构建的 DispatchTask 中
包含正确的 env_FRIDAY_TASK_MODE 和 env_FRIDAY_TASK_TASK_MODE 注入。
策略：使用 AST 解析 chat_tools.py 源码，提取 env_metadata 字典和
DispatchTask 构造参数，断言关键 key-value 存在且正确。
这比 mock 全量 DB 依赖更轻量且不易因无关重构而误报。
"""
import ast
from pathlib import Path
import pytest
# chat_tools.py 相对于 server/ 的路径
CHAT_TOOLS_PATH = Path(__file__).resolve.parent.parent / "agents" / "tools" / "chat_tools.py"
def _get_source -> str:
 """读取 chat_tools.py 源码。"""
 return CHAT_TOOLS_PATH.read_text(encoding="utf-8")
def _find_deep_analysis_func(tree: ast.Module) -> ast.AsyncFunctionDef | None:
 """在 AST 中找到 deep_analysis 函数定义。"""
 for node in ast.walk(tree):
 if isinstance(node, ast.AsyncFunctionDef) and node.name == "deep_analysis":
 return node
 return None
def _extract_env_metadata_dict(func_node: ast.AsyncFunctionDef) -> dict[str, str]:
 """从 deep_analysis 函数体中提取 env_metadata 字典的字面量 key-value。
 只提取值为字符串字面量的项（跳过变量引用如 api_key）。
 """
 result: dict[str, str] = {}
 for node in ast.walk(func_node):
 # 匹配: env_metadata: dict[str, str] = { ... } 或 env_metadata = { ... }
 if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
 if node.target.id == "env_metadata" and isinstance(node.value, ast.Dict):
 for key, value in zip(node.value.keys, node.value.values):
 if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
 result[key.value] = value.value
 elif isinstance(node, ast.Assign):
 for target in node.targets:
 if isinstance(target, ast.Name) and target.id == "env_metadata":
 if isinstance(node.value, ast.Dict):
 for key, value in zip(node.value.keys, node.value.values):
 if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
 result[key.value] = value.value
 return result
def _find_dispatch_task_type(func_node: ast.AsyncFunctionDef) -> str | None:
 """从 deep_analysis 函数体中提取 DispatchTask 构造的 task_type 参数值。"""
 for node in ast.walk(func_node):
 if isinstance(node, ast.Call):
 # 匹配 DispatchTask(...) 调用
 func = node.func
 if isinstance(func, ast.Name) and func.id == "DispatchTask":
 for kw in node.keywords:
 if kw.arg == "task_type" and isinstance(kw.value, ast.Constant):
 return kw.value.value
 return None
class TestDeepAnalysisDispatchMode:
 """验证 deep_analysis 构建的 DispatchTask 包含正确的 explore 模式标识。"""
 @pytest.fixture(autouse=True)
 def _parse_source(self) -> None:
 """解析 chat_tools.py 源码并提取 deep_analysis 函数。"""
 source = _get_source
 tree = ast.parse(source)
 func = _find_deep_analysis_func(tree)
 assert func is not None, "chat_tools.py 中未找到 deep_analysis 函数"
 self.func_node = func
 self.env_metadata = _extract_env_metadata_dict(func)
 def test_env_friday_task_mode_is_explore(self) -> None:
 """env_metadata 包含 env_FRIDAY_TASK_MODE='explore'（Shell 层 wrapper 读取）。"""
 assert "env_FRIDAY_TASK_MODE" in self.env_metadata, \
 "env_metadata 缺少 env_FRIDAY_TASK_MODE 键"
 assert self.env_metadata["env_FRIDAY_TASK_MODE"] == "explore", \
 f"env_FRIDAY_TASK_MODE 应为 'explore'，实际为 '{self.env_metadata['env_FRIDAY_TASK_MODE']}'"
 def test_env_friday_task_task_mode_is_explore(self) -> None:
 """env_metadata 包含 env_FRIDAY_TASK_TASK_MODE='explore'（pydantic-settings Python 层映射）。"""
 assert "env_FRIDAY_TASK_TASK_MODE" in self.env_metadata, \
 "env_metadata 缺少 env_FRIDAY_TASK_TASK_MODE 键"
 assert self.env_metadata["env_FRIDAY_TASK_TASK_MODE"] == "explore", \
 f"env_FRIDAY_TASK_TASK_MODE 应为 'explore'，实际为 '{self.env_metadata['env_FRIDAY_TASK_TASK_MODE']}'"
 def test_dispatch_task_type_is_explore(self) -> None:
 """DispatchTask 的 task_type 为 'explore'。"""
 task_type = _find_dispatch_task_type(self.func_node)
 assert task_type == "explore", \
 f"DispatchTask.task_type 应为 'explore'，实际为 '{task_type}'"
