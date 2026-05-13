"""Agent tool contract snapshot tests —— per Phase / 。
锁住两条契约：
1. ``inspect.signature(search_repository_code)``（unwrap @tool decorator 后）
 序列化为 dict，与 ``fixtures/search_repository_code_signature.json`` 字节级
 diff —— 函数签名漂移立即抓出。
2. ``SearchRepositoryCodeInput.model_json_schema`` 与
 ``fixtures/search_repository_code_input_schema.json`` 字节级 diff —— Pydantic
 字段命名 / 类型 / 默认值 / 约束漂移立即抓出。
Fixture 更新流程（**显式动作**）:
 cd server && DJANGO_SETTINGS_MODULE=friday.settings \\
 uv run python -m tests.agents._generate_contract_fixtures
 git diff tests/agents/fixtures/ # review
 git add tests/agents/fixtures/*.json && git commit
Phase 灰度切换函数签名时，本测试会先红再 baseline → review → commit，
让契约升级 ＝ 一次显式提交。
参见：
- /：Pydantic 字段冻结表
-：双 snapshot 测试要求
-：agent tool schema 包路径锁
"""
from __future__ import annotations
import inspect
import json
from pathlib import Path
from typing import Any
FIXTURE_DIR = Path(__file__).parent / "fixtures"
_SIGNATURE_FIXTURE = FIXTURE_DIR / "search_repository_code_signature.json"
_INPUT_SCHEMA_FIXTURE = FIXTURE_DIR / "search_repository_code_input_schema.json"
_REGENERATE_HINT = (
 "若变更属预期，请运行 "
 "`cd server && DJANGO_SETTINGS_MODULE=friday.settings uv run python -m "
 "tests.agents._generate_contract_fixtures` 重新生成 fixture，再 review diff 后提交。"
)
def _normalize_signature(fn: Any) -> dict[str, dict[str, Any]]:
 """``inspect.signature`` 序列化为字节稳定的 dict。
 与 ``_generate_contract_fixtures._normalize_signature`` 完全同实现，让生成
 路径与断言路径走同一个序列化逻辑（杜绝"生成器与断言器分叉"导致的幽灵 diff）。
 """
 unwrapped = inspect.unwrap(fn)
 sig = inspect.signature(unwrapped)
 return {
 name: {
 "kind": str(p.kind),
 "default": (
 repr(p.default) if p.default is not inspect.Parameter.empty else None
 ),
 "annotation": str(p.annotation),
 }
 for name, p in sig.parameters.items
 }
def test_search_repository_code_signature_snapshot -> None:
 """``search_repository_code`` 函数签名 vs fixture 字节级 diff。
 @tool decorator 用 ``functools.wraps``，所以 ``inspect.unwrap`` 能拿回原始
 函数；fixture 锁的是 *当前* 函数签名（含 ``repository_id`` / ``limit`` /
 ``min_score`` 等遗留字段），Phase 切到 新签名时此测试会失败 →
 届时刷新 fixture 即视作契约升级动作。
 """
 from agents.tools.space_tools import search_repository_code
 actual = _normalize_signature(search_repository_code)
 expected = json.loads(_SIGNATURE_FIXTURE.read_text(encoding="utf-8"))
 assert actual == expected, (
 "search_repository_code signature drifted from fixture baseline. "
 f"{_REGENERATE_HINT}"
 )
def test_search_repository_code_input_schema_snapshot -> None:
 """``SearchRepositoryCodeInput.model_json_schema`` vs fixture 字节级 diff。
 Pydantic v2 ``model_json_schema`` 输出 stable（字段顺序由模型决定，
 fixture 用 sort_keys 标准化）；任何字段命名 / 类型 / description / 约束
 （min_length / ge / le / default）的变更都会触发 diff。
 """
 from agents.tools.schemas import SearchRepositoryCodeInput
 actual = SearchRepositoryCodeInput.model_json_schema
 expected = json.loads(_INPUT_SCHEMA_FIXTURE.read_text(encoding="utf-8"))
 assert actual == expected, (
 "SearchRepositoryCodeInput.model_json_schema drifted from fixture baseline. "
 f"{_REGENERATE_HINT}"
 )
