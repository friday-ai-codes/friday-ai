"""BlueprintRepoPlanAdapter —— 阶段 2 逐仓分仓方案（Phase 113-03，FLOW-05 / SCHEMA-03）。

五条契约（模块级不变量，改动前先读）：

1. **组合而非继承**：direct 仓起容器复用 `BlueprintResearchAdapter.dispatch(mode="plan")`
   的派发五步与 metadata 构造；本文件只负责仓集来源、indirect 合成、落库与完成判据。
2. **INV-6**：`RepoResearchTask` / `PartialPlan` 的写入只经 `ResearchService`；澄清线程只经
   `BlueprintLifecycleService`。本文件读一律 `values()` / `afirst()`，async 上下文不裸访问
   lazy-FK。
3. **WR-02 单仓错误隔离**：任何单仓失败只记 warning + 该仓留待下轮，**绝不上抛** —— 上抛会
   被 engine 的通用 except 转成整个 session 失败。
4. **仓集来源是确认门锁定的 `repo_associations`**（最新 `ArtifactVersion`），不复用路由候选面：
   阶段 2 的 direct/indirect 是人工裁决结果，与路由期的 `role_suggestion` 语义已不同。
5. **`record_partial` 是整体覆写语义**：写 `repo_plan` 段必须**读-合并-写**（唯一入口
   `arecord_repo_plan`）。裸传 `{"repo_plan": ...}` 会让 `acollect_fitness` 读到空 fitness，
   确认门快照与 `current_state_analysis` 投影全线失血（P-1）。
"""

from __future__ import annotations

import json
import time
from typing import Any, Protocol, runtime_checkable

import structlog
from asgiref.sync import sync_to_async

from common.logging import redact_secrets_in_text
from delivery.models import RepoResearchTaskStatus
from delivery.services import ResearchService
from services.process_runtime.blueprint_repo_plan_schema import (
    REPO_PLAN_AVAILABILITY,
    validate_repo_plan,
)
from services.process_runtime.blueprint_repo_waves import build_api_waves
from services.process_runtime.blueprint_research_adapter import (
    BLUEPRINT_REPO_PLAN_SOURCE,
    BlueprintResearchAdapter,
    summarize_requirement_context,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "BlueprintRepoPlanAdapter",
    "BLUEPRINT_REPO_PLAN_SOURCE",
    "MAX_REPO_PLAN_ATTEMPTS",
    "STAGE_STATE_KEY",
    "RepoPlanSynthesizer",
]

# 有界重试上界（CONTEXT：「不合格触发有界重试 ≤2 轮，仍不合格开澄清线程而非静默降级」）。
# 回调侧按同一常量判 direct 仓的容器重跑次数；本文件用它兜 indirect 仓的 LLM 合成轮次。
MAX_REPO_PLAN_ATTEMPTS = 2

# `stage_state` 新键（与既有 9 键无冲突）；只存 id / 计数（单字段 < 2KB，DESIGN §5.6）。
STAGE_STATE_KEY = "repo_plan"

_MAX_ERROR_CHARS = 500
_MAX_PROMPT_TEXT_CHARS = 2000
_VALID_ROLES = ("direct", "indirect")

# waiter 超时清理的默认龄期（挂 barrier 续驱路径调用，**不新起定时任务**）。
# 取值口径：短等待硬上界 5min ⇒ 长等待被清理前至少给足 6 倍余量，避免正常协商被误清。
DEFAULT_WAITER_MAX_AGE_SECONDS = 30 * 60


@runtime_checkable
class RepoPlanSynthesizer(Protocol):
    """indirect 仓的服务端 LLM 合成器协议（测试注替身，生产零参构造）。"""

    async def synthesize(self, session: Any, repo: dict) -> dict: ...


class LLMRepoPlanSynthesizer:
    """默认合成器：provider_config 解析 + chat model + 健壮 JSON 解析。

    照 `architect_merge_adapter.LLMMergedPlanSynthesizer` 的五步骨架（**只读 analog，
    复制不 import**）：`aresolve` → `build_chat_model` → `use_call_source` → 文本归一 → 解析。
    解析不出结构就 `raise`，由调用方按有界重试处理（绝不返回半截产物）。
    """

    async def synthesize(self, session: Any, repo: dict) -> dict:
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.call_source import CallSource, use_call_source
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            raise RuntimeError("no_default_model")
        model = build_chat_model(resolved, model_name, streaming=False)
        system = SystemMessage(content=self._system_prompt())
        human = HumanMessage(content=self._build_prompt(session, repo))
        # 111 已注册的 call_source，不新增枚举值
        with use_call_source(CallSource.BLUEPRINT_REPO_PLAN):
            response = await model.ainvoke([system, human])
        parsed = _parse_json(_content_to_text(response.content))
        if parsed is None:
            raise ValueError("repo_plan_parse_failed")
        return parsed

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是软件架构师，正在为一个**间接相关**仓库整理它在本次需求中的能力引用清单。"
            "该仓预计不需要改动，你的产出用于让其他仓知道能从它这里取什么。只输出 JSON。"
        )

    @staticmethod
    def _build_prompt(session: Any, repo: dict) -> str:
        """由服务端权威状态构造（不把外部用户原文当执行指令拼接）。

        需求上下文与调研/拟方案容器同源（`summarize_requirement_context`）：indirect 仓
        虽不改动，但「别的仓会向它要什么能力」只有对照完整需求（含验收标准/测试用例）
        才判断得出来。
        """
        repository_id = str(repo.get("repository_id") or "")
        responsibility = _blocks_to_text(repo.get("responsibility"))[:_MAX_PROMPT_TEXT_CHARS]
        fitness = repo.get("fitness") if isinstance(repo.get("fitness"), dict) else {}
        return (
            f"{summarize_requirement_context(session)}\n\n"
            f"## 本仓信息\n"
            f"仓库 id：{repository_id}\n"
            f"确认门锁定的职责：{responsibility or '（未填）'}\n"
            f"阶段 1 适配度结论：{fitness.get('verdict') or 'unknown'}\n\n"
            "请只输出一个 JSON 对象，顶层键为 `repo_plan`，其值字段：\n"
            f'- repository_id: "{repository_id}"；role: "indirect"\n'
            "- responsibility: Block[]（沿用上面锁定的职责）\n"
            "- apis_provided: [{name, method, path, description, citations}] —— 本仓已能对外"
            "提供、本次需求可能被消费的能力\n"
            "- impl_items: []（间接仓默认不改动；确有必要的完善项用 change_type="
            '"indirect_refine"）\n'
            "- risks: Block[]（把「无法确认的能力」写成风险，不要编造接口）\n"
            f"- 如需其他仓配合，写进 apis_consumed[].data_source（availability ∈ "
            f"{'、'.join(REPO_PLAN_AVAILABILITY)}，needs_support 时必填 support_repository_id）\n"
        )


class BlueprintRepoPlanAdapter:
    """蓝图 `repo_plan` stage 依赖：仓集 / direct 派发 / indirect 合成 / 落库 / 完成判据。

    依赖全 keyword-only 可注入（测试注 mock，生产零参构造）：

    - `research_service`：`ResearchService` 形状（唯一业务写入面）
    - `research_adapter`：`BlueprintResearchAdapter` 形状（复用 `dispatch(mode="plan")`）
    - `synthesizer`：`RepoPlanSynthesizer` 形状（indirect 仓服务端合成）
    - `lifecycle_service`：`BlueprintLifecycleService` 形状（澄清线程唯一入口）
    """

    def __init__(
        self,
        *,
        research_service: Any = None,
        research_adapter: Any = None,
        synthesizer: Any = None,
        lifecycle_service: Any = None,
        node_execution_id: str = "",
    ) -> None:
        self.research_service = research_service or ResearchService()
        self.research_adapter = research_adapter or BlueprintResearchAdapter(
            node_execution_id=node_execution_id
        )
        self.synthesizer = synthesizer or LLMRepoPlanSynthesizer()
        self._lifecycle_service = lifecycle_service
        self.node_execution_id = node_execution_id or ""

    # ── 仓集来源（确认门锁定产物） ─────────────────────────────────────────

    async def acollect_locked_repos(self, session: Any) -> list[dict]:
        """确认门锁定的仓集：`[{repository_id, role, responsibility, fitness}]`。

        基线取 artifact 的**最新** `ArtifactVersion`（`order_by("-version_no")`）而不是会话
        钉住的那一版 —— 后者只在 handler 显式回填 `StageOutcome` 时才推进，读它会拿到确认门
        落锁之前的旧内容（112-05 Deviation 3 同源坑）。取不到则回落
        `stage_state["confirmation"]` 快照；两者都无 → `[]`（上层判「无可拟方案的仓」）。
        """
        try:
            artifact_id = await self._aresolve_artifact_id(getattr(session, "id", None))
            content = (
                await self._aload_latest_content(artifact_id) if artifact_id is not None else None
            )
            repos = _normalize_locked_repos((content or {}).get("repo_associations"))
            if repos:
                return repos
        except Exception as exc:  # noqa: BLE001 — 读失败回落快照，绝不上抛
            logger.warning(
                "blueprint_repo_plan_locked_repos_load_failed",
                session_id=str(getattr(session, "id", "")),
                error=redact_secrets_in_text(str(exc)),
                category="sampling",
                component="process_runtime",
            )
        stage_state = getattr(session, "stage_state", None) or {}
        snapshot = stage_state.get("confirmation") if isinstance(stage_state, dict) else None
        return _normalize_locked_repos(_iter_snapshot_repos(snapshot))

    # ── 派发主入口 ────────────────────────────────────────────────────────

    async def dispatch_plans(self, session: Any) -> dict:
        """逐仓拟方案（**增量 + 按波次**）：direct 起容器、indirect 服务端合成。

        返回形状**恒定五键** `{dispatched, synthesized, pending, completed, repositories}`
        （113-03 已把它作为契约声明给下游，本 plan 不加键；波次摘要请另调 `aplan_waves`）。
        已产出 `repo_plan` 段的仓不重派（T-113-16）。

        **波次推进语义（BUS-02 第一道防线）**：每次调用只派发**当前可派发波次**的仓 ——
        即「按 API provider/consumer 关系分层后，最早那一波里还没产出 `repo_plan` 的仓」。
        后续波次的仓本轮进 `pending`；前一波产出后 barrier 续驱会再进本函数，此时下一波
        自然变成「当前波次」被派发。这样 provider 仓先行，consumer 仓开工时契约已在总线上，
        `await_blueprint_context` 只需兜预排推不出的动态依赖。零依赖输入 ⇒ 全部在 wave 1，
        与预排前的全并行行为逐字一致。
        """
        started = time.monotonic()
        repos = await self.acollect_locked_repos(session)
        if not repos:
            return {
                "dispatched": 0,
                "synthesized": 0,
                "pending": 0,
                "completed": [],
                "repositories": [],
            }

        logger.info(
            "blueprint_repo_plan_dispatch_started",
            session_id=str(getattr(session, "id", "")),
            repo_count=len(repos),
            category="sampling",
            component="process_runtime",
        )

        existing = await self.acollect_repo_plans(session)
        prearrange = await self.aplan_waves(session, repos=repos, plans=existing)
        waves = prearrange.get("waves") or {}
        current_wave, dispatchable = _current_wave(waves, completed=set(existing))
        task_map = await self._aload_task_map(getattr(session, "id", None))
        # 显式门控（MJ-02）：仍有 active waiter 的仓本轮不重派 —— 它等的 key 还没上总线，
        # 现在起容器只会再等一次然后再退出（白烧一份容器额度，同仓还会出现双容器）。
        # 它的重派由**写入侧** `satisfy_waiters` → `aredispatch_waiting_repos` 或超龄清理驱动。
        waiting = await self.aactive_waiting_repository_ids(session)
        dispatched = 0
        synthesized = 0
        completed: list[str] = []
        pending: list[str] = []

        for repo in repos:
            repository_id = repo["repository_id"]
            if existing.get(repository_id):
                completed.append(repository_id)
                continue
            if repository_id in waiting:
                pending.append(repository_id)
                continue
            if dispatchable and repository_id not in dispatchable:
                # 后续波次：等前一波 provider 仓产出契约后由 barrier 续驱推进（见 docstring）。
                pending.append(repository_id)
                continue
            try:
                if repo.get("role") == "indirect":
                    if await self._asynthesize_indirect_plan(session, repo):
                        synthesized += 1
                        completed.append(repository_id)
                    else:
                        pending.append(repository_id)
                    continue
                dispatched += await self._adispatch_direct_plan(
                    session, repo, task=task_map.get(repository_id)
                )
                pending.append(repository_id)
                # 每仓 `repo_plan.repo_started` 事件由派发漏斗（research_adapter.dispatch 的
                # mode 分流）发射（quick-260806 观测整改）：此前这里与漏斗各发一条 ——
                # stage 路径双发、绕过本 handler 的重派路径（waiter 重派 / 手动单仓）零痕迹。
            except Exception as exc:  # noqa: BLE001 — WR-02 单仓隔离，绝不上抛
                pending.append(repository_id)
                logger.warning(
                    "blueprint_repo_plan_dispatch_failed",
                    session_id=str(getattr(session, "id", "")),
                    repository_id=repository_id,
                    error=redact_secrets_in_text(str(exc)),
                    category="sampling",
                    component="process_runtime",
                )

        # 118（LIVE-03）：波次推进可见（第几波 / 共几波 / 本波几个仓）
        #
        # ⚠️ 只在**真有波次可派**时发：`_current_wave` 在「所有波次都已产出」时按约定返回
        # `(0, set())`，那是一次 no-op 续驱（barrier 每收一个容器回调都会再进本函数）。
        # 无条件发会在活动流里堆一串「进入第 0/N 波，本波 0 个仓」——用户读到的是
        # 「波次算错了」，其实是「这一趟什么都没派」。⛔ 不要为了「事件连续」而发空事件。
        if dispatchable:
            await self._aemit_wave_advanced(
                session,
                wave=current_wave,
                total_waves=len(waves),
                repository_count=len(dispatchable),
            )
        logger.info(
            "blueprint_repo_plan_dispatch_completed",
            session_id=str(getattr(session, "id", "")),
            dispatched=dispatched,
            synthesized=synthesized,
            pending=len(pending),
            completed_count=len(completed),
            current_wave=current_wave,
            wave_count=len(waves),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            category="sampling",
            component="process_runtime",
        )
        return {
            "dispatched": dispatched,
            "synthesized": synthesized,
            "pending": len(pending),
            "completed": completed,
            "repositories": [repo["repository_id"] for repo in repos],
        }

    # ── 波次预排（第一道防线：provider 仓先行） ─────────────────────────────

    async def aplan_waves(
        self, session: Any, *, repos: list[dict] | None = None, plans: dict | None = None
    ) -> dict:
        """按 API provider/consumer 关系预排波次；成环立即开 blocking 澄清交人裁决。

        输入优先用已产出的 `repo_plan` 段（`apis_provided` / `apis_consumed` 权威），首轮
        尚无产物时回落确认门锁定条目自带的接口信息（没有就是空 ⇒ 全并行，零回归）。

        返回 `build_api_waves` 的四键结果**再加** `stage_state_summary`（`{waves, cycle_count,
        unresolved_count}`）—— 本仓约定 stage_state 由 handler 持久化，adapter 只产出摘要：
        并行容器高频写单行 JSON 会 lost-update（PLAN prohibitions 明令 waiter 状态不进
        stage_state，波次摘要同理只走 handler 的单点写）。摘要口径与 `build_stage_state(waves=…)`
        一致，113-06 直接透传即可。
        """
        repos = repos if repos is not None else await self.acollect_locked_repos(session)
        plans = plans if plans is not None else await self.acollect_repo_plans(session)
        inputs: dict[str, dict] = {}
        for repo in repos:
            repository_id = repo["repository_id"]
            section = plans.get(repository_id) or {}
            inputs[repository_id] = {
                "apis_provided": _api_items(section, repo, "apis_provided"),
                "apis_consumed": _api_items(section, repo, "apis_consumed"),
            }
        result = build_api_waves(inputs)
        cycles = result.get("cycles") or []
        if cycles:
            await self._aopen_cycle_clarification(session, cycles, result.get("edges") or [])
        logger.info(
            "blueprint_repo_plan_waves_planned",
            session_id=str(getattr(session, "id", "")),
            wave_count=len(result.get("waves") or {}),
            edge_count=len(result.get("edges") or []),
            cycle_count=len(cycles),
            unresolved_count=len(result.get("unresolved_consumed") or []),
            category="sampling",
            component="process_runtime",
        )
        return {
            **result,
            "stage_state_summary": {
                "waves": {
                    int(wave): list(ids) for wave, ids in (result.get("waves") or {}).items()
                },
                "cycle_count": len(cycles),
                "unresolved_count": len(result.get("unresolved_consumed") or []),
            },
        }

    async def _aopen_cycle_clarification(
        self, session: Any, cycles: list[list[str]], edges: list[dict]
    ) -> str:
        """互等环 → 开一条 blocking 澄清线程交人裁决（**不静默打平波次**）。

        幂等：该 artifact 上已有 OPEN 的 blocking `ai_clarification` 线程时不再叠开 ——
        会话已被阻塞，重复开线程只会刷 HITL 面板。`return_stage="repo_plan"` 必填（B3）。
        question 只含仓 id 与 api 名，**不含任何方案正文**。
        """
        try:
            artifact = await self._aload_artifact(getattr(session, "id", None))
            if artifact is None:
                logger.warning(
                    "blueprint_repo_plan_wave_cycle_no_artifact",
                    session_id=str(getattr(session, "id", "")),
                    cycle_count=len(cycles),
                    category="sampling",
                    component="process_runtime",
                )
                return ""
            if await self._acount_open_blocking_clarifications(artifact.id):
                return ""
            cycle_text = "；".join(" ⇄ ".join(cycle) for cycle in cycles)
            api_text = "、".join(
                sorted(
                    {
                        str(edge.get("api") or "")
                        for edge in edges
                        if str(edge.get("api") or "")
                        and any(str(edge.get("from") or "") in cycle for cycle in cycles)
                    }
                )
            )
            thread = await self._get_lifecycle_service().open_thread(
                artifact,
                kind="ai_clarification",
                blocking=True,
                question=(
                    f"检测到仓库间接口互相等待（成环）：{cycle_text}。"
                    f"涉及的接口：{api_text or '（未指明）'}。"
                    "请裁决由哪一侧先定契约（或拆出中间层），否则这些仓无法排出先后顺序。"
                ),
                initiated_by_user_id=_initiated_by(session),
                return_stage="repo_plan",
            )
            thread_id = str(getattr(thread, "id", "") or "")
            logger.info(
                "blueprint_repo_plan_wave_cycle_clarification_opened",
                session_id=str(getattr(session, "id", "")),
                cycle_count=len(cycles),
                thread_id=thread_id,
                initiated_by_user_id=_initiated_by(session),
                category="caller",
                component="process_runtime",
            )
            return thread_id
        except Exception as exc:  # noqa: BLE001 — 开线程失败不反噬派发主链
            logger.warning(
                "blueprint_repo_plan_wave_cycle_clarification_failed",
                session_id=str(getattr(session, "id", "")),
                error=redact_secrets_in_text(str(exc))[:_MAX_ERROR_CHARS],
                category="sampling",
                component="process_runtime",
            )
            return ""

    # ── waiter 满足后的自动重派（长等待闭环） ───────────────────────────────

    async def aredispatch_waiting_repos(self, session: Any, repository_ids: list) -> int:
        """把 `satisfy_waiters` 返回的等待仓重新派发续作，返回真正重派的仓数。

        逐仓 `mark_stale`（WR-01：只有终态 task 能置回可派发白名单）后走
        `dispatch(session, mode="plan", repository_ids={rid})` 的单仓定向通路 —— 复用 112 的
        增量派发白名单，已完成仓天然被跳过。prompt 带**上一轮 partial 产物引用**续作
        （`partial_plan_id` + 已产出的段名），非续作场景该段为空串、prompt 与首轮逐字一致。

        单仓失败只记 warning 并继续（WR-02），**绝不上抛** —— 本方法的调用方是 MCP
        `report_blueprint_context` 端点，上抛会反噬容器的写入响应。
        """
        ids = [str(rid) for rid in (repository_ids or []) if str(rid or "")]
        if not ids:
            return 0
        started = time.monotonic()
        task_map = await self._aload_task_map(getattr(session, "id", None))
        redispatched = 0
        for repository_id in ids:
            try:
                task = task_map.get(repository_id)
                if task is not None and str(task.get("status")) not in (
                    RepoResearchTaskStatus.PENDING,
                    RepoResearchTaskStatus.STALE,
                ):
                    await self.research_service.mark_stale([task["id"]])
                resume_hint = await self._aload_resume_hint(
                    getattr(session, "id", None), repository_id
                )
                result = await self.research_adapter.dispatch(
                    session,
                    mode="plan",
                    repository_ids={repository_id},
                    resume_hints={repository_id: resume_hint} if resume_hint else None,
                )
                count = int((result if isinstance(result, dict) else {}).get("dispatched") or 0)
                redispatched += count
                # 容器起停是用户可归因的调用类事件（观测规范：必须绑定触发用户）
                logger.info(
                    "blueprint_repo_plan_waiter_redispatched",
                    session_id=str(getattr(session, "id", "")),
                    repository_id=repository_id,
                    dispatched=count,
                    resumed=bool(resume_hint),
                    initiated_by_user_id=_initiated_by(session),
                    category="caller",
                    component="process_runtime",
                )
            except Exception as exc:  # noqa: BLE001 — WR-02 单仓隔离，绝不上抛
                logger.warning(
                    "blueprint_repo_plan_waiter_redispatch_failed",
                    session_id=str(getattr(session, "id", "")),
                    repository_id=repository_id,
                    error=redact_secrets_in_text(str(exc))[:_MAX_ERROR_CHARS],
                    category="sampling",
                    component="process_runtime",
                )
        logger.info(
            "blueprint_repo_plan_waiter_redispatch_completed",
            session_id=str(getattr(session, "id", "")),
            requested=len(ids),
            redispatched=redispatched,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            category="sampling",
            component="process_runtime",
        )
        return redispatched

    async def aactive_waiting_repository_ids(self, session: Any) -> set[str]:
        """仍有 active waiter 的仓集（委托 `BlueprintContextService`，读失败返回空集合）。"""
        try:
            from delivery.services.blueprint_context_service import BlueprintContextService

            return await BlueprintContextService().aactive_waiting_repository_ids(session)
        except Exception as exc:  # noqa: BLE001 — 门控读失败按「无人在等」处理，不阻塞派发
            logger.warning(
                "blueprint_repo_plan_active_waiters_read_failed",
                session_id=str(getattr(session, "id", "")),
                error=redact_secrets_in_text(str(exc))[:_MAX_ERROR_CHARS],
                category="sampling",
                component="process_runtime",
            )
            return set()

    async def aall_locked_repos_waiting(self, session: Any) -> bool:
        """全员长等待判据（MJ-03）：**没有任何容器在途**且每个未完成仓都在等一个 key。

        这是「所有容器都以 `waiting_context` 退出」那条闭合死路的可判定形状：容器都退出了
        ⇒ 不会再有回调 ⇒ 不会再 advance ⇒ 超龄清理与 stuck 探测都到不了。判 True 的调用方
        应当**立刻开阻塞澄清**让死锁可见（而不是让会话无声悬挂在 waiting_event）。

        「在途」只算 `pending`/`running`：`stale` 在本相位语义是「等 key 的可重派态」，
        把它算成在途会让本判据恒为 False（`aall_research_tasks_terminal` 正是这个口径，
        故**不复用**它）。无锁定仓 / 全部已产出 → False（没有死锁可言）。
        """
        repos = await self.acollect_locked_repos(session)
        if not repos:
            return False
        plans = await self.acollect_repo_plans(session)
        task_map = await self._aload_task_map(getattr(session, "id", None))
        waiting = await self.aactive_waiting_repository_ids(session)
        outstanding = 0
        for repo in repos:
            repository_id = repo["repository_id"]
            if plans.get(repository_id):
                continue
            status = str((task_map.get(repository_id) or {}).get("status") or "")
            if status in (RepoResearchTaskStatus.PENDING, RepoResearchTaskStatus.RUNNING):
                return False  # 还有容器在途/待派，等它回调即可
            if str(status) == RepoResearchTaskStatus.FAILED:
                continue  # 失败仓不阻塞 barrier（由 merge 阶段标未决项）
            if repository_id not in waiting:
                return False  # 有仓既不在途也不在等 ⇒ 下一轮派发能推进，不是死锁
            outstanding += 1
        return outstanding > 0

    async def aopen_deadlock_clarification(self, session: Any, repository_ids: list) -> str:
        """全员长等待 → 开一条 blocking 澄清让死锁可见（幂等，`return_stage="repo_plan"`）。

        与 `_aopen_cycle_clarification` 同一幂等口径（已有 OPEN blocking 线程就不叠开）。
        question 只含仓 id 与「都在等待」这一事实，**不含任何 key 正文或方案正文**。
        """
        try:
            artifact = await self._aload_artifact(getattr(session, "id", None))
            if artifact is None:
                logger.warning(
                    "blueprint_repo_plan_deadlock_no_artifact",
                    session_id=str(getattr(session, "id", "")),
                    category="sampling",
                    component="process_runtime",
                )
                return ""
            if await self._acount_open_blocking_clarifications(artifact.id):
                return ""
            repo_text = "、".join(
                sorted(str(rid) for rid in (repository_ids or []) if str(rid or ""))
            )
            thread = await self._get_lifecycle_service().open_thread(
                artifact,
                kind="ai_clarification",
                blocking=True,
                question=(
                    "本轮所有待拟方案的仓库都在等待其他仓的接口契约，已没有任何容器在跑"
                    f"（涉及仓库：{repo_text or '（未指明）'}）。"
                    "请裁决由哪一侧先定契约、或确认某个依赖可以先按假设推进。"
                ),
                initiated_by_user_id=_initiated_by(session),
                return_stage="repo_plan",
            )
            thread_id = str(getattr(thread, "id", "") or "")
            logger.info(
                "blueprint_repo_plan_all_waiting_clarification_opened",
                session_id=str(getattr(session, "id", "")),
                repo_count=len(repository_ids or []),
                thread_id=thread_id,
                initiated_by_user_id=_initiated_by(session),
                category="caller",
                component="process_runtime",
            )
            return thread_id
        except Exception as exc:  # noqa: BLE001 — 开线程失败不反噬回调主链
            logger.warning(
                "blueprint_repo_plan_all_waiting_clarification_failed",
                session_id=str(getattr(session, "id", "")),
                error=redact_secrets_in_text(str(exc))[:_MAX_ERROR_CHARS],
                category="sampling",
                component="process_runtime",
            )
            return ""

    async def aexpire_stale_waiters(
        self, session: Any, *, max_age_seconds: int = DEFAULT_WAITER_MAX_AGE_SECONDS
    ) -> list[str]:
        """清理超龄 waiter 并返回待重派仓清单（委托 `BlueprintContextService.expire_waiters`）。

        **不新起定时任务**（CONTEXT 锁定）。**两个挂载点**（MJ-03：只挂 barrier 不够）：

        1. barrier 续驱路径（`_h_bp_repo_plan`，113-06）——正常推进时每轮清一次；
        2. **容器 `waiting_context` 退出的回调路径**（`callbacks._ahandle_blueprint_waiting_context`）
           ——barrier 只能由 engine advance 驱动，而 advance 在本链只由容器回调触发：当**本波
           全部容器都以 `waiting_context` 退出**时容器已全退、回调不再来、barrier 因此永不可达，
           清理挂在它上面等于在最需要它的状态下失效。挂到「退出瞬间」才有可达路径。

        读失败一律返回 `[]`（观测代码不反噬业务）。
        """
        try:
            from delivery.services.blueprint_context_service import BlueprintContextService

            return await BlueprintContextService().expire_waiters(
                session=session,
                max_age_seconds=int(max_age_seconds or 0),
                initiated_by_user_id=_initiated_by(session),
            )
        except Exception as exc:  # noqa: BLE001 — 清理失败不反噬 barrier
            logger.warning(
                "blueprint_repo_plan_waiter_expire_failed",
                session_id=str(getattr(session, "id", "")),
                error=redact_secrets_in_text(str(exc))[:_MAX_ERROR_CHARS],
                category="sampling",
                component="process_runtime",
            )
            return []

    async def _adispatch_direct_plan(self, session: Any, repo: dict, *, task: dict | None) -> int:
        """direct 仓起 plan 容器：先置回可派发态，再复用派发面的 `mode="plan"`。

        **必须先 `mark_stale`**：阶段 2 复用阶段 1 的同一 `RepoResearchTask`，而
        `record_partial` 已把它置 DONE —— 不置 stale 则派发面的可派发白名单判定为终态直接
        skip，plan 容器永不启动（与 112-04 Deviation 1 同源的静默失效模式）。
        """
        repository_id = repo["repository_id"]
        if task is not None and str(task.get("status")) not in (
            RepoResearchTaskStatus.PENDING,
            RepoResearchTaskStatus.STALE,
        ):
            await self.research_service.mark_stale([task["id"]])
        result = await self.research_adapter.dispatch(
            session, mode="plan", repository_ids={repository_id}
        )
        result = result if isinstance(result, dict) else {}
        dispatched = int(result.get("dispatched") or 0)
        if result.get("degraded"):
            # plan 模式不做轻量降级（那会挤掉 repo_plan 段）——无 runner 时该仓保持待办。
            logger.warning(
                "blueprint_repo_plan_dispatch_no_runner",
                session_id=str(getattr(session, "id", "")),
                repository_id=repository_id,
                category="sampling",
                component="process_runtime",
            )
        # 容器动作是用户可归因的调用类事件（观测规范：必须绑定触发用户）
        logger.info(
            "blueprint_repo_plan_container_dispatched",
            session_id=str(getattr(session, "id", "")),
            repository_id=repository_id,
            dispatched=dispatched,
            initiated_by_user_id=_initiated_by(session),
            category="caller",
            component="process_runtime",
        )
        return dispatched

    # ── indirect 仓：服务端 LLM 合成（不起容器） ───────────────────────────

    async def _asynthesize_indirect_plan(self, session: Any, repo: dict) -> bool:
        """indirect 仓的能力引用清单：与 direct 同形落 `PartialPlan.content.repo_plan`。

        产物过 `validate_repo_plan`；不合格重试至 `MAX_REPO_PLAN_ATTEMPTS`，仍不合格则开
        blocking 澄清线程并落一份 **degraded 但合法**的最小 repo_plan（`impl_items=[]` +
        risks 记明缺失原因）——**绝不静默丢弃**（T-113-13）。
        """
        repository_id = repo["repository_id"]
        task = await self._aensure_task(session, repository_id)
        if task is None:
            return False

        section: dict | None = None
        last_error = ""
        for _attempt in range(MAX_REPO_PLAN_ATTEMPTS + 1):
            try:
                raw = await self.synthesizer.synthesize(session, repo)
            except Exception as exc:  # noqa: BLE001 — 合成失败按「本轮不合格」处理
                last_error = redact_secrets_in_text(str(exc))[:_MAX_ERROR_CHARS]
                continue
            candidate = _extract_section(raw)
            candidate = _apply_authoritative_fields(candidate, repo)
            ok, err = validate_repo_plan(candidate)
            if ok:
                section = candidate
                break
            last_error = str(err or "")[:_MAX_ERROR_CHARS]

        if section is None:
            thread_id = await self.aopen_clarification(session, repository_id, last_error)
            section = _degraded_section(repo, reason=last_error, thread_id=thread_id)
            ok, err = validate_repo_plan(section)
            if not ok:
                # 兜底产物自身非法 = 本文件的 bug；宁可留待下轮也不落非法 content。
                logger.warning(
                    "blueprint_repo_plan_degraded_section_invalid",
                    session_id=str(getattr(session, "id", "")),
                    repository_id=repository_id,
                    error=str(err or "")[:_MAX_ERROR_CHARS],
                    category="sampling",
                    component="process_runtime",
                )
                return False

        await self.arecord_repo_plan(task, section)
        logger.info(
            "blueprint_repo_plan_indirect_synthesized",
            session_id=str(getattr(session, "id", "")),
            repository_id=repository_id,
            degraded=bool(last_error),
            item_count=len(section.get("impl_items") or []),
            category="sampling",
            component="process_runtime",
        )
        return True

    # ── 落库唯一入口（读-合并-写） ─────────────────────────────────────────

    async def arecord_repo_plan(self, task: Any, repo_plan_section: dict) -> Any:
        """写 `repo_plan` 段的**唯一入口**：读最新 content → 浅合并 → `record_partial`。

        ⚠️ 裸传 `{"repo_plan": ...}` 会让 `acollect_fitness` 读到空 fitness —— `record_partial`
        每次都 `create` 全量新行，而下游只取最新一行，确认门快照与投影全线失血（P-1）。
        """
        prev = await self._aload_latest_valid_content(task)
        content = {**prev, "repo_plan": repo_plan_section}
        # repository_id 由服务端权威写入，不采信容器/LLM 上报值
        content["repository_id"] = str(getattr(task, "repository_id", "") or "")
        partial = await self.research_service.record_partial(task, content)
        # 118（LIVE-03）：该仓分仓方案落库即可见（产出了多少实现项 / 多少接口契约）
        await self._aemit_repo_plan_completed(task, repo_plan_section)
        return partial

    # ── 活动流埋点（118，LIVE-03；均 best-effort，绝不反噬业务）──────────────
    # ⭐ 每仓 `repo_plan.repo_started` 的发射点已收敛到派发漏斗
    # （blueprint_research_adapter._emit_started 的 mode 分流），本文件不再发射。

    async def _aemit_wave_advanced(
        self, session: Any, *, wave: Any, total_waves: int, repository_count: int
    ) -> None:
        try:
            from delivery.services.convergence_session_service import ConvergenceSessionService
            from delivery.services.event_taxonomy import (
                EVENT_BLUEPRINT_REPO_PLAN_WAVE_ADVANCED,
            )

            await ConvergenceSessionService().aemit_event(
                EVENT_BLUEPRINT_REPO_PLAN_WAVE_ADVANCED,
                session,
                {
                    "wave": wave,
                    "total_waves": int(total_waves or 0),
                    "repository_count": int(repository_count or 0),
                },
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort
            pass

    async def _aemit_repo_plan_completed(self, task: Any, repo_plan_section: Any) -> None:
        """该仓分仓方案落库 → `blueprint.repo_plan.repo_completed`（只带计数，⛔ 不带方案正文）。

        会话经 ``task.session_id`` 反查（本方法的入参只有 task）：⛔ 不访问 lazy-FK
        ``task.session``，那在 async 上下文里会抛 ``SynchronousOnlyOperation``。

        ⚠️ 计数键**必须**取 ``blueprint_repo_plan_schema`` 的真实字段名：本段是 RepoPlan
        中间产物，实现项叫 ``impl_items``、接口分 ``apis_provided`` / ``apis_consumed``。
        曾误读蓝图顶层的 ``implementation_items`` / ``api_contracts``（RepoPlan 段里**根本
        不存在**这两个键）⇒ 两个计数恒为 0，界面上每个仓都是「0 项实现 · 0 条接口」。
        """
        try:
            from delivery.models import ConvergenceSession
            from delivery.services.convergence_session_service import ConvergenceSessionService
            from delivery.services.event_taxonomy import (
                EVENT_BLUEPRINT_REPO_PLAN_REPO_COMPLETED,
            )

            session_id = getattr(task, "session_id", None)
            if not session_id:
                return
            session = await ConvergenceSession.objects.filter(id=session_id).afirst()
            if session is None:
                return
            section = repo_plan_section if isinstance(repo_plan_section, dict) else {}
            provided = section.get("apis_provided") or []
            consumed = section.get("apis_consumed") or []
            await ConvergenceSessionService().aemit_event(
                EVENT_BLUEPRINT_REPO_PLAN_REPO_COMPLETED,
                session,
                {
                    "repository_id": str(getattr(task, "repository_id", "") or ""),
                    "role": str(section.get("role") or ""),
                    "item_count": len(section.get("impl_items") or []),
                    # `api_count` 保持「本仓涉及的接口契约总数」口径（前端既有消费方按它显示），
                    # 供需两侧再各给一个分项，让「提供 3 条 / 消费 1 条」可核对。
                    "api_count": len(provided) + len(consumed),
                    "api_provided_count": len(provided),
                    "api_consumed_count": len(consumed),
                    "current_state_count": len(section.get("current_state") or []),
                    "risk_count": len(section.get("risks") or []),
                    "open_question_count": len(section.get("open_question_thread_ids") or []),
                },
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort
            pass

    # ── 产物读取与完成判据 ────────────────────────────────────────────────

    async def acollect_repo_plans(self, session: Any) -> dict[str, dict]:
        """按仓聚合**最新有效**的 `repo_plan` 段：`{repository_id: repo_plan}`。

        一仓多条 `PartialPlan` 按三要素取最新（与 `acollect_fitness` 逐字同口径）：
        `valid=True` 过滤 + `-created_at` 降序 + 每 `research_task_id` 只取首见。
        历史行不被覆盖，只是不作为该仓 canonical 产物。
        """
        try:
            return await self._acollect_repo_plans_sync(getattr(session, "id", None))
        except Exception as exc:  # noqa: BLE001 — 读失败按「无产物」处理（判据保守为未完成）
            logger.warning(
                "blueprint_repo_plan_collect_failed",
                session_id=str(getattr(session, "id", "")),
                error=redact_secrets_in_text(str(exc)),
                category="sampling",
                component="process_runtime",
            )
            return {}

    async def aall_repo_plans_ready(self, session: Any) -> bool:
        """阶段 2 的**自写完成判据**（供 113-06 的 handler 调用）。

        判据 = 锁定仓集里每个仓都有非空 `repo_plan` 段，或该仓 task 已 `failed`（失败仓不
        阻塞 barrier，由 merge 阶段标未决项）。**只看 `repo_plan` 段存在性 + 失败终态**，
        不看 `done`/`stale`：阶段 1 与阶段 2 复用同一 task，`done` 在两阶段都出现，而
        `mark_stale` 会让「全部终态」类判据短暂为假。
        """
        repos = await self.acollect_locked_repos(session)
        if not repos:
            return True
        plans = await self.acollect_repo_plans(session)
        task_map = await self._aload_task_map(getattr(session, "id", None))
        for repo in repos:
            repository_id = repo["repository_id"]
            if plans.get(repository_id):
                continue
            task = task_map.get(repository_id) or {}
            if str(task.get("status")) == RepoResearchTaskStatus.FAILED:
                continue
            return False
        return True

    # ── 单仓定向补调研（复用既有通路，不新建机制） ──────────────────────────

    async def arequest_targeted_research(self, session: Any, repository_id: str) -> bool:
        """阶段 2 中对某仓发起定向补调研：直接委托既有 `aupgrade_to_deep`。

        内部走 `dispatch(force_deep_repository_ids={rid})`（`mode` 缺省 research），复用
        112 的增量派发白名单与单仓隔离，**不新建机制**。返回其 bool（False = 未受理）。
        """
        return bool(await self.research_adapter.aupgrade_to_deep(session, str(repository_id or "")))

    # ── stage_state 小摘要 ────────────────────────────────────────────────

    def build_stage_state(
        self,
        *,
        plans: dict,
        dispatched: list,
        pending: list,
        attempts: dict | None = None,
        waves: dict | None = None,
    ) -> dict:
        """`stage_state["repo_plan"]` 小摘要：**只存 id 与计数**（单字段 < 2KB，DESIGN §5.6）。

        方案正文一律由下游按 `repository_id` 自取 `PartialPlan`，绝不往 `stage_state` 里塞。
        `waves` 传 `aplan_waves` 结果里的 `stage_state_summary`（`{waves, cycle_count,
        unresolved_count}`）即可；不传则不写该键（波次是可选摘要，缺失不影响完成判据）。
        """
        ready = sorted(str(rid) for rid, section in (plans or {}).items() if section)
        pending_ids = sorted({str(rid) for rid in (pending or []) if str(rid or "")} - set(ready))
        counter = {
            str(rid): int(count or 0) for rid, count in (attempts or {}).items() if str(rid or "")
        }
        for rid in dispatched or []:
            counter.setdefault(str(rid), 1)
        state = {
            "ready_repository_ids": ready,
            "pending_repository_ids": pending_ids,
            "attempts": counter,
        }
        if isinstance(waves, dict) and waves:
            state["waves"] = {
                "waves": {
                    str(wave): [str(rid) for rid in ids]
                    for wave, ids in (waves.get("waves") or {}).items()
                },
                "cycle_count": int(waves.get("cycle_count") or 0),
                "unresolved_count": int(waves.get("unresolved_count") or 0),
            }
        return state

    # ── 澄清线程（唯一入口经 lifecycle service） ────────────────────────────

    async def aopen_clarification(self, session: Any, repository_id: str, detail: str) -> str:
        """开一条阻塞澄清线程；`return_stage` **必填**（B3），否则恢复会退回阶段 1。

        question 只含仓名与缺失字段说明，**不含 content 正文**（半可信正文不进 HITL 面板）。
        best-effort：开不出线程只记 warning 并返回空串，绝不反噬主链。
        """
        try:
            artifact = await self._aload_artifact(getattr(session, "id", None))
            if artifact is None:
                logger.warning(
                    "blueprint_repo_plan_clarification_no_artifact",
                    session_id=str(getattr(session, "id", "")),
                    repository_id=repository_id,
                    category="sampling",
                    component="process_runtime",
                )
                return ""
            thread = await self._get_lifecycle_service().open_thread(
                artifact,
                kind="ai_clarification",
                blocking=True,
                question=(
                    f"仓库 {repository_id} 的分仓方案连续 {MAX_REPO_PLAN_ATTEMPTS + 1} 次未能"
                    f"产出合规结构，请补充信息或调整该仓职责。校验失败原因："
                    f"{str(detail or '')[:_MAX_ERROR_CHARS] or '未知'}"
                ),
                initiated_by_user_id=_initiated_by(session),
                # B3：漏传会让 `blueprint_resume` 无 stage 依据、阶段 2 的澄清恢复退回阶段 1
                return_stage="repo_plan",
            )
            thread_id = str(getattr(thread, "id", "") or "")
            logger.info(
                "blueprint_repo_plan_clarification_opened",
                session_id=str(getattr(session, "id", "")),
                repository_id=repository_id,
                thread_id=thread_id,
                initiated_by_user_id=_initiated_by(session),
                category="caller",
                component="process_runtime",
            )
            return thread_id
        except Exception as exc:  # noqa: BLE001 — 开线程失败不反噬主链
            logger.warning(
                "blueprint_repo_plan_clarification_failed",
                session_id=str(getattr(session, "id", "")),
                repository_id=repository_id,
                error=redact_secrets_in_text(str(exc)),
                category="sampling",
                component="process_runtime",
            )
            return ""

    def _get_lifecycle_service(self) -> Any:
        if self._lifecycle_service is not None:
            return self._lifecycle_service
        from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

        return BlueprintLifecycleService()

    # ── ORM 只读边界（全部经 sync_to_async / afirst，不裸访问 lazy-FK） ──────

    async def _aensure_task(self, session: Any, repository_id: str) -> Any:
        """取该仓的 `RepoResearchTask`；缺失则经 service 幂等新建（阶段 2 才纳入的仓）。"""
        tasks = await self.research_service.create_tasks_for_session(
            session, [{"repository_id": repository_id, "routed_confidence": ""}]
        )
        for task in tasks or []:
            if str(getattr(task, "repository_id", "")) == str(repository_id):
                return task
        return None

    @staticmethod
    @sync_to_async
    def _aresolve_artifact_id(session_id: Any) -> Any:
        """会话 → artifact id（只取标量，async 安全）。"""
        from delivery.models import ConvergenceSession

        return (
            ConvergenceSession.objects.filter(id=session_id)
            .values_list("current_artifact_version__artifact_id", flat=True)
            .first()
        )

    @staticmethod
    async def _aload_latest_content(artifact_id: Any) -> dict | None:
        """artifact 的**最新**版本 content（`order_by("-version_no")`，绝不读会话钉住的版本）。"""
        from delivery.models import ArtifactVersion

        row = await (
            ArtifactVersion.objects.filter(artifact_id=artifact_id)
            .order_by("-version_no")
            .values("content")
            .afirst()
        )
        content = (row or {}).get("content")
        return content if isinstance(content, dict) else {}

    @staticmethod
    async def _aload_artifact(session_id: Any) -> Any:
        from delivery.models import Artifact, ConvergenceSession

        artifact_id = await (
            ConvergenceSession.objects.filter(id=session_id)
            .values_list("current_artifact_version__artifact_id", flat=True)
            .afirst()
        )
        if not artifact_id:
            return None
        return await Artifact.objects.filter(id=artifact_id).afirst()

    @staticmethod
    @sync_to_async
    def _acount_open_blocking_clarifications(artifact_id: Any) -> int:
        """该 artifact 上 OPEN 的阻塞澄清线程数（幂等守门：已有阻塞就不再叠开）。"""
        from delivery.models import BlueprintThread, ThreadKind, ThreadStatus

        return BlueprintThread.objects.filter(
            artifact_id=artifact_id,
            kind=ThreadKind.AI_CLARIFICATION,
            blocking=True,
            status=ThreadStatus.OPEN,
        ).count()

    @staticmethod
    @sync_to_async
    def _aload_resume_hint(session_id: Any, repository_id: str) -> dict:
        """该仓最新 `PartialPlan` 的续作引用：`{partial_plan_id, produced_keys}`。

        只取 **id 与段名**（不取正文）—— 续作提示进的是容器 prompt，正文由容器自己按
        partial_plan_id 与总线取回，避免 prompt 膨胀与半可信正文二次拼接。
        """
        from delivery.models import PartialPlan, RepoResearchTask

        task_ids = list(
            RepoResearchTask.objects.filter(
                session_id=session_id, repository_id=repository_id
            ).values_list("id", flat=True)
        )
        if not task_ids:
            return {}
        row = (
            PartialPlan.objects.filter(research_task_id__in=task_ids)
            .order_by("-created_at")
            .values("id", "content")
            .first()
        )
        if not row:
            return {}
        content = row.get("content")
        content = content if isinstance(content, dict) else {}
        return {
            "partial_plan_id": str(row["id"]),
            "produced_keys": sorted(str(key) for key in content if str(key or "")),
        }

    @staticmethod
    @sync_to_async
    def _aload_task_map(session_id: Any) -> dict[str, dict]:
        from delivery.models import RepoResearchTask

        rows = RepoResearchTask.objects.filter(session_id=session_id).values(
            "id", "repository_id", "status", "attempt"
        )
        return {
            str(row["repository_id"]): {
                "id": row["id"],
                "status": str(row["status"]),
                "attempt": int(row["attempt"] or 0),
            }
            for row in rows
        }

    @staticmethod
    @sync_to_async
    def _acollect_repo_plans_sync(session_id: Any) -> dict[str, dict]:
        from delivery.models import PartialPlan, RepoResearchTask

        tasks = dict(
            RepoResearchTask.objects.filter(session_id=session_id).values_list(
                "id", "repository_id"
            )
        )
        if not tasks:
            return {}
        latest: dict[Any, dict] = {}
        rows = (
            PartialPlan.objects.filter(research_task__session_id=session_id, valid=True)
            .order_by("-created_at")
            .values("research_task_id", "content")
        )
        for row in rows:
            # 降序取首见即最新（每 task 只取一条）
            latest.setdefault(row["research_task_id"], row["content"] or {})
        collected: dict[str, dict] = {}
        for task_id, repository_id in tasks.items():
            content = latest.get(task_id) or {}
            section = content.get("repo_plan") if isinstance(content, dict) else None
            if isinstance(section, dict) and section:
                collected[str(repository_id)] = section
        return collected

    @staticmethod
    @sync_to_async
    def _aload_latest_valid_content(task: Any) -> dict:
        """该 task 最新 content（读-合并-写的「读」）。

        优先 `valid=True` 的最新一行；**全部失效时回落最新的失效行** —— 阶段 2 派发前会
        `mark_stale` 把阶段 1 的行置 `valid=False`，只认 valid 会让合并基线变空，
        `repo_plan` 落库时把 112 的 fitness / findings / §7 五键一起吃掉（正是 P-1 要防的）。
        """
        from delivery.models import PartialPlan

        for valid_only in (True, False):
            query = PartialPlan.objects.filter(research_task=task)
            if valid_only:
                query = query.filter(valid=True)
            row = query.order_by("-created_at").values("content").first()
            content = (row or {}).get("content")
            if isinstance(content, dict) and content:
                return content
        return {}


# ── 模块级纯函数 ──────────────────────────────────────────────────────────


def _api_items(section: Any, repo: dict, key: str) -> list[dict]:
    """波次预排的输入项：优先已产出 `repo_plan` 段，回落确认门条目自带的接口信息。

    两处都没有就是空 list —— **绝不从 responsibility 文本里猜接口**（猜错会把仓排到错误波次，
    比全并行更糟）。首轮无产物 ⇒ 全部空 ⇒ 全并行，与预排前行为逐字一致。
    """
    for source in (section, repo):
        if not isinstance(source, dict):
            continue
        raw = source.get(key)
        if isinstance(raw, list):
            items = [item for item in raw if isinstance(item, dict)]
            if items:
                return items
    return []


def _current_wave(waves: dict, *, completed: set[str]) -> tuple[int, set[str]]:
    """当前可派发波次：最早那一波里**还有仓没产出 `repo_plan`** 的波次。

    Returns:
        `(wave_no, repository_ids)`；无波次信息时 `(0, set())` —— 调用方据此不做波次门控
        （退化为全并行，零回归）。
    """
    for wave in sorted(int(w) for w in (waves or {})):
        ids = {str(rid) for rid in (waves.get(wave) or waves.get(str(wave)) or [])}
        if ids - completed:
            return wave, ids
    return 0, set()


def _initiated_by(session: Any) -> str:
    """触发用户归因（无触发用户记 `system`，绝不伪造 actor）。"""
    return str(getattr(session, "initiated_by_user_id", "") or "") or "system"


def _normalize_locked_repos(raw: Any) -> list[dict]:
    """`repo_associations` / 确认门快照 → `[{repository_id, role, responsibility, fitness}]`。

    半可信输入逐层 `.get` 防御；`role` 非法回落 `direct`（把「要改的仓」误判成「不用改」
    的代价远高于反过来）。
    """
    if not isinstance(raw, list):
        return []
    repos: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        repository_id = str(item.get("repository_id") or "")
        if not repository_id or repository_id in seen:
            continue
        if item.get("removed") is True:
            continue
        seen.add(repository_id)
        role = str(item.get("role") or item.get("role_suggestion") or "").strip()
        if role not in _VALID_ROLES:
            role = "direct"
        fitness = item.get("fitness")
        entry = {
            "repository_id": repository_id,
            "repository_name": str(item.get("repository_name") or ""),
            "role": role,
            "responsibility": item.get("responsibility"),
            "fitness": fitness if isinstance(fitness, dict) else {},
        }
        # 波次预排的**首轮**预估输入：确认门条目若自带接口信息就带上（113-04）。
        # 没有就不造 —— `_api_items` 会退化为空、全部仓进 wave 1（全并行，零回归）。
        for api_key in ("apis_provided", "apis_consumed"):
            raw_api = item.get(api_key)
            if isinstance(raw_api, list):
                entry[api_key] = [api for api in raw_api if isinstance(api, dict)]
        repos.append(entry)
    return repos


def _iter_snapshot_repos(snapshot: Any) -> list[dict]:
    """确认门快照的仓清单（兼容 `{"repos": [...]}` 与裸 list 两种形状）。"""
    if isinstance(snapshot, dict):
        for key in ("repos", "repositories", "candidates"):
            value = snapshot.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []
    if isinstance(snapshot, list):
        return [item for item in snapshot if isinstance(item, dict)]
    return []


def _extract_section(raw: Any) -> Any:
    """产物归一：容器/LLM 可能直接给 `repo_plan` 段，也可能包一层同名顶层键。"""
    if isinstance(raw, dict) and isinstance(raw.get("repo_plan"), dict):
        return raw["repo_plan"]
    return raw


def _apply_authoritative_fields(section: Any, repo: dict) -> Any:
    """服务端权威字段覆写：`repository_id` / `role` / `responsibility` 不采信上报值。"""
    if not isinstance(section, dict):
        return section
    merged = {**section}
    merged["repository_id"] = repo["repository_id"]
    merged["role"] = repo.get("role") or "direct"
    responsibility = repo.get("responsibility")
    if isinstance(responsibility, list) and responsibility:
        merged["responsibility"] = responsibility
    return merged


def _degraded_section(repo: dict, *, reason: str, thread_id: str) -> dict:
    """有界重试耗尽后的 **degraded 但合法** 最小 repo_plan（绝不静默丢弃）。"""
    repository_id = repo["repository_id"]
    responsibility = repo.get("responsibility")
    section: dict[str, Any] = {
        "repository_id": repository_id,
        "role": repo.get("role") or "indirect",
        "impl_items": [],
        "risks": [
            {
                "block_id": f"blk_repo_plan_degraded_{repository_id}",
                "type": "paragraph",
                "text": (
                    f"本仓分仓方案未能自动产出合规结构（已重试 {MAX_REPO_PLAN_ATTEMPTS} 轮），"
                    f"已开阻塞澄清线程等待人工补充。原因：{str(reason or '')[:_MAX_ERROR_CHARS]}"
                ),
            }
        ],
        "open_question_thread_ids": [thread_id] if thread_id else [],
    }
    if isinstance(responsibility, list) and responsibility:
        section["responsibility"] = responsibility
    return section


def _content_to_text(content: Any) -> str:
    """把 LLM response.content（str / list[block]）归一化为文本。"""
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


def _parse_json(text: str) -> dict | None:
    """健壮解析：取首 `{` 到末 `}`，不 eval；非 dict 返 None。"""
    candidate = (text or "").strip()
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = candidate[start : end + 1]
    try:
        obj = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _blocks_to_text(blocks: Any) -> str:
    """Block[] → 纯文本（只取 text；prompt 只需语义文本不需渲染）。"""
    if isinstance(blocks, str):
        return blocks
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, list):
            parts.extend(entry for entry in text if isinstance(entry, str) and entry)
        elif isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)
