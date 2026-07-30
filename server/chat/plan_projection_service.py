"""编排方案版本 → chat ``CodingPlan`` 的投影（Phase 109 · SPINE-01）。

本模块是「编排产出直连执行流」的服务端半边：把 ``delivery.ArtifactVersion``
（§7 MergedPlan content）**幂等**投影成 chat ``CodingPlan``，让编排产物直接点亮
既有执行流四步（选目标仓 → 配置分支 → 确认编码 → 飞书导出）——那四步全部只以
``CodingPlan.id`` 为锚点（见 ``tests/test_spa_coding_chain_e2e.py`` 的不变量护栏）。

两层职责刻意分开：

- ``map_merged_plan_to_coding_plan``：**纯函数**（无 IO / ORM / LLM），只做字段搬运与
  枚举转换。半可信 LLM 产物（``ArtifactVersion.content``）恒不抛异常。
- ``PlanProjectionService.aproject``：写入口（唯一），负责 conversation 解析、幂等、
  观测埋点。
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "map_merged_plan_to_coding_plan",
]

# §7 ``execution_plan[].files[].action`` → chat ``CodingPlan.affected_files[].change_type``。
#
# 🔴 这张表是一个**静默失守点**的唯一防线：§7 用 ``action: create``，而 chat
# ``CodingPlan.affected_files`` 的 schema 是 ``{"file_path": str, "change_type": str}``
# 且取值为 ``add``。既有 ``agents/tools/coding_tools.py::_normalize_affected_files``
# 只做 ``path → file_path`` 的键改名、**不做**枚举映射；前端 ``TechPlanCard.vue``
# 又原样渲染 ``change_type``（109-UI-SPEC §B.4 明确裁定前端**不做**兼容映射，
# 以免掩盖后端缺陷）。⇒ 漏做本转换**不会崩、不会报错**，只会在界面上静默显示成
# ``create``。因此测试必须对三个已知取值逐条断言 ``file_path`` **与** ``change_type``
# 两个键（只断言 file_path 是本坑的典型警示信号）。
_ACTION_TO_CHANGE_TYPE: dict[str, str] = {
    "create": "add",
    "modify": "modify",
    "delete": "delete",
}

# 未知 / 缺失 action 的保守回退：修改语义最弱，不会把「改一行」误报成「新增文件」。
_DEFAULT_CHANGE_TYPE = "modify"


def map_merged_plan_to_coding_plan(content: Any) -> dict[str, Any]:
    """§7 MergedPlan content → chat ``CodingPlan`` 四个字段的纯映射。

    Args:
        content: 半可信 ``ArtifactVersion.content``（LLM 产物，字段可能缺失/类型错）。

    Returns:
        ``{"title", "tech_plan", "affected_files", "recommended_repository_ids"}``。
        ``title`` 不在此处截断——由调用方按 ``CodingPlan.title`` 的 max_length=200 截。

    映射口径：

    - ``tech_plan``：复用 ``render_merged_plan_markdown``（唯一渲染器，**禁止**在此
      新写第二个）。它产的是飞书 lark_md 方言（``•`` 字面项目符号而非 ``- ``），在
      前端 markdown-it（GFM）下显示为纯文本项目符号——109-UI-SPEC §Unresolved 第 7 条
      裁定**接受现状**：可读、语义不丢。若观感不可接受，处置方式是给该函数加
      ``flavor: 'lark_md' | 'gfm'`` 参数，**仍不 fork 渲染器**。
    - ``affected_files``：**全仓聚合**（遍历 ``execution_plan[]`` 所有 task 的
      ``files[]``，不按 repository 筛——与 ``mcp_tools.orchestration_delegate.
      map_canonical_to_coding_plan`` 的单仓版语义不同），按 ``(file_path, change_type)``
      去重并保序。
    - ``recommended_repository_ids``：按 task 出现顺序去重保序（保序即保
      ``release_order`` 意图）。

    半可信输入恒不抛：顶层非 dict、``execution_plan`` 非 list、``files`` 项非 dict、
    ``path`` 为空串等一律降级为空结构（防御性风格照抄
    ``map_canonical_to_coding_plan`` 的 ``isinstance`` 守卫）。
    """
    from services.process_runtime.render import render_merged_plan_markdown

    safe: dict[str, Any] = content if isinstance(content, dict) else {}

    raw_tasks = safe.get("execution_plan")
    tasks: list[Any] = raw_tasks if isinstance(raw_tasks, list) else []

    affected_files: list[dict[str, str]] = []
    seen_files: set[tuple[str, str]] = set()
    repository_ids: list[str] = []
    seen_repos: set[str] = set()

    for task in tasks:
        if not isinstance(task, dict):
            continue

        repository_id = str(task.get("repository_id") or "")
        if repository_id and repository_id not in seen_repos:
            seen_repos.add(repository_id)
            repository_ids.append(repository_id)

        raw_files = task.get("files")
        files: list[Any] = raw_files if isinstance(raw_files, list) else []
        for entry in files:
            if not isinstance(entry, dict):
                continue
            file_path = str(entry.get("path") or "")
            if not file_path:
                continue
            action = str(entry.get("action") or "")
            change_type = _ACTION_TO_CHANGE_TYPE.get(action, _DEFAULT_CHANGE_TYPE)
            key = (file_path, change_type)
            if key in seen_files:
                continue
            seen_files.add(key)
            affected_files.append({"file_path": file_path, "change_type": change_type})

    return {
        "title": str(safe.get("title") or ""),
        "tech_plan": render_merged_plan_markdown(safe),
        "affected_files": affected_files,
        "recommended_repository_ids": repository_ids,
    }
