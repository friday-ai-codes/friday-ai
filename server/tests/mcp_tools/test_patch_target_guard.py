"""stale patch target 守卫测试（Phase 104 UNIFY-03，T-104-06 mitigate）。

删缝/随迁后测试假通过的防线：对本次迁移影响面（+ Phase 26 前科面 test_batch_pr.py）的
测试文件，用正则提取 ``monkeypatch.setattr("X.Y.Z", ...)`` 与 ``mock.patch("X.Y.Z")`` /
``patch("X.Y.Z")`` 的 dotted-path 字符串 target，逐个执行「``importlib.import_module``
最长可导入前缀 + 剩余段逐级 ``getattr``」——任一解析失败即 fail 并报出 target 与所在文件。

空集防御：断言至少提取到 N>0 个 target（防正则失配导致空集假通过）。
pytest-django 环境已 django.setup，import 应用模块安全。
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

_TESTS_ROOT = Path(__file__).resolve().parent.parent

# 覆盖清单：本次迁移影响面 + Phase 26 前科面（test_batch_pr.py 位于 tests/ 根目录）。
_GUARDED_FILES = [
    _TESTS_ROOT / "mcp_tools" / "test_planning_tools.py",
    _TESTS_ROOT / "mcp_tools" / "test_create_coding_plan_delegate.py",
    _TESTS_ROOT / "knowledge" / "test_mcp_artifact_sources.py",
    _TESTS_ROOT / "services" / "test_process_runtime_extra_evidence.py",
    _TESTS_ROOT / "test_batch_pr.py",
]

# 提取首个 dotted-path 字符串字面量参数：monkeypatch.setattr("X.Y.Z", ...) /
# mock.patch("X.Y.Z") / 裸 patch("X.Y.Z")（patch.object 的对象形式天然不匹配）。
_TARGET_PATTERN = re.compile(
    r"""(?:monkeypatch\.setattr|mock\.patch|(?<![\w.])patch)\(\s*["']([A-Za-z_][\w.]*\.\w+)["']"""
)


def _extract_targets(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    return _TARGET_PATTERN.findall(source)


def _resolve(target: str) -> None:
    """最长可导入前缀 import + 剩余段逐级 getattr；失败抛出带上下文的 AssertionError。"""
    parts = target.split(".")
    module = None
    consumed = 0
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        try:
            module = importlib.import_module(candidate)
            consumed = i
            break
        except ImportError:
            continue
    assert module is not None, f"无可导入前缀：{target}"
    obj = module
    for attr in parts[consumed:]:
        assert hasattr(obj, attr), f"段解析失败：{target}（{obj!r} 无属性 {attr}）"
        obj = getattr(obj, attr)


def test_guarded_files_exist() -> None:
    """覆盖清单文件必须都在（防文件改名后守卫静默缩水）。"""
    missing = [str(p) for p in _GUARDED_FILES if not p.is_file()]
    assert not missing, f"守卫覆盖文件缺失：{missing}"


def test_all_patch_targets_importable() -> None:
    """全部 patch target 字符串可 import（stale target 零容忍）。"""
    all_targets: list[tuple[str, str]] = []
    for path in _GUARDED_FILES:
        for target in _extract_targets(path):
            all_targets.append((str(path.relative_to(_TESTS_ROOT)), target))

    # 空集防御：正则失配导致空集即假通过——至少要提取到一个 target。
    assert all_targets, "未提取到任何 patch target（正则失配或覆盖文件为空）"

    failures: list[str] = []
    for file_name, target in all_targets:
        try:
            _resolve(target)
        except AssertionError as exc:
            failures.append(f"{file_name}: {target} → {exc}")
        except Exception as exc:  # noqa: BLE001 — import 副作用异常同样视为解析失败
            failures.append(f"{file_name}: {target} → {type(exc).__name__}: {exc}")

    assert not failures, "stale patch target 检出：\n" + "\n".join(failures)


@pytest.mark.parametrize(
    "target",
    [
        "mcp_tools.views.delegate_process_runtime",
        "services.process_runtime.start_orchestration",
    ],
)
def test_known_migration_targets_resolve(target: str) -> None:
    """本次迁移的关键 patch 路径显式钉住（正则之外的直接断言）。"""
    _resolve(target)
