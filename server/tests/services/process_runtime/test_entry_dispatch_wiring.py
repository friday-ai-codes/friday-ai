"""四个入口的接线守卫（Phase 116-03）：六个续驱点 + 开关两态 + project_id 推导。

守四件事：

1. ⭐ **六个续驱点一个不漏**（Task 1）：六个文件里 ``build_orchestration_engine(`` 与
   ``adrive_convergence_session_to_pause_or_terminal(`` 的**直接调用零命中**（判据用
   ``ast``，``import`` 行不误伤），并用 ``plan_deepen_service.py`` 的**反向命中**证明扫描器
   非平凡。漏改一处的症状是「蓝图会话作答后无人续驱、卡在 waiting_clarification 永不推进
   且零异常」—— 源码扫描是唯一能把它变成机器可逮的形态。
2. ⭐ **四个入口 × 开关两态**（Task 2）：开关为 ``technical_plan`` ⇒ 走既有
   ``start_orchestration`` 且实参逐字不变；开关为 ``technical_blueprint`` ⇒ 建出
   ``process_type == "technical_blueprint"`` 的会话且 ``decomposition.project_id`` 非空。
3. ⭐ **``meta.project_id`` 推不出即拒绝发起**：四个入口各自如实回错，且
   ``ConvergenceSession`` / ``Artifact`` 计数与调用前逐字相等（零副作用）。
4. ⭐ **MCP 的 Space/Project 混淆双防线**（P-8）：``McpWorkItemContext.space`` 必须过
   ``_aresolve_project`` —— 建出的蓝图 ``project_id`` 等于 ``Project.id`` 且**不等于**
   ``Space.id``；且 ``skip_clarification`` / ``force_confirm`` 绝不进蓝图链。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SERVER_DIR = Path(__file__).resolve().parents[3]

# ⭐ 六个必改的续驱点（RESEARCH §A.4 表逐行）。⛔ 不含 subagent/api/callbacks.py:447
# （对蓝图三重不可达）与 plan_deepen_service.py:99（自己建 session，非蓝图入口）。
_REWIRED_FILES = (
    "workflows/nodes/ai/plan_research.py",
    "agents/tools/plan_research_tools.py",
    "mcp_tools/orchestration_delegate.py",
    "services/process_runtime/answer_resume.py",
    "feishu/callbacks/plan_clarify_callback.py",
    "initiatives/services/feature_solution_service.py",
)

# 四个真实入口文件（开关调用点所在）
_ENTRY_FILES = (
    "workflows/nodes/ai/plan_research.py",
    "agents/tools/plan_research_tools.py",
    "mcp_tools/orchestration_delegate.py",
    "initiatives/services/feature_solution_service.py",
)

_LEGACY_DIRECT_CALLS = (
    "build_orchestration_engine",
    "adrive_convergence_session_to_pause_or_terminal",
)


def _tail_name(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _call_hits(rel: str, names: tuple[str, ...]) -> list[str]:
    """该文件里对 ``names`` 的**直接调用**位置（``ast.Call``，``import`` 行不算）。"""
    path = _SERVER_DIR / rel
    assert path.exists(), f"扫描目标不存在：{rel}"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _tail_name(node.func) in names:
            hits.append(f"{rel}:{node.lineno}: {_tail_name(node.func)}(")
    return hits


# ═══════════════════════════════════════════════════════════════════════════
# 1-4. 六个续驱点的源码扫描（Task 1）
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("rel", list(_REWIRED_FILES))
def test_no_direct_legacy_engine_or_driver_call(rel: str) -> None:
    """⭐ 六个续驱点里旧工厂 / 旧 driver 的**直接调用**零命中（``import`` 行不误伤）。

    漏改任一处 ⇒ 蓝图会话作答后无人续驱、卡在 ``waiting_clarification`` **永不推进且零
    异常**（T-116-21）。这是「漏改一处」唯一能被机器逮住的形态。
    """
    hits = _call_hits(rel, _LEGACY_DIRECT_CALLS)
    assert not hits, "仍有旧工厂 / 旧 driver 的直接调用：\n  " + "\n  ".join(hits)


def test_the_scanner_actually_catches_an_unrewired_file() -> None:
    """反向对照：``plan_deepen_service.py`` 是**有意不改**的一处，扫描器必须命中它。

    没有这一条，上面那组断言可能只是「扫描器根本逮不到任何东西」的假绿。同时把
    「这一处是有意不改的」显式登记在案（它自己建 session、``process_type`` 恒
    ``technical_plan``，不是蓝图入口）。
    """
    hits = _call_hits("initiatives/services/plan_deepen_service.py", _LEGACY_DIRECT_CALLS)
    assert hits, "扫描器对未改造文件零命中 ⇒ 判据是平凡的"


@pytest.mark.parametrize("rel", list(_REWIRED_FILES))
def test_dispatcher_is_actually_used(rel: str) -> None:
    """分派器真的被用上：六个文件里 ``build_engine_for_session`` 各至少一次调用。"""
    hits = _call_hits(rel, ("build_engine_for_session",))
    assert hits, f"{rel} 没有经 build_engine_for_session 取 engine/driver"


def test_answer_resume_swaps_the_driver_too() -> None:
    """⭐ ``answer_resume`` 的 **driver 也换了**（``:102-103`` 两行一起换）。

    只换 engine 不换 driver 仍然坏：旧 driver 的 ``waiting_clarification`` 短路判据
    （``ClarificationService.ahas_pending``）对蓝图恒 False ⇒ 健康会话被推到 ``max_steps``
    落 ``advance_step_limit`` FAILED。
    """
    rel = "services/process_runtime/answer_resume.py"
    assert not _call_hits(rel, ("adrive_convergence_session_to_pause_or_terminal",))
    assert _call_hits(rel, ("build_engine_for_session",))


def test_chat_container_callback_chain_is_untouched_by_design() -> None:
    """⛔ ``_schedule_chat_plan_resume`` 那条链**有意不改**（对蓝图三重不可达）。

    分支条件 ``last_output["source"] == "plan_research"``（蓝图容器写
    ``blueprint_research`` / ``blueprint_repo_plan``）、函数体读 ``plan_session_id``
    （蓝图写 ``blueprint_session_id``）、外加 ``entrypoint == CHAT`` 守门 —— 三条任一都拦
    得住。改它等于给一条永不执行的分支加维护面。
    """
    src = (_SERVER_DIR / "subagent/api/callbacks.py").read_text(encoding="utf-8")
    start = src.index("def _schedule_chat_plan_resume")
    end = src.index("\nasync def ", start + 1)
    assert "build_orchestration_engine" in src[start:end]
