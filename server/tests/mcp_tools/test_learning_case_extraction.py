"""aextract_learning_case 守护测试（Phase 101 / LOOP-03，ROADMAP 成功标准 3）：

- kill switch 关 → 跳过且 LLM 未调用
- 失败任务不提炼（状态门）
- 幂等：同 session_id 重入只产一条
- 质量门不过 → 显式 REJECT 事件且不入库
- 成功路径：脱敏入库（run=None）+ aschedule_ingestion 入图投递
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from structlog.testing import capture_logs

from mcp_tools.learning_case_extraction import aextract_learning_case
from mcp_tools.models import McpLearningCase

pytestmark = pytest.mark.django_db(transaction=True)

_LLM_PATH = "mcp_tools.learning_case_extraction._acall_llm"
_SWITCH_PATH = "mcp_tools.learning_case_extraction.aget_bool_setting"
_INGEST_PATH = "knowledge.ingestion.aschedule_ingestion"

_SECRET = "sk-ant-abcd1234secretvalue9876543210"

_GOOD_PAYLOAD = {
    "title": "异步 ORM 访问需经 sync_to_async 桥接",
    "problem": (
        "在 Django 异步视图或异步任务中直接访问 ORM 会触发 "
        "SynchronousOnlyOperation 异常，导致请求中断且难以排查"
    ),
    "root_cause": "Django ORM 默认同步实现，异步事件循环中直接调用被保护机制拦截",
    "solution": (
        f"所有异步上下文中的 ORM 访问统一经 asgiref.sync_to_async 桥接（凭证如 {_SECRET} "
        "不应出现在产物中），并复用既有 service 层封装，避免在事件循环内阻塞"
    ),
    "outcome": "success",
}
_GOOD_JSON = json.dumps(_GOOD_PAYLOAD, ensure_ascii=False)


def _call(session_id: str = "sess-001", task_status: str = "completed", **kwargs):
    defaults = {
        "session_id": session_id,
        "task_status": task_status,
        "requirement_text": "实现异步接口",
        "text_output": "任务完成，改动 3 个文件",
        "branch_name": "feature/async-orm",
        "pr_url": "https://git.example.com/mr/1",
        "modified_files": ["server/app/views.py"],
        "repositories": ["backend"],
        "work_item_type": "story",
        "work_item_id": 42,
    }
    defaults.update(kwargs)
    return aextract_learning_case(**defaults)


async def test_kill_switch_off_skips_without_llm():
    """开关关：返回 None、DB 零行、LLM 未调用（可秒关止血阀）。"""
    llm = AsyncMock(return_value=_GOOD_JSON)
    with (
        patch(_SWITCH_PATH, new=AsyncMock(return_value=False)),
        patch(_LLM_PATH, new=llm),
    ):
        result = await _call()
    assert result is None
    assert await McpLearningCase.objects.acount() == 0
    llm.assert_not_awaited()


async def test_failed_task_status_gate_no_op():
    """失败任务不提炼：状态门前置于 LLM，不烧 token。"""
    llm = AsyncMock(return_value=_GOOD_JSON)
    with patch(_LLM_PATH, new=llm):
        result = await _call(task_status="failed")
    assert result is None
    assert await McpLearningCase.objects.acount() == 0
    llm.assert_not_awaited()


async def test_idempotent_reentry_single_case():
    """同 session_id 连续调两次只产一条（幂等键 source_session_id）。"""
    llm = AsyncMock(return_value=_GOOD_JSON)
    with (
        patch(_LLM_PATH, new=llm),
        patch(_INGEST_PATH, new=AsyncMock()),
    ):
        first = await _call(session_id="sess-dup")
        second = await _call(session_id="sess-dup")
    assert first is not None
    assert second is None  # 第二次走 duplicate skip
    assert await McpLearningCase.objects.acount() == 1
    assert llm.await_count == 1  # 幂等检查在 LLM 之前，重入不烧 token


async def test_reject_path_emits_event_no_store():
    """质量门不过：显式 REJECT 事件 learning_case_rejected，且不入库。"""
    bad = dict(_GOOD_PAYLOAD, solution="暂无")  # solution 过短 + 模板废话
    with (
        patch(_LLM_PATH, new=AsyncMock(return_value=json.dumps(bad, ensure_ascii=False))),
        capture_logs() as logs,
    ):
        result = await _call(session_id="sess-reject")
    assert result is None
    assert await McpLearningCase.objects.acount() == 0
    rejected = [log for log in logs if log.get("event") == "learning_case_rejected"]
    assert len(rejected) == 1
    assert rejected[0]["reason"] == "solution_too_short"
    assert rejected[0]["category"] == "caller"
    assert rejected[0]["initiated_by_user_id"] == "system"


def test_admission_gate_no_false_kill_on_wu_prefixed_solutions():
    """质量门收窄（101 IN-01）：'无需/无论…' 开头的正常 solution 不被模板门误杀。

    单字 "无"/"略" 已移出 startswith 前缀集（超短模板产物由 _MIN_FIELD_LEN 拦截）；
    "暂无…" 等真模板前缀仍拦。
    """
    from mcp_tools.learning_case_extraction import _admission_gate

    problem = "在 Django 异步视图中直接访问 ORM 会触发 SynchronousOnlyOperation 异常"
    ok_solution = "无需改动配置，直接把所有异步上下文中的 ORM 访问统一经 sync_to_async 桥接即可"
    assert _admission_gate({"problem": problem, "solution": ok_solution}) is None

    ok_solution_2 = "无论走哪条链路，都应复用既有 service 层封装并在入口统一做权限校验兜底"
    assert _admission_gate({"problem": problem, "solution": ok_solution_2}) is None

    # 真模板前缀仍拦（凑长度绕过 _MIN_FIELD_LEN 后依旧 REJECT）。
    template_solution = "暂无" + "详细方案，待后续补充完善说明" * 3
    assert (
        _admission_gate({"problem": problem, "solution": template_solution}) == "solution_template"
    )

    # 纯 "无"/"略" 由长度门拦截（reason 为 too_short，而非漏放行）。
    assert _admission_gate({"problem": problem, "solution": "无"}) == "solution_too_short"


async def test_success_redacted_store_and_ingestion_dispatch():
    """成功路径：case 落库（run=None、幂等键正确、字段已脱敏）+ 入图投递。"""
    ingest = AsyncMock()
    with (
        patch(_LLM_PATH, new=AsyncMock(return_value=f"```json\n{_GOOD_JSON}\n```")),
        patch(_INGEST_PATH, new=ingest),
    ):
        case = await _call(session_id="sess-ok", initiated_by_user_id="u-7")
    assert case is not None
    assert case.run_id is None
    assert case.source_session_id == "sess-ok"
    assert case.work_item_type == "story"
    assert case.work_item_id == 42
    assert case.branches == ["feature/async-orm"]
    assert case.mr_urls == ["https://git.example.com/mr/1"]
    assert case.source_links["session_id"] == "sess-ok"
    assert case.source_links["source"] == "auto_extract"
    # 脱敏断言：输入埋的明文凭证不得出现在任何产物字段（T-101-02-01）。
    assert _SECRET not in case.solution
    assert "REDACTED" in case.solution
    assert _SECRET not in case.embedding_text
    # 入图投递：Phase 100 通路（INV-6）。
    ingest.assert_awaited_once()
    request = ingest.await_args.args[0]
    assert request.source_kind == "learning_case"
    assert request.source_id == str(case.id)
    assert ingest.await_args.kwargs.get("initiated_by_user_id") == "u-7"
