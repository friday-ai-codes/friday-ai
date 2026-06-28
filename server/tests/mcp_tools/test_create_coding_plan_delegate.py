"""create_coding_plan delegate 守护测试（Phase 94 UNIFY-04）。

覆盖（plan Task 1 六守护）：
- ① delegate 被调且 ``include_repos=[repository_id]``（单仓约束，Open Q2 决议）+ actor 透传。
- ② canonical ``execution_plan`` 该仓 task → ``affected_files``/``steps``/``test_plan``/``title`` 映射正确。
- ③ 响应键集合 snapshot（旧键全在 + ``session_id`` + ``status``，T-94-04-COMPAT）。
- ④ ``McpCodingPlan`` / ``McpCodingPlanVersion`` 继续落库（兼容旧调用方）。
- ⑤ partial 挂起态 output 携 ``session_id`` 不崩（status=partial，调用方续推契约）。
- ⑥ actor 解析透传 delegate（created_by 为真实用户）；空 content 映射安全降级（V4 文档化降级）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from rest_framework.test import APIClient

from mcp_tools.models import McpCodingPlan, McpCodingPlanVersion

pytestmark = pytest.mark.django_db

# create_coding_plan 响应外形契约：旧键集合不得缩减（T-94-04-COMPAT snapshot 守护）。
_LEGACY_OUTPUT_KEYS = {
    "plan_id",
    "version_id",
    "version",
    "repository_id",
    "branch",
    "plan",
    "evidence",
    "run_id",
}


def _merged_content(repo_id: str, repo_name: str) -> dict:
    """合法 §7 MergedPlan content（单仓最小集，过 validate_merged_plan），含该仓 task files。"""
    return {
        "title": "登录超时修复方案",
        "summary": "在 auth 仓修复 token 刷新边界。",
        "api_contracts": [],
        "dependency_dag": {},
        "data_migrations": [],
        "compat_risks": ["token 边界变更需回归登录态"],
        "release_order": [repo_id],
        "rollback_plan": {repo_id: "revert 对应 PR"},
        "risks": ["需求可能未覆盖所有调用路径"],
        "execution_plan": [
            {
                "id": "t1",
                "name": "修复 token 刷新",
                "description": "对齐刷新边界",
                "repository_id": repo_id,
                "repository_name": repo_name,
                "branch_strategy": "feature",
                "coding_instruction": "在 session 校验处补刷新边界判断并加测试。",
                "files": [
                    {"path": "src/auth/session.py", "action": "modify"},
                    {"path": "src/auth/refresh.py", "action": "create"},
                ],
                "dependencies": [],
            }
        ],
    }


def _fake_delegate_result(*, status: str, repo_id: str, repo_name: str) -> Any:
    """构造 DelegateResult（view 级测试用，不触发真实编排）。"""
    from mcp_tools.orchestration_delegate import DelegateResult

    if status == "completed":
        return DelegateResult(
            session=SimpleNamespace(id=uuid.uuid4()),
            status="completed",
            content=_merged_content(repo_id, repo_name),
            plan_version_id=str(uuid.uuid4()),
            markdown="**登录超时修复方案**",
        )
    return DelegateResult(
        session=SimpleNamespace(id=uuid.uuid4()),
        status=status,
        content={},
        plan_version_id=None,
        markdown="",
    )


def _post_create_coding_plan(client: APIClient, repo_id: str) -> Any:
    return client.post(
        "/api/mcp/tools/create_coding_plan/",
        {"repository_id": repo_id, "requirement": "登录超过 30 秒 token 过期，需修复刷新边界。"},
        format="json",
    )


# ============================== ① 单仓约束 + delegate 被调 ==============================


def test_create_coding_plan_delegates_single_repo(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    access_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delegate 被调 + include_repos=[repository_id]（单仓约束）+ actor(created_by) 透传。"""
    client, _plaintext = mcp_client
    repo_id = str(indexed_repository.id)
    captured: dict[str, Any] = {}

    async def _fake_delegate(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_delegate_result(
            status="completed", repo_id=repo_id, repo_name=indexed_repository.name
        )

    monkeypatch.setattr("mcp_tools.views.delegate_process_runtime", _fake_delegate)

    response = _post_create_coding_plan(client, repo_id)

    assert response.status_code == 200
    # 单仓约束：编排只跑该仓（Open Q2 决议）。
    assert captured["include_repos"] == [repo_id]
    assert captured["work_item"] is None
    assert captured["requirement_text"]
    # actor 透传（T-94-04-ELEV）：真实 PAT 用户 → created_by 为该用户。
    assert "created_by" in captured
    assert getattr(captured["created_by"], "id", None) == access_user.id


# ============================== ② canonical 映射 ==============================


def test_create_coding_plan_maps_canonical_task_fields(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """canonical execution_plan 该仓 task → affected_files/steps/test_plan/title（显式白名单）。"""
    client, _plaintext = mcp_client
    repo_id = str(indexed_repository.id)

    async def _fake_delegate(**_kwargs: Any) -> Any:
        return _fake_delegate_result(
            status="completed", repo_id=repo_id, repo_name=indexed_repository.name
        )

    monkeypatch.setattr("mcp_tools.views.delegate_process_runtime", _fake_delegate)

    response = _post_create_coding_plan(client, repo_id)

    assert response.status_code == 200
    plan = response.json()["plan"]
    assert plan["title"] == "登录超时修复方案"
    assert plan["repository_id"] == repo_id
    assert plan["repository_name"] == indexed_repository.name
    # affected_files ← 该 task files[].path（顺序保留）。
    assert plan["affected_files"] == ["src/auth/session.py", "src/auth/refresh.py"]
    # steps ← coding_instruction 拆解为最小步骤结构。
    assert len(plan["steps"]) == 1
    assert plan["steps"][0]["detail"] == "在 session 校验处补刷新边界判断并加测试。"
    assert plan["steps"][0]["files"] == ["src/auth/session.py", "src/auth/refresh.py"]
    # test_plan best-effort（canonical 无 per-task 测试字段）→ 空 list。
    assert plan["test_plan"] == []
    # risks ← content.risks（best-effort）。
    assert plan["risks"] == ["需求可能未覆盖所有调用路径"]
    # 他仓 task 不进单仓响应（execution_plan 仅该仓）。
    assert "execution_plan" not in plan


# ============================== ③ 响应外形 snapshot ==============================


def test_create_coding_plan_response_shape_snapshot(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """响应键集合不缩减（旧键全在）+ 新增可选 session_id/status（T-94-04-COMPAT）。"""
    client, _plaintext = mcp_client
    repo_id = str(indexed_repository.id)

    async def _fake_delegate(**_kwargs: Any) -> Any:
        return _fake_delegate_result(
            status="completed", repo_id=repo_id, repo_name=indexed_repository.name
        )

    monkeypatch.setattr("mcp_tools.views.delegate_process_runtime", _fake_delegate)

    response = _post_create_coding_plan(client, repo_id)

    assert response.status_code == 200
    body = response.json()
    assert _LEGACY_OUTPUT_KEYS <= set(body.keys())
    assert "session_id" in body and body["session_id"]
    assert body["status"] == "completed"
    assert body["repository_id"] == repo_id
    # evidence 由映射后 affected_files 推导（外形兼容，kind=file）。
    assert {e["file_path"] for e in body["evidence"]} == {
        "src/auth/session.py",
        "src/auth/refresh.py",
    }


# ============================== ④ 落库兼容 ==============================


def test_create_coding_plan_persists_plan_and_version(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """McpCodingPlan / McpCodingPlanVersion 继续落库（plan_body=canonical content，字段全保留）。"""
    client, _plaintext = mcp_client
    repo_id = str(indexed_repository.id)

    async def _fake_delegate(**_kwargs: Any) -> Any:
        return _fake_delegate_result(
            status="completed", repo_id=repo_id, repo_name=indexed_repository.name
        )

    monkeypatch.setattr("mcp_tools.views.delegate_process_runtime", _fake_delegate)

    response = _post_create_coding_plan(client, repo_id)

    assert response.status_code == 200
    body = response.json()
    plan = McpCodingPlan.objects.get(id=body["plan_id"])
    assert str(plan.repository_id) == repo_id
    assert plan.title == "登录超时修复方案"
    assert plan.current_version == 1

    version = McpCodingPlanVersion.objects.get(id=body["version_id"])
    assert version.version == 1
    # plan_body = canonical content（含 §7 execution_plan）。
    assert version.plan_body["execution_plan"][0]["repository_id"] == repo_id
    assert version.affected_files == ["src/auth/session.py", "src/auth/refresh.py"]
    assert version.steps[0]["title"] == "修复 token 刷新"
    assert version.test_plan == []
    assert version.risks == ["需求可能未覆盖所有调用路径"]


# ============================== ⑤ partial 挂起态 ==============================


def test_create_coding_plan_partial_carries_session(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """编排挂起（RESEARCHING）→ status=partial + session_id；落库不崩（调用方续推契约）。"""
    client, _plaintext = mcp_client
    repo_id = str(indexed_repository.id)

    async def _fake_delegate(**_kwargs: Any) -> Any:
        return _fake_delegate_result(
            status="partial", repo_id=repo_id, repo_name=indexed_repository.name
        )

    monkeypatch.setattr("mcp_tools.views.delegate_process_runtime", _fake_delegate)

    response = _post_create_coding_plan(client, repo_id)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["session_id"]
    # 空 content 降级：plan 仍为安全最小外形（旧键全在）。
    assert body["plan"]["affected_files"] == []
    assert body["plan"]["steps"] == []
    assert body["plan"]["title"] == indexed_repository.name
    # partial 仍建版本（version=1），plan_body 回退映射后单仓 payload。
    version = McpCodingPlanVersion.objects.get(id=body["version_id"])
    assert version.version == 1


# ============================== ⑥ actor / 映射降级 ==============================


def test_map_canonical_to_coding_plan_empty_content_degrades(indexed_repository) -> None:
    """缺 canonical content（delegate failed/partial 产 {}）→ 安全最小 payload，不抛（V4 降级）。"""
    from mcp_tools.planning_service import map_canonical_to_coding_plan

    payload = map_canonical_to_coding_plan(
        content={},
        repository=indexed_repository,
        branch="main",
        requirement="需求文本",
    )

    assert payload["title"] == indexed_repository.name
    assert payload["repository_id"] == str(indexed_repository.id)
    assert payload["affected_files"] == []
    assert payload["steps"] == []
    assert payload["test_plan"] == []
    assert payload["risks"] == []
    assert payload["branch"] == "main"
    assert payload["requirement"] == "需求文本"
