"""Phase 125 冻结面守卫 Wave 0 验收桩（MOD-04 / D-13）。

行为用例由 125-04 最终去 skip 填实：社区/摘要/signal 模块不得 import
``repo_router_v2``；生产路径不得改写 ``mcp/`` submodule。
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 0 桩：由 125-04 落地")
def test_phase_125_does_not_touch_repo_router_v2() -> None:
    """静态：社区/摘要/signal 模块不 import ``repo_router_v2``；可选 git diff 守卫。

    （Req: MOD-04, 决策: D-13）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-04 落地")
def test_phase_125_does_not_modify_mcp_submodule() -> None:
    """生产代码路径不引用 ``mcp/`` 包内相对改写（本相位只允许改 ``server/mcp_tools/views.py``）。

    （Req: MOD-04, 决策: D-13）
    """
    pytest.fail("Wave 0 桩")
