"""Agent tool contract snapshot tests —— per implementation contract / contract。

锁住两条契约：

1. ``inspect.signature(search_repository_code)``（unwrap @tool decorator 后）
   序列化为 dict，与 ``fixtures/search_repository_code_signature.json`` 字节级
   diff —— 函数签名漂移立即抓出。
2. ``SearchRepositoryCodeInput.model_json_schema()`` 与
   ``fixtures/search_repository_code_input_schema.json`` 字节级 diff —— Pydantic
   字段命名 / 类型 / 默认值 / 约束漂移立即抓出。

Fixture 更新流程（**显式动作**）::

    cd server && DJANGO_SETTINGS_MODULE=friday.settings \\
        uv run python -m tests.agents._generate_contract_fixtures
    git diff tests/agents/fixtures/  # review
    git add tests/agents/fixtures/*.json && git commit

implementation 灰度切换函数签名时，本测试会先红再 baseline → review → commit，
让契约升级 ＝ 一次显式提交。

参见：
- contract / contract：Pydantic 字段冻结表
- contract：双 snapshot 测试要求
- contract：agent tool schema 包路径锁
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).parent / "fixtures"
_SIGNATURE_FIXTURE = FIXTURE_DIR / "search_repository_code_signature.json"
_INPUT_SCHEMA_FIXTURE = FIXTURE_DIR / "search_repository_code_input_schema.json"
_FIND_RELATED_SIGNATURE_FIXTURE = FIXTURE_DIR / "find_related_code_signature.json"
_FIND_RELATED_INPUT_SCHEMA_FIXTURE = (
    FIXTURE_DIR / "find_related_code_input_schema.json"
)
_FIND_RELATED_OUTPUT_SCHEMA_FIXTURE = (
    FIXTURE_DIR / "find_related_code_output_schema.json"
)

# API MCP tools snapshot fixtures
_FIND_API_HANDLER_SIGNATURE_FIXTURE = FIXTURE_DIR / "find_api_handler_signature.json"
_FIND_API_HANDLER_INPUT_SCHEMA_FIXTURE = FIXTURE_DIR / "find_api_handler_input_schema.json"
_FIND_API_CALLERS_SIGNATURE_FIXTURE = FIXTURE_DIR / "find_api_callers_signature.json"
_FIND_API_CALLERS_INPUT_SCHEMA_FIXTURE = FIXTURE_DIR / "find_api_callers_input_schema.json"
_LIST_ENDPOINTS_SIGNATURE_FIXTURE = FIXTURE_DIR / "list_endpoints_signature.json"
_LIST_ENDPOINTS_INPUT_SCHEMA_FIXTURE = FIXTURE_DIR / "list_endpoints_input_schema.json"

# chat @tool 创作入参漂移守护（Phase 109 / SPINE-02）
_CREATE_CODING_PLAN_SIGNATURE_FIXTURE = FIXTURE_DIR / "create_coding_plan_signature.json"
_UPDATE_CODING_PLAN_SIGNATURE_FIXTURE = FIXTURE_DIR / "update_coding_plan_signature.json"

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
        for name, p in sig.parameters.items()
    }


def test_search_repository_code_signature_snapshot() -> None:
    """``search_repository_code`` 函数签名 vs fixture 字节级 diff。

    @tool decorator 用 ``functools.wraps``，所以 ``inspect.unwrap`` 能拿回原始
    函数；fixture 锁的是 *当前* 函数签名（含 ``repository_id`` / ``limit`` /
    ``min_score`` 等遗留字段），implementation 切到 contract 新签名时此测试会失败 →
    届时刷新 fixture 即视作契约升级动作。
    """
    from agents.tools.space_tools import search_repository_code

    actual = _normalize_signature(search_repository_code)
    expected = json.loads(_SIGNATURE_FIXTURE.read_text(encoding="utf-8"))

    assert actual == expected, (
        "search_repository_code signature drifted from fixture baseline. "
        f"{_REGENERATE_HINT}"
    )


def test_search_repository_code_input_schema_snapshot() -> None:
    """``SearchRepositoryCodeInput.model_json_schema()`` vs fixture 字节级 diff。

    Pydantic v2 ``model_json_schema`` 输出 stable（字段顺序由模型决定，
    fixture 用 sort_keys 标准化）；任何字段命名 / 类型 / description / 约束
    （min_length / ge / le / default）的变更都会触发 diff。
    """
    from agents.tools.schemas import SearchRepositoryCodeInput

    actual = SearchRepositoryCodeInput.model_json_schema()
    expected = json.loads(_INPUT_SCHEMA_FIXTURE.read_text(encoding="utf-8"))

    assert actual == expected, (
        "SearchRepositoryCodeInput.model_json_schema drifted from fixture baseline. "
        f"{_REGENERATE_HINT}"
    )


def test_find_related_code_signature_snapshot() -> None:
    """``find_related_code`` 函数签名 vs fixture 字节级 diff —— per implementation 03。

    与 ``test_search_repository_code_signature_snapshot`` 同模式：``inspect.unwrap``
    剥 @tool wrapper 后比对原始函数 ``async def find_related_code(...)`` 的参数表。
    @tool decorator 的 ``description`` 参数**不在 inspect.signature 范围**——本快照
    与 description 字面演化解耦。
    """
    from agents.tools.find_related_code import find_related_code

    actual = _normalize_signature(find_related_code)
    expected = json.loads(
        _FIND_RELATED_SIGNATURE_FIXTURE.read_text(encoding="utf-8")
    )

    assert actual == expected, (
        "find_related_code signature drifted from fixture baseline. "
        f"{_REGENERATE_HINT}"
    )


def test_find_related_code_input_schema_snapshot() -> None:
    """``FindRelatedCodeInput.model_json_schema()`` vs fixture 字节级 diff。

    锁三选一互斥起点 + relation_types Literal 6 类 + hops/limit 范围约束 +
    direction Literal 三值；任何字段命名 / 类型 / 默认值 / description 漂移立即抓出。
    """
    from agents.tools.schemas import FindRelatedCodeInput

    actual = FindRelatedCodeInput.model_json_schema()
    expected = json.loads(
        _FIND_RELATED_INPUT_SCHEMA_FIXTURE.read_text(encoding="utf-8")
    )

    assert actual == expected, (
        "FindRelatedCodeInput.model_json_schema drifted from fixture baseline. "
        f"{_REGENERATE_HINT}"
    )


def test_find_related_code_output_schema_snapshot() -> None:
    """``FindRelatedCodeOutput.model_json_schema()`` vs fixture 字节级 diff。

    锁 ``neighbors: list[NeighborOutput]`` + ``message: str``；NeighborOutput 字段
    顺序与 ``services.retrieval.types.NeighborMetadata`` dataclass 一致 + ``reason``
    ``min_length=1`` 守门——任何字段名漂移会破坏 plan ``NeighborOutput(**asdict(n))``
    单步装配。
    """
    from agents.tools.schemas import FindRelatedCodeOutput

    actual = FindRelatedCodeOutput.model_json_schema()
    expected = json.loads(
        _FIND_RELATED_OUTPUT_SCHEMA_FIXTURE.read_text(encoding="utf-8")
    )

    assert actual == expected, (
        "FindRelatedCodeOutput.model_json_schema drifted from fixture baseline. "
        f"{_REGENERATE_HINT}"
    )


# ---------------------------------------------------------------------------
# API MCP tool snapshot tests (work item / work item / work item)
# ---------------------------------------------------------------------------


def test_find_api_handler_signature_snapshot() -> None:
    """``find_api_handler`` 函数签名 vs fixture 字节级 diff —— per implementation。"""
    from agents.tools.find_api_handler import find_api_handler

    actual = _normalize_signature(find_api_handler)
    expected = json.loads(_FIND_API_HANDLER_SIGNATURE_FIXTURE.read_text(encoding="utf-8"))

    assert actual == expected, (
        "find_api_handler signature drifted from fixture baseline. "
        f"{_REGENERATE_HINT}"
    )


def test_find_api_handler_input_schema_snapshot() -> None:
    """``FindApiHandlerInput.model_json_schema()`` vs fixture 字节级 diff。"""
    from agents.tools.schemas.api_tools import FindApiHandlerInput

    actual = FindApiHandlerInput.model_json_schema()
    expected = json.loads(_FIND_API_HANDLER_INPUT_SCHEMA_FIXTURE.read_text(encoding="utf-8"))

    assert actual == expected, (
        "FindApiHandlerInput.model_json_schema drifted from fixture baseline. "
        f"{_REGENERATE_HINT}"
    )


def test_find_api_callers_signature_snapshot() -> None:
    """``find_api_callers`` 函数签名 vs fixture 字节级 diff —— per implementation。"""
    from agents.tools.find_api_callers import find_api_callers

    actual = _normalize_signature(find_api_callers)
    expected = json.loads(_FIND_API_CALLERS_SIGNATURE_FIXTURE.read_text(encoding="utf-8"))

    assert actual == expected, (
        "find_api_callers signature drifted from fixture baseline. "
        f"{_REGENERATE_HINT}"
    )


def test_find_api_callers_input_schema_snapshot() -> None:
    """``FindApiCallersInput.model_json_schema()`` vs fixture 字节级 diff。"""
    from agents.tools.schemas.api_tools import FindApiCallersInput

    actual = FindApiCallersInput.model_json_schema()
    expected = json.loads(_FIND_API_CALLERS_INPUT_SCHEMA_FIXTURE.read_text(encoding="utf-8"))

    assert actual == expected, (
        "FindApiCallersInput.model_json_schema drifted from fixture baseline. "
        f"{_REGENERATE_HINT}"
    )


def test_list_endpoints_signature_snapshot() -> None:
    """``list_endpoints`` 函数签名 vs fixture 字节级 diff —— per implementation。"""
    from agents.tools.list_endpoints import list_endpoints

    actual = _normalize_signature(list_endpoints)
    expected = json.loads(_LIST_ENDPOINTS_SIGNATURE_FIXTURE.read_text(encoding="utf-8"))

    assert actual == expected, (
        "list_endpoints signature drifted from fixture baseline. "
        f"{_REGENERATE_HINT}"
    )


def test_list_endpoints_input_schema_snapshot() -> None:
    """``ListEndpointsInput.model_json_schema()`` vs fixture 字节级 diff。"""
    from agents.tools.schemas.api_tools import ListEndpointsInput

    actual = ListEndpointsInput.model_json_schema()
    expected = json.loads(_LIST_ENDPOINTS_INPUT_SCHEMA_FIXTURE.read_text(encoding="utf-8"))

    assert actual == expected, (
        "ListEndpointsInput.model_json_schema drifted from fixture baseline. "
        f"{_REGENERATE_HINT}"
    )


# ---------------------------------------------------------------------------
# chat @tool 创作入参守护（SPINE-02：移除徒手创作路径）
# ---------------------------------------------------------------------------


def test_create_coding_plan_signature_snapshot() -> None:
    """``create_coding_plan`` 函数签名 vs fixture 字节级 diff。

    该工具此前**没有任何漂移守护**，而 SPINE-02 的核心验收是"结构上不可能徒手
    编写方案正文"——没有守护则后人把创作入参加回来无人发现。

    baseline 记录的是 **SPINE-02 收窄前的现状快照**（含 ``tech_plan`` /
    ``affected_files`` 两个创作入参）。收窄发生时本测试**应当变红**：届时按
    ``_REGENERATE_HINT`` 显式再生成 fixture + review diff 即视作一次契约升级，
    与本文件其余 snapshot 用例同一工作流（契约变更 ＝ 一次可 review 的提交）。
    """
    from agents.tools.coding_tools import create_coding_plan

    actual = _normalize_signature(create_coding_plan)
    expected = json.loads(
        _CREATE_CODING_PLAN_SIGNATURE_FIXTURE.read_text(encoding="utf-8")
    )

    assert actual == expected, (
        "create_coding_plan signature drifted from fixture baseline. "
        f"{_REGENERATE_HINT}"
    )


def test_update_coding_plan_signature_snapshot() -> None:
    """``update_coding_plan`` 函数签名 vs fixture 字节级 diff。

    ``update_coding_plan`` 的必填入参同样是 ``tech_plan`` + ``affected_files``，
    是同一个徒手创作漏洞的**第二个门**——只守 create 则模型可改走 update 写正文。
    因此两个门共用同一套漂移守护。

    与 ``test_create_coding_plan_signature_snapshot`` 同理：baseline 是收窄前的
    现状快照，收窄时应当变红并走显式再生成流程。
    """
    from agents.tools.coding_tools import update_coding_plan

    actual = _normalize_signature(update_coding_plan)
    expected = json.loads(
        _UPDATE_CODING_PLAN_SIGNATURE_FIXTURE.read_text(encoding="utf-8")
    )

    assert actual == expected, (
        "update_coding_plan signature drifted from fixture baseline. "
        f"{_REGENERATE_HINT}"
    )
