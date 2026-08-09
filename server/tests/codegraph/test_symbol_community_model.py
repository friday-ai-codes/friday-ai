"""``SymbolCommunity`` 模型 Wave 0 验收桩（MOD-01 / D-01 / D-02）。

行为用例由 125-02 去 skip 填实。
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 0 桩：由 125-02 落地")
def test_symbol_community_fields_and_unique_together() -> None:
    """``SymbolCommunity`` 字段齐全；``unique_together`` 覆盖仓库/分支/社区键。

    （Req: MOD-01, 决策: D-01）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-02 落地")
def test_symbol_has_no_community_fk_or_m2m() -> None:
    """``Symbol`` 模型无 community FK/M2M（社区侧软引用，不污染符号表）。

    （Req: MOD-01, 决策: D-02）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-02 落地")
def test_members_symbol_id_is_soft_string_not_fk() -> None:
    """``members`` JSON 内 ``symbol_id`` 为软字符串，非 ORM FK。

    （Req: MOD-01, 决策: D-02）
    """
    pytest.fail("Wave 0 桩")
