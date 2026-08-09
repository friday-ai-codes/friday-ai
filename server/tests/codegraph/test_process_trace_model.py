"""ProcessTrace 模型契约验收桩（EXEC-01 / D-01 / D-04）。

Wave 0：节点名已登记；实现由 126-02 去 skip。
"""

from __future__ import annotations

import pytest

_SKIP = pytest.mark.skip(reason="Wave 0 桩：由 126-02/03/04/05 落地")


@_SKIP
def test_process_trace_fields_and_unique_together() -> None:
    """ProcessTrace 字段最小集 + unique_together=(repository, branch_name, process_key)。

    （Req: EXEC-01, 决策: D-01）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_process_trace_has_no_endpoint_fk() -> None:
    """entry_endpoint 为 JSONField；无指向 Endpoint 的 ForeignKey。

    （Req: EXEC-01, 决策: D-01）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_process_trace_not_named_process() -> None:
    """codegraph.models 无名为 Process 的 ORM 类（避免与 process_runtime 撞名）。

    （Req: EXEC-01, 决策: D-01）
    """
    pytest.fail("Wave 0 桩")
