"""SDD spec 生成（D-49-4/5/6）—— 融合通过后逐 SDD 仓产 openspec spec draft。

镜像 ``architect_merge_adapter`` 的可注入协议 + 默认 LLM 合成器 + 健壮文本归一化范式：

- ``SddSpecSynthesizer``（Protocol，可注入）：需求 + MergedPlan + 仓库 → openspec markdown。
- ``LLMSddSpecSynthesizer``：默认 LLM 合成器，``ProviderConfigService.aresolve`` +
  ``build_chat_model``，system prompt 教 openspec change-proposal 结构。**真 LLM 路径本
  phase 仅构造 + 单测 mock，真容器/真模型 E2E deferred**（对齐 LLMMergedPlanSynthesizer）。
- ``agenerate_specs_for_plan``：解析 ``PlanVersion.content``（MergedPlan）取涉及仓 → 过滤
  ``Repository.facets["methodology"]=="SDD"`` → 逐 SDD 仓 synthesize + create_draft + emit
  ``spec.drafted``；**逐仓 try/except 隔离**（单仓失败不影响其余）；无 SDD 仓 = no-op。

async ORM 防裸 lazy-FK（规避 Phase 38 CR-01）：一律用 ``*_id`` 标量 / ``afirst`` /
``.values``。所有跨模块 import 用函数内 lazy import 规避 import 环
（``process_runtime.__init__`` 在加载期 re-export 本模块）。
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "SddSpecSynthesizer",
    "LLMSddSpecSynthesizer",
    "agenerate_specs_for_plan",
]


@runtime_checkable
class SddSpecSynthesizer(Protocol):
    """SDD spec LLM 合成器协议（可注入）：需求 + MergedPlan + 仓库 → openspec markdown。"""

    async def synthesize(self, *, requirement: str, merged_plan: dict, repository: Any) -> str: ...


class LLMSddSpecSynthesizer:
    """默认 LLM 合成器：provider_config 解析 + chat model + openspec change-proposal prompt。

    **真实 LLM 路径本 phase 仅构造 + 单测 mock 覆盖，E2E 真容器/真模型 deferred**
    （对齐 ``LLMMergedPlanSynthesizer``）。合成/空文本 → 抛异常（由 hook 逐仓捕获降级）。
    """

    async def synthesize(self, *, requirement: str, merged_plan: dict, repository: Any) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            raise RuntimeError("no_default_model")
        model = build_chat_model(resolved, model_name, streaming=False)
        system = SystemMessage(content=self._system_prompt())
        human = HumanMessage(content=self._build_prompt(requirement, merged_plan, repository))
        response = await model.ainvoke([system, human])
        content = _strip_code_fences(_content_to_text(response.content).strip())
        if not content:
            raise ValueError("spec_synthesis_empty")
        return content

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是 SDD（规格驱动开发）架构师，负责把跨仓主方案落成单仓的 openspec change "
            "proposal。请只输出 markdown change proposal，不要任何解释，须含以下结构：\n"
            "## Why\n（变更动机：要解决什么问题）\n"
            "## What Changes\n（高层变更点列表）\n"
            "## Spec Deltas\n"
            "### ADDED Requirements\n"
            "（每条新增需求，附 `#### Scenario:` 描述验收场景）\n"
            "### MODIFIED Requirements\n"
            "（每条修改需求，附 `#### Scenario:`）\n"
            "### REMOVED Requirements\n"
            "（每条移除需求）\n"
            "只输出上述 markdown，不要代码块包裹、不要解释。"
        )

    @staticmethod
    def _build_prompt(requirement: str, merged_plan: dict, repository: Any) -> str:
        merged_json = json.dumps(merged_plan, ensure_ascii=False)
        repo_name = getattr(repository, "name", "")
        return (
            f"需求：\n{requirement}\n\n"
            f"跨仓主方案（MergedPlan）：\n{merged_json}\n\n"
            f"目标仓库：{repo_name}\n\n"
            "请针对该仓库产出 openspec change proposal markdown。"
        )


async def agenerate_specs_for_plan(
    artifact_version_id: Any,
    *,
    synthesizer: SddSpecSynthesizer | None = None,
    spec_service: Any = None,
) -> list:
    """融合通过后逐 SDD 仓产 spec draft（D-49-4/5）；返回已产 spec id 列表。

    解析 ``PlanVersion.content`` 的 ``execution_plan[].repository_id`` 取涉及仓，过滤
    ``Repository.facets["methodology"]=="SDD"`` 的仓（非 SDD 跳过 = 零回归；无 SDD 仓 =
    no-op）。逐 SDD 仓 try/except 隔离：synthesize → ``SddSpecService.create_draft`` →
    emit ``spec.drafted``（best-effort）；单仓异常吞为 warning ``sdd_spec_generation_failed``
    继续下一仓。
    """
    from delivery.models import ArtifactVersion, ConvergenceSession, WorkItem
    from delivery.services import ConvergenceSessionService, SddSpecService
    from delivery.services.event_taxonomy import EVENT_SPEC_DRAFTED
    from repositories.models import Repository

    synthesizer = synthesizer or LLMSddSpecSynthesizer()
    spec_service = spec_service or SddSpecService()

    av = await ArtifactVersion.objects.filter(id=artifact_version_id).afirst()
    if av is None:
        return []
    merged_plan = av.content if isinstance(av.content, dict) else {}

    # 来源 session（emit + requirement + work_item）；async 安全标量
    session = await ConvergenceSession.objects.filter(
        current_artifact_version_id=artifact_version_id
    ).afirst()
    requirement = ""
    work_item = None
    if session is not None:
        requirement = (session.decomposition or {}).get("requirement_text", "")
        if session.work_item_id is not None:
            work_item = await WorkItem.objects.filter(id=session.work_item_id).afirst()

    # 解析涉及仓（去重，过滤空串）
    repo_ids: list[str] = []
    seen: set[str] = set()
    for item in merged_plan.get("execution_plan", []) or []:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("repository_id") or "")
        if rid and rid not in seen:
            seen.add(rid)
            repo_ids.append(rid)

    session_service = ConvergenceSessionService()
    produced: list = []
    for repo_id in repo_ids:
        try:
            repo = await Repository.objects.filter(id=repo_id).afirst()
            if repo is None or (repo.facets or {}).get("methodology") != "SDD":
                continue
            content = await synthesizer.synthesize(
                requirement=requirement, merged_plan=merged_plan, repository=repo
            )
            spec = await spec_service.create_draft(
                artifact_version_id=artifact_version_id,
                repository=repo,
                work_item=work_item,
                content=content,
            )
            if session is not None:
                try:
                    await session_service._emit_event(
                        EVENT_SPEC_DRAFTED,
                        session,
                        {
                            "spec_id": str(spec.id),
                            "repository_id": str(repo.id),
                            "artifact_version_id": str(artifact_version_id),
                        },
                    )
                except Exception:  # noqa: BLE001 — 事件 best-effort，绝不阻断 spec 生成
                    logger.warning(
                        "spec_drafted_emit_failed",
                        spec_id=str(spec.id),
                        artifact_version_id=str(artifact_version_id),
                    )
            produced.append(spec.id)
        except Exception as exc:  # noqa: BLE001 — 单仓合成失败隔离，不影响其余仓
            logger.warning(
                "sdd_spec_generation_failed",
                repository_id=str(repo_id),
                artifact_version_id=str(artifact_version_id),
                error=str(exc),
            )
    return produced


def _strip_code_fences(text: str) -> str:
    """剥离 LLM 可能包裹的 ``` 代码块围栏（IN-01 健壮性）。

    模型偶尔无视「不要代码块包裹」指令，把整段 markdown 包进 ```markdown ... ```。
    仅当整段被单一围栏包裹时剥离（首行 ``` 开头、末行 ``` 收尾）；否则原样返回，
    避免误伤正文中合法的内嵌代码块。
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 2 or not lines[-1].strip().startswith("```"):
        return stripped
    # 去首行（```lang）与末行（```），保中间正文
    return "\n".join(lines[1:-1]).strip()


def _content_to_text(content: Any) -> str:
    """把 LLM response.content（str / list[block]）归一化为文本（镜像 architect adapter）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content)
