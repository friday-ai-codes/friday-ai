r"""delivery Artifact 两模型旁路写表 INV-6 grep 守护。

纯本地源码扫描，无 DB / 网络（沿用 test_release_inv6_guard.py / test_document_inv6_guard.py
的精确锚定范式）。

补齐覆盖缺口：``tests/delivery/`` 下 architect_merge / document / release /
repo_coding_task / research / sdd_spec 六个聚合根都有 INV-6 守卫，唯独 Chassis v2
引入的 ``delivery.models.Artifact``（交付物脊柱）没有——当前实际无旁路写入，但缺守护
意味着以后加旁路不会被发现。

- **INV-6**：``Artifact`` / ``ArtifactVersion``（``db_table`` 分别为 ``delivery_artifact``
  / ``delivery_artifact_version``）落库只经 ``ArtifactService``
  （``delivery/services/artifact_service.py``）。
- **同名不同物**：``initiatives.models.Artifact`` 与本模型**同名但毫无关系**，各自有各自
  的单一 writer。正则只认符号名、认不出属主，故必须把 initiatives 侧的 model/writer
  模块排除，否则两侧守卫会互相误报。对称地，``tests/initiatives/test_artifact_inv6_guard.py``
  也排除了本 app 的对应模块。该豁免由 ``test_sibling_app_exemption_cannot_smuggle_delivery_writes``
  兜底：被豁免的 initiatives 模块不得引用 delivery，豁免因而不可能被用来夹带真实旁路。
"""

from __future__ import annotations

import re
from pathlib import Path

# server/ 根目录（tests/delivery/test_artifact_inv6_guard.py → parents[2]）
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

# 唯一允许写 delivery Artifact 两模型的模块（相对 server/）
_ALLOWED_WRITER = "delivery/services/artifact_service.py"

# 同名不同物的兄弟 app 模块：它们写的是 initiatives.models.Artifact，与本守卫无关。
_SIBLING_APP_MODULES = frozenset(
    {
        "initiatives/models/artifact.py",
        "initiatives/services/artifact_service.py",
    }
)

_MODELS = ("Artifact", "ArtifactVersion")

# A：<Model>.objects.<write>（锚定类本体；.filter/.get 读路径不命中）
# B：直接实例化 <Model>(...)（"\s*\(" 紧跟，天然排除 ArtifactStatus( / ArtifactSerializer( 等更长符号）
# C：链式实例化 + save
_PATTERNS: list[re.Pattern[str]] = []
for _model in _MODELS:
    _PATTERNS.append(
        re.compile(
            rf"\b{_model}\.objects\.(?:create|bulk_create|get_or_create|update_or_create)\b"
        )
    )
    _PATTERNS.append(re.compile(rf"\b{_model}\s*\("))
    _PATTERNS.append(re.compile(rf"\b{_model}\([^)]*\)\.save\("))


def _iter_py_files() -> list[Path]:
    """遍历 server/ 下 .py 文件（剪掉 venv/缓存/静态目录）。"""
    files: list[Path] = []
    for path in SERVER_DIR.rglob("*.py"):
        if any(part in _PRUNE_DIRS for part in path.relative_to(SERVER_DIR).parts):
            continue
        files.append(path)
    return files


def _is_scanned(rel: str) -> bool:
    """扫描范围：排除 writer 自身 / 兄弟 app 同名模型 / tests/ / migrations/ / delivery/models/。"""
    if rel == _ALLOWED_WRITER or rel in _SIBLING_APP_MODULES:
        return False
    if rel.startswith("tests/") or "/tests/" in rel:
        return False
    if "/migrations/" in rel:
        return False
    if rel.startswith("delivery/models/"):
        return False
    return True


def test_inv6_no_bypass_delivery_artifact_write() -> None:
    """INV-6：除 ArtifactService 外，server 源码无旁路 delivery Artifact 写表入口。"""
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            # 跳过模型/枚举定义行（class Artifact / class ArtifactVersion / class ArtifactStatus ...）
            if stripped.startswith("class Artifact"):
                continue
            if any(pattern.search(line) for pattern in _PATTERNS):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路 delivery Artifact 写表（落库只允许经 "
        f"ArtifactService / {_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


# 判定「是否 import 了 delivery app」：跨 app 写 delivery 的表，前提是先导入其模型。
# 只认导入语句，不认字符串/注释中出现的 "delivery" 字样（如 docstring 里提到 Qdrant
# 集合名 delivery_knowledge，与写表无关）。
_RE_DELIVERY_IMPORT = re.compile(r"^\s*(?:from\s+delivery[\w.]*\s+import\b|import\s+delivery\b)")


def test_sibling_app_exemption_cannot_smuggle_delivery_writes() -> None:
    """守卫的守卫：被豁免的 initiatives 模块不得导入 delivery，豁免不可用于夹带旁路。

    两个 app 的 Artifact 同名，豁免是按模块路径给的。若某天 initiatives 侧模块开始
    import delivery 的模型并在其中写表，本守卫会因豁免而看不见——此断言堵住该口子。
    """
    for rel in sorted(_SIBLING_APP_MODULES):
        path = SERVER_DIR / rel
        assert path.exists(), f"豁免清单里的 {rel} 不存在，请同步更新豁免"
        offenders = [
            f"{rel}:{lineno}: {line.strip()}"
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            )
            if _RE_DELIVERY_IMPORT.search(line)
        ]
        assert not offenders, (
            f"{rel} 被豁免于 delivery Artifact INV-6 扫描，却导入了 delivery——"
            "豁免可能被用来夹带真实旁路写入，请收紧豁免或改走 ArtifactService：\n"
            + "\n".join(offenders)
        )


def test_inv6_writer_module_actually_writes() -> None:
    """守护有效性：唯一允许的 writer 确实含写表（否则断言形同虚设）。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    for model in _MODELS:
        orm = re.compile(
            rf"\b{model}\.objects\.(?:create|bulk_create|get_or_create|update_or_create)\b"
        )
        inst = re.compile(rf"\b{model}\s*\(")
        assert orm.search(text) or inst.search(text), (
            f"ArtifactService 应是唯一 delivery Artifact 写表点，但未检出 {model} 写表"
        )
