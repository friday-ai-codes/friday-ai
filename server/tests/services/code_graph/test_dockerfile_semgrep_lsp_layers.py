"""Dockerfile Semgrep / LSP 运行时层验收桩（D-01/D-11；归属 127-02）。

Wave 0：节点名可收集；实现由 127-02 去 skip。
"""

from __future__ import annotations

import pytest

_SKIP = pytest.mark.skip(reason="Wave 0 桩：由 127-02 落地")


@_SKIP
def test_dockerfile_installs_semgrep_outside_server_venv() -> None:
    """含 /opt/semgrep 或等价独立 install；无 pyproject/uv.lock 装 semgrep。

    （Req: TAINT-01 / LSP-01, 决策: D-01）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_dockerfile_installs_node_go_volar_gopls() -> None:
    """Node/gopls/@vue/language-server 字面量或安装指令。

    （Req: LSP-01, 决策: D-11）
    """
    pytest.fail("Wave 0 桩")
