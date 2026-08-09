"""``services/code_graph/model.py`` 的契约用例（覆盖 GRAPH-01）。

由 **Plan 121-02** 填充：四档置信度枚举（resolved / bare_name / cross_repo /
chunk_level）与数值映射，以及 ``reason`` 字符串「输出时现推、不进边属性」的
D-08 决策。

本文件刻意**不 import networkx**：``model.py`` 的 adapter seam（运行期零 networkx）
是本相位的架构约束之一，用例自身把它当黑盒校验（见
``test_model_module_never_imports_networkx_at_runtime``）。
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest

from services.code_graph import model
from services.code_graph.model import (
    BARE_NAME_BLACKLIST,
    LOW_RESOLUTION_THRESHOLD,
    REDACTED_REPOSITORY,
    EdgeConfidence,
    EdgeKind,
    confidence_score,
    derive_reason,
)


# 121-VALIDATION.md：四档置信度枚举与数值映射（resolved=1.0 / bare_name=0.3 /
# cross_repo=match_confidence 原值 / chunk_level 默认关）。
def test_edge_confidence_values() -> None:
    """四档恰好四个成员，取值与数值映射均为契约的一部分。"""
    assert [c.value for c in EdgeConfidence] == [
        "resolved",
        "bare_name",
        "cross_repo",
        "chunk_level",
    ]
    assert len(EdgeConfidence) == 4

    assert confidence_score(EdgeConfidence.RESOLVED) == 1.0
    assert confidence_score(EdgeConfidence.BARE_NAME) == 0.3
    # chunk_level 与 bare_name 是语义等价的弱证据档，共用同一数值。
    assert confidence_score(EdgeConfidence.CHUNK_LEVEL) == 0.3
    # cross_repo 取 CrossRepoApiCall 的原值，不归一化。
    assert confidence_score(EdgeConfidence.CROSS_REPO, match_confidence=0.7) == 0.7
    assert confidence_score(EdgeConfidence.CROSS_REPO, match_confidence=0.4) == 0.4

    # 缺 match_confidence 时必须抛错，不得静默兜底成常量。
    with pytest.raises(ValueError, match="match_confidence"):
        confidence_score(EdgeConfidence.CROSS_REPO)


# 121-VALIDATION.md：`reason` 现推不存（D-08）——边属性维持 3 个以内，
# reason 不得出现在 MultiDiGraph 的边属性字典里。
def test_reason_not_stored_on_edge_attrs() -> None:
    """``reason`` 只能由 :func:`derive_reason` 现推，不得成为任何契约字段。"""
    assert inspect.isfunction(derive_reason)

    # 契约层的任何值对象都不得带 reason 字段——一旦有，loader 会顺手把它
    # 写成第 4 个边属性（30 万边约 +6.9MB，D-08 明确禁止）。
    for _name, obj in vars(model).items():
        if dataclasses.is_dataclass(obj) and isinstance(obj, type):
            assert "reason" not in {f.name for f in dataclasses.fields(obj)}

    # 纪律必须有代码内留痕，供后续相位 review 时引用。
    doc = derive_reason.__doc__ or ""
    assert "D-08" in doc
    assert "第 4 个边属性" in doc


def test_edge_kind_values() -> None:
    """边种类三值，与置信度档位正交。"""
    assert [k.value for k in EdgeKind] == ["call", "chunk", "cross_repo"]


def test_derive_reason_is_distinct_per_tier() -> None:
    """四档各自产出非空且互不相同的理由串。"""
    reasons = [
        derive_reason(EdgeKind.CALL, EdgeConfidence.RESOLVED),
        derive_reason(EdgeKind.CALL, EdgeConfidence.BARE_NAME, callee_name="handle"),
        derive_reason(EdgeKind.CROSS_REPO, EdgeConfidence.CROSS_REPO, match_confidence=0.7),
        derive_reason(EdgeKind.CHUNK, EdgeConfidence.CHUNK_LEVEL),
    ]
    assert all(reasons)
    assert len(set(reasons)) == 4

    assert "handle" in reasons[1]
    # match_confidence 以原值出现在文案里（0.7 不能被渲染成 0.700000）。
    assert "0.7" in reasons[2]


def test_model_module_never_imports_networkx_at_runtime() -> None:
    """``model.py`` 的 networkx import 必须全部落在 ``if TYPE_CHECKING:`` 块内。

    这是「未来换 rustworkx」的 adapter seam：上层只 import 契约类型就能写出
    impact / trace 的输出结构，不必把 networkx 变成它们的必需依赖。

    不断言 ``"networkx" not in sys.modules``——测试进程里 llama-index 等上游
    随时可能已经把它载入，那个断言会变成环境噪声。改为对源码做结构化断言，
    并核对模块命名空间里没有 ``nx``。
    """
    source_path = Path(model.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    type_checking_ranges = [
        (node.lineno, max(child.end_lineno or child.lineno for child in node.body))
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "TYPE_CHECKING"
    ]

    networkx_import_lines = [
        node.lineno
        for node in ast.walk(tree)
        if (isinstance(node, ast.Import) and any(a.name.split(".")[0] == "networkx" for a in node.names))
        or (isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "networkx")
    ]

    for lineno in networkx_import_lines:
        assert any(start <= lineno <= end for start, end in type_checking_ranges), (
            f"model.py:{lineno} 在运行期 import networkx，破坏 adapter seam"
        )

    # 运行期命名空间里不该出现 networkx 别名。
    assert "nx" not in vars(model)
    assert "networkx" not in vars(model)


def test_bare_name_blacklist_is_frozenset() -> None:
    """黑名单以不可变模块常量落地，覆盖 CONTEXT Area 3 点名的全部常见名。"""
    assert isinstance(BARE_NAME_BLACKLIST, frozenset)
    assert len(BARE_NAME_BLACKLIST) >= 17
    assert {"get", "set", "run", "handle", "main", "String", "Error"} <= BARE_NAME_BLACKLIST


def test_thresholds_and_redaction_literal() -> None:
    """阈值与折叠占位符是跨相位共享的字面量，改动会波及 Phase 122 输出文案。"""
    assert LOW_RESOLUTION_THRESHOLD == 0.6
    # 121-09 的 barrel 会导出它；这里先钉死字面量，避免缺失要到两个 wave
    # 之后才在 __all__ 长度校验上暴雷。
    assert REDACTED_REPOSITORY == "redacted_repository"
