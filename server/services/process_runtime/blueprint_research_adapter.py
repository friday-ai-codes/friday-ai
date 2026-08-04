"""BlueprintResearchAdapter —— 阶段 1 逐仓容器调研派发（FLOW-02 / FLOW-04）。

五条契约（模块级不变量，改动前先读）：

1. **独立文件、零 import 冻结面**：本模块把 §13.2 冻结的 researching 派发范式**复制**过来
   （幂等白名单 / 单仓错误隔离 / 派发五步 / metadata 逐键 env），既不改那个文件也不 import 它。
2. **INV-6**：`RepoResearchTask` / `PartialPlan` 的写入只经 `ResearchService`；本文件不裸写
   ORM（读一律 `values()` / `afirst()` / `acount()`，async 上下文不裸访问 lazy-FK）。
3. **WR-02 单仓错误隔离**：任何单仓 dispatch 失败只标该 task 失败 + emit failed + continue，
   **绝不上抛**——上抛会被 engine 的通用 except 转成整个 session 失败（FLOW-02 要求过程可见）。
4. **PAT-02**：明文任务 token 只进 dispatch metadata（内存直进容器 env），绝不落盘、绝不进
   日志、绝不进 `ConvergenceSessionEvent` payload；prompt 正文与 git token 同样不进日志。
5. **不扩容器 MCP 白名单**（Context Bus 留给 Phase 113）：仓库章程内容**随 prompt 注入**，
   容器不需要新工具即可看到章程。

派发是**天然增量**的：候选来源 = `stage_state["routing"].candidates` ∪
`stage_state["confirmation"]` 内 `pending_research is True` 的仓，**减去**
`stage_state["reroute"]["excluded"]` 排除集；只对 `PENDING` / `STALE` 的 task 起容器或合成，
已 `running` / `done` / `failed` 的仓一律跳过。因此确认门的 `add_repo` / `reclassify_role`
让会话重进 `repo_research` 时，既有结论被保留，而被判 `unsuitable` 排除的仓不会被再次派发。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from common.logging import redact_secrets_in_text
from delivery.models import RepoResearchTaskStatus
from delivery.services import ConvergenceSessionService, ResearchService
from delivery.services.event_taxonomy import (
    EVENT_BLUEPRINT_REPO_RESEARCH_FAILED,
    EVENT_BLUEPRINT_REPO_RESEARCH_STARTED,
    EVENT_BLUEPRINT_REROUTE_TRIGGERED,
)
from services.process_runtime.blueprint_repo_plan_schema import (
    REPO_PLAN_AVAILABILITY,
    REPO_PLAN_CHANGE_TYPES,
)
from services.process_runtime.constants import MAX_REROUTE_ROUNDS as _MAX_REROUTE_ROUNDS

logger = structlog.get_logger(__name__)

__all__ = [
    "BlueprintResearchAdapter",
    "BLUEPRINT_RESEARCH_SOURCE",
    "BLUEPRINT_REPO_PLAN_SOURCE",
    "MAX_REROUTE_ROUNDS",
    "decide_reroute",
]

# runner 在线判定窗口（秒）—— 3 倍心跳，与既有容器链一致
_RUNNER_HEARTBEAT_WINDOW_SECONDS = 120
# 调研容器超时（秒）；同时作为任务 token 的 timeout_seconds（服务侧再加 10min 余量）
_RESEARCH_TIMEOUT = 30 * 60

# 回调路由的唯一依据（写进 `SubAgentSession.last_output["source"]`）。
# **必须是新值**：沿用既有方案链的 source 会被它的 §7 PartialPlan handler 抢走并按错误 schema 落库。
BLUEPRINT_RESEARCH_SOURCE = "blueprint_research"
_BLUEPRINT_RESEARCH_SOURCE = BLUEPRINT_RESEARCH_SOURCE

# 阶段 2（113-03）拟方案容器的 source。**必须与调研链不同值**：`callbacks._is_blueprint_research`
# 的唯一路由依据就是这个值，同值会让 plan 产物被调研解析器抢走并因缺 `fitness.verdict` 判失败。
BLUEPRINT_REPO_PLAN_SOURCE = "blueprint_repo_plan"

# 自实现重试上界。**既有 ResearchService 的单仓重试入口不可复用**：它硬编码断言会话
# stage 名为 "research"，本相位 stage 名是 repo_research，复用会恒 raise ValueError。
# 因此重试语义在本文件自实现：超过上界的 task 直接判失败，不无限重派容器（T-112-19 同源）。
_MAX_ATTEMPTS = 2

# 幂等白名单：resume / re-advance / 确认门重进本 stage 时跳过 running/done/failed，
# 既不重派已完成容器（重置进度、浪费额度、扰乱 barrier），也不为已处理仓重复合成。
_DISPATCHABLE_STATUSES = (RepoResearchTaskStatus.PENDING, RepoResearchTaskStatus.STALE)

# 深调研桶的 confidence 兜底口径（仅当候选没给 role_suggestion 时使用）
_DEEP_CONFIDENCE = frozenset({"high", "medium"})

_MAX_PROMPT_TEXT_CHARS = 2000
_MAX_LIST_ITEMS = 10

# 重路由轮次上界：定义下沉到零依赖的 `constants` 模块，本文件与 `builtin_processes`
# 都从那里读同一个数值（后者不必再为一个数字 import 本重型模块）。此处保留再导出，
# 既有 `from ...blueprint_research_adapter import MAX_REROUTE_ROUNDS` 的调用方不受影响。
MAX_REROUTE_ROUNDS = _MAX_REROUTE_ROUNDS

_UNSUITABLE_VERDICT = "unsuitable"
# stage_state 里两个新键：轮次账本与逐仓结论精简摘要（正文由下游按 id 自取，单字段 <2KB）
_REROUTE_STATE_KEY = "reroute"
_FITNESS_STATE_KEY = "repo_research_fitness"


class BlueprintResearchAdapter:
    """蓝图 `repo_research` stage 依赖：逐仓 fan-out 容器调研 + indirect 轻量合成。

    依赖全 keyword-only 可注入（测试注 mock，生产零参构造）：

    - `research_service`：`ResearchService` 形状（唯一业务写入面）
    - `session_service`：`ConvergenceSessionService` 形状（事件 emit 通道）
    - `dispatcher_factory`：无参 callable 返回有 `dispatch(DispatchTask)` 的对象
    - `charters_loader`：`aload_charters(ids) -> {repository_id: 章程字段}` 形状的 async 函数
    - `route_adapter`：`route(session, *, exclude_repository_ids=) -> 112-03 契约摘要`
      形状（reroute 轮补候选复用它，缺省惰性构造 `BlueprintRouteAdapter`）
    """

    def __init__(
        self,
        *,
        research_service: Any = None,
        session_service: Any = None,
        dispatcher_factory: Any = None,
        charters_loader: Any = None,
        route_adapter: Any = None,
        node_execution_id: str = "",
    ) -> None:
        self.research_service = research_service or ResearchService()
        self.session_service = session_service or ConvergenceSessionService()
        self._dispatcher_factory = dispatcher_factory
        self._charters_loader = charters_loader
        self._route_adapter = route_adapter
        self.node_execution_id = node_execution_id or ""

    # ── 派发主入口 ────────────────────────────────────────────────────────

    async def dispatch(
        self,
        session: Any,
        *,
        force_deep_repository_ids: set[str] | None = None,
        mode: str = "research",
        repository_ids: set[str] | None = None,
        resume_hints: dict[str, dict] | None = None,
    ) -> dict:
        """逐仓派发（**增量**）：返回 `{dispatched, synthesized, degraded, tasks}`。

        既是首轮派发入口，也是 reroute 补候选、确认门 `add_repo`、`aupgrade_to_deep`
        的复用入口 —— 靠第 4 步的 `_DISPATCHABLE_STATUSES` 白名单天然只处理新增/待重调研仓。

        `force_deep_repository_ids` 让「人工升级为深调研」的仓无论路由期 `role_suggestion`
        是什么都进 deep 桶（否则升级动作会被重新分回 light 桶再合成一遍）。

        **113 扩展点（阶段 2 拟方案）**：`mode="plan"` 只影响四处 —— prompt / `session_id`
        前缀 / `last_output.source` / `call_source`；分桶规则、metadata 的
        `env_FRIDAY_TASK_MODE`（恒 `explore`，管 git 写拦截，与调研/拟方案正交）、增量白名单
        一律不受影响。`mode="research"` 缺省路径与 112 逐字等价（两个既有调用方零改动）。
        `repository_ids` 非 None 时**跳过 `_collect_candidates`**：阶段 2 的仓集来自确认门
        锁定的 `repo_associations`，与路由候选面语义已不同（见 `blueprint_repo_plan.py`）。

        **113-04 扩展点**：`resume_hints`（`{repository_id: {partial_plan_id, produced_keys}}`）
        只在长等待重派时由 `aredispatch_waiting_repos` 传入，往 plan prompt 末尾追加一段续作
        引用；不传（含全部 research 路径）时该段为**空串**，prompt 与首轮逐字一致（零扰动）。
        """
        started = time.monotonic()
        forced = {str(rid) for rid in (force_deep_repository_ids or set())}
        # `forced` 是人工显式动作（升级深调研端点）——它是排除集的唯一豁免口。
        candidates = (
            self._plan_candidates(repository_ids)
            if repository_ids is not None
            else self._collect_candidates(session, allow_repository_ids=forced)
        )
        if not candidates:
            # 形状恒定（下游 handler 无需判空分支）：缺 "routing" 键 / candidates 为空 /
            # 确认门无 pending_research 仓 —— 一律零派发，不抛。
            return {"dispatched": 0, "synthesized": 0, "degraded": False, "tasks": []}

        logger.info(
            "blueprint_repo_research_dispatch_started",
            session_id=str(getattr(session, "id", "")),
            candidate_count=len(candidates),
            forced_deep_count=len(forced),
            category="sampling",
            component="process_runtime",
        )

        deep_index, light_index = self._bucket(candidates, forced=forced)
        degraded = False
        if deep_index:
            online = await self._count_online_runners()
            if online == 0:
                # 编排是后台推进（非交互）：无 runner 不做重试循环，整体降级轻量合成，
                # 绝不阻断本 stage —— 轻量结论仍产出，确认门仍有现状可展示。
                degraded = True
                logger.warning(
                    "blueprint_repo_research_degraded_to_light",
                    session_id=str(getattr(session, "id", "")),
                    deep_count=len(deep_index),
                    category="sampling",
                    component="process_runtime",
                )
                light_index = {**light_index, **deep_index}
                deep_index = {}

        charters = await self._aload_charters(list(candidates.keys()))
        task_ids: list[str] = []
        dispatched = 0
        synthesized = 0

        if deep_index:
            deep_tasks = await self.research_service.create_tasks_for_session(
                session, [self._task_seed(c) for c in deep_index.values()]
            )
            for task in deep_tasks:
                repository_id = str(task.repository_id)
                if task.status not in _DISPATCHABLE_STATUSES:
                    continue
                # plan 模式豁免本上界：`attempt` 是**跨阶段共用**的派发计数（阶段 1 已把它
                # 涨到 1），沿用会让阶段 2 的第一次重试就撞 `max_attempts_exhausted` 而静默
                # 降级。阶段 2 的有界重试上界另在回调侧按 `bp-plan-` 容器次数判（≤2 轮）。
                if mode != "plan" and int(getattr(task, "attempt", 0) or 0) >= _MAX_ATTEMPTS:
                    # 自实现重试上界（见 _MAX_ATTEMPTS）：超限直接判失败，不无限重派容器。
                    await self.research_service.mark_failed(
                        task, {"reason": "max_attempts_exhausted"}
                    )
                    await self._emit_failed(session, task, "max_attempts_exhausted")
                    continue
                task_ids.append(str(task.id))
                try:
                    if await self._dispatch_deep_task(
                        session,
                        task,
                        candidate=deep_index.get(repository_id) or {},
                        charter=charters.get(repository_id),
                        mode=mode,
                        resume_hint=(resume_hints or {}).get(repository_id),
                    ):
                        dispatched += 1
                except Exception as exc:  # noqa: BLE001 — WR-02 单仓隔离，绝不上抛
                    logger.warning(
                        "blueprint_repo_research_dispatch_failed",
                        session_id=str(getattr(session, "id", "")),
                        task_id=str(task.id),
                        repository_id=repository_id,
                        error=redact_secrets_in_text(str(exc)),
                        category="sampling",
                        component="process_runtime",
                    )
                    await self.research_service.mark_failed(
                        task,
                        {
                            "reason": "dispatch_failed",
                            "error": redact_secrets_in_text(str(exc)),
                        },
                    )
                    await self._emit_failed(session, task, "dispatch_failed")

        if mode == "plan":
            # plan 模式**绝不**走轻量合成：`_synthesize_light_partial` 产出的是调研形状结论，
            # `record_partial` 落库会把该仓最新 content 换成没有 `repo_plan` 段的一行，阶段 2
            # 的完成判据永远不满足（无界重合成）。无 runner 时宁可零派发让该仓保持待办，
            # 由 `BlueprintRepoPlanAdapter` 记 warning（`degraded=True` 已在返回值里可见）。
            light_index = {}

        if light_index:
            light_tasks = await self.research_service.create_tasks_for_session(
                session, [self._task_seed(c) for c in light_index.values()]
            )
            for task in light_tasks:
                if task.status not in _DISPATCHABLE_STATUSES:
                    continue
                repository_id = str(task.repository_id)
                task_ids.append(str(task.id))
                repo = await self._get_repository(task.repository_id)
                content = self._synthesize_light_partial(
                    session,
                    task,
                    repo,
                    candidate=light_index.get(repository_id) or {},
                    charter=charters.get(repository_id),
                )
                await self.research_service.record_partial(task, content)
                synthesized += 1

        logger.info(
            "blueprint_repo_research_dispatch_completed",
            session_id=str(getattr(session, "id", "")),
            dispatched=dispatched,
            synthesized=synthesized,
            degraded=degraded,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            category="sampling",
            component="process_runtime",
        )
        return {
            "dispatched": dispatched,
            "synthesized": synthesized,
            "degraded": degraded,
            "tasks": task_ids,
        }

    # ── 候选来源与分桶 ────────────────────────────────────────────────────

    @staticmethod
    def _excluded_repository_ids(stage_state: Any) -> set[str]:
        """reroute 排除集（`stage_state["reroute"]["excluded"]`）—— **唯一读取方在候选筛选处**。

        被判 `unsuitable` 的仓由 `aadvance_reroute` 累积写入这里；派发侧读它做剔除，
        使「排除 unsuitable」为真：被排除仓不会再进任何一轮派发（否则重路由只是空转）。
        """
        if not isinstance(stage_state, dict):
            return set()
        reroute = stage_state.get(_REROUTE_STATE_KEY)
        if not isinstance(reroute, dict):
            return set()
        raw = reroute.get("excluded")
        if not isinstance(raw, list):
            return set()
        return {str(item) for item in raw if str(item or "")}

    @staticmethod
    def _collect_candidates(
        session: Any, *, allow_repository_ids: set[str] | None = None
    ) -> dict[str, dict]:
        """候选并集（按 `repository_id` 去重）：路由候选 ∪ 确认门 `pending_research` 仓，
        **减去** `stage_state["reroute"]["excluded"]` 排除集。

        `stage_state["routing"]` 逐字按 112-03 契约读，**只取三键**：`repository_id` /
        `role_suggestion` / `confidence`（`confidence` 直作 `routed_confidence` 入参）；
        其余顶层键仅供事件回显，不参与派发判定。确认门快照（112-05 写入）里
        `pending_research is True` 的仓 = `add_repo` 新增 + `reclassify_role` 需重调研，
        后写者覆盖前者（确认门是更晚的人工裁决）。

        `allow_repository_ids` 是排除集的豁免口，只由**人工显式动作**填（升级深调研）：
        自动重路由排除的仓仍允许用户手动指名重开，但绝不会被自动流程再派发。
        """
        stage_state = getattr(session, "stage_state", None) or {}
        if not isinstance(stage_state, dict):
            return {}

        excluded = BlueprintResearchAdapter._excluded_repository_ids(stage_state) - (
            allow_repository_ids or set()
        )
        collected: dict[str, dict] = {}

        routing = stage_state.get("routing")
        raw_candidates = routing.get("candidates") if isinstance(routing, dict) else None
        for item in raw_candidates or []:
            if not isinstance(item, dict):
                continue
            repository_id = str(item.get("repository_id") or "")
            if not repository_id or repository_id in excluded:
                continue
            collected[repository_id] = {
                "repository_id": repository_id,
                "repository_name": str(item.get("repository_name") or ""),
                "role_suggestion": str(item.get("role_suggestion") or ""),
                "confidence": str(item.get("confidence") or "").lower(),
                "evidence": item.get("evidence") if isinstance(item.get("evidence"), dict) else {},
            }

        for item in _iter_confirmation_repos(stage_state.get("confirmation")):
            repository_id = str(item.get("repository_id") or "")
            if not repository_id or repository_id in excluded or not item.get("pending_research"):
                continue
            existing = collected.get(repository_id) or {}
            collected[repository_id] = {
                "repository_id": repository_id,
                "repository_name": str(
                    item.get("repository_name") or existing.get("repository_name") or ""
                ),
                "role_suggestion": str(
                    item.get("role_suggestion") or existing.get("role_suggestion") or ""
                ),
                "confidence": str(
                    item.get("confidence") or existing.get("confidence") or ""
                ).lower(),
                "evidence": existing.get("evidence") or {},
            }
        return collected

    @staticmethod
    def _plan_candidates(repository_ids: set[str] | None) -> dict[str, dict]:
        """阶段 2 的显式仓集 → 候选形状（113 扩展，**不经排除集与路由候选面**）。

        `role_suggestion` 固定 `direct`：阶段 2 只对 direct 仓起容器（indirect 仓由
        `BlueprintRepoPlanAdapter` 服务端 LLM 合成，根本不进本入口），所以此处全部进 deep 桶。
        """
        return {
            str(rid): {
                "repository_id": str(rid),
                "repository_name": "",
                "role_suggestion": "direct",
                "confidence": "",
                "evidence": {},
            }
            for rid in (repository_ids or set())
            if str(rid or "")
        }

    @staticmethod
    def _bucket(
        candidates: dict[str, dict], *, forced: set[str]
    ) -> tuple[dict[str, dict], dict[str, dict]]:
        """按 `role_suggestion` 分 deep(direct) / light(indirect) 两桶。

        `role_suggestion` 缺失时才回退 `confidence`（high/medium 视为 direct）——路由期
        契约恒带 `role_suggestion`，兜底只服务于确认门快照里手填的稀疏条目。
        """
        deep: dict[str, dict] = {}
        light: dict[str, dict] = {}
        for repository_id, candidate in candidates.items():
            if repository_id in forced:
                deep[repository_id] = candidate
                continue
            role = candidate.get("role_suggestion") or ""
            if role == "direct":
                deep[repository_id] = candidate
            elif role == "indirect":
                light[repository_id] = candidate
            elif candidate.get("confidence") in _DEEP_CONFIDENCE:
                deep[repository_id] = candidate
            else:
                light[repository_id] = candidate
        return deep, light

    @staticmethod
    def _task_seed(candidate: dict) -> dict:
        """`create_tasks_for_session` 的入参项（幂等 get_or_create 只用这两个键）。"""
        return {
            "repository_id": candidate["repository_id"],
            "routed_confidence": candidate.get("confidence") or "",
        }

    # ── 深调研派发五步 ────────────────────────────────────────────────────

    async def _dispatch_deep_task(
        self,
        session: Any,
        task: Any,
        *,
        candidate: dict,
        charter: dict | None,
        mode: str = "research",
        resume_hint: dict | None = None,
    ) -> bool:
        """单仓起独立 `SubAgentSession(PLAN)` 容器：五步顺序即正确性。

        ① 缺 `git_url` 直接判失败**不起注定 clone 失败的占位容器**；② `session_id` 必带 uuid
        后缀（stale 重跑会对同一 task 再派发，确定性命名会撞 UNIQUE）；③ 建 AgentSession +
        SubAgentSession 并写 `last_output`（**回调路由只认 last_output，不靠 session_id 命名**）；
        ④ metadata（含 mint 出的明文 token）→ dispatch，失败先主动 arevoke 再上抛给外层单仓
        隔离；⑤ `mark_running` + emit started。
        """
        from agents.call_source import CallSource, use_call_source
        from agents.models import AgentSession
        from runners.dispatcher import DispatchTask
        from subagent.models import SubAgentSession

        repo = await self._get_repository(task.repository_id)
        repo_url = getattr(repo, "git_url", "") if repo is not None else ""
        if not repo_url:
            await self.research_service.mark_failed(task, {"reason": "missing_git_url"})
            await self._emit_failed(session, task, "missing_git_url")
            return False

        # 113 扩展：阶段 2 换前缀与 source（uuid 后缀保留——stale 重跑会对同一 task 再派发）
        prefix = "bp-plan" if mode == "plan" else "bp-research"
        source_value = BLUEPRINT_REPO_PLAN_SOURCE if mode == "plan" else _BLUEPRINT_RESEARCH_SOURCE
        # 派发用户：113-02 的会话归属校验读 `sub.main_session.user_id`；此处不写 = 那道校验
        # 永远判 session_not_owned，跨会话越权防线恒失效、总线全链不可用（B1）。
        dispatch_user = await self._resolve_dispatch_user(session)
        session_id = f"{prefix}-{task.id.hex[:12]}-{uuid.uuid4().hex[:6]}"
        agent_session = await AgentSession.objects.acreate(
            session_id=f"agent-{session_id}",
            status=AgentSession.Status.RUNNING,
            # `dispatch_user` 为 None 时字段留空（null=True）——绝不伪造 system 用户提权
            user=dispatch_user,
            metadata={
                "source": source_value,
                "blueprint_session_id": str(session.id),
            },
        )
        subagent_session = await SubAgentSession.objects.acreate(
            session_id=session_id,
            main_session=agent_session,
            repo_url=repo_url,
            task_type=SubAgentSession.TaskType.PLAN,
            status=SubAgentSession.Status.PENDING,
            node_execution_id=self.node_execution_id or None,
            last_output={
                "source": source_value,
                "blueprint_session_id": str(session.id),
                "research_task_id": str(task.id),
                "repository_id": str(task.repository_id),
            },
        )

        prompt = self._build_prompt(
            session, task, repo, charter, candidate=candidate, mode=mode, resume_hint=resume_hint
        )
        metadata = await self._build_dispatch_metadata(
            session, task, repo=repo, subagent_session_id=session_id, mode=mode
        )
        # 120（REDO-03）：同仓上一次容器的 agent 会话可续 ⇒ 注入 resume 分片，让重跑**接着
        # 上次的分析继续**而不是从零重新读一遍仓库。取不到就是空 dict，容器全新执行（默认安全）。
        metadata.update(await self._aresume_env(task))

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
            node_execution_id=self.node_execution_id or "",
            session_id=session_id,
            metadata=metadata,
        )
        try:
            plan_source = CallSource.BLUEPRINT_REPO_PLAN  # 111 已注册，不新增枚举值
            with use_call_source(
                plan_source if mode == "plan" else CallSource.BLUEPRINT_REPO_RESEARCH
            ):
                await self._get_dispatcher().dispatch(dispatch_task)
        except Exception:
            # dispatch 失败没有终态回调兜底吊销 → 立刻主动吊销刚铸出的 token（避免悬空
            # 凭证活到 timeout + 10min）。arevoke 自身吞异常，不改变本次失败语义。
            from access_tokens.services import arevoke_task_tokens

            await arevoke_task_tokens(session_id)
            raise

        await self.research_service.mark_running(task, subagent_session)
        # 派发计数自增：`attempt` 只在这一处涨，`_MAX_ATTEMPTS` 上界才真的可触发。
        # 少了这一步，upgrade-research / reclassify(indirect→direct) /
        # edit_responsibility({"rerun": true}) 每调一次都能无上限重开 30 分钟调研容器。
        await self.research_service.bump_attempt(task)
        # 容器动作是用户可归因的调用类事件（观测规范：必须绑定触发用户）
        logger.info(
            "blueprint_repo_research_container_dispatched",
            session_id=str(session.id),
            subagent_session_id=session_id,
            repository_id=str(task.repository_id),
            has_user_token="env_FRIDAY_TASK_USER_TOKEN" in metadata,
            has_knowledge_endpoint="env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT" in metadata,
            initiated_by_user_id=self._initiated_by(session),
            category="caller",
            component="process_runtime",
        )
        await self._emit_started(session, task)
        return True

    async def _aresume_env(self, task: Any) -> dict[str, str]:
        """同仓上一次容器的 resume 分片 env（Phase 120，REDO-03）；无可续上下文返回 ``{}``。

        判据：**同一 ``repository_id``、同一蓝图会话**下最近一条带 ``sdk_transcript`` 的
        ``SubAgentSession``。为什么按仓而不是按 task：``mark_stale`` 重跑复用同一条
        ``RepoResearchTask``（``attempt`` 递增），而每次派发都新建一条 ``SubAgentSession``
        ⇒ 上一轮的留痕挂在**上一条** SubAgentSession 上，按 task 反查拿不到。

        ⛔ **不跨蓝图会话取**：另一份蓝图对同一个仓的调研上下文是另一个需求的推理过程，
        续到本轮里会让 agent 拿着无关结论继续（比没有 resume 更糟）。
        ⛔ 分片规则不在这里重写：一律走 ``chat.sdk_resume.build_resume_env``（容器侧按
        ``_CHUNKS`` + ``_{i}`` 重组，两处漂移会还原出半份 transcript）。

        整段吞异常：resume 是加速项，取不到就全新执行，绝不阻断派发。
        """
        try:
            from chat.sdk_resume import build_resume_env
            from subagent.models import SubAgentSession as _SubAgentSession

            repository_id = str(getattr(task, "repository_id", "") or "")
            blueprint_session_id = str(getattr(task, "session_id", "") or "")
            if not repository_id or not blueprint_session_id:
                return {}
            previous = (
                await _SubAgentSession.objects.filter(
                    last_output__repository_id=repository_id,
                    last_output__blueprint_session_id=blueprint_session_id,
                )
                .exclude(sdk_transcript="")
                .order_by("-sdk_session_saved_at")
                .afirst()
            )
            if previous is None:
                return {}
            env = build_resume_env(
                previous.sdk_session_id,
                previous.sdk_transcript,
                owner_id=str(previous.id),
            )
            if env:
                logger.info(
                    "blueprint_research_resume_env_injected",
                    session_id=blueprint_session_id,
                    repository_id=repository_id,
                    previous_subagent_session_id=str(previous.id),
                    chunks=env.get("env_FRIDAY_TASK_RESUME_TRANSCRIPT_CHUNKS"),
                    category="caller",
                    component="process_runtime",
                )
            return env
        except Exception as exc:  # noqa: BLE001 — resume 是加速项，绝不阻断派发
            logger.warning(
                "blueprint_research_resume_env_failed",
                repository_id=str(getattr(task, "repository_id", "") or ""),
                error=redact_secrets_in_text(str(exc)),
                category="sampling",
                component="process_runtime",
            )
            return {}

    async def _build_dispatch_metadata(
        self,
        session: Any,
        task: Any,
        *,
        repo: Any,
        subagent_session_id: str,
        mode: str = "research",
    ) -> dict[str, str]:
        """容器 env metadata（逐键 `env_` 前缀；**空值一律不注入该键**）。

        本相位补齐的三键（PLAN 链此前只有 explore/Claude/git 六类）：
        `env_FRIDAY_TASK_TOOLS_ENDPOINT` / `env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT` 由
        `settings.FRIDAY_BASE_URL` 推导（**绝不用 runner 的回调地址**——那会把工具调用打到
        runner 中转导致 404）；`env_FRIDAY_TASK_USER_TOKEN` 由 `mint_task_token` 新签发，
        `session_id` 与 `SubAgentSession` 一致（终态吊销按此定位），故 mint 必须在建行之后。
        """
        from django.conf import settings

        from services.git_credentials import aresolve_git_token
        from services.provider_config import aget_claude_code_runtime_config

        metadata: dict[str, str] = {
            "repository_id": str(getattr(repo, "id", "") or ""),
            # 只读 explore 语义：双层 git 写操作拦截（调研阶段绝不写 git）
            "env_FRIDAY_TASK_MODE": "explore",
            "env_FRIDAY_TASK_TASK_MODE": "explore",
        }
        if mode == "plan":
            # 阶段 2 的等待原语靠容器侧有界轮询（113-04），配额上界提到 400 吸收轮询开销；
            # `mode="research"` 路径**不注入该键**，缺省行为逐字等价 112。
            metadata["env_FRIDAY_TASK_KNOWLEDGE_QUOTA"] = "400"
        try:
            cc = await aget_claude_code_runtime_config()
            for key, value in (
                ("env_FRIDAY_TASK_CLAUDE_API_KEY", cc.get("api_key", "")),
                # 空值不注入（容器内沿用 SDK 默认端点）——不沿用 PLAN 链既有的无条件写入瑕疵
                ("env_FRIDAY_TASK_CLAUDE_BASE_URL", cc.get("base_url", "")),
                ("env_FRIDAY_TASK_CLAUDE_MODEL", cc.get("default_model", "")),
                ("env_FRIDAY_TASK_CLAUDE_SMALL_MODEL", cc.get("haiku_model", "")),
            ):
                if value:
                    metadata[key] = str(value)
        except Exception:  # noqa: BLE001 — 凭证缺失不阻断调度（容器内自报错）
            logger.warning(
                "blueprint_repo_research_runtime_config_failed",
                session_id=str(getattr(session, "id", "")),
                category="sampling",
                component="process_runtime",
            )

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
        except Exception:  # noqa: BLE001 — git 凭证解析失败不阻断调度，且不记正文
            logger.warning(
                "blueprint_repo_research_git_token_failed",
                session_id=str(getattr(session, "id", "")),
                category="sampling",
                component="process_runtime",
            )
        metadata["_repo_url"] = repo_url

        base = str(getattr(settings, "FRIDAY_BASE_URL", "") or "").rstrip("/")
        if base:
            metadata["env_FRIDAY_TASK_TOOLS_ENDPOINT"] = f"{base}/api/tools/execute/"
            # 裸 base（无路径后缀）——task 侧自拼 /api/mcp/tools/{name}/
            metadata["env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT"] = base

        dispatch_user = await self._resolve_dispatch_user(session)
        if dispatch_user is not None:
            from access_tokens.services import mint_task_token

            # 明文只在内存里走一趟直进容器 env（PAT-02）：不落盘、不进日志、不进事件 payload
            metadata["env_FRIDAY_TASK_USER_TOKEN"] = await mint_task_token(
                dispatch_user, subagent_session_id, _RESEARCH_TIMEOUT
            )
            # 31u：**非敏感**发起用户 id 随派发快照落库（不是凭证）。派发经 durable 队列后
            # 任务体只按 redacted 快照重建，rehydrate 据此键重铸 USER_TOKEN——不落则
            # 调研容器首派就挂不上知识工具（回归）。
            metadata["task_token_user_id"] = str(dispatch_user.id)
        return metadata

    # ── prompt 构造（服务端权威状态 + 章程注入） ───────────────────────────

    def _build_prompt(
        self,
        session: Any,
        task: Any,
        repo: Any,
        charter: dict | None,
        *,
        candidate: dict,
        mode: str = "research",
        resume_hint: dict | None = None,
    ) -> str:
        """调研 prompt：需求目标 + 功能点 + 路由证据 + **仓库章程**，并写死输出 JSON 形状。

        全部内容取自**服务端权威 session 状态**（不把外部用户原文当执行指令拼接）；
        章程随 prompt 注入 = 不扩容器 MCP 白名单也能让容器看到「这仓该管什么、不该管什么」。

        `mode="plan"`（113 扩展）走 `_build_plan_prompt`；缺省 `research` 的 return 体一字不动。
        """
        if mode == "plan":
            return self._build_plan_prompt(
                session, task, repo, charter, candidate=candidate, resume_hint=resume_hint
            )
        repo_name = getattr(repo, "name", "") if repo is not None else ""
        spec = _requirement_spec_from_state(session)
        return (
            f"你正在为仓库「{repo_name}」评估它与本次需求的适配度（fitness）并调研现状。\n\n"
            f"## 需求目标\n{self._summarize_goal(spec)}\n\n"
            f"## 功能点\n{self._summarize_feature_points(spec)}\n\n"
            f"## 路由证据（服务端已算，供你核对，不要盲信）\n"
            f"{self._summarize_route_evidence(candidate)}\n\n"
            f"## 仓库章程\n{self._summarize_charter(charter)}\n\n"
            "请深入阅读本仓代码后，**只输出一个 JSON 对象**，字段如下：\n"
            '- fitness: {"verdict": "suitable|partial|unsuitable", "reasons": [...], '
            '"citations": [...]}\n'
            '- role_suggestion: "direct"（需要改动本仓）或 "indirect"（只需了解/被依赖）\n'
            "- responsibility: 一段话说明本仓在这次需求里承担什么职责\n"
            '- findings: [{"title": ..., "detail": ..., "citations": [...]}]，逐条描述与本次'
            "需求相关的现状（已有能力、缺口、约束）\n\n"
            "纪律：citations 必须是你真实读到的文件路径或符号，**不要编造**；判不出适配度就填"
            ' verdict="partial" 并在 reasons 里说明缺什么信息，不要猜。'
        )

    def _build_plan_prompt(
        self,
        session: Any,
        task: Any,
        repo: Any,
        charter: dict | None,
        *,
        candidate: dict,
        resume_hint: dict | None = None,
    ) -> str:
        """阶段 2 拟方案 prompt（113-03）：锁定职责 + 阶段 1 结论 + RepoPlan 输出契约。

        与调研 prompt 同纪律：全部内容取自**服务端权威 session 状态**，绝不把外部用户原文
        当执行指令拼进来。总线工具的措辞是**条件式**的（向后兼容 P1）：老镜像没有这两个
        工具时 agent 记录假设继续跑，不许停下等。
        """
        repository_id = str(getattr(task, "repository_id", "") or "")
        repo_name = getattr(repo, "name", "") if repo is not None else ""
        spec = _requirement_spec_from_state(session)
        change_types = "、".join(REPO_PLAN_CHANGE_TYPES)
        return (
            f"你正在为仓库「{repo_name}」拟定本次需求的**分仓实现方案**（RepoPlan）。\n"
            "仓库集与职责已由人工确认门锁定，**不要再讨论该不该改这个仓**。\n\n"
            f"## 需求目标\n{self._summarize_goal(spec)}\n\n"
            f"## 功能点\n{self._summarize_feature_points(spec)}\n\n"
            f"## 本仓被锁定的职责（人工裁决，只读）\n{self._summarize_locked_role(session, repository_id)}\n\n"
            f"## 阶段 1 对本仓的调研结论（供你续作，不要重复调研）\n"
            f"{self._summarize_stage1(session, repository_id)}\n\n"
            f"## 仓库章程\n{self._summarize_charter(charter)}\n\n"
            "请深入阅读本仓代码后，**只输出一个 JSON 对象**，顶层键为 `repo_plan`，其值字段如下：\n"
            f'- repository_id: "{repository_id}"；role: "direct" 或 "indirect"\n'
            "- responsibility: Block[]（沿用上面锁定的职责，不要改写语义）\n"
            '- current_state: [{"summary": ..., "findings": [{"title", "detail", "citations"}]}]\n'
            "- impl_items: [{item_id, title, change_type, how, files_touched, depends_on, "
            "test_strategy, citations}]，其中\n"
            f"  - change_type ∈ {change_types}\n"
            "  - depends_on 只能引用**本仓**其他 item_id；跨仓依赖一律走 apis_consumed\n"
            "- apis_provided: [{name, method, path, request_schema, response_schema, "
            "description, citations}]\n"
            "- apis_consumed: 同上，另加 from_repository_id 与\n"
            "  data_source: {from_service, from_api, fields_needed, availability, "
            "support_repository_id, notes}\n"
            f"  - availability ∈ {'、'.join(REPO_PLAN_AVAILABILITY)}，**嵌在 data_source 下"
            "，不是顶层字段**\n"
            "  - availability 为 needs_support 时 data_source.support_repository_id **必填**"
            "（指出哪个仓要配合）\n"
            "- local_impact: {affected_modules, affected_features, migration_required, notes}\n"
            "- risks: Block[]\n\n"
            f"## 跨仓协商（若工具可用）\n"
            f"若 `report_blueprint_context` / `read_blueprint_context` 工具可用：请把你对外提供的\n"
            f"接口契约以 `repo:{repository_id}.api_surface` 为 key 写入总线；需要消费其他仓接口时\n"
            "先 read 总线看对方是否已声明。**若工具不可用，记录假设并继续，不要停下等待。**\n\n"
            "纪律：citations 必须是你真实读到的文件路径或符号，**不要编造**；判不出就在 risks 里\n"
            "写清缺什么信息，不要猜。"
            # 长等待重派的续作段（113-04）：非重派场景恒为空串 ⇒ prompt 与首轮逐字一致。
            f"{self._summarize_resume(resume_hint)}"
        )

    @staticmethod
    def _summarize_resume(resume_hint: dict | None) -> str:
        """长等待重派的续作引用段（无 hint 返回**空串**，首轮 prompt 零扰动）。

        只带 `partial_plan_id` 与已产出的段名 —— 正文由容器自己按 id 与总线取回，
        避免 prompt 膨胀，也避免半可信正文被二次拼进执行指令。
        """
        if not isinstance(resume_hint, dict):
            return ""
        partial_plan_id = str(resume_hint.get("partial_plan_id") or "")
        if not partial_plan_id:
            return ""
        produced = [str(key) for key in (resume_hint.get("produced_keys") or []) if str(key or "")]
        return (
            "\n\n## 续作（上一轮你因等待其他仓的接口契约而退出）\n"
            f"- 上一轮的部分产物已保存，partial_plan_id：{partial_plan_id}\n"
            f"- 已产出的段：{'、'.join(produced) or '（无）'}\n"
            "- 你等待的条目现已写入总线：请先用 read_blueprint_context 取回，再在上一轮结论\n"
            "  基础上补全，**不要从零重做**。"
        )

    @staticmethod
    def _summarize_locked_role(session: Any, repository_id: str) -> str:
        """确认门快照里本仓的 role / responsibility（`stage_state["confirmation"]`）。"""
        stage_state = getattr(session, "stage_state", None) or {}
        if not isinstance(stage_state, dict):
            return "（无锁定记录，请按调研结论自行判断本仓职责）"
        for item in _iter_confirmation_repos(stage_state.get("confirmation")):
            if str(item.get("repository_id") or "") != repository_id:
                continue
            role = str(item.get("role") or item.get("role_suggestion") or "") or "unknown"
            text = _blocks_to_text(item.get("responsibility"))[:_MAX_PROMPT_TEXT_CHARS]
            return f"- role：{role}\n- responsibility：{text or '（未填）'}"
        return "（无锁定记录，请按调研结论自行判断本仓职责）"

    @staticmethod
    def _summarize_stage1(session: Any, repository_id: str) -> str:
        """阶段 1 结论摘要（`stage_state["repo_research_fitness"]`，只存标量摘要）。"""
        stage_state = getattr(session, "stage_state", None) or {}
        fitness = stage_state.get(_FITNESS_STATE_KEY) if isinstance(stage_state, dict) else None
        item = fitness.get(repository_id) if isinstance(fitness, dict) else None
        if not isinstance(item, dict):
            return "（无阶段 1 结论摘要，请直接读代码）"
        return "\n".join(
            [
                f"- fitness.verdict：{item.get('verdict') or 'unknown'}",
                f"- 阶段 1 role 建议：{item.get('role_suggestion') or 'unknown'}",
                f"- 阶段 1 任务状态：{item.get('task_status') or 'unknown'}",
            ]
        )

    @staticmethod
    def _summarize_goal(spec: dict) -> str:
        text = _blocks_to_text(spec.get("goal"))
        return text[:_MAX_PROMPT_TEXT_CHARS] or "（无）"

    @staticmethod
    def _summarize_feature_points(spec: dict) -> str:
        lines: list[str] = []
        for point in (spec.get("feature_points") or [])[:_MAX_LIST_ITEMS]:
            if not isinstance(point, dict):
                continue
            title = str(point.get("title") or "").strip()
            intent = str(point.get("intent") or "").strip()
            detail = _blocks_to_text(point.get("description"))[:500]
            lines.append(f"- [{intent or 'unknown'}] {title}：{detail}")
        return "\n".join(lines) or "（无）"

    @staticmethod
    def _summarize_route_evidence(candidate: dict) -> str:
        evidence = candidate.get("evidence") if isinstance(candidate, dict) else None
        evidence = evidence if isinstance(evidence, dict) else {}
        paths = evidence.get("matched_node_paths") or []
        domains = [
            str(d.get("domain", "")) if isinstance(d, dict) else str(d)
            for d in (evidence.get("matched_domains") or [])
        ]
        boundaries = evidence.get("violated_boundaries") or []
        parts = [
            f"- 路由置信度：{candidate.get('confidence') or 'unknown'}",
            f"- 角色初判：{candidate.get('role_suggestion') or 'unknown'}",
            f"- 命中能力节点：{_join(paths) or '（无）'}",
            f"- 命中章程领域：{_join(domains) or '（无）'}",
            f"- 命中章程禁区：{_join(boundaries) or '（无）'}",
        ]
        return "\n".join(parts)

    @staticmethod
    def _summarize_charter(charter: dict | None) -> str:
        if not isinstance(charter, dict) or not charter:
            return "（该仓尚无章程，请仅依据代码现状判断）"
        owned = [
            f"{item.get('domain', '')}（{item.get('status', '')}）"
            for item in (charter.get("owned_domains") or [])[:_MAX_LIST_ITEMS]
            if isinstance(item, dict) and item.get("domain")
        ]
        boundaries = [
            str(item.get("rule", ""))
            for item in (charter.get("boundaries") or [])[:_MAX_LIST_ITEMS]
            if isinstance(item, dict) and item.get("rule")
        ]
        return "\n".join(
            [
                f"- positioning：{str(charter.get('positioning') or '')[:500] or '（无）'}",
                f"- owned_domains：{_join(owned) or '（无）'}",
                f"- boundaries（禁区）：{_join(boundaries) or '（无）'}",
                f"- evolution：{charter.get('evolution') or ''}",
            ]
        )

    # ── indirect 轻量合成 ─────────────────────────────────────────────────

    def _synthesize_light_partial(
        self,
        session: Any,
        task: Any,
        repo: Any,
        *,
        candidate: dict,
        charter: dict | None,
    ) -> dict:
        """indirect 仓的服务端轻量合成（不起容器、不调 LLM）。

        与深调研**同形**：`fitness` / `role_suggestion` / `responsibility` / `findings`
        与既有 §7 键平级。`verdict` 取保守的 `partial` —— 没有容器读过代码，既不能声称
        `suitable`（会让确认门误以为已核实），也不能声称 `unsuitable`（会误触发重路由）。
        证据来自路由期已有的能力树命中 / 章程领域 / 历史召回可得性。
        """
        repo_name = getattr(repo, "name", "") if repo is not None else ""
        evidence = candidate.get("evidence") if isinstance(candidate, dict) else None
        evidence = evidence if isinstance(evidence, dict) else {}
        findings: list[dict] = []

        paths = [str(p) for p in (evidence.get("matched_node_paths") or [])][:_MAX_LIST_ITEMS]
        if paths:
            findings.append(
                {
                    "title": "能力树命中",
                    "detail": f"路由期在本仓命中能力节点：{_join(paths)}",
                    "citations": paths,
                }
            )
        domains = [
            str(item.get("domain", "")) if isinstance(item, dict) else str(item)
            for item in (evidence.get("matched_domains") or [])
        ][:_MAX_LIST_ITEMS]
        if domains:
            findings.append(
                {
                    "title": "章程领域命中",
                    "detail": f"本仓章程声明拥有：{_join(domains)}",
                    "citations": [f"repo_charter:{task.repository_id}"],
                }
            )
        history_unavailable = str(evidence.get("history_match_unavailable") or "")
        findings.append(
            {
                "title": "历史落点证据",
                "detail": (
                    f"历史落点召回不可得（原因：{history_unavailable}）"
                    if history_unavailable
                    else "已参考同类需求的历史落点召回"
                ),
                "citations": [],
            }
        )
        if isinstance(charter, dict) and charter.get("positioning"):
            findings.append(
                {
                    "title": "仓库定位",
                    "detail": str(charter.get("positioning"))[:500],
                    "citations": [f"repo_charter:{task.repository_id}"],
                }
            )

        summary = (
            f"仓库「{repo_name}」被判为间接相关（indirect），未起独立调研容器；"
            "结论由服务端依据能力树命中、章程领域与历史落点证据轻量合成。"
        )
        return {
            "repository_id": str(task.repository_id),
            "research_summary": summary,
            "proposed_changes": [],
            "candidate_files": [],
            "api_contracts_exposed": [],
            "dependencies_on_other_repos": [],
            "fitness": {
                "verdict": "partial",
                "reasons": ["间接相关仓走轻量合成，未经容器深读代码核实"],
                "citations": paths,
            },
            "role_suggestion": "indirect",
            "responsibility": (
                f"本仓在本次需求中预计不需要改动，作为被依赖/参考方参与；如需确认改动面，"
                f"请对本仓升级为深调研。（路由置信度：{candidate.get('confidence') or 'unknown'}）"
            ),
            "findings": findings,
        }

    # ── 人工升级为深调研（112-05 第七个 REST 端点的服务层入口） ─────────────

    async def aupgrade_to_deep(self, session: Any, repository_id: str) -> bool:
        """把某 indirect 仓升级为深调研（幂等、增量）。

        调用方是 REST 动作（112-05 的 `POST .../blueprint-gate/upgrade-research/`，经
        `BlueprintLifecycleService` 收口），**不是内部隐式触发**。

        语义：已有 task → 经公开写路径 `mark_stale` 置回可派发态（`STALE` 在
        `_DISPATCHABLE_STATUSES` 内）后重跑 `dispatch`（增量白名单天然只派发它一个）；
        尚无 task 但该仓在候选来源内 → 靠 `create_tasks_for_session` 的幂等语义新建 `PENDING`。
        **绝不走既有 service 的单仓重试入口**（它断言 stage 名为 "research"，本 stage 恒 raise）。

        Returns:
            `True` = 已受理（容器已派发、已置为待派发，或该仓调研本就在途——`mark_stale`
            按 WR-01 只动已终态 task，在途 task 无需也不该重开）；`False` = 该仓不存在于
            本会话的候选与既有 task 内，或依赖不可用 —— 端点据此回 404/503。
        """
        repository_id = str(repository_id or "")
        if not repository_id:
            return False
        try:
            task_id = await self._afind_task_id(session, repository_id)
            if task_id is not None:
                await self.research_service.mark_stale([task_id])
            elif repository_id not in self._collect_candidates(
                session, allow_repository_ids={repository_id}
            ):
                return False
            result = await self.dispatch(session, force_deep_repository_ids={repository_id})
            logger.info(
                "blueprint_repo_research_upgraded_to_deep",
                session_id=str(getattr(session, "id", "")),
                repository_id=repository_id,
                dispatched=result.get("dispatched", 0),
                synthesized=result.get("synthesized", 0),
                initiated_by_user_id=self._initiated_by(session),
                category="caller",
                component="process_runtime",
            )
            return True
        except Exception as exc:  # noqa: BLE001 — 依赖不可用回 False，端点据此回 503
            logger.warning(
                "blueprint_repo_research_upgrade_failed",
                session_id=str(getattr(session, "id", "")),
                repository_id=repository_id,
                error=redact_secrets_in_text(str(exc)),
                category="sampling",
                component="process_runtime",
            )
            return False

    # ── reroute 判定面（有界循环 + 超限升确认门） ──────────────────────────

    async def acollect_fitness(self, session: Any) -> dict[str, dict]:
        """按仓聚合**最新有效**调研结论：`{repository_id: {verdict, role_suggestion, ...}}`。

        `record_partial` 每次都 `create` 新行（重跑/升级同一 task 会有多行），因此必须
        `valid=True` 过滤 + `created_at` 降序**每 task 只取最新一条**；`valid=False`
        （重索引/澄清失效）的行一律忽略。ORM 经 `sync_to_async`（INV-6：只读）。
        """
        try:
            return await self._collect_fitness_sync(getattr(session, "id", None))
        except Exception as exc:  # noqa: BLE001 — 读失败按「无结论」处理，判定会走 converged
            logger.warning(
                "blueprint_repo_research_fitness_collect_failed",
                session_id=str(getattr(session, "id", "")),
                error=redact_secrets_in_text(str(exc)),
                category="sampling",
                component="process_runtime",
            )
            return {}

    @staticmethod
    @sync_to_async
    def _collect_fitness_sync(session_id: Any) -> dict[str, dict]:
        from delivery.models import PartialPlan, RepoResearchTask

        tasks = list(
            RepoResearchTask.objects.filter(session_id=session_id).values(
                "id", "repository_id", "status"
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
        for task in tasks:
            content = latest.get(task["id"]) or {}
            fitness = content.get("fitness") if isinstance(content, dict) else None
            fitness = fitness if isinstance(fitness, dict) else {}
            collected[str(task["repository_id"])] = {
                "verdict": str(fitness.get("verdict") or ""),
                "role_suggestion": str(content.get("role_suggestion") or "")
                if isinstance(content, dict)
                else "",
                "responsibility": str(content.get("responsibility") or "")
                if isinstance(content, dict)
                else "",
                "findings": content.get("findings") or [] if isinstance(content, dict) else [],
                "task_status": str(task["status"]),
            }
        return collected

    async def aadvance_reroute(self, session: Any) -> dict:
        """barrier 收敛后的**单点串行**判定与轮次递增（P3 lost-update 的唯一缓解手段）。

        返回 `{"event", "stage_state_update", "escalation", "decision"}`；**adapter 只返回
        dict，真正的 `transition` 由 112-05 注册的 handler 用 `StageOutcome` 承担**（engine 纯度）。

        `stage_state` 是**整字典替换**而非深合并：只回写增量会清空 `decomposition` /
        `routing` / `recall_context` 等既有键（它们正是只读视图属性的数据源），所以这里
        `{**state, ...}` 浅合并整体回写，且 `session` 必须是**刚从 DB 读的新实例**。

        判 `reroute` 时**必须真的补到新仓**才回边：排除集之外重跑一次双面路由，新候选
        追加进 `routing.candidates`（回边后由 `dispatch` 的增量白名单只为它们起容器）；
        **补不到任何新候选就地转 `escalate`**（`reason="no_new_candidates"`）带全部现状
        升确认门 —— 否则回边只是空转，白烧一轮上界。
        """
        session = await self._areload_session(session)
        state = getattr(session, "stage_state", None) or {}
        if not isinstance(state, dict):
            state = {}
        round_no = 0
        existing = state.get(_REROUTE_STATE_KEY)
        if isinstance(existing, dict):
            try:
                round_no = int(existing.get("count", 0) or 0)
            except (TypeError, ValueError):
                round_no = 0

        fitness = await self.acollect_fitness(session)
        decision = decide_reroute(fitness=fitness, round_no=round_no)

        # 排除集**累积**：本轮 unsuitable ∪ 历轮已排除（历轮的仓可能已无最新结论，
        # 只靠本轮判定会让它「复活」回候选，排除就不是永久的了）。
        excluded_all = sorted(
            self._excluded_repository_ids(state) | set(decision["unsuitable_repository_ids"])
        )
        supplemented: list[str] = []
        refilled_routing: dict | None = None
        if decision["action"] == "reroute":
            refill = await self._arefill_candidates(
                session, state=state, excluded=set(excluded_all), tried=set(fitness or {})
            )
            supplemented = refill["added"]
            refilled_routing = refill["routing"]
            if not supplemented:
                # 补不到新仓 ⇒ 回边必然空转 ⇒ 直接升确认门交人裁决（绝不静默失败）。
                decision = {
                    "action": "escalate",
                    "unsuitable_repository_ids": decision["unsuitable_repository_ids"],
                    "next_round": round_no,
                    "reason": "no_new_candidates",
                }

        merged = {
            **state,
            _REROUTE_STATE_KEY: {
                "count": decision["next_round"],
                "excluded": excluded_all,
                "last_reason": decision["reason"],
                "supplemented": supplemented,
            },
            # 只存小摘要（正文与 findings 由下游按 repository_id 自取 PartialPlan）
            _FITNESS_STATE_KEY: {
                repository_id: {
                    "verdict": item["verdict"],
                    "role_suggestion": item["role_suggestion"],
                    "task_status": item["task_status"],
                }
                for repository_id, item in fitness.items()
            },
        }
        if refilled_routing is not None:
            # 补候选只**追加** candidates（顶层其余键沿用首轮路由摘要），回边后由
            # dispatch 的增量白名单只为新仓起容器，既有仓结论一行不动。
            merged["routing"] = refilled_routing

        event_map = {
            "converged": "converged",
            "reroute": "reroute_needed",
            "escalate": "exhausted",
        }
        event = event_map[decision["action"]]
        escalation: dict = {}
        if decision["action"] == "escalate":
            # 带**全部现状**升确认门（每仓 verdict/role/responsibility），交用户裁决
            escalation = {
                "reason": decision["reason"],
                "round": round_no,
                "unsuitable_repository_ids": decision["unsuitable_repository_ids"],
                "excluded_repository_ids": excluded_all,
                "repos": [
                    {
                        "repository_id": repository_id,
                        "verdict": item["verdict"],
                        "role_suggestion": item["role_suggestion"],
                        "responsibility": item["responsibility"],
                        "task_status": item["task_status"],
                    }
                    for repository_id, item in fitness.items()
                ],
            }

        if decision["action"] in ("reroute", "escalate"):
            await self._emit(
                EVENT_BLUEPRINT_REROUTE_TRIGGERED,
                session,
                {
                    "round": decision["next_round"],
                    "excluded_count": len(decision["unsuitable_repository_ids"]),
                    "action": decision["action"],
                },
            )
        logger.info(
            "blueprint_reroute_decided",
            session_id=str(getattr(session, "id", "")),
            action=decision["action"],
            round=decision["next_round"],
            excluded_count=len(decision["unsuitable_repository_ids"]),
            category="sampling",
            component="process_runtime",
        )
        return {
            "event": event,
            "stage_state_update": merged,
            "escalation": escalation,
            "decision": decision,
        }

    async def _arefill_candidates(
        self, session: Any, *, state: dict, excluded: set[str], tried: set[str]
    ) -> dict:
        """reroute 轮补候选：在**排除集 ∪ 已试仓**之外重跑双面路由，取真正的新仓。

        复用 112-03 的 `BlueprintRouteAdapter.route`（同一份三分量评分与章程补入逻辑，
        不另写一套选仓判据）。返回 `{"added": [repository_id...], "routing": dict|None}`；
        `routing` 是**追加新候选后的整份 routing 摘要**（None = 无新候选，不动 stage_state）。

        best-effort：路由重跑失败按「补不到」处理 —— 调用方据此升确认门，绝不静默失败。
        """
        routing = state.get("routing")
        routing = routing if isinstance(routing, dict) else {}
        existing = [item for item in (routing.get("candidates") or []) if isinstance(item, dict)]
        known = {str(item.get("repository_id") or "") for item in existing}
        known |= {str(repository_id) for repository_id in tried}
        known.discard("")
        skip = known | excluded

        started = time.monotonic()
        try:
            result = await self._get_route_adapter().route(session, exclude_repository_ids=skip)
        except Exception as exc:  # noqa: BLE001 — 补候选失败 = 补不到（后续升门），不上抛
            logger.warning(
                "blueprint_reroute_refill_failed",
                session_id=str(getattr(session, "id", "")),
                error=redact_secrets_in_text(str(exc)),
                category="sampling",
                component="process_runtime",
            )
            return {"added": [], "routing": None}

        added: list[dict] = []
        for item in (result or {}).get("candidates") or []:
            if not isinstance(item, dict):
                continue
            repository_id = str(item.get("repository_id") or "")
            if not repository_id or repository_id in skip:
                continue
            skip.add(repository_id)
            added.append(item)

        logger.info(
            "blueprint_reroute_refill_completed",
            session_id=str(getattr(session, "id", "")),
            excluded_count=len(excluded),
            tried_count=len(known),
            added_count=len(added),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            category="sampling",
            component="process_runtime",
        )
        if not added:
            return {"added": [], "routing": None}
        return {
            "added": [str(item["repository_id"]) for item in added],
            "routing": {**routing, "candidates": existing + added},
        }

    def _get_route_adapter(self) -> Any:
        if self._route_adapter is not None:
            return self._route_adapter
        from services.process_runtime.blueprint_route import BlueprintRouteAdapter

        return BlueprintRouteAdapter()

    @staticmethod
    @sync_to_async
    def _areload_session(session: Any) -> Any:
        """重读 session 新实例（绝不用早先持有的陈旧对象做 read-modify-write）。"""
        from delivery.models import ConvergenceSession

        return ConvergenceSession.objects.filter(id=getattr(session, "id", None)).first() or session

    # ── 事件与外部依赖（各自 best-effort） ────────────────────────────────

    async def _emit_started(self, session: Any, task: Any) -> None:
        await self._emit(
            EVENT_BLUEPRINT_REPO_RESEARCH_STARTED,
            session,
            {
                "repository_id": str(task.repository_id),
                "task_id": str(task.id),
                "routed_confidence": task.routed_confidence or "",
            },
        )

    async def _emit_failed(self, session: Any, task: Any, reason: str) -> None:
        await self._emit(
            EVENT_BLUEPRINT_REPO_RESEARCH_FAILED,
            session,
            {
                "repository_id": str(task.repository_id),
                "task_id": str(task.id),
                "error": reason,
            },
        )

    async def _emit(self, event: str, session: Any, payload: dict) -> None:
        """事件 best-effort：payload 只含标量与关联键，绝不含 token / prompt / 需求正文。"""
        try:
            await self.session_service.aemit_event(event, session, payload)
        except Exception:  # noqa: BLE001 — 观测绝不反噬调度主流程
            logger.warning(
                "blueprint_repo_research_emit_failed",
                event=event,
                session_id=str(getattr(session, "id", "")),
                category="sampling",
                component="process_runtime",
            )

    @staticmethod
    def _initiated_by(session: Any) -> str:
        """触发用户归因（无触发用户记 `system`，绝不伪造 actor）。"""
        return str(getattr(session, "initiated_by_user_id", "") or "") or "system"

    def _get_dispatcher(self) -> Any:
        if self._dispatcher_factory is not None:
            return self._dispatcher_factory()
        from runners.dispatcher import get_dispatcher

        return get_dispatcher()

    async def _aload_charters(self, repository_ids: list[str]) -> dict[str, dict]:
        """批量读章程（供 prompt 注入与轻量合成），best-effort：失败按「无章程」处理。"""
        loader = self._charters_loader
        if loader is None:
            from services.process_runtime.blueprint_charter_match import aload_charters

            loader = aload_charters
        try:
            return await loader(repository_ids) or {}
        except Exception as exc:  # noqa: BLE001 — 章程读失败不阻断派发
            logger.warning(
                "blueprint_repo_research_charter_load_failed",
                error=redact_secrets_in_text(str(exc)),
                category="sampling",
                component="process_runtime",
            )
            return {}

    @staticmethod
    @sync_to_async
    def _resolve_dispatch_user(session: Any) -> Any:
        """取 `session.created_by` 真实 `User` 实例（lazy-FK 必须在 sync 上下文取）。

        为空时调用方**省略 token 键降级不挂**——绝不伪造 system 用户提权铸 token。
        """
        return getattr(session, "created_by", None)

    @staticmethod
    @sync_to_async
    def _afind_task_id(session: Any, repository_id: str) -> Any:
        from delivery.models import RepoResearchTask

        return (
            RepoResearchTask.objects.filter(session_id=session.id, repository_id=repository_id)
            .values_list("id", flat=True)
            .first()
        )

    @staticmethod
    async def _count_online_runners() -> int:
        """在线 runner 计数（3 倍心跳窗口；后台推进不做重试循环）。"""
        from datetime import timedelta

        from django.utils import timezone as tz

        from runners.models import Runner

        threshold = tz.now() - timedelta(seconds=_RUNNER_HEARTBEAT_WINDOW_SECONDS)
        return await Runner.objects.filter(status="online", last_heartbeat__gte=threshold).acount()

    @staticmethod
    async def _get_repository(repository_id: Any) -> Any:
        from repositories.models import Repository

        return await Repository.objects.filter(id=repository_id).afirst()


# ── 模块级纯函数 ──────────────────────────────────────────────────────────


def decide_reroute(*, fitness: dict, round_no: int, max_rounds: int = MAX_REROUTE_ROUNDS) -> dict:
    """重路由三分支判定（**纯函数**，可单测、可被 golden set 评估）。

    - 无 `unsuitable` 仓 → `converged`（`next_round` 保持不变，不白烧一轮）。
    - 有 `unsuitable` 且 `round_no < max_rounds` → `reroute`，带被排除仓清单交主 agent 补候选。
    - 有 `unsuitable` 且 `round_no >= max_rounds` → **`escalate`**（`reason="reroute_exhausted"`），
      带全部现状升确认门交用户裁决。

    返回值里**根本不存在** failed 类动作：不收敛是「需要人裁决」，不是「流程失败」
    （CONTEXT「绝不静默失败」；无界重路由本身也是烧容器额度的 DoS 面 T-112-19）。

    Returns:
        `{"action": "converged"|"reroute"|"escalate", "unsuitable_repository_ids": [...],
        "next_round": int, "reason": str}`
    """
    try:
        current = max(0, int(round_no))
    except (TypeError, ValueError):
        current = 0
    try:
        limit = max(0, int(max_rounds))
    except (TypeError, ValueError):
        limit = MAX_REROUTE_ROUNDS

    unsuitable = sorted(
        str(repository_id)
        for repository_id, item in (fitness or {}).items()
        if isinstance(item, dict)
        and str(item.get("verdict") or "").strip().lower() == _UNSUITABLE_VERDICT
    )
    if not unsuitable:
        return {
            "action": "converged",
            "unsuitable_repository_ids": [],
            "next_round": current,
            "reason": "no_unsuitable",
        }
    if current < limit:
        return {
            "action": "reroute",
            "unsuitable_repository_ids": unsuitable,
            "next_round": current + 1,
            "reason": "unsuitable_repos_excluded",
        }
    return {
        "action": "escalate",
        "unsuitable_repository_ids": unsuitable,
        "next_round": current,
        "reason": "reroute_exhausted",
    }


def _iter_confirmation_repos(confirmation: Any) -> list[dict]:
    """确认门快照的仓清单（兼容 `{"repos": [...]}` 与裸 list 两种形状）。"""
    if isinstance(confirmation, dict):
        for key in ("repos", "repositories", "candidates"):
            value = confirmation.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []
    if isinstance(confirmation, list):
        return [item for item in confirmation if isinstance(item, dict)]
    return []


def _requirement_spec_from_state(session: Any) -> dict:
    """从 `stage_state` 取 `requirement_spec`（在途蓝图产物挂这里；取不到返 `{}`）。"""
    stage_state = getattr(session, "stage_state", None) or {}
    if not isinstance(stage_state, dict):
        return {}
    for holder in (stage_state.get("blueprint"), stage_state):
        if not isinstance(holder, dict):
            continue
        spec = holder.get("requirement_spec")
        if isinstance(spec, dict) and spec:
            return spec
    return {}


def _blocks_to_text(blocks: Any) -> str:
    """Block[] → 纯文本（只取 paragraph/list 的 text；prompt 只需语义文本不需渲染）。"""
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


def _join(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    return "、".join(str(item) for item in items[:_MAX_LIST_ITEMS] if str(item))
