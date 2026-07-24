"""workspace_discovery 单元测试（fixture mock_nx_monorepo + ≥ 10 测试）。

per implementation plan Task 3 acceptance：
- 三探针并集去重 + tsconfig.json 兜底过滤
- node_modules 子目录显式跳过
- Vue 2.6- 标记后仍纳入 list（防御 raise 在 VolarPool 入口）
- is_vue_27_or_newer parametrize 8 case
- structlog 事件字段断言
"""

from __future__ import annotations

from pathlib import Path

import pytest
from structlog.testing import capture_logs

from codegraph.lsp.workspace_discovery import (
    SubProject,
    discover_sub_projects,
    is_vue_27_or_newer,
)

_FIXTURE_ROOT: Path = (
    Path(__file__).parent / "fixtures" / "mock_nx_monorepo"
).resolve()


def _names(sub_projects: list[SubProject]) -> set[str]:
    return {sp.root.name for sp in sub_projects}


def test_discover_sub_projects_returns_list_of_sub_projects() -> None:
    """返 list[SubProject]。"""
    result = discover_sub_projects(_FIXTURE_ROOT)
    assert isinstance(result, list)
    assert all(isinstance(sp, SubProject) for sp in result)
    assert len(result) >= 3


def test_discover_sub_projects_finds_courses() -> None:
    """apps/courses（Vue 2.7.14）在 list 内。"""
    result = discover_sub_projects(_FIXTURE_ROOT)
    courses = [sp for sp in result if sp.root.name == "courses"]
    assert len(courses) == 1
    assert courses[0].vue_version == "2.7.14"
    assert courses[0].package_name == "@app-learn/courses"
    assert courses[0].tsconfig_path.name == "tsconfig.json"


def test_discover_sub_projects_finds_onion_utils() -> None:
    """packages/shared-utils（devDependencies.vue=2.7.14）在 list 内。"""
    result = discover_sub_projects(_FIXTURE_ROOT)
    onion = [sp for sp in result if sp.root.name == "shared-utils"]
    assert len(onion) == 1
    assert onion[0].vue_version == "2.7.14"


def test_discover_sub_projects_skips_legacy_no_tsconfig() -> None:
    """apps/legacy 缺 tsconfig.json → 自动跳过。"""
    result = discover_sub_projects(_FIXTURE_ROOT)
    assert "legacy" not in _names(result)


def test_discover_sub_projects_includes_vue26_with_marker() -> None:
    """apps/vue26-app 有 tsconfig 仍纳入 list；vue_version=2.6.14 由 VolarPool.get 入口防御。"""
    result = discover_sub_projects(_FIXTURE_ROOT)
    vue26 = [sp for sp in result if sp.root.name == "vue26-app"]
    assert len(vue26) == 1
    assert vue26[0].vue_version == "2.6.14"


def test_discover_sub_projects_excludes_node_modules() -> None:
    """node_modules/fake-pkg 即使有 tsconfig 也不被采纳。"""
    result = discover_sub_projects(_FIXTURE_ROOT)
    assert "fake-pkg" not in _names(result)


def test_discover_sub_projects_dedupes_across_probes() -> None:
    """三探针都返同一路径 → list 内仅出现一次。"""
    result = discover_sub_projects(_FIXTURE_ROOT)
    roots = [sp.root for sp in result]
    assert len(roots) == len(set(roots))


def test_discover_sub_projects_logs_event() -> None:
    """structlog 事件 volar_workspace_discovery_completed 含字段。"""
    with capture_logs() as logs:
        discover_sub_projects(_FIXTURE_ROOT)
    events = [log for log in logs if log.get("event") == "volar_workspace_discovery_completed"]
    assert len(events) >= 1
    event = events[-1]
    assert "sub_project_count" in event
    assert "skipped_missing_tsconfig" in event
    assert event["skipped_missing_tsconfig"] >= 1  # apps/legacy 缺 tsconfig


def test_subproject_is_frozen_hashable() -> None:
    """SubProject frozen=True 让其可作 dict key / set member。"""
    sp = SubProject(
        root=Path("/x/sub"),
        package_name="@x/sub",
        vue_version="2.7.14",
        tsconfig_path=Path("/x/sub/tsconfig.json"),
    )
    bag = {sp}
    assert sp in bag
    with pytest.raises(Exception):
        sp.vue_version = "3.0.0"  # type: ignore[misc]


@pytest.mark.parametrize(
    "spec, expected",
    [
        ("2.7.14", True),
        ("^2.7.14", True),
        ("~2.7.14", True),
        ("2.7.x", True),
        ("3.0.0", True),
        (">=2.7.0", True),
        ("2.6.14", False),
        ("^2.6.14", False),
        (None, False),
        ("", False),
        ("invalid", False),
    ],
)
def test_is_vue_27_or_newer(spec: str | None, expected: bool) -> None:
    """is_vue_27_or_newer 11 case 覆盖（含无效 / None）。"""
    assert is_vue_27_or_newer(spec) is expected
