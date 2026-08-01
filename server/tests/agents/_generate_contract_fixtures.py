"""一次性 fixture 生成脚本 —— per implementation contract。

仅在以下两种场景手动运行：

1. 第一次落 baseline（本 phase plan task 2）。
2. agent tool 函数签名 / Pydantic schema 字段做了 *预期内* 的变更，需要刷新
   ``tests/agents/fixtures/*.json`` baseline（review diff → commit 才算契约升级）。

用法（必须从 ``server/`` 目录执行 + Django 已 setup）::

    cd server && DJANGO_SETTINGS_MODULE=friday.settings uv run python -m tests.agents._generate_contract_fixtures

文件名前缀 ``_`` 让 pytest 自动跳过收集（不会污染测试集）。

per contract + contract：fixture 是 contract baseline，drift 只能显式更新。
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import django

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _normalize_signature(fn: object) -> dict[str, dict[str, object]]:
    """``inspect.signature`` 序列化为字节稳定的 dict。

    与 ``test_tool_contracts.py`` 中 ``_normalize_signature`` 完全同实现，避免
    "生成器与断言器路径分叉"导致 fixture 与运行期不一致。
    """
    unwrapped = inspect.unwrap(fn)  # type: ignore[arg-type]
    sig = inspect.signature(unwrapped)
    return {
        name: {
            "kind": str(p.kind),
            "default": (
                repr(p.default) if p.default is not inspect.Parameter.empty else None
            ),
            "annotation": str(p.annotation),
        }
        for name, p in sig.parameters.items()
    }


def _dump(path: Path, payload: object) -> None:
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    print(f"[fixture] wrote {path.relative_to(Path.cwd())} ({len(text)} bytes)")


def main() -> None:
    django.setup()

    from agents.tools.coding_tools import create_coding_plan, update_coding_plan
    from agents.tools.find_api_callers import find_api_callers
    from agents.tools.find_api_handler import find_api_handler
    from agents.tools.find_related_code import find_related_code
    from agents.tools.list_endpoints import list_endpoints
    from agents.tools.schemas import (
        FindRelatedCodeInput,
        FindRelatedCodeOutput,
        SearchRepositoryCodeInput,
    )
    from agents.tools.schemas.api_tools import (
        FindApiCallersInput,
        FindApiHandlerInput,
        ListEndpointsInput,
    )
    from agents.tools.space_tools import search_repository_code

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    _dump(
        FIXTURE_DIR / "search_repository_code_signature.json",
        _normalize_signature(search_repository_code),
    )
    _dump(
        FIXTURE_DIR / "search_repository_code_input_schema.json",
        SearchRepositoryCodeInput.model_json_schema(),
    )
    _dump(
        FIXTURE_DIR / "find_related_code_signature.json",
        _normalize_signature(find_related_code),
    )
    _dump(
        FIXTURE_DIR / "find_related_code_input_schema.json",
        FindRelatedCodeInput.model_json_schema(),
    )
    _dump(
        FIXTURE_DIR / "find_related_code_output_schema.json",
        FindRelatedCodeOutput.model_json_schema(),
    )

    # API MCP tools (work item)
    _dump(
        FIXTURE_DIR / "find_api_handler_signature.json",
        _normalize_signature(find_api_handler),
    )
    _dump(
        FIXTURE_DIR / "find_api_handler_input_schema.json",
        FindApiHandlerInput.model_json_schema(),
    )
    _dump(
        FIXTURE_DIR / "find_api_callers_signature.json",
        _normalize_signature(find_api_callers),
    )
    _dump(
        FIXTURE_DIR / "find_api_callers_input_schema.json",
        FindApiCallersInput.model_json_schema(),
    )
    _dump(
        FIXTURE_DIR / "list_endpoints_signature.json",
        _normalize_signature(list_endpoints),
    )
    _dump(
        FIXTURE_DIR / "list_endpoints_input_schema.json",
        ListEndpointsInput.model_json_schema(),
    )

    # chat @tool 创作入参守护（Phase 109 / SPINE-02 收窄前 baseline）
    _dump(
        FIXTURE_DIR / "create_coding_plan_signature.json",
        _normalize_signature(create_coding_plan),
    )
    _dump(
        FIXTURE_DIR / "update_coding_plan_signature.json",
        _normalize_signature(update_coding_plan),
    )


if __name__ == "__main__":
    main()
