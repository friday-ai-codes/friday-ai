"""`code_relations.constants` 暴露 initial implementation / initial implementation 编排器共享常量。

覆盖 assertion：

initial implementation（既有）：
- MAX_HOPS == 2 / TOP_NEIGHBORS_PER_HOP1 == 10 / TOP_NEIGHBORS_PER_HOP2 == 50 字面值
- 类型均为 `int`
- 三常量均**不通过 `env.*` 读取**（runtime 不允许通过环境变量绕开 hops 上限或邻居裁剪量）

initial implementation plan（新增）：
- CO_CHANGED_WINDOW_COMMITS == 2000（per contract，CoChangedEdgeBuilder 滑窗）
- SEMANTIC_SCORE_THRESHOLD == 0.85（per initial implementation success criterion，SemanticEdgeBuilder Qdrant 阈值）
- 类型分别为 int / float 且非 bool
- 既有常量 MAX_NEIGHBORS_PER_CHUNK == 20 / MAX_HOPS == 2 回归保护
"""

from __future__ import annotations

import re
from pathlib import Path

from code_relations import constants


def test_max_hops_literal_value() -> None:
    assert constants.MAX_HOPS == 2
    assert isinstance(constants.MAX_HOPS, int)


def test_top_neighbors_per_hop1_literal_value() -> None:
    assert constants.TOP_NEIGHBORS_PER_HOP1 == 10
    assert isinstance(constants.TOP_NEIGHBORS_PER_HOP1, int)


def test_top_neighbors_per_hop2_literal_value() -> None:
    assert constants.TOP_NEIGHBORS_PER_HOP2 == 50
    assert isinstance(constants.TOP_NEIGHBORS_PER_HOP2, int)


def test_constants_not_env_derived() -> None:
    """硬约束：3 个常量不允许从 env / os.environ 读取（否则 hops 守卫可被绕过）。

    实现方式：扫描 `constants.py` 源码，断言 MAX_HOPS / TOP_NEIGHBORS_PER_HOP1 /
    TOP_NEIGHBORS_PER_HOP2 三行 RHS 是纯字面整数赋值，不出现 `env`/`os.environ`。
    """
    source = Path(constants.__file__).read_text(encoding="utf-8")
    for name, expected in (
        ("MAX_HOPS", 2),
        ("TOP_NEIGHBORS_PER_HOP1", 10),
        ("TOP_NEIGHBORS_PER_HOP2", 50),
    ):
        match = re.search(
            rf"^{name}\s*:\s*int\s*=\s*(.+?)$",
            source,
            re.MULTILINE,
        )
        assert match is not None, f"{name} 必须以 `NAME: int = LITERAL` 形式赋值"
        rhs = match.group(1).strip()
        assert rhs == str(expected), (
            f"{name} 赋值必须为字面值 {expected}（实际 `{rhs}`）；"
            "禁止通过 env / os.environ 读取"
        )
    assert "env(" not in source.split("MAX_HOPS", 1)[1][:500], (
        "MAX_HOPS 周边代码段不允许出现 env(...) 调用"
    )


# ---------------------------------------------------------------------------
# initial implementation plan：新增 CO_CHANGED_WINDOW_COMMITS / SEMANTIC_SCORE_THRESHOLD
# ---------------------------------------------------------------------------


def test_co_changed_window_commits_literal_value() -> None:
    """``CO_CHANGED_WINDOW_COMMITS`` 字面值锁定 == 2000（per initial implementation contract）。"""
    from code_relations.constants import CO_CHANGED_WINDOW_COMMITS

    assert CO_CHANGED_WINDOW_COMMITS == 2000
    assert isinstance(CO_CHANGED_WINDOW_COMMITS, int)
    assert not isinstance(CO_CHANGED_WINDOW_COMMITS, bool)


def test_semantic_score_threshold_literal_value() -> None:
    """``SEMANTIC_SCORE_THRESHOLD`` 字面值锁定 == 0.85（per initial implementation success criterion 防漂移）。"""
    from code_relations.constants import SEMANTIC_SCORE_THRESHOLD

    assert SEMANTIC_SCORE_THRESHOLD == 0.85
    assert isinstance(SEMANTIC_SCORE_THRESHOLD, float)
    assert not isinstance(SEMANTIC_SCORE_THRESHOLD, bool)


def test_phase_256_constants_not_env_derived() -> None:
    """硬约束：CO_CHANGED_WINDOW_COMMITS / SEMANTIC_SCORE_THRESHOLD 不允许 env 读取。

    与 initial implementation 三常量同款防御：扫描源码，断言 RHS 是纯字面赋值，
    禁止通过 env / os.environ 绕过滑窗 / 阈值上限。
    """
    source = Path(constants.__file__).read_text(encoding="utf-8")
    for name, expected, type_hint in (
        ("CO_CHANGED_WINDOW_COMMITS", "2000", "int"),
        ("SEMANTIC_SCORE_THRESHOLD", "0.85", "float"),
    ):
        match = re.search(
            rf"^{name}\s*:\s*{type_hint}\s*=\s*(.+?)$",
            source,
            re.MULTILINE,
        )
        assert match is not None, (
            f"{name} 必须以 `NAME: {type_hint} = LITERAL` 形式赋值"
        )
        rhs = match.group(1).strip()
        assert rhs == expected, (
            f"{name} 赋值必须为字面值 {expected}（实际 `{rhs}`）；"
            "禁止通过 env / os.environ 读取"
        )


def test_existing_constants_unchanged_regression_guard() -> None:
    """既有常量 MAX_NEIGHBORS_PER_CHUNK / MAX_HOPS 未被改动（initial implementation 回归保护）。

    initial implementation plan ``<action>`` 明确"不修改既有常量"——本测试在新增常量
    PR 引入意外副作用时锁定既有值。
    """
    assert constants.MAX_NEIGHBORS_PER_CHUNK == 20
    assert constants.MAX_HOPS == 2
