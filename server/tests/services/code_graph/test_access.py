"""``services/code_graph/access.py`` 的 fail-closed 收口用例（覆盖 GRAPH-04）。

本文件目前只有用例桩，由 **Plan 121-03**（可读性闸门、matcher fail-closed、
指纹 memo、观测契约守护）、**Plan 121-05**（exclusion 过滤节点连带邻接边）与
**Plan 121-09**（barrel 导出红线）填充。

桩的存在是 Wave 0 的 Nyquist 要求：121-VALIDATION.md 里每个 ``-k`` 选择器都必须
从第一个 task 起就能解析到真实用例名。
"""

from __future__ import annotations

import pytest


# 121-VALIDATION.md 121-05-T2：命中 exclusion 的符号不在节点集，
# 其邻接边一并消失（装配阶段过滤，不是输出阶段过滤）。
@pytest.mark.skip(reason="stub：由 Plan 121-05 实现")
def test_exclusion_hides_symbols_and_edges() -> None:
    pass


# 121-VALIDATION.md 121-03-T2：matcher 构造失败 ⇒ 抛 GraphAccessDenied，
# 不返回未过滤的图（出口是 raise，不是空列表）。
@pytest.mark.skip(reason="stub：由 Plan 121-03 实现")
def test_fail_closed_on_matcher_build_error() -> None:
    pass


# 121-VALIDATION.md 121-03-T1：index_status != INDEXED ⇒ 显式抛错，
# 不返回空图（空图会被上层误读为「没有影响」）。
@pytest.mark.skip(reason="stub：由 Plan 121-03 实现")
def test_not_indexed_raises() -> None:
    pass


# 121-VALIDATION.md 121-03-T1：is_deleted=True 的仓库 ⇒ 拒绝。
@pytest.mark.skip(reason="stub：由 Plan 121-03 实现")
def test_deleted_repo_denied() -> None:
    pass


# 121-VALIDATION.md 121-03-T3（planner 追加行）：观测契约守护——包内每个 structlog
# 调用都带 component="code_graph" + category="sampling" + code_graph_ 事件名前缀。
@pytest.mark.skip(reason="stub：由 Plan 121-03 实现")
def test_observability_contract() -> None:
    pass


# 121-VALIDATION.md 121-03-T2（planner 追加行）：matcher/指纹 60s TTL memo——
# 连算两次只解析一次；invalidate 后重新解析；构造失败不写 memo。
@pytest.mark.skip(reason="stub：由 Plan 121-03 实现")
def test_matcher_fingerprint_memo_ttl() -> None:
    pass


# 121-VALIDATION.md 121-09-T1（planner 追加行）：barrel 恰导出 17 项
# （含 invalidate_repository），loader/cache/signature/access 不可从包顶层取得。
@pytest.mark.skip(reason="stub：由 Plan 121-09 实现")
def test_barrel_exports_are_curated() -> None:
    pass
