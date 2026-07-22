"""extra_evidence 编排消费接线三层守护测试（Phase 104 UNIFY-02）。

覆盖 analyze 产物「编排实际消费」链路的三层：

1. ``start_orchestration(extra_evidence=[...])`` → ``session.decomposition`` 含
   ``extra_evidence``；不传 → 不写键（既有会话形态零扰动）。
2. ``LLMMergedPlanSynthesizer._build_prompt``：带 extra_evidence 的 session → prompt 含
   证据内容；无证据 → prompt 不含「补充证据」段（静态方法直测，无需 DB）。
3. ``delegate_process_runtime`` kwargs 透传：patch ``services.process_runtime.
   start_orchestration``（delegate 内函数级 import，运行时从模块属性解析）捕获
   ``extra_evidence`` 入参。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from delivery.models import ConvergenceSessionStatus
from services.process_runtime import start_orchestration
from services.process_runtime.architect_merge_adapter import LLMMergedPlanSynthesizer

pytestmark = pytest.mark.django_db(transaction=True)

_EVIDENCE = [
    {
        "kind": "repository_analysis",
        "analysis_id": str(uuid.uuid4()),
        "summary": {"architecture_summary": "server 主要模块为 mcp_tools"},
    }
]


# ============================== ① start_orchestration → stage_state ==============================


@pytest.mark.asyncio
async def test_start_orchestration_injects_extra_evidence_into_decomposition() -> None:
    """extra_evidence 传入 → decomposition.extra_evidence 原样落 stage_state。"""
    session = await start_orchestration(
        entrypoint="workflow",
        requirement_text="带证据的编排需求",
        extra_evidence=_EVIDENCE,
    )

    decomposition = session.decomposition or {}
    assert decomposition["requirement_text"] == "带证据的编排需求"
    assert decomposition["extra_evidence"] == _EVIDENCE


@pytest.mark.asyncio
async def test_start_orchestration_omits_key_without_extra_evidence() -> None:
    """不传 extra_evidence → decomposition 不写该键（既有会话形态零扰动）。"""
    session = await start_orchestration(
        entrypoint="workflow",
        requirement_text="无证据的编排需求",
    )

    decomposition = session.decomposition or {}
    assert "extra_evidence" not in decomposition
    assert decomposition["requirement_text"] == "无证据的编排需求"


# ============================== ② merge prompt 消费 ==============================


def test_build_prompt_includes_extra_evidence_section() -> None:
    """带 extra_evidence 的 session → merge prompt 含补充证据段与证据内容。"""
    session = SimpleNamespace(
        decomposition={
            "requirement_text": "跨仓需求",
            "include_repos": [],
            "extra_evidence": _EVIDENCE,
        }
    )

    prompt = LLMMergedPlanSynthesizer._build_prompt(session, partials=[])

    assert "调用方补充证据" in prompt
    assert "server 主要模块为 mcp_tools" in prompt
    assert "跨仓需求" in prompt


def test_build_prompt_omits_evidence_section_without_extra_evidence() -> None:
    """无 extra_evidence → prompt 不含「补充证据」段（既有 prompt 形态不变）。"""
    session = SimpleNamespace(decomposition={"requirement_text": "跨仓需求", "include_repos": []})

    prompt = LLMMergedPlanSynthesizer._build_prompt(session, partials=[])

    assert "调用方补充证据" not in prompt
    assert "跨仓需求" in prompt


# ============================== ③ delegate 透传 ==============================


@pytest.mark.asyncio
async def test_delegate_process_runtime_forwards_extra_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delegate_process_runtime(extra_evidence=...) 原样透传 start_orchestration。"""
    from mcp_tools.orchestration_delegate import delegate_process_runtime

    captured: dict[str, Any] = {}
    fake_session = SimpleNamespace(
        id=uuid.uuid4(),
        status=ConvergenceSessionStatus.FAILED,
        current_artifact_version_id=None,
    )

    async def _fake_start_orchestration(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return fake_session

    async def _fake_drive(_engine: Any, session: Any) -> Any:
        return session

    monkeypatch.setattr("services.process_runtime.start_orchestration", _fake_start_orchestration)
    monkeypatch.setattr(
        "services.process_runtime.build_orchestration_engine", lambda **_kw: object()
    )
    monkeypatch.setattr(
        "services.process_runtime.adrive_convergence_session_to_pause_or_terminal",
        _fake_drive,
    )

    result = await delegate_process_runtime(
        requirement_text="需求文本",
        include_repos=["repo-1"],
        extra_evidence=_EVIDENCE,
    )

    assert captured["extra_evidence"] == _EVIDENCE
    assert captured["include_repos"] == ["repo-1"]
    assert result.status == "failed"
