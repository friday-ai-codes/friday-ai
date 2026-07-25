"""INV-6 旁路写表 grep 守护（Phase 79）：``Artifact`` / ``ArtifactType`` 落库只经
``initiatives.services.ArtifactService``。

镜像 ``test_project_inv6_guard`` 范式：纯本地源码扫描，无 DB / 网络。扫描 ``server/`` 源码
（排除 tests/ / migrations/ / initiatives/models/ 与 service 自身），断言无旁路写表入口；
命中即 fail 并列出文件:行。
"""

from __future__ import annotations

import re
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2]

_PRUNE_DIRS = {
    ".venv",
    "node_modules",
    "staticfiles",
    "__pycache__",
    ".git",
    "htmlcov",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}

_ALLOWED_WRITER = "initiatives/services/artifact_service.py"

# 同名异物豁免（Chassis v2）：``delivery.models.Artifact``（db_table ``delivery_artifact``，
# 交付物脊柱）与本守护关心的 ``initiatives.models.Artifact``（工件实例）是**两个完全不同
# 的聚合根**，只是恰好同名。本守护按裸名 grep，区分不了 app，故按模块豁免 delivery 侧的
# 模型定义与其自己的单一 writer；豁免面仅这两个文件，其余任何模块旁路写
# ``Artifact``/``ArtifactType`` 仍判违规（守护强度不变）。
_SIBLING_APP_MODULES = frozenset(
    {
        "delivery/models/artifact.py",
        "delivery/services/artifact_service.py",
    }
)

_MODELS = ("Artifact", "ArtifactType")
_RE_ORM_WRITE = {
    m: re.compile(
        rf"\b{m}\.objects\.(?:create|bulk_create|get_or_create|update_or_create)\b"
    )
    for m in _MODELS
}
# 直接实例化 Model(...)（紧跟 "(" 排除 ArtifactType( 误伤 Artifact、Serializer 等更长符号）
_RE_INSTANTIATE = {m: re.compile(rf"\b{m}\s*\(") for m in _MODELS}


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for path in SERVER_DIR.rglob("*.py"):
        if any(part in _PRUNE_DIRS for part in path.relative_to(SERVER_DIR).parts):
            continue
        files.append(path)
    return files


def _is_scanned(rel: str) -> bool:
    if rel == _ALLOWED_WRITER or rel in _SIBLING_APP_MODULES:
        return False
    if rel.startswith("tests/") or "/tests/" in rel:
        return False
    if "/migrations/" in rel:
        return False
    if rel.startswith("initiatives/models/"):
        return False
    return True


def test_inv6_no_bypass_artifact_write() -> None:
    """INV-6：除 ArtifactService 外，server 源码无旁路 Artifact/ArtifactType 写表入口。"""
    violations: list[str] = []
    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("class Artifact"):
                continue
            for m in _MODELS:
                # ArtifactType 命中时跳过 Artifact 的 instantiate 误报（ArtifactType( 不应记为 Artifact()）
                if m == "Artifact" and _RE_INSTANTIATE["ArtifactType"].search(line):
                    continue
                if _RE_ORM_WRITE[m].search(line) or _RE_INSTANTIATE[m].search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")
                    break

    assert not violations, (
        "INV-6 违反：发现旁路 Artifact/ArtifactType 写表"
        f"（落库只允许经 ArtifactService / {_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


def test_sibling_app_exemption_cannot_smuggle_initiatives_writes() -> None:
    """豁免安全性：被豁免的 delivery 模块确实只碰自己 app 的同名模型。

    只要它们不引用 ``initiatives`` 的 Artifact，就不可能借豁免旁路写本守护关心的
    模型——否则 ``_SIBLING_APP_MODULES`` 会退化成真正的漏洞。
    """
    for rel in sorted(_SIBLING_APP_MODULES):
        path = SERVER_DIR / rel
        assert path.exists(), f"{rel} 不存在（豁免项已失效，应清理）"
        text = path.read_text(encoding="utf-8")
        assert "initiatives" not in text, (
            f"{rel} 引用了 initiatives，豁免不再安全——请收紧 _SIBLING_APP_MODULES"
        )


def test_inv6_writer_module_actually_writes() -> None:
    """守护有效性：唯一 writer 确实含工件写表，防守护形同虚设。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert "Artifact.objects.create" in text and "ArtifactType.objects.create" in text, (
        "ArtifactService 应是唯一工件写表点，但未检出 Artifact/ArtifactType .objects.create"
    )
