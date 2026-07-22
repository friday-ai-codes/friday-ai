"""CodingSession 专用 LangGraph StateGraph -- 单阶段编码 + PR 编排。

拓扑:
  START -> dispatch_coding -> wait_coding_complete(interrupt)
       -> (conditional: failed->END, success->conflict_check)
       -> conflict_check
       -> generate_pr_draft -> create_pr_or_skip
       -> create_pr_or_skip -> (conditional) -> END

Runner 在 coding 阶段直接生成最终 commit message、commit 并 push；Server 收到
completed callback 后只负责冲突预检和默认创建 PR。旧的 commit_confirm /
coding_commit 节点保留给历史 checkpoint/API 兼容，但新图不再连入。

每个 wait/await 节点使用 interrupt() 暂停 graph，通过 Command(resume=...) 恢复。
interrupt() 前只做幂等操作（UPDATE 同值），避免 resume 时重放副作用。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import anthropic
import structlog
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from chat.coding_session_service import dispatch_coding_task
from chat.models import CodingSession
from orchestration.coding_state import CodingSessionState

logger = structlog.get_logger(__name__)


async def _get_coding_session(state: CodingSessionState) -> CodingSession:
    """从 state 中的 coding_session_id 查询 CodingSession（含 select_related）。"""
    return await CodingSession.objects.select_related(
        "repository",
        "conversation__space",
        "coding_plan",
        "subagent_session",
    ).aget(id=state["coding_session_id"])


def _resolve_target_branch(coding_session: CodingSession) -> str:
    """解析 PR 目标分支：优先用户在启动编码时选定的值，否则回退默认 develop。"""
    from chat.branch_service import DEFAULT_TARGET_BRANCH

    selected = (coding_session.target_branch or "").strip()
    return selected or DEFAULT_TARGET_BRANCH


def _format_execution_spec(coding_session: CodingSession) -> str:
    """把结构化执行边界写进容器 prompt，避免依赖 Markdown 文案推断。"""
    repo = coding_session.repository
    affected_files = coding_session.affected_files or []
    files_text = "\n".join(
        f"- {item.get('file_path') or item.get('path') or item}"
        for item in affected_files
    ) or "- 未指定，按技术方案最小范围修改"
    return (
        "执行规格：\n"
        f"- 仓库：{repo.name}\n"
        f"- 基础分支：{repo.default_branch}\n"
        f"- 工作分支：{coding_session.branch_name}\n"
        f"- 目标分支：{_resolve_target_branch(coding_session)}\n"
        f"- 影响文件：\n{files_text}\n"
    )


def _extract_task_title(coding_session: CodingSession) -> str:
    """从 CodingPlan.title 或 tech_plan 标题提取给 Runner 使用的短标题。"""
    coding_plan = getattr(coding_session, "coding_plan", None)
    plan_title = getattr(coding_plan, "title", "") if coding_plan is not None else ""
    if isinstance(plan_title, str) and plan_title.strip():
        return plan_title.strip()[:200]

    tech_plan = getattr(coding_session, "tech_plan_effective", "") or getattr(
        coding_session, "tech_plan", "",
    )
    if isinstance(tech_plan, str):
        for raw_line in tech_plan.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            heading = re.sub(r"^#{1,6}\s*", "", line).strip()
            if heading:
                return heading[:200]

    repo = getattr(coding_session, "repository", None)
    repo_name = getattr(repo, "name", "") or "代码仓库"
    return f"{repo_name} 自动编码"[:200]


async def dispatch_coding_node(state: CodingSessionState) -> dict[str, Any]:
    """Phase: dispatch 编码任务到 Runner。

    从 state 提取 coding_session_id，查询 CodingSession，
    构建 prompt 调用 dispatch_coding_task，返回 phase1_session_id。
    """
    coding_session = await _get_coding_session(state)
    project = coding_session.conversation.space
    repo = coding_session.repository

    prompt = (
        f"你正在对项目「{project.name}」的代码仓库「{repo.name}」执行编码任务。\n\n"
        f"{_format_execution_spec(coding_session)}\n"
        f"技术方案：\n{coding_session.tech_plan}\n\n"
        f"请根据以上技术方案进行编码实现，只修改必要的代码文件。"
        f"不要执行任何分支、提交、推送或合并请求操作；这些由 Runner 和服务端统一处理。"
    )

    session_id = await dispatch_coding_task(
        coding_session,
        task_type="coding",
        prompt=prompt,
        extra_metadata={"env_FRIDAY_TASK_TASK_TITLE": _extract_task_title(coding_session)},
    )

    # implementation contract: 推进 CodingSession 状态 confirmed -> running。
    # 必须放在这里（dispatch_coding_node 内部）而非 view，因为 wait_coding_complete_node
    # resume 时会调 amark_awaiting_confirmation，该方法要求 status == RUNNING 前置。
    # 注意：dispatch_coding_task 返回的是 SubAgentSession.session_id（字符串），
    # 不是 FK int；但 dispatch_coding_task 内部已经在 `coding_session` 实例上
    # 设过 subagent_session_id 并 asave，因此这里直接读 FK 即可。
    await coding_session.amark_running(
        subagent_session_id=coding_session.subagent_session_id,
    )

    logger.info(
        "coding_graph_dispatch_coding",
        coding_session_id=state["coding_session_id"],
        phase1_session_id=session_id,
    )

    return {"phase": "waiting_coding", "phase1_session_id": session_id}


async def wait_coding_complete_node(state: CodingSessionState) -> dict[str, Any]:
    """Phase 等待: interrupt 暂停，等待容器完成回调 resume。

    resume 值为 {"success": True/False, "suggested_commit_message": "..."} 或 {"success": False, "error": "..."}。
    成功时自动采用容器建议 commit message 进入 commit 阶段，不再打断用户确认。
    失败时同步 CodingSession DB 状态为 failed。
    """
    result = interrupt({
        "waiting_for": "coding_complete",
        "coding_session_id": state["coding_session_id"],
    })

    coding_session = await _get_coding_session(state)

    if result.get("success"):
        suggested_msg = result.get("suggested_commit_message", "")
        if not suggested_msg:
            suggested_msg = "feat: implement changes"
        coding_session.suggested_commit_message = suggested_msg
        await coding_session.asave(update_fields=["suggested_commit_message", "updated_at"])
        logger.info(
            "coding_graph_phase1_success",
            coding_session_id=state["coding_session_id"],
            suggested_commit_message=suggested_msg,
        )
        return {
            "phase": "pr_pending",
            "suggested_commit_message": suggested_msg,
            "confirmed_commit_message": suggested_msg,
        }

    error = result.get("error", "未知错误")
    await coding_session.amark_failed(error)
    logger.warning(
        "coding_graph_phase1_failed",
        coding_session_id=state["coding_session_id"],
        error=error,
    )
    return {"phase": "failed", "error": error}


async def await_commit_confirm_node(state: CodingSessionState) -> dict[str, Any]:
    """兼容旧 checkpoint 的 commit message 确认节点。

    新流程不再进入此节点；Phase 成功后自动使用建议 commit message 进入
    dispatch_commit。保留本节点是为了让已经停在旧 checkpoint 的会话仍可被用户
    确认后继续推进。

    implementation G2 修复:
      - 前置节点为 conflict_check_node（由 build_coding_graph Phase 边拓扑决定）
      - interrupt 前 refresh DB 读取最新 conflict_check_result + diff_summary
        （由刚刚执行的 conflict_check_node 写入）
      - interrupt payload 新增 conflict_check_result 和 diff_summary 两个 key，
        作为前端 CommitConfirmCard 冲突警告区的冗余保底数据源
        （主数据源通过 conversation_service.build_runtime_state 轮询 DB 获取）

    resume 值为 confirmed_commit_message 字符串。
    resume 后同步 CodingSession DB 状态为 running。
    LangGraph interrupt 重放语义保证 resume 时 node 函数从头执行，
    _get_coding_session 会再次 refresh DB -- 安全读取最新状态。
    """
    # implementation G2: interrupt 前 refresh DB 拿 conflict_check_node 写入的最新结果
    coding_session = await _get_coding_session(state)

    interrupt_payload: dict[str, Any] = {
        "waiting_for": "commit_confirm",
        "suggested_commit_message": state.get("suggested_commit_message", ""),
        "conflict_check_result": coding_session.conflict_check_result,
        "diff_summary": coding_session.diff_summary,
    }
    confirmed_msg: str = interrupt(interrupt_payload)

    await coding_session.aresume_running()

    logger.info(
        "coding_graph_commit_confirmed",
        coding_session_id=state["coding_session_id"],
        confirmed_commit_message=confirmed_msg,
    )

    return {"phase": "committing", "confirmed_commit_message": confirmed_msg}


async def conflict_check_node(state: CodingSessionState) -> dict[str, Any]:
    """冲突预检节点 -- 检查功能分支与 base 分支的潜在冲突（per contract）。

    非阻断性: 任何错误都不阻止后续 dispatch_commit 流程（per contract）。
    一次 compare 调用同时产出冲突预检和 diff 摘要数据（per contract）。
    结果持久化到 CodingSession.conflict_check_result 和 diff_summary（per contract, contract）。

    implementation G2 修复后: 此节点在 await_commit_confirm 之前运行，
    不能推进 phase —— 必须保留 wait_coding_complete_node 设置的 "awaiting_commit_confirm"，
    由 await_commit_confirm_node 在 resume 后自行推进到 "committing"。
    """
    coding_session = await _get_coding_session(state)
    repo = coding_session.repository

    try:
        from services.git_credentials import aresolve_git_token
        from services.git_platform import get_git_platform_client

        # 经统一解析器取 token：per-repo 优先 → host 实例池 fallback（D-02）
        token = await aresolve_git_token(repo)
        if not token:
            logger.info("conflict_check_no_credential", coding_session_id=state["coding_session_id"])
            return {}

        client = get_git_platform_client(repo, token)

        result = await client.compare_branches(
            source_branch=coding_session.branch_name,
            target_branch=repo.default_branch,
        )

        if result.success:
            from django.utils import timezone

            suggestion = ""
            if result.has_potential_conflicts:
                suggestion = f"以下 {len(result.conflicting_files)} 个文件同时被修改，可能存在合并冲突，建议在 push 前本地解决"
            elif result.behind_by > 0:
                suggestion = f"目标分支有 {result.behind_by} 个新 commit，但未修改相同文件，预计可自动合并"

            conflict_data = {
                "has_conflicts": result.has_potential_conflicts,
                "conflicting_files": result.conflicting_files,
                "behind_by": result.behind_by,
                "suggestion": suggestion,
                "checked_at": timezone.now().isoformat(),
            }
            coding_session.conflict_check_result = conflict_data

            diff_data = {
                "files": [
                    {
                        "path": f.path,
                        "additions": f.additions,
                        "deletions": f.deletions,
                        "change_type": f.change_type,
                    }
                    for f in result.files
                ],
                "total_additions": result.total_additions,
                "total_deletions": result.total_deletions,
                "truncated": result.truncated,
            }
            coding_session.diff_summary = diff_data

            await coding_session.asave(update_fields=[
                "conflict_check_result", "diff_summary", "updated_at",
            ])

            logger.info(
                "conflict_check_completed",
                coding_session_id=state["coding_session_id"],
                has_conflicts=result.has_potential_conflicts,
                behind_by=result.behind_by,
                file_count=len(result.files),
            )
        else:
            logger.warning(
                "conflict_check_api_error",
                coding_session_id=state["coding_session_id"],
                error=result.error,
            )

    except Exception:
        logger.exception(
            "conflict_check_error",
            coding_session_id=state["coding_session_id"],
        )

    return {}


async def dispatch_commit_node(state: CodingSessionState) -> dict[str, Any]:
    """Phase: dispatch commit 修正任务到 Runner。

    使用 coding_commit task_type，通过 extra_metadata 传递用户确认的 commit message。
    容器 checkout 编码分支后执行 git commit --amend + git push --force-with-lease。
    """
    coding_session = await _get_coding_session(state)
    confirmed_msg = state["confirmed_commit_message"]

    prompt = (
        f"{_format_execution_spec(coding_session)}\n"
        f"Runner 将在上述工作分支执行以下操作：\n"
        f"1. 使用 FRIDAY_TASK_COMMIT_MESSAGE 执行 git commit --amend\n"
        f"2. git push --force-with-lease\n"
        f"合并请求由服务端后续流程处理，本阶段只负责修正 commit message 并推送分支。\n"
    )

    session_id = await dispatch_coding_task(
        coding_session,
        task_type="coding_commit",
        extra_metadata={"env_FRIDAY_TASK_COMMIT_MESSAGE": confirmed_msg},
        prompt=prompt,
    )

    logger.info(
        "coding_graph_dispatch_commit",
        coding_session_id=state["coding_session_id"],
        phase2_session_id=session_id,
    )

    return {"phase": "waiting_commit", "phase2_session_id": session_id}


async def wait_commit_complete_node(state: CodingSessionState) -> dict[str, Any]:
    """Phase 等待: interrupt 暂停，等待 commit 容器完成回调 resume。

    resume 值为 {"success": True/False}。
    成功时保持 running 状态（后续 generate_pr_draft 处理）。
    失败时同步 CodingSession DB 状态为 failed。
    """
    result = interrupt({
        "waiting_for": "commit_complete",
        "coding_session_id": state["coding_session_id"],
    })

    coding_session = await _get_coding_session(state)

    if result.get("success"):
        # 成功时不再调用 amark_completed，保持 running 状态让后续 generate_pr_draft 处理
        logger.info(
            "coding_graph_phase2_success",
            coding_session_id=state["coding_session_id"],
        )
        return {"phase": "pr_pending"}

    error = result.get("error", "未知错误")
    await coding_session.amark_failed(error)
    logger.warning(
        "coding_graph_phase2_failed",
        coding_session_id=state["coding_session_id"],
        error=error,
    )
    return {"phase": "failed", "error": error}


# ---------------------------------------------------------------------------
# Phase: PR 草稿生成 + 确认 + 创建/跳过
# ---------------------------------------------------------------------------


async def _call_llm_for_pr_draft(
    coding_session: CodingSession,
    confirmed_commit_message: str,
) -> tuple[str, str]:
    """调用 LLM 生成 PR 标题和描述。

    Returns:
        (title, description) 元组。
    """
    # Claude Code 编码容器配置：PR 草稿生成跟随 Claude Code 选定凭证；
    # 未配置时 runtime_config 内部回退系统默认 anthropic 凭证。
    from services.provider_config import aget_claude_code_runtime_config

    cc = await aget_claude_code_runtime_config()
    api_key = cc["api_key"]
    base_url = cc["base_url"]
    model = cc["default_model"] or cc["sonnet_model"] or "claude-sonnet-4-20250514"

    if not api_key:
        raise ValueError("Anthropic API key 未配置")

    if base_url:
        client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)
    else:
        client = anthropic.AsyncAnthropic(api_key=api_key)

    # 构建 prompt
    affected_files_str = ""
    if coding_session.affected_files:
        affected_files_str = "\n".join(
            f"- {f.get('path', '')} ({f.get('change_type', '')})"
            for f in coding_session.affected_files[:20]
        )

    prompt = (
        "根据以下编码任务信息，生成一个 Pull Request 的标题和描述。\n\n"
        f"## 技术方案\n{coding_session.tech_plan}\n\n"
        f"## Commit Message\n{confirmed_commit_message}\n\n"
        f"## 影响文件\n{affected_files_str}\n\n"
        "请以 JSON 格式返回，格式如下：\n"
        '{"title": "简洁的 PR 标题（不超过 100 字符）", "description": "详细的 PR 描述（Markdown 格式）"}\n\n'
        "只返回 JSON，不要其他文字。"
    )

    response = await client.messages.create(
        model=model,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()  # type: ignore[union-attr]

    # 尝试 JSON 解析
    try:
        data = json.loads(text)
        return data.get("title", "")[:200], data.get("description", "")
    except (json.JSONDecodeError, KeyError):
        # 尝试从文本提取
        lines = text.strip().split("\n")
        title = lines[0][:200] if lines else ""
        description = "\n".join(lines[1:]) if len(lines) > 1 else ""
        return title, description


def build_branch_url(git_url: str, git_platform: str, branch_name: str) -> str:
    """构建分支 URL。"""
    from services.git_platform import (
        extract_github_owner_repo,
        extract_gitlab_url,
        extract_project_path,
    )

    if git_platform == "github":
        try:
            owner, repo = extract_github_owner_repo(git_url)
            return f"https://github.com/{owner}/{repo}/tree/{branch_name}"
        except ValueError:
            return ""
    elif git_platform == "gitlab":
        try:
            base_url = extract_gitlab_url(git_url)
            project_path = extract_project_path(git_url)
            return f"{base_url}/{project_path}/-/tree/{branch_name}"
        except ValueError:
            return ""
    return ""


async def generate_pr_draft_node(state: CodingSessionState) -> dict[str, Any]:
    """Phase 步骤 1: 使用 LLM 生成 PR 草稿标题和描述。

    幂等检查: 如果 CodingSession.suggested_pr_title 已有值则跳过 LLM 调用。
    LLM 失败时使用 fallback 模板（不标记 failed）。
    """
    coding_session = await _get_coding_session(state)
    confirmed_msg = state.get("confirmed_commit_message", "")

    # 幂等检查
    if coding_session.suggested_pr_title:
        title = coding_session.suggested_pr_title
        description = coding_session.suggested_pr_description
        logger.info(
            "coding_graph_pr_draft_idempotent",
            coding_session_id=state["coding_session_id"],
        )
    else:
        try:
            title, description = await asyncio.wait_for(
                _call_llm_for_pr_draft(coding_session, confirmed_msg),
                timeout=20,
            )
            if not title:
                raise ValueError("LLM 返回空标题")
        except Exception:
            logger.exception(
                "coding_graph_pr_draft_llm_failed",
                coding_session_id=state["coding_session_id"],
            )
            # fallback: commit message 第一行作为 title，tech_plan 前 500 字符作为 description
            first_line = confirmed_msg.split("\n")[0] if confirmed_msg else "PR"
            title = first_line[:200]
            description = (coding_session.tech_plan or "")[:500]

        # 持久化到 DB
        coding_session.suggested_pr_title = title
        coding_session.suggested_pr_description = description
        await coding_session.asave(update_fields=[
            "suggested_pr_title", "suggested_pr_description", "updated_at",
        ])

    logger.info(
        "coding_graph_pr_draft_generated",
        coding_session_id=state["coding_session_id"],
        title=title[:50],
    )

    return {
        "phase": "creating_pr",
        "skip_pr": False,
        "suggested_pr_title": title,
        "suggested_pr_description": description,
        "confirmed_pr_title": title,
        "confirmed_pr_description": description,
        "target_branch": _resolve_target_branch(coding_session),
    }


async def await_pr_confirm_node(state: CodingSessionState) -> dict[str, Any]:
    """Phase 步骤 2: interrupt 等待用户确认 PR 操作（创建 or 跳过）。

    resume 值为 dict:
    - skip_pr=True: 跳过 PR 创建
    - skip_pr=False: 创建 PR，包含 title/description/target_branch
    """
    result: dict[str, Any] = interrupt({
        "waiting_for": "pr_confirm",
        "suggested_pr_title": state.get("suggested_pr_title", ""),
        "suggested_pr_description": state.get("suggested_pr_description", ""),
    })

    coding_session = await _get_coding_session(state)

    if result.get("skip_pr"):
        return {"phase": "skipping_pr", "skip_pr": True}

    await coding_session.aresume_running()
    return {
        "phase": "creating_pr",
        "skip_pr": False,
        "confirmed_pr_title": result["title"],
        "confirmed_pr_description": result["description"],
        "target_branch": result.get("target_branch", state.get("target_branch", "")),
    }


async def _run_completion_loop(
    coding_session: CodingSession,
    *,
    pr_url: str,
    write_back: bool,
) -> None:
    """chat 链完工闭环（LOOP-02/03 / 101-03）：公共回写 + learning case 提炼调度。

    调用方须整块 try/except 包裹（best-effort fail-soft，绝不影响节点返回值）。

    - 回写（仅 ``write_back=True``，即 PR 创建成功分支；skip-PR 不回写——CONTEXT 锁定）：
      经 ``aresolve_triple_for_coding_session`` 反查三元组，反查不到自然跳过
      （debug 级日志，不加会话级开关——避免新配置面）。
    - 提炼：编码成功完成即调度（skip-PR 分支也触发——LOOP-03 "任一链路编码成功完成"
      语义；MR 已知 = 无，pr_url 传 ""）。经 ``run_in_background`` 后台调度、
      不 await Future，绝不阻塞 graph 节点收尾。
    - 归因（T-101-03-04）：chat 链发起用户 = conversation.created_by（标量取）。
    """
    # lazy import 防循环。
    from chat.models import Conversation
    from delivery.services.coding_completion import (
        CompletionWritebackService,
        RepoResult,
        aresolve_triple_for_coding_session,
    )
    from mcp_tools.learning_case_extraction import aextract_for_session
    from services.background_runner import run_in_background

    # 发起用户标量取；取不到 fail-soft 为 None（公共层记 "system"）。
    initiated_by: str | None = None
    try:
        created_by_id = (
            await Conversation.objects.filter(id=coding_session.conversation_id)
            .values_list("created_by_id", flat=True)
            .afirst()
        )
        initiated_by = str(created_by_id) if created_by_id else None
    except Exception:  # noqa: BLE001, S110 — 归因取不到不阻断闭环
        initiated_by = None

    triple = await aresolve_triple_for_coding_session(coding_session)

    if write_back:
        if triple is None:
            logger.debug(
                "chat_writeback_skipped_no_work_item",
                coding_session_id=str(coding_session.id),
            )
        else:
            title = ""
            try:
                if coding_session.coding_plan is not None:
                    title = coding_session.coding_plan.title or ""
            except Exception:  # noqa: BLE001, S110 — 标题增强 fail-soft
                title = ""
            repo = coding_session.repository
            await CompletionWritebackService().awrite_back(
                feishu_project_key=triple.feishu_project_key,
                work_item_type=triple.work_item_type,
                work_item_id=triple.work_item_id,
                title=title or "编码任务",
                results=[
                    RepoResult(
                        repo_name=repo.name,
                        status="completed",
                        branch_name=coding_session.branch_name,
                        mr_url=pr_url,
                    )
                ],
                space_id=triple.space_id,
                initiated_by_user_id=initiated_by,
            )

    # 提炼调度（回写与否互不依赖：提炼有自己的 kill switch 与质量门）。
    if coding_session.subagent_session_id:
        session_id = str(coding_session.subagent_session.session_id)
        requirement_text = ""
        try:
            if coding_session.coding_plan is not None:
                requirement_text = coding_session.coding_plan.title or ""
            if not requirement_text:
                requirement_text = (coding_session.tech_plan or "")[:500]
        except Exception:  # noqa: BLE001, S110 — 需求文本增强 fail-soft
            requirement_text = ""
        run_in_background(
            lambda: aextract_for_session(
                session_id,
                requirement_text=requirement_text,
                work_item_type=triple.work_item_type if triple else "",
                work_item_id=triple.work_item_id if triple else None,
                pr_url=pr_url,
                initiated_by_user_id=initiated_by,
            ),
            name=f"learning-case-{session_id}",
            initiated_by_user_id=initiated_by,
        )


async def create_pr_or_skip_node(state: CodingSessionState) -> dict[str, Any]:
    """Phase 步骤 3: 根据用户选择创建 PR 或跳过。

    Skip 路径: 标记 completed + 返回 branch_url + 调用 store_coding_complete_to_message
    创建 PR 路径: 通过 GitPlatformClient 创建 PR
    """
    from chat.coding_events import store_coding_complete_to_message
    from services.git_credentials import aresolve_git_token
    from services.git_platform import get_git_platform_client
    from services.git_platform.models import MRCreateRequest

    coding_session = await _get_coding_session(state)
    repo = coding_session.repository

    if state.get("skip_pr"):
        # Skip 路径
        branch_url = build_branch_url(
            repo.git_url, repo.git_platform, coding_session.branch_name,
        )
        await coding_session.amark_completed(pr_url="")

        # INGEST-02（14-06）：skip-PR 完成锚点投递统一摄取（时序防线：归档挂
        # PR 决策之后而非容器回调；skip 路径 pr_url="" 属预期，归档走 branch diff）。
        if coding_session.subagent_session_id:
            from knowledge import ingestion  # lazy import 防循环

            await ingestion.aschedule_ingestion(
                ingestion.IngestionRequest(
                    "task_result",
                    str(coding_session.subagent_session.session_id),
                    "chat_coding_pr_skipped",
                )
            )

        await store_coding_complete_to_message(coding_session, branch_url=branch_url)

        # LOOP-03（101-03）：skip-PR 分支不回写（CONTEXT 锁定），但提炼照常触发——
        # 编码已成功完成，MR 结果已知（= 无）。整块 fail-soft，绝不影响返回值。
        try:
            await _run_completion_loop(coding_session, pr_url="", write_back=False)
        except Exception as exc:  # noqa: BLE001 — 完工闭环 fail-soft
            logger.warning(
                "coding_graph_completion_loop_failed",
                coding_session_id=state["coding_session_id"],
                error=str(exc),
            )

        logger.info(
            "coding_graph_pr_skipped",
            coding_session_id=state["coding_session_id"],
            branch_url=branch_url,
        )
        return {"phase": "completed", "branch_url": branch_url}

    # 创建 PR 路径：经统一解析器取 token（per-repo 优先 → host 实例池 fallback，D-02）
    token = await aresolve_git_token(repo)
    if not token:
        error_msg = "Git 凭据未配置，无法创建 PR"
        await coding_session.amark_failed(error_msg)
        logger.warning(
            "coding_graph_pr_no_credential",
            coding_session_id=state["coding_session_id"],
        )
        return {"phase": "failed", "error": error_msg}

    client = get_git_platform_client(repo, token)
    mr_request = MRCreateRequest(
        source_branch=coding_session.branch_name,
        target_branch=state.get("target_branch") or _resolve_target_branch(coding_session),
        title=state["confirmed_pr_title"],
        description=state["confirmed_pr_description"],
    )

    result = await client.create_merge_request(mr_request)

    if result.success:
        await coding_session.amark_completed(pr_url=result.mr_url)

        # INGEST-02（14-06）：PR 创建成功锚点投递统一摄取（mr_url 权威源已经
        # amark_completed 持久化进 CodingSession.pr_url，normalizer 后台重读）。
        if coding_session.subagent_session_id:
            from knowledge import ingestion  # lazy import 防循环

            await ingestion.aschedule_ingestion(
                ingestion.IngestionRequest(
                    "task_result",
                    str(coding_session.subagent_session.session_id),
                    "chat_coding_pr_created",
                )
            )

        await store_coding_complete_to_message(coding_session)

        # LOOP-02/03（101-03）：PR 创建成功（MR 已知）锚点——公共回写（能反查到
        # work_item 三元组才回写，反查不到自然跳过）+ 提炼调度。整块 fail-soft。
        try:
            await _run_completion_loop(
                coding_session, pr_url=result.mr_url, write_back=True
            )
        except Exception as exc:  # noqa: BLE001 — 完工闭环 fail-soft
            logger.warning(
                "coding_graph_completion_loop_failed",
                coding_session_id=state["coding_session_id"],
                error=str(exc),
            )

        logger.info(
            "coding_graph_pr_created",
            coding_session_id=state["coding_session_id"],
            pr_url=result.mr_url,
        )
        return {"phase": "completed", "pr_url": result.mr_url}

    await coding_session.amark_failed(result.error)
    logger.warning(
        "coding_graph_pr_creation_failed",
        coding_session_id=state["coding_session_id"],
        error=result.error,
    )
    return {"phase": "failed", "error": result.error}


# ---------------------------------------------------------------------------
# 条件路由
# ---------------------------------------------------------------------------


def route_after_coding(state: CodingSessionState) -> str:
    """条件路由: coding 失败 -> END, 成功 -> conflict_check。"""
    if state.get("phase") == "failed":
        return END
    return "conflict_check"


def route_after_commit(state: CodingSessionState) -> str:
    """条件路由: Phase 失败 -> END, 成功 -> generate_pr_draft。"""
    if state.get("phase") == "failed":
        return END
    return "generate_pr_draft"


def route_after_pr(state: CodingSessionState) -> str:
    """条件路由: PR 创建/跳过后 -> END。"""
    return END


def build_coding_graph() -> StateGraph:
    """构建 CodingSession 编排 StateGraph builder。

    拓扑（单阶段编码 + 默认 PR）:
      START -> dispatch_coding -> wait_coding_complete
        -> (conditional: failed->END, success->conflict_check)
        -> conflict_check
        -> generate_pr_draft -> create_pr_or_skip
        -> (conditional) -> END

    旧节点 await_commit_confirm / dispatch_commit / wait_commit_complete 保留给历史
    checkpoint 兼容；新流程不再启动 coding_commit 容器。
    """
    builder: StateGraph = StateGraph(CodingSessionState)

    # Phase + 2 原有节点
    builder.add_node("dispatch_coding", dispatch_coding_node)
    builder.add_node("wait_coding_complete", wait_coding_complete_node)
    builder.add_node("await_commit_confirm", await_commit_confirm_node)
    builder.add_node("conflict_check", conflict_check_node)
    builder.add_node("dispatch_commit", dispatch_commit_node)
    builder.add_node("wait_commit_complete", wait_commit_complete_node)

    # Phase 新增节点
    builder.add_node("generate_pr_draft", generate_pr_draft_node)
    builder.add_node("await_pr_confirm", await_pr_confirm_node)
    builder.add_node("create_pr_or_skip", create_pr_or_skip_node)

    # Phase 边
    builder.add_edge(START, "dispatch_coding")
    builder.add_edge("dispatch_coding", "wait_coding_complete")
    builder.add_conditional_edges("wait_coding_complete", route_after_coding)

    # 编码完成后直接进入 PR 流程，不再 dispatch coding_commit amend 容器。
    builder.add_edge("conflict_check", "generate_pr_draft")

    # Phase 边：生成 PR 草稿后默认创建 PR；await_pr_confirm 仅保留给旧 checkpoint/API 兼容。
    builder.add_edge("generate_pr_draft", "create_pr_or_skip")
    builder.add_edge("await_pr_confirm", "create_pr_or_skip")
    builder.add_conditional_edges("create_pr_or_skip", route_after_pr)

    return builder
