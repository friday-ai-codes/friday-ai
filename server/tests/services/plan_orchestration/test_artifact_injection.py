"""artifact_injection 渲染纯函数单测（Phase 45-02，ARTIFACT-02）。

仅覆盖 ``render_upstream_artifacts_section`` 纯函数（无 django_db、无 IO）：
空串零回归命门 / 单上游契约段 / 多上游各仓契约齐全。``acollect_upstream_artifacts``
是 async ORM 反查（需 DB），在 coding 节点集成路径覆盖，本文件不测。
"""

from __future__ import annotations

from services.plan_orchestration import render_upstream_artifacts_section


def test_empty_list_renders_empty_string():
    """空 list → "" （零回归命门，绝不渲染空标题）。"""
    assert render_upstream_artifacts_section([]) == ""


def test_single_upstream_renders_contract_section():
    """单上游 → 段含标题 + 仓名 + 分支 + MR + OpenAPI/契约文件名 + 变更文件数。"""
    section = render_upstream_artifacts_section(
        [
            {
                "repository_id": "r1",
                "repository_name": "backend",
                "branch": "feat/api",
                "mr_url": "https://gitlab.example.com/mr/1",
                "openapi": ["api/openapi.yaml"],
                "api_contracts": ["proto/user.proto"],
                "diff_summary": {"files_changed": 3},
            }
        ]
    )
    assert "# 上游产物 / 上游契约" in section
    assert "backend" in section
    assert "feat/api" in section
    assert "https://gitlab.example.com/mr/1" in section
    assert "api/openapi.yaml" in section
    assert "proto/user.proto" in section
    assert "3" in section


def test_single_upstream_falls_back_to_repository_id_when_no_name():
    """无 repository_name → 回退渲染 repository_id。"""
    section = render_upstream_artifacts_section(
        [{"repository_id": "repo-xyz", "diff_summary": {"files_changed": 0}}]
    )
    assert "repo-xyz" in section


def test_multiple_upstreams_render_each_repo_contracts():
    """多上游 → 段含各仓各自契约文件名。"""
    section = render_upstream_artifacts_section(
        [
            {
                "repository_id": "r1",
                "repository_name": "backend",
                "api_contracts": ["proto/order.proto"],
            },
            {
                "repository_id": "r2",
                "repository_name": "gateway",
                "openapi": ["gateway/openapi.json"],
            },
        ]
    )
    assert "backend" in section
    assert "proto/order.proto" in section
    assert "gateway" in section
    assert "gateway/openapi.json" in section


def test_empty_contract_fields_omit_labels():
    """无契约文件 → 不渲染 OpenAPI / API 契约 标签（仅按非空才输出）。"""
    section = render_upstream_artifacts_section(
        [
            {
                "repository_id": "r1",
                "repository_name": "backend",
                "branch": "feat/x",
                "openapi": [],
                "api_contracts": [],
            }
        ]
    )
    assert "backend" in section
    assert "OpenAPI" not in section
    assert "API 契约" not in section
