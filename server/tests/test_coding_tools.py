"""coding_tools 单元测试 — create_coding_plan / update_coding_plan @tool。

coding-plan workflow：``create_coding_plan`` 不再创建 ``CodingSession``，
session 由前端通过 fan-out endpoint
``POST /api/chat/coding-plans/{plan_id}/sessions/`` 创建。

**SPINE-02（Phase 109）**：两个工具的创作半边已在 schema 层砍掉 —— 入参不再有
``tech_plan`` / ``affected_files``，改为必填 ``artifact_version_id``。因此本文件的
用例全部按「先造一个编排产出的 ``ArtifactVersion``，再让工具把它投影 / re-bind」
的形状造数。原有覆盖意图（不产 session、space / repository / conversation 三段校验、
推荐仓库四种来源、dual-id 兼容键）逐条保留。

分组（``-k`` 选择器）：

- ``reject``：无来源 / 非法来源 / 跨会话的创作尝试一律被拒绝且留痕
- ``update``：re-bind 成功、版本已被占用、legacy session_id 兼容路径
"""

import uuid
from typing import Any

import pytest
import structlog
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from structlog.testing import capture_logs

from chat.models import CodingPlan, CodingPlanProvenance, CodingSession, Conversation
from delivery.models import (
    Artifact,
    ArtifactVersion,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
    WorkItem,
    WorkItemOrigin,
)
from repositories.models import Repository

User = get_user_model()

_AUTHORING_REJECTED_EVENT = "coding_plan_authoring_attempt_rejected"


# ============================================================================
# 造数 helper —— 编排来源链（WorkItem → Artifact → ArtifactVersion）
# ============================================================================


def _task(
    *,
    repository_id: str = "",
    files: Any = None,
    task_id: str = "t1",
) -> dict[str, Any]:
    """构造一条 §7 ``execution_plan[]`` task（只填投影映射关心的键）。"""
    return {
        "id": task_id,
        "name": "任务",
        "repository_id": repository_id,
        "repository_name": f"repo-{repository_id or 'none'}",
        "branch_strategy": "feature",
        "coding_instruction": "实现任务",
        "files": [] if files is None else files,
    }


def _content(*tasks: dict[str, Any], title: str = "编排产出的技术方案") -> dict[str, Any]:
    return {
        "title": title,
        "summary": "由完整编排链路产出的方案正文。",
        "execution_plan": list(tasks),
        "compat_risks": [],
    }


def _mk_artifact_version(
    *,
    conversation: Conversation | None,
    content: Any = None,
    artifact: Artifact | None = None,
    version_no: int = 1,
) -> ArtifactVersion:
    """造一条完整来源链；``conversation`` 决定投影的归属会话与 owner。"""
    session = ConvergenceSession.objects.create(
        process_type="technical_plan",
        entrypoint=(
            ConvergenceSessionEntrypoint.CHAT
            if conversation is not None
            else ConvergenceSessionEntrypoint.WORKFLOW
        ),
        current_stage="merge",
        status=ConvergenceSessionStatus.DONE,
        conversation_id=conversation.id if conversation is not None else None,
    )
    if artifact is None:
        artifact = Artifact.objects.create(
            artifact_type="technical_plan",
            work_item=WorkItem.objects.create(
                feishu_project_key=f"pk-{uuid.uuid4().hex[:8]}",
                work_item_type="story",
                work_item_id=int(uuid.uuid4().int % 10_000_000),
                origin=WorkItemOrigin.MANUAL,
                title="需求标题",
            ),
            title="技术方案",
        )
    return ArtifactVersion.objects.create(
        artifact=artifact,
        version_no=version_no,
        content=_content(_task(files=[{"path": "src/api.py", "action": "create"}]))
        if content is None
        else content,
        produced_by_session_id=str(session.id),
    )


_amk_artifact_version = sync_to_async(_mk_artifact_version)


@pytest.fixture
def plan_owner(db):
    """会话归属用户 —— 归属判定下移进投影 service 后，造数必须有明确 owner。"""
    return User.objects.create_user(
        username=f"coding_owner_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@coding.local",
        password="testpass123",
    )


@pytest.fixture
def conversation(project, plan_owner):
    """创建绑定到 project 的测试 Conversation（带 created_by）。

    ``created_by`` 是必需的：``create_coding_plan`` 取不到请求上下文用户时退回
    conversation 的创建者作为归属主体，而 service 侧的归属判定**拒绝**空身份。
    """
    return Conversation.objects.create(
        space=project,
        title="测试编码对话",
        created_by=plan_owner,
    )


@pytest.fixture
def other_repository(db):
    """创建不属于 project 的独立 Repository。"""
    return Repository.objects.create(
        name="Other Repo",
        git_url="https://github.com/other/repo.git",
        git_platform="github",
        default_branch="main",
    )


@pytest.fixture
def as_owner(plan_owner):
    """把 ``plan_owner`` 绑成当前请求上下文用户（第一优先来源）。

    归属主体的两个来源：① 请求上下文；② 服务端注入的 ``conversation_id`` 反查会话
    创建者。本 fixture 只覆盖 ①；② 的可用性由
    ``TestUpdateCodingPlanActorResolution`` 按生产绑定形态单独锁住（109-REVIEW BL-01：
    生产里 contextvars 恒为中间件写的 ``"system"`` 占位，只有 ① 时本工具恒失败）。
    """
    tokens = structlog.contextvars.bind_contextvars(user_id=str(plan_owner.id))
    yield plan_owner
    structlog.contextvars.reset_contextvars(**tokens)


# ============================================================================
# create_coding_plan 测试（SPINE-02 收窄后：投影而非撰写）
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestCreateCodingPlan:
    """create_coding_plan @tool 测试 — 工具只把编排产出投影成 CodingPlan。"""

    @pytest.mark.asyncio
    async def test_create_coding_plan_success_returns_plan_only(
        self, project, repository, conversation
    ):
        """传入有效来源版本 → success=True，返回 plan_id 非空、session_id 为 None。"""
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(conversation=conversation)
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is True
        assert result.output["coding_plan_id"]
        assert result.output["coding_session_id"] is None
        assert result.output["session_id"] is None
        assert result.output["status"] == "plan_only"
        # branch_name 不再由工具产；fan-out endpoint 自己生成
        assert result.output["branch_name"] == ""

    @pytest.mark.asyncio
    async def test_create_coding_plan_payload_key_set_is_frozen(
        self, project, repository, conversation
    ):
        """返回 payload 的 10 个键一个不少 —— 前端 ``codingPlanData`` 与历史消息解析
        依赖这套键形，删键会静默降级（SPINE-02 只砍创作半边，执行半边键形不变）。"""
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(conversation=conversation)
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is True
        assert set(result.output) == {
            "coding_plan_id",
            "coding_session_id",
            "session_id",
            "repository_id",
            "repository_name",
            "status",
            "branch_name",
            "recommended_repository_ids",
            "recommended_repositories",
            "recommended_source",
            "message",
        }

    @pytest.mark.asyncio
    async def test_create_coding_plan_does_not_create_session(
        self, project, repository, conversation
    ):
        """工具不再 acreate CodingSession：调用前后 DB 计数不变。"""
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(conversation=conversation)
        before = await CodingSession.objects.acount()
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            artifact_version_id=str(version.id),
        )
        after = await CodingSession.objects.acount()
        assert result.success is True
        assert before == after  # 工具不再产 session

    @pytest.mark.asyncio
    async def test_create_coding_plan_persists_projected_body(
        self, project, repository, conversation
    ):
        """正文与影响文件一律来自来源版本的渲染结果（工具不接受正文入参）。

        同时锁住 ``action → change_type`` 的枚举映射（``create → add``）——
        漏做该转换不会崩，只会在界面上静默显示成 ``create``。
        """
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(
            conversation=conversation,
            content=_content(
                _task(
                    files=[
                        {"path": "src/a.py", "action": "create"},
                        {"path": "src/b.py", "action": "modify"},
                    ]
                ),
                title="投影正文用例",
            ),
        )
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is True
        plan = await CodingPlan.objects.aget(id=result.output["coding_plan_id"])
        assert "投影正文用例" in plan.tech_plan
        assert plan.affected_files == [
            {"file_path": "src/a.py", "change_type": "add"},
            {"file_path": "src/b.py", "change_type": "modify"},
        ]
        # 投影来源可追溯，且 provenance 标记为编排产出（不是徒手撰写）。
        assert str(plan.source_artifact_version_id) == str(version.id)
        assert plan.provenance == CodingPlanProvenance.ORCHESTRATED

    @pytest.mark.asyncio
    async def test_create_coding_plan_is_idempotent_on_same_source_version(
        self, project, repository, conversation
    ):
        """同一来源版本连续投影两次 → 同一条 plan（幂等键是 source_artifact_version_id）。"""
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(conversation=conversation)
        kwargs = dict(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            artifact_version_id=str(version.id),
        )
        first = await create_coding_plan(**kwargs)
        second = await create_coding_plan(**kwargs)
        assert first.success and second.success
        assert first.output["coding_plan_id"] == second.output["coding_plan_id"]
        assert first.output["coding_session_id"] is None
        assert second.output["coding_session_id"] is None

    @pytest.mark.asyncio
    async def test_create_coding_plan_project_not_found(self, repository, conversation):
        """传入不存在的 space_id，返回 success=False。"""
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(conversation=conversation)
        result = await create_coding_plan(
            space_id=str(uuid.uuid4()),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_coding_plan_repo_not_in_project(
        self, project, other_repository, conversation
    ):
        """传入不属于该 space 的 repository_id，返回 success=False。

        repository_id 现在 optional，但传入后仍校验 space 归属。
        """
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(conversation=conversation)
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(other_repository.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is False
        assert "does not belong" in (result.error or "")

    @pytest.mark.asyncio
    async def test_create_coding_plan_conversation_not_found(self, project, repository):
        """传入不存在的 conversation_id，返回 success=False。"""
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(conversation=None)
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(uuid.uuid4()),
            repository_id=str(repository.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_coding_plan_without_repository_id(self, project, conversation):
        """coding-plan workflow：repository_id 可省略，工具仍能产生 plan。"""
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(conversation=conversation)
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is True
        assert result.output["coding_plan_id"]
        assert result.output["repository_id"] == ""
        assert result.output["repository_name"] == ""

    @pytest.mark.asyncio
    async def test_create_coding_plan_repository_id_topped_in_recommended(
        self, project, repository, conversation, other_repository
    ):
        """coding-plan workflow：传入 repository_id 时合并进 recommended（置顶）。

        ``recommended_repository_ids=[other]`` + ``repository_id=primary``：
        最终列表为 [primary, other]，primary 在前。
        """
        from agents.tools.coding_tools import create_coding_plan

        # 把 other_repository 也加入 project，让校验通过
        await sync_to_async(project.repositories.add)(other_repository)

        version = await _amk_artifact_version(conversation=conversation)
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            artifact_version_id=str(version.id),
            recommended_repository_ids=[str(other_repository.id)],
        )
        assert result.success is True
        ids = result.output["recommended_repository_ids"]
        assert ids[0] == str(repository.id)  # primary 置顶
        assert str(other_repository.id) in ids


# ============================================================================
# reject —— 无来源 / 非法来源 / 跨会话的创作尝试（SPINE-02 留痕）
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestCreateCodingPlanRejectsAuthoring:
    """schema 层收窄后仍可能被尝试的四种「无正当来源」路径，全部 fail-closed + 留痕。"""

    @pytest.mark.asyncio
    async def test_reject_missing_artifact_version_id(self, project, repository, conversation):
        from agents.tools.coding_tools import create_coding_plan

        with capture_logs() as logs:
            result = await create_coding_plan(
                space_id=str(project.id),
                conversation_id=str(conversation.id),
                repository_id=str(repository.id),
                artifact_version_id="",
            )
        assert result.success is False
        assert "artifact_version_id" in (result.error or "")
        assert _AUTHORING_REJECTED_EVENT in [entry.get("event") for entry in logs]
        assert await CodingPlan.objects.acount() == 0

    @pytest.mark.asyncio
    async def test_reject_unknown_artifact_version_id(self, project, repository, conversation):
        from agents.tools.coding_tools import create_coding_plan

        with capture_logs() as logs:
            result = await create_coding_plan(
                space_id=str(project.id),
                conversation_id=str(conversation.id),
                repository_id=str(repository.id),
                artifact_version_id=str(uuid.uuid4()),
            )
        assert result.success is False
        assert "artifact_version_not_found" in (result.error or "")
        rejected = [e for e in logs if e.get("event") == _AUTHORING_REJECTED_EVENT]
        assert rejected, "无来源尝试必须留痕"
        assert rejected[0]["category"] == "caller"
        assert rejected[0]["component"] == "agents"
        assert await CodingPlan.objects.acount() == 0

    @pytest.mark.asyncio
    async def test_reject_source_content_is_not_dict(self, project, repository, conversation):
        """来源版本的 ``content`` 非 dict → 与「不存在」同一机器码（fail-closed）。"""
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(
            conversation=conversation,
            content="不是 dict 的正文",
        )
        with capture_logs() as logs:
            result = await create_coding_plan(
                space_id=str(project.id),
                conversation_id=str(conversation.id),
                repository_id=str(repository.id),
                artifact_version_id=str(version.id),
            )
        assert result.success is False
        assert _AUTHORING_REJECTED_EVENT in [entry.get("event") for entry in logs]
        assert await CodingPlan.objects.acount() == 0

    @pytest.mark.asyncio
    async def test_reject_cross_conversation_source_without_leaking_body(
        self, project, repository, conversation, plan_owner
    ):
        """工具以 A 会话的来源版本 + B 的用户上下文调用 → 拒绝且 error 不回显他人正文。

        工具路径与 HTTP 端点共享 service 内的同一道归属判定
        （``artifact_version_forbidden``），这条用例是「工具没有第二条绕行路」的证据。
        """
        from agents.tools.coding_tools import create_coding_plan

        secret_title = "用户 A 的机密方案标题"
        version = await _amk_artifact_version(
            conversation=conversation,
            content=_content(
                _task(files=[{"path": "secret/plan.py", "action": "create"}]),
                title=secret_title,
            ),
        )
        intruder = await sync_to_async(User.objects.create_user)(
            username=f"intruder_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@coding.local",
            password="testpass123",
        )
        tokens = structlog.contextvars.bind_contextvars(user_id=str(intruder.id))
        try:
            with capture_logs() as logs:
                result = await create_coding_plan(
                    space_id=str(project.id),
                    conversation_id=str(conversation.id),
                    repository_id=str(repository.id),
                    artifact_version_id=str(version.id),
                )
        finally:
            structlog.contextvars.reset_contextvars(**tokens)

        assert result.success is False
        assert "artifact_version_forbidden" in (result.error or "")
        assert secret_title not in (result.error or "")
        assert "secret/plan.py" not in (result.error or "")
        assert _AUTHORING_REJECTED_EVENT in [entry.get("event") for entry in logs]
        assert await CodingPlan.objects.acount() == 0


# ============================================================================
# update —— re-bind 到新的编排方案版本
# ============================================================================


def _mk_session_for_plan(*, conversation, repository, plan, status=None, branch_name="manual-test"):
    """同步辅助：在 plan 上手建一条 CodingSession（替代旧路径里 create_coding_plan
    顺便产 session 的副作用）。"""
    return CodingSession.objects.create(
        conversation=conversation,
        coding_plan=plan,
        repository=repository,
        tech_plan=plan.tech_plan,
        affected_files=plan.affected_files,
        branch_name=branch_name,
        status=status or CodingSession.Status.DRAFT,
    )


@pytest.fixture
def draft_coding_session(conversation, repository):
    """创建 draft 状态、**未关联 plan** 的 CodingSession（legacy 兼容路径造数）。"""
    return CodingSession.objects.create(
        conversation=conversation,
        repository=repository,
        tech_plan="## 初始方案",
        affected_files=[{"file_path": "src/old.py", "change_type": "modify"}],
        branch_name="coding-test1234",
    )


@pytest.mark.django_db(transaction=True)
class TestUpdateCodingPlan:
    """update_coding_plan @tool 测试 —— 语义收窄为 re-bind（不接受正文）。"""

    @pytest.mark.asyncio
    async def test_update_coding_plan_rebinds_by_plan_id(
        self, project, repository, conversation, as_owner
    ):
        """coding_plan_id 路径：plan 正文换成新版本渲染结果 + draft session 同步。"""
        from agents.tools.coding_tools import create_coding_plan, update_coding_plan

        v1 = await _amk_artifact_version(
            conversation=conversation,
            content=_content(_task(files=[{"path": "v1.py", "action": "create"}]), title="方案 v1"),
        )
        created = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            artifact_version_id=str(v1.id),
        )
        plan_id = created.output["coding_plan_id"]
        plan = await CodingPlan.objects.aget(id=plan_id)
        # session 不再由工具自动产，测 update 同步前先手建一条 draft
        session = await sync_to_async(_mk_session_for_plan)(
            conversation=conversation,
            repository=repository,
            plan=plan,
        )

        v2 = await _amk_artifact_version(
            conversation=conversation,
            content=_content(_task(files=[{"path": "v2.py", "action": "delete"}]), title="方案 v2"),
        )
        result = await update_coding_plan(
            conversation_id=str(conversation.id),
            coding_plan_id=plan_id,
            artifact_version_id=str(v2.id),
        )
        assert result.success is True
        assert result.output["coding_plan_id"] == plan_id
        assert result.output["synced_sessions_count"] >= 1

        refreshed = await CodingPlan.objects.aget(id=plan_id)
        assert "方案 v2" in refreshed.tech_plan
        assert refreshed.affected_files == [{"file_path": "v2.py", "change_type": "delete"}]
        assert str(refreshed.source_artifact_version_id) == str(v2.id)
        assert refreshed.provenance == CodingPlanProvenance.ORCHESTRATED

        session_refreshed = await CodingSession.objects.aget(id=session.id)
        assert "方案 v2" in session_refreshed.tech_plan
        assert session_refreshed.affected_files[0]["file_path"] == "v2.py"

    @pytest.mark.asyncio
    async def test_update_coding_plan_target_version_already_projected(
        self, project, repository, conversation, as_owner
    ):
        """目标版本已被另一条 plan 占用 → fail-closed，两边正文都不被改写。"""
        from agents.tools.coding_tools import create_coding_plan, update_coding_plan

        v1 = await _amk_artifact_version(
            conversation=conversation,
            content=_content(_task(files=[{"path": "a.py", "action": "modify"}]), title="方案 A"),
        )
        v2 = await _amk_artifact_version(
            conversation=conversation,
            content=_content(_task(files=[{"path": "b.py", "action": "modify"}]), title="方案 B"),
        )
        first = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            artifact_version_id=str(v1.id),
        )
        second = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            artifact_version_id=str(v2.id),
        )
        plan1_id, plan2_id = first.output["coding_plan_id"], second.output["coding_plan_id"]
        plan1_body = (await CodingPlan.objects.aget(id=plan1_id)).tech_plan
        plan2_body = (await CodingPlan.objects.aget(id=plan2_id)).tech_plan

        result = await update_coding_plan(
            conversation_id=str(conversation.id),
            coding_plan_id=plan1_id,
            artifact_version_id=str(v2.id),
        )
        assert result.success is False
        assert "artifact_version_already_projected" in (result.error or "")
        assert (await CodingPlan.objects.aget(id=plan1_id)).tech_plan == plan1_body
        assert (await CodingPlan.objects.aget(id=plan2_id)).tech_plan == plan2_body

    @pytest.mark.asyncio
    async def test_update_coding_plan_by_legacy_session_id(
        self, draft_coding_session, conversation, as_owner
    ):
        """legacy session_id 路径：自动回填 plan 并 re-bind 到指定来源版本。"""
        from agents.tools.coding_tools import update_coding_plan

        version = await _amk_artifact_version(
            conversation=conversation,
            content=_content(
                _task(files=[{"path": "legacy.py", "action": "modify"}]), title="legacy 路径方案"
            ),
        )
        result = await update_coding_plan(
            conversation_id=str(conversation.id),
            session_id=str(draft_coding_session.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is True
        assert "coding_plan_id" in result.output

        await draft_coding_session.arefresh_from_db()
        assert "legacy 路径方案" in draft_coding_session.tech_plan
        assert draft_coding_session.coding_plan_id is not None

    @pytest.mark.asyncio
    async def test_update_coding_plan_session_not_found(self, conversation, as_owner):
        """传入不存在的 session_id 返回 error。"""
        from agents.tools.coding_tools import update_coding_plan

        version = await _amk_artifact_version(conversation=conversation)
        result = await update_coding_plan(
            conversation_id=str(conversation.id),
            session_id=str(uuid.uuid4()),
            artifact_version_id=str(version.id),
        )
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_update_coding_plan_missing_id_returns_error(self, conversation, as_owner):
        """两个 plan 定位 id 都不传 → success=False + error 提示。"""
        from agents.tools.coding_tools import update_coding_plan

        version = await _amk_artifact_version(conversation=conversation)
        result = await update_coding_plan(
            conversation_id=str(conversation.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is False
        assert "coding_plan_id" in result.error
        assert "session_id" in result.error

    @pytest.mark.asyncio
    async def test_update_coding_plan_reject_missing_artifact_version_id(
        self, conversation, draft_coding_session, as_owner
    ):
        """无来源的 update 尝试同样被拒绝并留痕（``-k reject`` 组）。"""
        from agents.tools.coding_tools import update_coding_plan

        with capture_logs() as logs:
            result = await update_coding_plan(
                conversation_id=str(conversation.id),
                session_id=str(draft_coding_session.id),
                artifact_version_id="",
            )
        assert result.success is False
        assert _AUTHORING_REJECTED_EVENT in [entry.get("event") for entry in logs]

    @pytest.mark.asyncio
    async def test_update_coding_plan_does_not_touch_running_sessions(
        self, project, repository, conversation, as_owner
    ):
        """plan 关联 1 draft + 1 running 时，update 只同步 draft，不污染 running。

        ``(coding_plan, repository)`` 部分唯一约束限制同时只能 1 个 active session；
        本用例通过创建第二个 Repository 模拟多仓 fan-out 让 draft 与 running 落在不同
        repo 上，规避 unique_active_plan_repo。
        """
        from agents.tools.coding_tools import create_coding_plan, update_coding_plan

        repository_b = await sync_to_async(Repository.objects.create)(
            name="Test Repo B",
            git_url="https://gitlab.com/test/repo-b.git",
            git_platform="gitlab",
            default_branch="main",
        )
        await sync_to_async(project.repositories.add)(repository_b)

        v1 = await _amk_artifact_version(
            conversation=conversation,
            content=_content(
                _task(files=[{"path": "a.py", "action": "modify"}]), title="同方案 fan-out"
            ),
        )
        created = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            artifact_version_id=str(v1.id),
        )
        plan_id = created.output["coding_plan_id"]
        plan = await CodingPlan.objects.aget(id=plan_id)
        draft_session = await sync_to_async(_mk_session_for_plan)(
            conversation=conversation,
            repository=repository,
            plan=plan,
            branch_name="draft-branch",
        )
        running_session = await CodingSession.objects.acreate(
            conversation=conversation,
            repository=repository_b,
            coding_plan=plan,
            tech_plan=plan.tech_plan,
            affected_files=plan.affected_files,
            status=CodingSession.Status.RUNNING,
            branch_name="running-branch",
        )
        running_body = running_session.tech_plan

        v2 = await _amk_artifact_version(
            conversation=conversation,
            content=_content(
                _task(files=[{"path": "b.py", "action": "modify"}]), title="更新后的方案"
            ),
        )
        result = await update_coding_plan(
            conversation_id=str(conversation.id),
            coding_plan_id=plan_id,
            artifact_version_id=str(v2.id),
        )
        assert result.success is True
        # 只同步了 1 个 draft
        assert result.output["synced_sessions_count"] == 1

        draft_refreshed = await CodingSession.objects.aget(id=draft_session.id)
        assert "更新后的方案" in draft_refreshed.tech_plan

        running_refreshed = await CodingSession.objects.aget(id=running_session.id)
        # running 的 deprecated 字段保留旧值不动
        assert running_refreshed.tech_plan == running_body


# ============================================================================
# 109-REVIEW BL-01 / MN-04 —— 归属主体解析与会话一致性
#
# 🔴 本组用例刻意**不用** `as_owner`（手工 bind_contextvars(user_id=<真实 id>)）。
# 手工注入让 service 内的归属判定得到很好的覆盖，却掩盖了「生产里这个 contextvar
# 是什么形状」：`RequestLogContextMiddleware._bind` 写的是硬编码占位
# `user_id="system"`，真实 id 只由 `rebind_user` 补绑，而 `LogContextMixin` 全仓无
# 视图继承。BL-01 正是因为整套用例没有一条按生产形态调用而逃过了 785 行新测试。
# 因此这里一律用 `bind_request_context(..., user_id="system")` 复现真实入口。
# ============================================================================


@pytest.fixture
def as_production_request_context():
    """按中间件的**真实绑定形态**建立请求上下文（``user_id="system"`` 占位）。"""
    from common.log_context import LogSource, bind_request_context, clear_request_context

    bind_request_context(
        request_id="req-109-review",
        source=LogSource.REST,
        trace_id="trace-109-review",
        user_id="system",
    )
    yield
    clear_request_context()


@pytest.mark.django_db(transaction=True)
class TestUpdateCodingPlanActorResolution:
    """归属主体在生产绑定形态下必须可解析，且会话一致性必须早于任何写。"""

    def test_context_user_id_still_refuses_system_sentinel(self, as_production_request_context):
        """哨兵身份绝不被当成真实用户 —— 这条纪律不因 BL-01 的修复而松动。"""
        from agents.tools.coding_tools import _context_user_id

        assert _context_user_id() == ""

    @pytest.mark.asyncio
    async def test_update_coding_plan_succeeds_under_production_context_binding(
        self, project, repository, conversation, as_production_request_context
    ):
        """按生产入口形态（contextvars 只有 ``"system"`` 占位）调用 → 仍能 re-bind。

        🔴 这是 BL-01 的回归锁：修复前本用例会拿到「无法确定当前操作用户」早退。
        """
        from agents.tools.coding_tools import create_coding_plan, update_coding_plan

        v1 = await _amk_artifact_version(
            conversation=conversation,
            content=_content(_task(files=[{"path": "v1.py", "action": "create"}]), title="方案 v1"),
        )
        created = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            artifact_version_id=str(v1.id),
        )
        assert created.success is True

        v2 = await _amk_artifact_version(
            conversation=conversation,
            content=_content(_task(files=[{"path": "v2.py", "action": "modify"}]), title="方案 v2"),
        )
        result = await update_coding_plan(
            conversation_id=str(conversation.id),
            coding_plan_id=created.output["coding_plan_id"],
            artifact_version_id=str(v2.id),
        )
        assert result.success is True, f"生产绑定形态下 update 必须可用，实际：{result.error}"
        refreshed = await CodingPlan.objects.aget(id=created.output["coding_plan_id"])
        assert "方案 v2" in refreshed.tech_plan

    @pytest.mark.asyncio
    async def test_update_rejects_plan_of_another_conversation(
        self, project, repository, conversation, as_production_request_context
    ):
        """模型报他人会话的 coding_plan_id → 拒绝，且被指向的 plan 正文零改动（EoP）。"""
        from agents.tools.coding_tools import create_coding_plan, update_coding_plan

        victim_version = await _amk_artifact_version(
            conversation=conversation,
            content=_content(
                _task(files=[{"path": "victim.py", "action": "create"}]), title="他人方案"
            ),
        )
        victim = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            artifact_version_id=str(victim_version.id),
        )
        victim_plan_id = victim.output["coding_plan_id"]
        victim_body = (await CodingPlan.objects.aget(id=victim_plan_id)).tech_plan

        intruder = await sync_to_async(User.objects.create_user)(
            username=f"intruder_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@coding.local",
            password="testpass123",
        )
        attacker_conversation = await Conversation.objects.acreate(
            space=project,
            title="入侵者的会话",
            created_by=intruder,
        )
        attacker_version = await _amk_artifact_version(
            conversation=attacker_conversation,
            content=_content(
                _task(files=[{"path": "x.py", "action": "modify"}]), title="入侵者方案"
            ),
        )

        with capture_logs() as logs:
            result = await update_coding_plan(
                conversation_id=str(attacker_conversation.id),
                coding_plan_id=victim_plan_id,
                artifact_version_id=str(attacker_version.id),
            )

        assert result.success is False
        # 措辞与「不存在」逐字一致，不泄漏存在性
        assert result.error == f"CodingPlan not found: {victim_plan_id}"
        assert _AUTHORING_REJECTED_EVENT in [entry.get("event") for entry in logs]
        assert (await CodingPlan.objects.aget(id=victim_plan_id)).tech_plan == victim_body

    @pytest.mark.asyncio
    async def test_update_legacy_session_of_another_conversation_writes_nothing(
        self, project, repository, conversation, draft_coding_session, as_production_request_context
    ):
        """🔴 MN-04：legacy 分支的归属判定必须早于补 FK 的两次写。

        判定晚一步 = 「拒绝了，但已在他人会话下建出 CodingPlan 并改写了他人 session」。
        """
        from agents.tools.coding_tools import update_coding_plan

        intruder = await sync_to_async(User.objects.create_user)(
            username=f"intruder_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@coding.local",
            password="testpass123",
        )
        attacker_conversation = await Conversation.objects.acreate(
            space=project,
            title="入侵者的会话",
            created_by=intruder,
        )
        attacker_version = await _amk_artifact_version(
            conversation=attacker_conversation,
            content=_content(
                _task(files=[{"path": "x.py", "action": "modify"}]), title="入侵者方案"
            ),
        )
        plans_before = await CodingPlan.objects.acount()

        with capture_logs() as logs:
            result = await update_coding_plan(
                conversation_id=str(attacker_conversation.id),
                session_id=str(draft_coding_session.id),
                artifact_version_id=str(attacker_version.id),
            )

        assert result.success is False
        assert result.error == f"CodingSession not found: {draft_coding_session.id}"
        assert _AUTHORING_REJECTED_EVENT in [entry.get("event") for entry in logs]
        # 数据零污染：既没在他人会话下建 plan，也没改写他人 session 的反向 FK
        assert await CodingPlan.objects.acount() == plans_before
        await draft_coding_session.arefresh_from_db()
        assert draft_coding_session.coding_plan_id is None


# ============================================================================
# 工具注册测试
# ============================================================================


def test_coding_tools_registered_in_registry():
    """验证 coding_tools 模块的 @tool 已注册到全局 _tool_registry。"""
    import agents.tools.coding_tools  # noqa: F401
    from agents.tools.base import _tool_registry

    assert "create_coding_plan" in _tool_registry
    assert "update_coding_plan" in _tool_registry


@pytest.mark.asyncio
async def test_chat_runner_get_tool_names_gates_deep_analysis():
    """`chat_runner._get_tool_names(force_deep_analysis=False)` 必不返回 deep_analysis。

    防止后续代码改动重新把 deep_analysis 加回默认列表（这正是历史 bug：
    LLM 在普通模式被 prompt 诱导自主调 deep_analysis）。
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from agents.chat_runner import _get_tool_names

    fake_qs = MagicMock()
    fake_qs.aexists = AsyncMock(return_value=True)  # has_indexed=True

    with patch("agents.chat_runner.Repository.objects.filter", return_value=fake_qs):
        normal = await _get_tool_names("space-1", force_deep_analysis=False)
        forced = await _get_tool_names("space-1", force_deep_analysis=True)

    assert "deep_analysis" not in normal, (
        f"默认模式必须闸住 deep_analysis；当前列表：{sorted(normal)}"
    )
    assert "deep_analysis" in forced
    assert "search_repository_code" in normal  # 普通检索工具仍需暴露


def test_coding_tools_in_indexed_tool_names():
    """验证 chat_runner._INDEXED_TOOL_NAMES 含 coding tools 但**不含** deep_analysis。

    `_FULL_TOOL_NAMES` 已拆为 `_INDEXED_TOOL_NAMES`（默认）+ `_DEEP_ANALYSIS_TOOL_NAMES`
    （用户开「深度分析」开关时），避免 LLM 在普通模式自主调 deep_analysis。
    """
    from agents.chat_runner import _DEEP_ANALYSIS_TOOL_NAMES, _INDEXED_TOOL_NAMES

    assert "create_coding_plan" in _INDEXED_TOOL_NAMES
    assert "update_coding_plan" in _INDEXED_TOOL_NAMES
    # 默认列表绝不能含 deep_analysis（核心闸门契约）
    assert "deep_analysis" not in _INDEXED_TOOL_NAMES
    # 开启深度分析时才追加 deep_analysis
    assert "deep_analysis" in _DEEP_ANALYSIS_TOOL_NAMES
    assert set(_INDEXED_TOOL_NAMES).issubset(set(_DEEP_ANALYSIS_TOOL_NAMES))


# ============================================================================
# system prompt + _get_tool_names 测试
# ============================================================================


@pytest.mark.asyncio
async def test_system_prompt_contains_coding_guidance(monkeypatch):
    """验证 system prompt 包含编码意图识别指引。

    implementation Task 7: async 化 + 强制 fallback 路径（避免依赖 DB seed）。
    """
    from chat.conversation_service import _build_system_prompt

    monkeypatch.setenv(
        "PROMPT_CENTER_DISABLED_KEYS",
        "chat.system.developer,chat.strategy.default,chat.coding_guidance",
    )
    prompt = await _build_system_prompt("Test Space", "test-uuid", "developer")
    assert "create_coding_plan" in prompt
    assert "编码" in prompt or "代码变更" in prompt


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_tool_names_includes_coding_tools(project, repository):
    """有索引仓库时，_get_tool_names 返回列表包含 coding tools。"""
    from chat.conversation_service import _get_tool_names

    # 将 repository 设置为已索引状态
    repository.index_status = "indexed"
    await repository.asave(update_fields=["index_status"])

    tool_names = await _get_tool_names(str(project.id))
    assert "create_coding_plan" in tool_names
    assert "update_coding_plan" in tool_names


# ============================================================================
# create_coding_plan recommended_repository_ids 测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestCreateCodingPlanRecommendedRepos:
    """create_coding_plan 自动预填 recommended_repository_ids 行为。"""

    @pytest.mark.asyncio
    async def test_input_schema_has_optional_recommended_repository_ids(self):
        from agents.tools.registry import ToolRegistry

        tool = ToolRegistry.get_tool("create_coding_plan")
        assert tool is not None
        props = tool.parameters["properties"]
        assert "recommended_repository_ids" in props
        assert props["recommended_repository_ids"]["type"] == "array"
        # 不在 required
        assert "recommended_repository_ids" not in tool.parameters["required"]
        # coding-plan workflow：repository_id 也改为 optional
        assert "repository_id" not in tool.parameters["required"]

    @pytest.mark.asyncio
    async def test_explicit_ids_are_persisted_to_plan(self, project, repository, conversation):
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(conversation=conversation)
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            artifact_version_id=str(version.id),
            recommended_repository_ids=[str(repository.id)],
        )
        assert result.success is True
        assert result.output["recommended_source"] == "explicit"
        assert result.output["recommended_repository_ids"] == [str(repository.id)]
        plan = await CodingPlan.objects.aget(id=result.output["coding_plan_id"])
        assert plan.recommended_repository_ids == [str(repository.id)]

    @pytest.mark.asyncio
    async def test_no_explicit_inferred_from_latest_chat_tool_trace(
        self, project, repository, conversation, other_repository
    ):
        from agents.tools.coding_tools import create_coding_plan
        from chat.models import RepositoryRoutingTrace

        # 写一条 trace：only repository selected_by_user_final=True
        await RepositoryRoutingTrace.objects.acreate(
            conversation=conversation,
            query="q",
            candidates=[
                {
                    "repository_id": str(repository.id),
                    "repository_name": "x",
                    "score": 0.9,
                    "level": "high",
                    "evidence": "ev",
                    "selected_by_ai": True,
                    "selected_by_user_final": True,
                },
                {
                    "repository_id": str(other_repository.id),
                    "repository_name": "y",
                    "score": 0.3,
                    "level": "low",
                    "evidence": "ev",
                    "selected_by_ai": False,
                    "selected_by_user_final": False,
                },
            ],
            threshold=0.5,
            triggered_by=RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL,
        )

        version = await _amk_artifact_version(conversation=conversation)
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is True
        assert result.output["recommended_source"] == "trace_inferred"
        assert result.output["recommended_repository_ids"] == [str(repository.id)]
        plan = await CodingPlan.objects.aget(id=result.output["coding_plan_id"])
        assert plan.recommended_repository_ids == [str(repository.id)]

    @pytest.mark.asyncio
    async def test_manual_override_trace_takes_precedence(
        self, project, repository, conversation, other_repository
    ):
        from agents.tools.coding_tools import create_coding_plan
        from chat.models import RepositoryRoutingTrace

        # 第一行：chat_tool，only repository selected
        await RepositoryRoutingTrace.objects.acreate(
            conversation=conversation,
            query="q",
            candidates=[
                {
                    "repository_id": str(repository.id),
                    "repository_name": "x",
                    "score": 0.9,
                    "level": "high",
                    "evidence": "ev",
                    "selected_by_ai": True,
                    "selected_by_user_final": True,
                },
                {
                    "repository_id": str(other_repository.id),
                    "repository_name": "y",
                    "score": 0.3,
                    "level": "low",
                    "evidence": "ev",
                    "selected_by_ai": False,
                    "selected_by_user_final": False,
                },
            ],
            threshold=0.5,
            triggered_by=RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL,
        )
        # 第二行：manual_override，user 把 other 也选上
        await RepositoryRoutingTrace.objects.acreate(
            conversation=conversation,
            query="q",
            candidates=[
                {
                    "repository_id": str(repository.id),
                    "repository_name": "x",
                    "score": 0.9,
                    "level": "high",
                    "evidence": "ev",
                    "selected_by_ai": True,
                    "selected_by_user_final": True,
                },
                {
                    "repository_id": str(other_repository.id),
                    "repository_name": "y",
                    "score": 0.3,
                    "level": "low",
                    "evidence": "ev",
                    "selected_by_ai": False,
                    "selected_by_user_final": True,  # user 改选
                },
            ],
            threshold=0.5,
            triggered_by=RepositoryRoutingTrace.TriggeredBy.MANUAL_OVERRIDE,
        )

        version = await _amk_artifact_version(conversation=conversation)
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is True
        assert result.output["recommended_source"] == "trace_inferred"
        # 最新 trace（manual_override 行）的两个 selected_by_user_final=True 仓库都拿到
        ids = set(result.output["recommended_repository_ids"])
        assert str(repository.id) in ids
        assert str(other_repository.id) in ids

    @pytest.mark.asyncio
    async def test_no_trace_no_explicit_with_repository_id_falls_back_to_primary(
        self, project, repository, conversation
    ):
        """coding-plan workflow：trace + explicit 都空，但传了 repository_id
        → final_recommended 仅含 primary，recommended_source='primary_repo'。"""
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(
            conversation=conversation,
            # 来源版本不带 repository_id，隔离出「只有 primary 一条来源」的形状
            content=_content(_task(files=[{"path": "x.py", "action": "modify"}])),
        )
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is True
        assert result.output["recommended_source"] == "primary_repo"
        assert result.output["recommended_repository_ids"] == [str(repository.id)]
        plan = await CodingPlan.objects.aget(id=result.output["coding_plan_id"])
        assert plan.recommended_repository_ids == [str(repository.id)]

    @pytest.mark.asyncio
    async def test_no_trace_no_explicit_no_repository_id_returns_empty(self, project, conversation):
        """coding-plan workflow：trace + explicit + repository_id 全空，且来源版本
        本身不带目标仓 → empty 列表 + recommended_source='empty'。"""
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(
            conversation=conversation,
            content=_content(_task(files=[{"path": "x.py", "action": "modify"}])),
        )
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is True
        assert result.output["recommended_source"] == "empty"
        assert result.output["recommended_repository_ids"] == []
        plan = await CodingPlan.objects.aget(id=result.output["coding_plan_id"])
        assert plan.recommended_repository_ids == []

    @pytest.mark.asyncio
    async def test_projected_repository_ids_are_not_cleared_by_empty_resolution(
        self, project, conversation
    ):
        """trace + explicit + repository_id 全空，但来源版本自带目标仓
        → **保留**投影聚合出的仓库列表（不用空列表把 fan-out 目标抹掉）。"""
        from agents.tools.coding_tools import create_coding_plan

        source_repo_id = str(uuid.uuid4())
        version = await _amk_artifact_version(
            conversation=conversation,
            content=_content(
                _task(
                    repository_id=source_repo_id,
                    files=[{"path": "x.py", "action": "modify"}],
                )
            ),
        )
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is True
        assert result.output["recommended_source"] == "projected"
        assert result.output["recommended_repository_ids"] == [source_repo_id]
        plan = await CodingPlan.objects.aget(id=result.output["coding_plan_id"])
        assert plan.recommended_repository_ids == [source_repo_id]

    @pytest.mark.asyncio
    async def test_projected_ids_with_invalid_uuid_literal_do_not_break_the_tool(
        self, project, repository, conversation
    ):
        """🔴 109-REVIEW MN-03：来源版本里的非法仓库 id 不得把工具打成未处理异常。

        ``execution_plan[].repository_id`` 是 LLM 产物、schema 无强约束。半可信值直接
        喂 ``filter(id__in=...)`` 会抛 ``ValidationError`` 一路上穿 ``@tool``（装饰器无
        兜底）——而此时投影**已经落库**，用户看到「失败」但 DB 里多了一条 plan。
        """
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(
            conversation=conversation,
            content=_content(
                _task(
                    repository_id="not-a-uuid",
                    files=[{"path": "x.py", "action": "modify"}],
                    task_id="t1",
                ),
                _task(
                    repository_id=str(repository.id),
                    files=[{"path": "y.py", "action": "modify"}],
                    task_id="t2",
                ),
            ),
        )
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is True
        assert result.output["recommended_source"] == "projected"
        # 非法字面量被丢弃，合法 id 保留
        assert result.output["recommended_repository_ids"] == [str(repository.id)]
        assert [r["id"] for r in result.output["recommended_repositories"]] == [str(repository.id)]

    @pytest.mark.asyncio
    async def test_projected_repository_names_are_scoped_to_space(
        self, project, conversation, other_repository
    ):
        """名字回显按 space 过滤，与「LLM 显式传 id」分支同一可见性口径。

        ``recommended_repository_ids`` 仍保留全部合法 id —— 编排来源自带目标仓，用
        space 交集覆盖等于把跨 space 的 fan-out 目标抹掉。
        """
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(
            conversation=conversation,
            content=_content(
                _task(
                    repository_id=str(other_repository.id),
                    files=[{"path": "x.py", "action": "modify"}],
                )
            ),
        )
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            artifact_version_id=str(version.id),
        )
        assert result.success is True
        assert result.output["recommended_repository_ids"] == [str(other_repository.id)]
        assert result.output["recommended_repositories"] == []

    @pytest.mark.asyncio
    async def test_invalid_explicit_id_not_in_space_returns_error(
        self, project, repository, conversation, other_repository
    ):
        from agents.tools.coding_tools import create_coding_plan

        version = await _amk_artifact_version(conversation=conversation)
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            artifact_version_id=str(version.id),
            recommended_repository_ids=[str(other_repository.id)],
        )
        assert result.success is False
        assert "not in space" in (result.error or "")
