"""artifact_extraction 提取纯函数单测（Phase 45-01，ARTIFACT-01）。

覆盖 <behavior> 四场景：路径启发式归类 / git TaskResult 结构化 / 无 TaskResult 占位 /
空 modified_files。纯函数测试，无 ``django_db``、无 IO——用**未保存**的内存 ``TaskResult``
实例（不触 DB）。另含安全断言：产物不含 ``raw_output`` 正文 / token 字段。
"""

from __future__ import annotations

from services.process_runtime import build_produced_artifacts, classify_modified_files
from subagent.models import TaskResult


def _git_task_result(modified_files: list[str]) -> TaskResult:
    """构造未保存的内存 git TaskResult（不触 DB，字段为已物化标量）。"""
    return TaskResult(
        result_type="git",
        branch_name="feat/x",
        commit_sha="abc123",
        pr_url="https://example.com/mr/1",
        modified_files=modified_files,
        raw_output={"secret_token": "tok-should-never-leak", "body": "huge raw blob"},
    )


def test_classify_modified_files_buckets() -> None:
    """openapi.yaml → openapi 桶；.proto → api_contracts 桶；src/x.py 不进任何桶。"""
    api_contracts, openapi = classify_modified_files(
        ["api/openapi.yaml", "proto/svc.proto", "src/x.py"]
    )
    assert "api/openapi.yaml" in openapi
    assert "proto/svc.proto" in api_contracts
    assert "src/x.py" not in api_contracts
    assert "src/x.py" not in openapi


def test_classify_none_is_empty() -> None:
    """modified_files=None → 两桶皆空（绝不抛）。"""
    assert classify_modified_files(None) == ([], [])  # type: ignore[arg-type]


def test_build_produced_artifacts_git() -> None:
    """git TaskResult 含 openapi/proto/schema → available=True + 正确归类 + diff 计数。"""
    modified = [
        "api/openapi.yaml",
        "proto/svc.proto",
        "graphql/schema.graphql",
        "src/main.py",
    ]
    artifacts = build_produced_artifacts(
        repository_id="repo-1",
        repository_name="backend",
        task_result=_git_task_result(modified),
    )
    assert artifacts["available"] is True
    assert artifacts["repository_id"] == "repo-1"
    assert artifacts["repository_name"] == "backend"
    assert "extracted_at" in artifacts
    assert artifacts["branch"] == "feat/x"
    assert artifacts["commit_sha"] == "abc123"
    assert artifacts["mr_url"] == "https://example.com/mr/1"
    assert artifacts["modified_files"] == modified
    assert "api/openapi.yaml" in artifacts["openapi"]
    assert "proto/svc.proto" in artifacts["api_contracts"]
    assert "graphql/schema.graphql" in artifacts["api_contracts"]
    assert artifacts["diff_summary"]["files_changed"] == len(modified)


def test_build_produced_artifacts_none_placeholder() -> None:
    """task_result=None → {"available": False} 占位（含元信息），不抛。"""
    artifacts = build_produced_artifacts(
        repository_id="repo-2",
        repository_name="frontend",
        task_result=None,
    )
    assert artifacts["available"] is False
    assert artifacts["repository_id"] == "repo-2"
    assert artifacts["repository_name"] == "frontend"
    assert "extracted_at" in artifacts
    # 占位不应带 git 产物字段。
    assert "modified_files" not in artifacts
    assert "diff_summary" not in artifacts


def test_build_produced_artifacts_empty_modified() -> None:
    """空 modified_files → 结构合法、各契约桶空、files_changed==0。"""
    artifacts = build_produced_artifacts(
        repository_id="repo-3",
        repository_name="infra",
        task_result=_git_task_result([]),
    )
    assert artifacts["available"] is True
    assert artifacts["modified_files"] == []
    assert artifacts["api_contracts"] == []
    assert artifacts["openapi"] == []
    assert artifacts["diff_summary"]["files_changed"] == 0


def test_build_produced_artifacts_no_sensitive_values() -> None:
    """安全（T-45-01）：产物绝不含 raw_output 正文 / token 字段——仅 path/url/计数。"""
    artifacts = build_produced_artifacts(
        repository_id="repo-4",
        repository_name="svc",
        task_result=_git_task_result(["api/openapi.yaml"]),
    )
    assert "raw_output" not in artifacts
    serialized = str(artifacts)
    assert "tok-should-never-leak" not in serialized
    assert "huge raw blob" not in serialized
    assert "token" not in artifacts
