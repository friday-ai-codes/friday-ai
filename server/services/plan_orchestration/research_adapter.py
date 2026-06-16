"""ResearchDispatchAdapter —— researching 阶段 map 段真实实现（RESEARCH-01）。

替换骨架 ``SkeletonResearch``，实现 **filter_then_container**：先 server 端 filter
（复用 Phase 38 ``session.routing.candidates`` + confidence），只对「需深入」仓
（confidence ∈ {high, medium}）fan-out 独立 claude code 容器并行调研（上下文隔离）；
轻量仓（low / 缺失）走 server 端合成 ``PartialPlan`` 省资源（filter 的「filter」语义）。

**复用既有容器底座，不重造**：``runners.dispatcher.DispatchTask`` + ``get_dispatcher``
（mirror ``chat_tools.deep_analysis``）+ ``subagent.SubAgentSession(TaskType.PLAN)``；
写 RepoResearchTask/PartialPlan 只经 ``ResearchService``（INV-6，不旁路）。

聚合/结果解析/engine 接线在 39-04；本 adapter 只负责 filter + fan-out + 建 task +
派容器（fire-and-forget）+ 轻量合成 + emit ``repo.research.started``。
"""

from __future__ import annotations

from typing import Any

import structlog

from delivery.models import PlanSession, RepoResearchTaskStatus
from delivery.services import PlanSessionService, ResearchService

logger = structlog.get_logger(__name__)

__all__ = ["ResearchDispatchAdapter"]

# runner 在线判定窗口（秒）—— 与 deep_analysis 一致（3 倍心跳）
_RUNNER_HEARTBEAT_WINDOW_SECONDS = 120
# 调研容器超时（秒）
_RESEARCH_TIMEOUT = 30 * 60

# WR-01 resume-幂等：dispatch 仅处理「待派发 / 重索引过期」任务。已 running/done/failed
# 的任务在 re-advance/resume 时跳过——既不重派已完成 deep 容器（重置进度、浪费容器、
# 扰乱 barrier），也不为已处理 light 仓重复合成 PartialPlan。stale 须重跑（RESEARCH-03）。
_DISPATCHABLE_STATUSES = (RepoResearchTaskStatus.PENDING, RepoResearchTaskStatus.STALE)


class ResearchDispatchAdapter:
    """并行调研 stage 依赖真实实现（满足 ResearchProtocol，RESEARCH-01）。"""

    def __init__(
        self,
        *,
        deep_confidence: set[str] | None = None,
        session_service: PlanSessionService | None = None,
        research_service: ResearchService | None = None,
    ) -> None:
        # 「需深入」confidence 集合（默认 high+medium 起容器，可配——CONTEXT Claude's Discretion）
        self.deep_confidence = deep_confidence or {"high", "medium"}
        self.session_service = session_service or PlanSessionService()
        self.research_service = research_service or ResearchService()

    async def dispatch(self, session: PlanSession) -> dict:
        """filter + fan-out 调度，返回 ``{dispatched, light, runner_offline, ...}``。"""
        candidates = (session.routing or {}).get("candidates", []) or []
        if not candidates:
            return {"dispatched": [], "light": [], "skipped": "no_candidates"}

        deep_repos: list[dict] = []
        light_repos: list[dict] = []
        for c in candidates:
            repo_id = c.get("repo_id")
            if not repo_id:
                continue
            confidence = (c.get("confidence") or "").lower()
            item = {"repository_id": str(repo_id), "routed_confidence": confidence}
            if confidence in self.deep_confidence:
                deep_repos.append(item)
            else:
                light_repos.append(item)

        runner_offline = False
        if deep_repos:
            online = await self._count_online_runners()
            if online == 0:
                # 编排是后台推进（非交互 chat）：无 runner 不重试循环，降级为轻量处理，
                # 不阻断编排——轻量 partial 仍产出。
                runner_offline = True
                light_repos = light_repos + deep_repos
                deep_repos = []

        dispatched_ids: list[str] = []
        light_ids: list[str] = []

        # deep fan-out（每仓上下文隔离）
        if deep_repos:
            deep_tasks = await self.research_service.create_tasks_for_session(
                session, deep_repos
            )
            for task in deep_tasks:
                # WR-01 幂等：跳过已 running/done/failed 的任务（仅派发 pending/stale）
                if task.status not in _DISPATCHABLE_STATUSES:
                    continue
                # WR-02 单仓错误隔离（RESEARCH-02）：任一仓 dispatch 异常仅标该 task
                # failed + 发 repo.research.failed，继续其他仓——绝不上抛拖垮整个
                # PlanSession（异常上抛会被 engine advance 的通用 except 转 fail）。
                try:
                    await self._dispatch_deep_task(session, task)
                    dispatched_ids.append(str(task.id))
                except Exception as exc:  # noqa: BLE001 — 单仓失败隔离，不波及其他仓
                    logger.warning(
                        "research_dispatch_failed",
                        session_id=str(session.id),
                        task_id=str(task.id),
                        error=str(exc),
                    )
                    await self.research_service.mark_failed(
                        task, {"reason": "dispatch_failed", "error": str(exc)}
                    )
                    await self._emit_failed(session, task, "dispatch_failed")

        # light path（low / 降级仓）：建 task + 合成轻量 PartialPlan（不起容器，省资源）
        if light_repos:
            light_tasks = await self.research_service.create_tasks_for_session(
                session, light_repos
            )
            for task in light_tasks:
                # WR-01 幂等：跳过已处理（done/running/failed）的 light 仓，不重复落 PartialPlan
                if task.status not in _DISPATCHABLE_STATUSES:
                    continue
                repo = await self._get_repository(task.repository_id)
                content = self._synthesize_light_partial(session, task, repo)
                await self.research_service.record_partial(task, content)
                light_ids.append(str(task.id))

        return {
            "dispatched": dispatched_ids,
            "light": light_ids,
            "runner_offline": runner_offline,
        }

    async def _dispatch_deep_task(self, session: PlanSession, task: Any) -> None:
        """对单个需深入仓：建独立 SubAgentSession(PLAN) 容器 + 派发 + 回填 running + emit started。"""
        from agents.models import AgentSession
        from runners.dispatcher import DispatchTask, get_dispatcher
        from subagent.models import SubAgentSession

        repo = await self._get_repository(task.repository_id)
        repo_url = getattr(repo, "git_url", "") if repo is not None else ""

        session_id = f"research-{task.id.hex[:12]}"
        agent_session = await AgentSession.objects.acreate(
            session_id=f"agent-{session_id}",
            status=AgentSession.Status.RUNNING,
            metadata={"source": "plan_research", "plan_session_id": str(session.id)},
        )
        subagent_session = await SubAgentSession.objects.acreate(
            session_id=session_id,
            main_session=agent_session,
            repo_url=repo_url or f"https://invalid/{task.repository_id}.git",
            task_type=SubAgentSession.TaskType.PLAN,
            status=SubAgentSession.Status.PENDING,
            last_output={
                "source": "plan_research",
                "plan_session_id": str(session.id),
                "research_task_id": str(task.id),
                "repository_id": str(task.repository_id),
            },
        )

        prompt = self._build_research_prompt(session, task, repo)
        metadata = await self._build_dispatch_metadata(repo)

        dispatch_task = DispatchTask(
            task_id=session_id,
            task_type="plan",
            tags=[],
            image="",
            repo_url=metadata.pop("_repo_url", repo_url) or repo_url,
            branch=getattr(repo, "default_branch", "") or "main",
            target_branch="",
            prompt=prompt,
            timeout=_RESEARCH_TIMEOUT,
            node_execution_id="",
            session_id=session_id,
            metadata=metadata,
        )
        await get_dispatcher().dispatch(dispatch_task)
        await self.research_service.mark_running(task, subagent_session)

        await self._emit_started(session, task)

    async def _emit_started(self, session: PlanSession, task: Any) -> None:
        """emit repo.research.started（payload {repo_id, task_id, focus}），best-effort。"""
        payload = {
            "repo_id": str(task.repository_id),
            "task_id": str(task.id),
            "focus": task.routed_confidence or "",
        }
        try:
            await self.session_service._emit_event("repo.research.started", session, payload)
        except Exception:  # noqa: BLE001 — 事件 best-effort，绝不阻断调度
            logger.warning(
                "repo_research_started_emit_failed",
                session_id=str(session.id),
                task_id=str(task.id),
            )

    async def _emit_failed(self, session: PlanSession, task: Any, reason: str) -> None:
        """emit repo.research.failed（payload {repo_id, task_id, error}），best-effort。"""
        payload = {
            "repo_id": str(task.repository_id),
            "task_id": str(task.id),
            "error": reason,
        }
        try:
            await self.session_service._emit_event("repo.research.failed", session, payload)
        except Exception:  # noqa: BLE001 — 事件 best-effort，绝不阻断调度
            logger.warning(
                "repo_research_failed_emit_failed",
                session_id=str(session.id),
                task_id=str(task.id),
            )

    def _build_research_prompt(self, session: PlanSession, task: Any, repo: Any) -> str:
        """构造调研 prompt：注入该仓 routing 上下文 + recall_context + 需求 decomposition。

        要求容器产出结构化 PartialPlan（§7 字段，JSON 输出）。prompt 内容来自 server 端
        权威 session 状态（非外部用户原文拼接执行指令）。
        """
        decomposition = session.decomposition or {}
        requirement_text = decomposition.get("requirement_text", "")
        repo_name = getattr(repo, "name", "") if repo is not None else ""
        recall_summary = self._summarize_recall(session)

        return (
            f"你正在为仓库「{repo_name}」（路由置信度：{task.routed_confidence or 'unknown'}）"
            "做方案调研。\n\n"
            f"需求：\n{requirement_text}\n\n"
            f"相关历史召回（精简）：\n{recall_summary}\n\n"
            "请深入分析本仓代码，产出**结构化 PartialPlan**，以 JSON 输出，字段：\n"
            "- research_summary：本仓调研摘要\n"
            "- proposed_changes：建议改动列表\n"
            "- candidate_files：候选改动文件列表\n"
            "- api_contracts_exposed：本仓对外暴露的契约\n"
            "- dependencies_on_other_repos：依赖其他仓的契约\n"
        )

    @staticmethod
    def _summarize_recall(session: PlanSession) -> str:
        """把 recall_context 命中精简为标题行摘要（不外泄完整明细）。"""
        recall = session.recall_context or []
        if not isinstance(recall, list) or not recall:
            return "（无）"
        lines = []
        for hit in recall[:10]:
            if isinstance(hit, dict):
                lines.append(f"- [{hit.get('kind', '')}] {hit.get('title', '')}")
        return "\n".join(lines) or "（无）"

    def _synthesize_light_partial(
        self, session: PlanSession, task: Any, repo: Any
    ) -> dict:
        """轻量仓 server 端合成 PartialPlan（纯函数，不调 LLM/容器，省资源）。"""
        repo_name = getattr(repo, "name", "") if repo is not None else ""
        decomposition = session.decomposition or {}
        requirement_text = decomposition.get("requirement_text", "")
        summary = (
            f"仓库「{repo_name}」经 server 端快筛判定为低置信度"
            f"（{task.routed_confidence or 'low'}），未起独立调研容器；"
            f"基于路由/召回上下文合成轻量结论。需求：{requirement_text[:500]}"
        )
        return {
            "repository_id": str(task.repository_id),
            "research_summary": summary,
            "proposed_changes": [],
            "candidate_files": [],
            "api_contracts_exposed": [],
            "dependencies_on_other_repos": [],
        }

    async def _build_dispatch_metadata(self, repo: Any) -> dict[str, str]:
        """构造容器 env_metadata（复用 deep_analysis 凭证解析；只读 explore 语义）。

        any 异常不外泄到调度主轨（best-effort 取凭证；缺凭证容器内自报错）。
        """
        from services.git_credentials import aresolve_git_token
        from services.provider_config import aget_claude_code_runtime_config

        metadata: dict[str, str] = {
            "repository_id": str(getattr(repo, "id", "") or ""),
            # 只读 explore 语义：双层 git 写操作拦截（research 不写 git）
            "env_FRIDAY_TASK_MODE": "explore",
            "env_FRIDAY_TASK_TASK_MODE": "explore",
        }
        try:
            cc = await aget_claude_code_runtime_config()
            metadata["env_FRIDAY_TASK_CLAUDE_API_KEY"] = cc.get("api_key", "")
            metadata["env_FRIDAY_TASK_CLAUDE_BASE_URL"] = cc.get("base_url", "")
            metadata["env_FRIDAY_TASK_CLAUDE_MODEL"] = cc.get("default_model", "")
            metadata["env_FRIDAY_TASK_CLAUDE_SMALL_MODEL"] = cc.get("haiku_model", "")
        except Exception:  # noqa: BLE001 — 凭证缺失不阻断调度（容器内自报错）
            logger.warning("research_runtime_config_failed")

        repo_url = getattr(repo, "git_url", "") or ""
        try:
            if repo is not None:
                token = await aresolve_git_token(repo)
                if token:
                    metadata["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] = token
                    metadata["env_FRIDAY_TASK_GIT_AUTH_TYPE"] = "token"
                    metadata["env_FRIDAY_TASK_GIT_SSL_VERIFY"] = "false"
                    if repo_url.startswith("git@"):
                        import re

                        m = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", repo_url)
                        if m:
                            repo_url = f"https://{m.group(1)}/{m.group(2)}.git"
        except Exception:  # noqa: BLE001 — git 凭证缺失不阻断调度
            logger.warning("research_git_token_failed")
        metadata["_repo_url"] = repo_url
        return metadata

    async def _count_online_runners(self) -> int:
        """在线 runner 计数（mirror deep_analysis，无重试循环——后台推进非交互）。"""
        from datetime import timedelta

        from django.utils import timezone as tz

        from runners.models import Runner

        threshold = tz.now() - timedelta(seconds=_RUNNER_HEARTBEAT_WINDOW_SECONDS)
        return await Runner.objects.filter(
            status="online", last_heartbeat__gte=threshold
        ).acount()

    @staticmethod
    async def _get_repository(repository_id: Any) -> Any:
        """async 取 Repository（取不到返回 None，调用方防御 getattr）。"""
        from repositories.models import Repository

        return await Repository.objects.filter(id=repository_id).afirst()
