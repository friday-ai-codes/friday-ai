"""符号解析协议的用例（覆盖 D-19：uid 优先 + 重名返回候选列表）。

impact 与 trace **共用同一个解析器**，所以这条协议单独成文件而不是挂在任一内核旁边。
生产库符号重名率 **19.3%**（2,436 个名字对应 >20 个符号），候选列表是**主路径**而非异常
兜底——⛔ 绝不静默取第一个。

两条用例的数据库口径不同，刻意不给文件级 ``pytestmark``：``test_uid_takes_precedence``
是零 DB 的纯协议断言；``test_ambiguous_returns_candidates`` 要取 ``Symbol.signature``
（TextField，不在图节点属性里，只能回 ORM 补取），必须单独挂库标记。

Wave 0（Plan 122-01）只落骨架，用例由 122-02 / 122-05 填实。
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 0 桩：由 122-02 落地")
def test_uid_takes_precedence() -> None:
    """uid 优先：传 ``symbol_id`` 时不走候选路径。

    （Req: IMPACT-05, 决策: D-19）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.django_db
@pytest.mark.skip(reason="Wave 0 桩：由 122-05 落地")
def test_ambiguous_returns_candidates() -> None:
    """重名 → 候选列表（带 ``file:line``/``symbol_type``/``signature``），⛔ 绝不静默取第一个（D-19）。

    （Req: IMPACT-05, 决策: D-19）
    """
    pytest.fail("Wave 0 桩")
