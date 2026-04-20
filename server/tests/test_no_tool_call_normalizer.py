"""静态断言：禁止自写 tool_call 归一化层（ 原文禁线）。
依据：
- REQUIREMENTS "输出端完全依赖 LangChain AIMessage.tool_calls 标准化产物
 （不自写 tool_call 归一化层）"
- CONTEXT / （信任 LangChain bind_tools + output_version='v1' 统一能力）
- RESEARCH Anti-Patterns：自写 normalizer 与 直接冲突
允许：runner 内为 Gemini tool_call id 缺失补 uuid.uuid4.hex[:12]
（是协议缺字段填充，不是 normalizer / 不是 schema 转换）。
任何违反 的 commit（无论是新建文件还是 import 引用）都会被这两条静态断言捕获。
"""
from __future__ import annotations
from pathlib import Path
AGENTS_DIR = Path(__file__).parent.parent / "agents"
# 允许白名单：测试文件本身 + 允许出现触发词的文档化注释位置（如有）
# 当前 agents/ 下所有 .py 都应 0 触发词
_ALLOWED_MENTION_FILES: set[Path] = set
def test_no_tool_call_normalizer_file -> None:
 """server/agents/ 不得存在 tool_call_normalizer.py 文件（ 禁线）。"""
 forbidden = AGENTS_DIR / "tool_call_normalizer.py"
 assert not forbidden.exists, (
 f"禁止创建 {forbidden}（ 原文：输出端完全依赖 AIMessage.tool_calls 标准化产物）"
 )
def test_no_tool_call_normalizer_references -> None:
 """server/agents/ 下任一源码不得出现 tool_call_normalizer 字符串（ 禁线）。"""
 for py_file in AGENTS_DIR.rglob("*.py"):
 if py_file in _ALLOWED_MENTION_FILES:
 continue
 src = py_file.read_text(encoding="utf-8")
 assert "tool_call_normalizer" not in src, (
 f"{py_file} 引用了 tool_call_normalizer —— 禁线（"
 f"信任 LangChain AIMessage.tool_calls 归一化，不自写 normalizer）"
 )
