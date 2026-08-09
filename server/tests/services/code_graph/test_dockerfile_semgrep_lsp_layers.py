"""Dockerfile Semgrep / LSP 运行时层验收（D-01/D-11；归属 127-02）。"""

from __future__ import annotations

from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parents[3]
_DOCKERFILE = _SERVER_ROOT / "Dockerfile"
_PYPROJECT = _SERVER_ROOT / "pyproject.toml"
_UV_LOCK = _SERVER_ROOT / "uv.lock"


def _dockerfile_text() -> str:
    return _DOCKERFILE.read_text(encoding="utf-8")


def _line_of(text: str, needle: str) -> int:
    for i, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return i
    raise AssertionError(f"needle not found in Dockerfile: {needle!r}")


def _user_friday_directive_line(text: str) -> int:
    """真正的 ``USER friday`` 指令行（忽略注释里的同名字面量）。"""
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped == "USER friday" or stripped.startswith("USER friday "):
            return i
    raise AssertionError("USER friday directive not found in Dockerfile")


def test_dockerfile_installs_semgrep_outside_server_venv() -> None:
    """含 /opt/semgrep 独立 install；无 pyproject/uv.lock 装 semgrep。

    （Req: TAINT-01 / LSP-01, 决策: D-01）
    """
    text = _dockerfile_text()
    assert "semgrep==1.172" in text or "semgrep==1.172.0" in text
    assert "/opt/semgrep" in text
    assert "SEMGREP_BIN" in text

    user_line = _user_friday_directive_line(text)
    semgrep_line = _line_of(text, "semgrep==1.172")
    assert semgrep_line < user_line

    pyproject = _PYPROJECT.read_text(encoding="utf-8")
    assert "semgrep" not in pyproject.lower()
    if _UV_LOCK.is_file():
        # 允许无关历史字面量极小概率命中；硬约束是依赖声明不引入 semgrep 包
        for line in _UV_LOCK.read_text(encoding="utf-8").splitlines():
            if line.startswith("name = ") and "semgrep" in line.lower():
                raise AssertionError(f"semgrep must not appear in uv.lock: {line}")


def test_dockerfile_installs_node_go_volar_gopls() -> None:
    """Node/gopls/@vue/language-server 字面量或安装指令早于 USER friday。

    （Req: LSP-01, 决策: D-11）
    """
    text = _dockerfile_text()
    user_line = _user_friday_directive_line(text)
    for needle in (
        "@vue/language-server@",
        "typescript@",
        "gopls@v0.23",
        "ARG NODE_VERSION=",
        "ARG GO_VERSION=",
    ):
        assert needle in text, f"missing {needle!r}"
        assert _line_of(text, needle) < user_line
