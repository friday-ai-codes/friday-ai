"""review review round Fix #1/#2：``_handle_waiting_clarification_state`` 单元测试。

回归保护：

主 bug — ``conversation_service.py:920`` 的 graph 收尾分发只识别
``phase=="waiting"``（blocking_tasks 路径），缺 ``elif phase=="waiting_clarification"``
分支。implementation（commit 83218e04）在 graph 加了 ``wait_clarification_node``
+ ``WAITING_CLARIFICATION`` 状态，但 chat 层 post-graph 分发未同步 → graph 正确
``interrupt()`` 后 consumer 落 else → ``state.result_metadata={}`` →
``finalize.py:67`` ``status_str="unknown"`` → ``Conversation.Status.ERROR`` +
``AgentSession.Status.ERROR``。100% 重现，全文档详见
``project docs``。

本测试覆盖 ``_handle_waiting_clarification_state`` 辅助函数的核心契约：

- ``OrchestrationRun`` 状态从 RUNNING/PENDING → WAITING + phase=waiting_clarification
- ``ConversationIntentTrace`` 在生产代码中被 create（次因 #2 修复）
- ``Conversation.status`` **不变**（保持 RUNNING，等待用户答复）
- ``AgentSession.status`` **不变**（同样不动）
- ``do_finalize`` **不被调用**（关键 — 防本 bug 复现）
- 幂等：相同 clarification_id 二次进入用 ``aget_or_create`` 兜底不撞 unique
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from agents.models import AgentSession
from chat.conversation_service import _handle_waiting_clarification_state
from chat.models import Conversation, ConversationIntentTrace, Message
from orchestration.models import OrchestrationRun


def _make_state(
    *,
    clarification_id: str = "c-test-001",
    question: str = "你想看哪个仓库？",
    options: list[dict] | None = None,
) -> dict:
    return {
        "phase": "waiting_clarification",
        "pending_clarification": {
            "clarification_id": clarification_id,
            "question": question,
            "options": options or [
                {"id": "opt-A", "label": "example-app"},
                {"id": "opt-B", "label": "problem-app"},
            ],
            "allow_freeform": True,
        },
    }


@pytest.fixture
def conversation(project) -> Conversation:
    return Conversation.objects.create(
        space=project,
        title="waiting_clarification handler test",
        status=Conversation.Status.RUNNING,
    )


@pytest.fixture
def orch_run(conversation: Conversation) -> OrchestrationRun:
    return OrchestrationRun.objects.create(
        conversation=conversation,
        thread_id=str(conversation.id),
        status=OrchestrationRun.Status.RUNNING,
        phase=OrchestrationRun.Phase.EXECUTING,
    )


@pytest.fixture
def user_msg(conversation: Conversation) -> Message:
    return Message.objects.create(
        conversation=conversation,
        role=Message.Role.USER,
        content="我想看 example-app 和 problem-app 的 entrance 字段",
    )


@pytest.mark.django_db(transaction=True)
class TestHandleWaitingClarificationState:
    def test_updates_orch_run_to_waiting_phase_waiting_clarification(
        self,
        conversation: Conversation,
        orch_run: OrchestrationRun,
        user_msg: Message,
    ) -> None:
        state = _make_state()

        asyncio.run(_handle_waiting_clarification_state(
            state=state,
            orch_run=orch_run,
            conversation=conversation,
            triggering_message_id=str(user_msg.id),
            conv_id_str=str(conversation.id),
        ))

        orch_run.refresh_from_db()
        assert orch_run.status == OrchestrationRun.Status.WAITING
        assert orch_run.phase == OrchestrationRun.Phase.WAITING_CLARIFICATION

    def test_creates_conversation_intent_trace(
        self,
        conversation: Conversation,
        orch_run: OrchestrationRun,
        user_msg: Message,
    ) -> None:
        state = _make_state(clarification_id="c-trace-001")

        asyncio.run(_handle_waiting_clarification_state(
            state=state,
            orch_run=orch_run,
            conversation=conversation,
            triggering_message_id=str(user_msg.id),
            conv_id_str=str(conversation.id),
        ))

        trace = ConversationIntentTrace.objects.get(clarification_id="c-trace-001")
        assert trace.conversation_id == conversation.id
        assert trace.triggering_message_id == str(user_msg.id)
        assert trace.question == "你想看哪个仓库？"
        assert len(trace.options) == 2
        assert trace.answered_at is None
        assert trace.selected_option_id == ""

    def test_does_not_modify_conversation_status(
        self,
        conversation: Conversation,
        orch_run: OrchestrationRun,
        user_msg: Message,
    ) -> None:
        """conversation 维持 RUNNING — 不能变 completed/error/interrupted。

        这是核心防护：本 bug 的本质是 do_finalize 被错误调用把 conversation
        写成 error。如果本函数不慎调了 do_finalize 或自己设了 status，本测试 fail。
        """
        state = _make_state()

        asyncio.run(_handle_waiting_clarification_state(
            state=state,
            orch_run=orch_run,
            conversation=conversation,
            triggering_message_id=str(user_msg.id),
            conv_id_str=str(conversation.id),
        ))

        conversation.refresh_from_db()
        assert conversation.status == Conversation.Status.RUNNING

    def test_does_not_modify_agent_session_status(
        self,
        conversation: Conversation,
        orch_run: OrchestrationRun,
        user_msg: Message,
    ) -> None:
        """AgentSession 维持 RUNNING — finalize.py 的 unknown 路径会把它写成 ERROR。"""
        agent_session = AgentSession.objects.create(
            session_id=f"chat-{conversation.id}-test",
            status=AgentSession.Status.RUNNING,
        )
        state = _make_state()

        asyncio.run(_handle_waiting_clarification_state(
            state=state,
            orch_run=orch_run,
            conversation=conversation,
            triggering_message_id=str(user_msg.id),
            conv_id_str=str(conversation.id),
        ))

        agent_session.refresh_from_db()
        assert agent_session.status == AgentSession.Status.RUNNING

    def test_idempotent_on_duplicate_clarification_id(
        self,
        conversation: Conversation,
        orch_run: OrchestrationRun,
        user_msg: Message,
    ) -> None:
        """二次调用相同 clarification_id 不抛 unique 约束（aget_or_create 兜底）。"""
        state = _make_state(clarification_id="c-idem-001")

        asyncio.run(_handle_waiting_clarification_state(
            state=state, orch_run=orch_run, conversation=conversation,
            triggering_message_id=str(user_msg.id), conv_id_str=str(conversation.id),
        ))
        # 二次调用 — 不应抛
        asyncio.run(_handle_waiting_clarification_state(
            state=state, orch_run=orch_run, conversation=conversation,
            triggering_message_id=str(user_msg.id), conv_id_str=str(conversation.id),
        ))

        assert ConversationIntentTrace.objects.filter(clarification_id="c-idem-001").count() == 1

    def test_guards_interrupted_orch_run_not_overwritten(
        self,
        conversation: Conversation,
        orch_run: OrchestrationRun,
        user_msg: Message,
    ) -> None:
        """用户已主动 interrupt → 本函数不能把状态从 INTERRUPTED 改回 WAITING。

        与 ``_handle_waiting_state`` 同等 ``exclude(status=INTERRUPTED)`` 护栏。
        """
        orch_run.status = OrchestrationRun.Status.INTERRUPTED
        orch_run.save()
        state = _make_state()

        asyncio.run(_handle_waiting_clarification_state(
            state=state, orch_run=orch_run, conversation=conversation,
            triggering_message_id=str(user_msg.id), conv_id_str=str(conversation.id),
        ))

        orch_run.refresh_from_db()
        assert orch_run.status == OrchestrationRun.Status.INTERRUPTED

    def test_missing_clarification_id_returns_warning_no_trace(
        self,
        conversation: Conversation,
        orch_run: OrchestrationRun,
        user_msg: Message,
    ) -> None:
        """异常态：pending_clarification 没有 clarification_id —— 不应抛，写 warning + 不落 trace。"""
        state = {
            "phase": "waiting_clarification",
            "pending_clarification": {"question": "无 id 的不规则 payload"},
        }

        asyncio.run(_handle_waiting_clarification_state(
            state=state, orch_run=orch_run, conversation=conversation,
            triggering_message_id=str(user_msg.id), conv_id_str=str(conversation.id),
        ))

        orch_run.refresh_from_db()
        assert orch_run.status == OrchestrationRun.Status.WAITING
        assert ConversationIntentTrace.objects.filter(conversation=conversation).count() == 0


@pytest.mark.django_db(transaction=True)
class TestPhaseEnum:
    """OrchestrationRun.Phase 必须包含 WAITING_CLARIFICATION 常量（Fix #1 子项）。

    没有这个枚举值，conversation_service 写 phase 时只能用裸字符串，未来加节点
    再漏 elif 时静默化更难发现。
    """

    def test_enum_value_present(self) -> None:
        assert hasattr(OrchestrationRun.Phase, "WAITING_CLARIFICATION")
        assert OrchestrationRun.Phase.WAITING_CLARIFICATION == "waiting_clarification"


class TestDispatchSourceGuard:
    """T2 简化版：源码静态断言两处 elif 分支必存。

    本 bug 的本质是 ``conversation_service.py:920`` (SSE 在线路径) 和
    ``conversation_service.py:work-item`` (后台 ``_background_finalize`` 路径)
    都缺 ``elif phase == "waiting_clarification":`` 分支。一旦未来 refactor 删
    了任一处，本 bug 会立即静默重现（finalize.py:67 unknown 路径吃掉 status）。

    完整 SSE 端到端 mock 复杂度高（需要 mock get_compiled_graph 双 stream_mode
    + checkpoint 写入 + GeneratorExit 生命周期），ROI 远不如直接静态断言。
    这种 source guard 在 workflow `workflow-secure-phase` 模式下是合规手段。
    """

    def test_both_dispatch_branches_have_waiting_clarification_elif(self) -> None:
        from pathlib import Path

        source = Path(__file__).parent.parent / "chat" / "conversation_service.py"
        text = source.read_text(encoding="utf-8")

        # SSE 在线路径 + 后台 _background_finalize 路径都必须有 elif 分支
        elif_occurrences = text.count('elif phase == "waiting_clarification":')
        assert elif_occurrences >= 2, (
            f"conversation_service.py 必须在 SSE 在线分发 + 后台 _background_finalize "
            f"两处都加 `elif phase == \"waiting_clarification\":` 分支（review review round Fix #1）；"
            f"当前仅找到 {elif_occurrences} 处，可能 regression — 详见 "
            f"project docs"
        )

    def test_handle_waiting_clarification_state_called_in_both_paths(self) -> None:
        from pathlib import Path

        source = Path(__file__).parent.parent / "chat" / "conversation_service.py"
        text = source.read_text(encoding="utf-8")

        # 排除 def 行 + docstring 引用，只数实际调用
        call_count = sum(
            1 for line in text.splitlines()
            if "_handle_waiting_clarification_state(" in line
            and not line.lstrip().startswith(("def ", "*", "#", '"', "'"))
            and "_handle_waiting_clarification_state docstring" not in line
        )
        assert call_count >= 2, (
            f"_handle_waiting_clarification_state 必须在 SSE 在线 + 后台两处都被调用；"
            f"当前仅找到 {call_count} 处调用"
        )

    def test_graph_phase_transition_waiting_clarification_carries_payload(self) -> None:
        """review review round Fix C-1：编排层 PHASE_TRANSITION 事件必须带 question/options/allow_freeform。

        否则前端 `phase_transition` handler 拿不到 ClarificationCard payload —— 编排层
        自动构造的 clarification（_extract_relev_low_confidence_pending 触发的）不会
        产生 tool_use_result(ask_clarification) 事件兜底，前端 store 永远不写
        pendingClarification → ClarificationCard 不渲染 → graph 永久 hang。
        详见 project docs review round Gap C-1。
        """
        from pathlib import Path

        source = Path(__file__).parent.parent / "orchestration" / "graph.py"
        text = source.read_text(encoding="utf-8")

        # 找到 wait_clarification interrupt 触发位置的 writer 调用，断言 payload 含三键
        wait_clar_writer_idx = text.find('"phase": "waiting_clarification",')
        assert wait_clar_writer_idx > 0, (
            "graph.py 未找到 PHASE_TRANSITION(waiting_clarification) writer 调用 — "
            "C-1 fix 可能被 refactor 误删"
        )

        # 取该 writer 调用周围 30 行检查 payload 完整
        snippet_start = text.rfind("writer(", 0, wait_clar_writer_idx)
        snippet_end = text.find("})", wait_clar_writer_idx) + 2
        snippet = text[snippet_start:snippet_end]

        for required_key in ('"clarification_id"', '"question"', '"options"', '"allow_freeform"'):
            assert required_key in snippet, (
                f"graph.py wait_clarification PHASE_TRANSITION writer 缺少 {required_key} 字段 — "
                f"前端 ClarificationCard 将无法渲染（C-1 regression）。\n\n"
                f"writer 当前 payload:\n{snippet}"
            )


@pytest.mark.django_db(transaction=True)
class TestCleanupManagementCommand:
    """Fix #3：cleanup_waiting_clarification_errors 管理命令 dry-run smoke test。"""

    def test_dry_run_with_no_targets_outputs_clean(self, project) -> None:
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("cleanup_waiting_clarification_errors", stdout=out)
        assert "无需修复" in out.getvalue()

    def test_dry_run_lists_matching_conv_without_writes(self, project) -> None:
        """构造命中签名的 conv → dry-run 应列出但不改库。"""
        from io import StringIO

        from django.core.management import call_command

        conv = Conversation.objects.create(
            space=project,
            title="历史污染 conv",
            status=Conversation.Status.ERROR,
        )
        OrchestrationRun.objects.create(
            conversation=conv,
            thread_id=str(conv.id),
            status=OrchestrationRun.Status.COMPLETED,
            phase="waiting_clarification",
        )

        out = StringIO()
        call_command("cleanup_waiting_clarification_errors", stdout=out)
        output = out.getvalue()
        assert str(conv.id) in output
        assert "Dry-run" in output

        # 没写库 — conv 仍是 error
        conv.refresh_from_db()
        assert conv.status == Conversation.Status.ERROR

    def test_apply_fixes_conv_with_assistant_content_to_completed(self, project) -> None:
        from django.core.management import call_command

        conv = Conversation.objects.create(
            space=project,
            title="有完整 assistant 内容",
            status=Conversation.Status.ERROR,
        )
        run = OrchestrationRun.objects.create(
            conversation=conv,
            thread_id=str(conv.id),
            status=OrchestrationRun.Status.COMPLETED,
            phase="waiting_clarification",
        )
        # 模拟 hotfix 之前的 bug 路径：assistant 已写入 4677 字符内容（content 非空）
        Message.objects.create(
            conversation=conv,
            role=Message.Role.ASSISTANT,
            content="完整分析正文（4677 字符的回放）",
        )

        call_command("cleanup_waiting_clarification_errors", "--apply")

        conv.refresh_from_db()
        run.refresh_from_db()
        assert conv.status == Conversation.Status.COMPLETED
        assert run.status == OrchestrationRun.Status.WAITING
        assert run.phase == "waiting_clarification"

    def test_apply_fixes_conv_without_assistant_content_to_interrupted(self, project) -> None:
        from django.core.management import call_command

        conv = Conversation.objects.create(
            space=project,
            title="无 assistant 内容",
            status=Conversation.Status.ERROR,
        )
        OrchestrationRun.objects.create(
            conversation=conv,
            thread_id=str(conv.id),
            status=OrchestrationRun.Status.COMPLETED,
            phase="waiting_clarification",
        )

        call_command("cleanup_waiting_clarification_errors", "--apply")

        conv.refresh_from_db()
        assert conv.status == Conversation.Status.INTERRUPTED

    def test_explicit_dry_run_flag_equivalent_to_omitted(self, project) -> None:
        """显式 `--dry-run` 与省略 flag 等价 — 不写库。"""
        from io import StringIO

        from django.core.management import call_command

        conv = Conversation.objects.create(
            space=project,
            title="dry-run flag test",
            status=Conversation.Status.ERROR,
        )
        OrchestrationRun.objects.create(
            conversation=conv,
            thread_id=str(conv.id),
            status=OrchestrationRun.Status.COMPLETED,
            phase="waiting_clarification",
        )

        out = StringIO()
        call_command("cleanup_waiting_clarification_errors", "--dry-run", stdout=out)
        assert str(conv.id) in out.getvalue()
        assert "Dry-run" in out.getvalue()
        conv.refresh_from_db()
        assert conv.status == Conversation.Status.ERROR

    def test_apply_and_dry_run_mutually_exclusive(self, project) -> None:
        """--apply 与 --dry-run 同时给 → 报错退出（不写库）。"""
        from io import StringIO

        from django.core.management import call_command

        conv = Conversation.objects.create(
            space=project,
            title="mutex test",
            status=Conversation.Status.ERROR,
        )
        OrchestrationRun.objects.create(
            conversation=conv,
            thread_id=str(conv.id),
            status=OrchestrationRun.Status.COMPLETED,
            phase="waiting_clarification",
        )

        err = StringIO()
        call_command(
            "cleanup_waiting_clarification_errors", "--apply", "--dry-run", stderr=err,
        )
        assert "互斥" in err.getvalue()
        conv.refresh_from_db()
        assert conv.status == Conversation.Status.ERROR  # 未写库
