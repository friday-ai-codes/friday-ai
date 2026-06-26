"""RepoVerifyDispatchService —— 逐仓容器深验 fan-out（REPO-02，88-03）。

复刻 ``services.plan_orchestration.research_adapter.ResearchDispatchAdapter`` 的结构
（**复刻不复用**，避免污染 v0.7 ``PlanSession`` 编排状态机，RESEARCH Alternatives）：
对用户确认的每个仓库 fan-out 一个独立 claude code ``explore`` 只读容器，深入仓库**代码**
验证业务适配性（D-02，非元数据/README 匹配），容器 explore 产 JSON verdict；容器完成回调
经既有 ``subagent.api.callbacks`` → ``node_execution_id`` → ``_schedule_workflow_resume``
续驱挂起节点（Pitfall 2），verdict 经 ``RepoAssociationService`` 落 ``RepoVerifyTask``
（INV-6，本服务**绝不**直接写 ``RepoVerifyTask`` / ``RepoAssociation``）。

fail-soft 隔离（D-03，Pitfall 3）：每仓 ``create_verify_task`` + ``_dispatch_verify_task``
独立 ``try/except``——单仓 clone/容器异常仅 ``mark_verify_failed`` + continue，绝不上抛拖垮
其余仓；runner 离线（``_count_online_runners()==0``）降级：跳过容器、确认仓 verdict 记
``unknown``，不阻断终态（mirror research_adapter runner_offline）。

只读 explore 安全（D-02，Pitfall 1，T-88-03-TAMPER）：``_build_dispatch_metadata`` 逐字
复刻 research_adapter 的 explore 双层拦截（``env_FRIDAY_TASK_MODE`` /
``env_FRIDAY_TASK_TASK_MODE`` 均 ``explore``）+ claude code 凭证 + ``aresolve_git_token``
注入容器 env（git@→https 改写）；token **绝不**入日志（仅 ``has_git_token`` 布尔）。

观测（强制）：``initiated_by_user_id`` 透传（dispatch payload + ``SubAgentSession.last_output``
带触发用户）；容器 token 桥接 call_source 经 callbacks ``_derive_container_call_source`` 映射
``REPO_VERIFY → repo_verify_container``；结构化事件仅记 repo_id/计数/has_git_token，正文/凭证
不回显；异常经 ``redact_secrets_in_text``。
"""

from __future__ import annotations

import uuid
from time import perf_counter
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = ["RepoVerifyDispatchService"]

_COMPONENT = "repo_association"
# runner 在线判定窗口（秒）—— 与 research_adapter 一致（3 倍心跳）。
_RUNNER_HEARTBEAT_WINDOW_SECONDS = 120
# 容器深验超时（秒）。
_VERIFY_TIMEOUT = 30 * 60


class RepoVerifyDispatchService:
    """per-repo explore 容器深验 fan-out（复刻 ResearchDispatchAdapter，verify 语义）。"""

    def __init__(
        self,
        *,
        association_service: Any = None,
        node_execution_id: str = "",
    ) -> None:
        if association_service is None:
            # lazy import 防 service ↔ dispatch 循环
            from initiatives.services.repo_association_service import (
                RepoAssociationService,
            )

            association_service = RepoAssociationService()
        self.association_service = association_service
        # 工作流入口节点透传的 NodeExecution id（mirror AICodingNode）。非空时把每个 verify
        # SubAgentSession 关联到该 node_execution，使容器完成回调经既有
        # ``_schedule_workflow_resume`` 重新驱动挂起的 WAITING_EVENT 节点；Chat 入口留空。
        self.node_execution_id = node_execution_id or ""

    async def dispatch(
        self,
        associations: Any,
        *,
        initiated_by_user_id: Any = None,
    ) -> dict:
        """逐仓 fan-out explore 容器深验，返回 ``{dispatched, failed, runner_offline}``。

        ``associations`` 为用户确认的 ``RepoAssociation`` 列表（每项 per-repo，
        ``status=verifying``）。runner 离线时降级：不起容器，每仓 verdict 记 ``unknown``
        （经 service，不阻断终态）；单仓 dispatch 异常隔离（mark_verify_failed + continue）。
        """
        started = perf_counter()
        user_label = (
            str(initiated_by_user_id) if initiated_by_user_id is not None else "system"
        )
        items = list(associations or [])
        if not items:
            return {"dispatched": [], "failed": [], "runner_offline": False}

        online = await self._count_online_runners()
        runner_offline = online == 0

        dispatched: list[str] = []
        failed: list[str] = []

        for association in items:
            repo = await self._get_repository(association.repository_id)
            # 建 verify task（经 service，INV-6；get_or_create 幂等，resume 安全）
            task = await self.association_service.create_verify_task(
                association, repo, initiated_by_user_id=user_label
            )
            if runner_offline:
                # runner 离线降级：跳过容器，仓标 unknown（不阻断终态，D-03 fail-soft）
                await self.association_service.record_verdict(
                    task,
                    {
                        "fit": "unknown",
                        "confidence": "low",
                        "summary": "runner_offline",
                        "evidence_files": [],
                        "mismatch_reasons": [],
                    },
                )
                continue
            # 单仓错误隔离（Pitfall 3）：任一仓 dispatch 异常仅标该 task failed + continue，
            # 绝不上抛拖垮其余仓（异常上抛会被上游 except 转 fail）。
            try:
                ok = await self._dispatch_verify_task(
                    association, task, repo, user_label
                )
                if ok:
                    dispatched.append(str(task.id))
            except Exception as exc:  # noqa: BLE001 — 单仓失败隔离，不波及其他仓
                logger.warning(
                    "repo_verify_task_failed",
                    repo_id=str(association.repository_id),
                    reason=redact_secrets_in_text(str(exc)),
                    error_type=type(exc).__name__,
                    component=_COMPONENT,
                    category="caller",
                )
                await self.association_service.mark_verify_failed(
                    task,
                    {"reason": "dispatch_failed", "error": redact_secrets_in_text(str(exc))},
                )
                failed.append(str(task.id))

        logger.info(
            "repo_verify_dispatch_completed",
            dispatched=len(dispatched),
            failed=len(failed),
            runner_offline=runner_offline,
            scoped_repo_count=len(items),
            duration_ms=round((perf_counter() - started) * 1000, 2),
            initiated_by_user_id=user_label,
            component=_COMPONENT,
            category="caller",
        )
        return {
            "dispatched": dispatched,
            "failed": failed,
            "runner_offline": runner_offline,
        }

    async def _dispatch_verify_task(
        self,
        association: Any,
        task: Any,
        repo: Any,
        initiated_by_user_id: str,
    ) -> bool:
        """单仓：建 ``AgentSession`` + ``SubAgentSession(REPO_VERIFY)`` + 派 explore 容器 + 回填 running。

        缺 ``git_url`` → ``mark_verify_failed("missing_git_url")``，不派注定 clone 失败的占位
        URL 容器（省一次调度，mirror research_adapter IN-03）。返回是否真正派发容器。
        """
        from agents.models import AgentSession
        from runners.dispatcher import DispatchTask, get_dispatcher
        from subagent.models import SubAgentSession

        repo_url = getattr(repo, "git_url", "") if repo is not None else ""
        if not repo_url:
            await self.association_service.mark_verify_failed(
                task, {"reason": "missing_git_url"}
            )
            return False

        # session_id 每次派发唯一（附 uuid 后缀），回调侧经 last_output.repo_verify_task_id
        # 反查 task（不依赖 session_id 命名），故后缀不影响幂等/回调路由（mirror research_adapter）。
        session_id = f"repo-verify-{task.id.hex[:12]}-{uuid.uuid4().hex[:6]}"
        agent_session = await AgentSession.objects.acreate(
            session_id=f"agent-{session_id}",
            status=AgentSession.Status.RUNNING,
            metadata={"source": "repo_verify", "association_id": str(association.id)},
        )

        metadata = await self._build_dispatch_metadata(repo)
        repo_url = metadata.pop("_repo_url", repo_url) or repo_url

        subagent_session = await SubAgentSession.objects.acreate(
            session_id=session_id,
            main_session=agent_session,
            repo_url=repo_url,
            task_type=SubAgentSession.TaskType.REPO_VERIFY,
            status=SubAgentSession.Status.PENDING,
            # 关联工作流 node_execution（mirror AICodingNode）——容器完成回调据此经
            # _schedule_workflow_resume 重新驱动挂起节点；Chat 入口无节点时为 None。
            node_execution_id=self.node_execution_id or None,
            last_output={
                "source": "repo_verify",
                "repo_verify_task_id": str(task.id),
                "association_id": str(association.id),
                "repository_id": str(association.repository_id),
                "initiated_by_user_id": str(initiated_by_user_id or "system"),
            },
        )

        prompt = self._build_verify_prompt(association, task, repo)
        dispatch_task = DispatchTask(
            task_id=session_id,
            task_type="repo_verify",
            tags=[],
            image="",
            repo_url=repo_url,
            branch=getattr(repo, "default_branch", "") or "main",
            target_branch="",
            prompt=prompt,
            timeout=_VERIFY_TIMEOUT,
            node_execution_id=self.node_execution_id or "",
            session_id=session_id,
            metadata=metadata,
        )
        await get_dispatcher().dispatch(dispatch_task)
        await self.association_service.mark_verify_running(task, subagent_session)
        return True

    def _build_verify_prompt(self, association: Any, task: Any, repo: Any) -> str:
        """构造深验 prompt：注入本仓应承接的 feature（粗）+ 要求 explore 产 JSON verdict。

        prompt 来自 server 端权威关联状态（``RepoAssociation`` 的路由理由 / 命中能力树节点），
        非外部用户原文拼接执行指令（V5 输入校验）。
        """
        repo_name = getattr(repo, "name", "") if repo is not None else ""
        routed_reason = str(getattr(association, "routed_reason", "") or "")
        node_paths = list(getattr(association, "matched_node_paths", []) or [])
        node_paths_text = "\n".join(f"- {p}" for p in node_paths[:30]) or "（无）"

        return (
            f"你正在对仓库「{repo_name}」做业务适配性**深度代码校验**（只读 explore，不要修改/提交任何文件）。\n\n"
            "本仓被路由器判定可能承接以下业务（粗粒度，需你读代码核实）：\n"
            f"路由理由：{routed_reason or '（无）'}\n"
            f"命中能力树节点：\n{node_paths_text}\n\n"
            "请深入阅读本仓代码，判断本仓是否真正适配上述业务，并以 **JSON** 输出 verdict，字段：\n"
            '- fit："fit"（适配）| "mismatch"（不适配）| "unknown"（无法判定）\n'
            "- confidence：置信度（high/medium/low）\n"
            "- summary：结论摘要\n"
            "- evidence_files：支撑判断的关键文件路径列表\n"
            "- mismatch_reasons：若不适配，列出原因；适配则为空数组\n"
        )

    async def _build_dispatch_metadata(self, repo: Any) -> dict[str, str]:
        """构造容器 env_metadata（复刻 research_adapter；只读 explore 语义）。

        any 异常不外泄到调度主轨（best-effort 取凭证；缺凭证容器内自报错）。token 绝不入日志。
        """
        from services.git_credentials import aresolve_git_token
        from services.provider_config import aget_claude_code_runtime_config

        metadata: dict[str, str] = {
            "repository_id": str(getattr(repo, "id", "") or ""),
            # 只读 explore 语义：双层 git 写操作拦截（深验不写 git，Pitfall 1）
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
            logger.warning("repo_verify_runtime_config_failed", component=_COMPONENT)

        repo_url = getattr(repo, "git_url", "") or ""
        has_git_token = False
        try:
            if repo is not None:
                token = await aresolve_git_token(repo)
                if token:
                    has_git_token = True
                    metadata["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] = token
                    metadata["env_FRIDAY_TASK_GIT_AUTH_TYPE"] = "token"
                    metadata["env_FRIDAY_TASK_GIT_SSL_VERIFY"] = "false"
                    if repo_url.startswith("git@"):
                        import re

                        m = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", repo_url)
                        if m:
                            repo_url = f"https://{m.group(1)}/{m.group(2)}.git"
        except Exception:  # noqa: BLE001 — git 凭证缺失不阻断调度
            logger.warning("repo_verify_git_token_failed", component=_COMPONENT)
        # token 绝不入日志，仅记布尔
        logger.debug(
            "repo_verify_dispatch_metadata_built",
            repository_id=str(getattr(repo, "id", "") or ""),
            has_git_token=has_git_token,
            component=_COMPONENT,
            category="sampling",
        )
        metadata["_repo_url"] = repo_url
        return metadata

    async def _count_online_runners(self) -> int:
        """在线 runner 计数（mirror research_adapter，无重试循环——后台推进非交互）。"""
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
