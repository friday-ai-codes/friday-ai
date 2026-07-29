"""蓝图质量指标（Phase 111-04，GATE-02——质量标尺先建）。

指标口径出处：111-CONTEXT「Golden set 与观测」锁定项（对齐 v0.19.0 Phase 105
golden set 方法论）。本模块分两节：

- **纯函数节**（无 IO / 无 ORM / 无 LLM，stdlib only）：``citation_coverage``
  引用覆盖率与 ``target_repo_hit_rate`` 目标仓命中率——``evaluate_blueprint_golden``
  离线评估与 112–116 各相位回归共用的两把可用标尺。
- **DB 统计接口节**（占位）：AI 打回率 / 人审修改量 / 澄清轮次——数据由 112–114
  （审查循环 / 人审编辑 / 澄清线程）填充，本相位仅定义签名与口径 docstring；
  顶层零 ORM import，未来实装时依赖 delivery models 走函数内懒 import。

半可信输入（LLM 装配产物 / golden fixture）逐字段 ``.get`` 防御，绝不抛。
"""

from __future__ import annotations

from typing import Any, Iterator

__all__ = [
    "citation_coverage",
    "target_repo_hit_rate",
    "ai_rejection_rate",
    "human_edit_volume",
    "clarification_rounds",
]


# ---------------------------------------------------------------------------
# 纯函数节：可用指标（无 ORM）
# ---------------------------------------------------------------------------


def _cited(value: Any) -> bool:
    """条目引用判定：``citations`` 为非空 list 即视为已引用。"""
    return isinstance(value, list) and len(value) > 0


def _iter_key_conclusion_citations(blueprint: Any) -> Iterator[Any]:
    """走查三类关键结论条目，逐条产出其 citations 值（可能为 None / 非 list）。

    三类口径（CONTEXT 锁定）：

    - ``current_state_analysis[].findings[]``——citations 取 ``finding.citations``；
    - ``repo_associations[]``（rationale 级）——citations 取 ``rationale.citations``；
    - ``impact_analysis.affected_features[]``——citations 取 ``feature.citations``。
    """
    if not isinstance(blueprint, dict):
        return
    for analysis in blueprint.get("current_state_analysis") or []:
        if not isinstance(analysis, dict):
            continue
        for finding in analysis.get("findings") or []:
            if isinstance(finding, dict):
                yield finding.get("citations")
    for assoc in blueprint.get("repo_associations") or []:
        if not isinstance(assoc, dict):
            continue
        rationale = assoc.get("rationale")
        yield rationale.get("citations") if isinstance(rationale, dict) else None
    impact = blueprint.get("impact_analysis")
    features = impact.get("affected_features") if isinstance(impact, dict) else None
    for feature in features or []:
        if isinstance(feature, dict):
            yield feature.get("citations")


def citation_coverage(blueprint: dict) -> float:
    """引用覆盖率：三类关键结论条目中 ``citations`` 非空的占比。

    分子 = citations 为非空 list 的条目数；分母 = 三类条目总数。
    **分母为 0 返回 1.0**——空文档（三类条目全空）视为无引用缺口，约定而非巧合：
    golden 门槛是「已写下的关键结论必须有据」，不惩罚未写内容。
    """
    values = list(_iter_key_conclusion_citations(blueprint))
    if not values:
        return 1.0
    covered = sum(1 for value in values if _cited(value))
    return covered / len(values)


def target_repo_hit_rate(blueprint: dict, expected_direct_repo_names: list[str]) -> float:
    """目标仓命中率：期望 direct 仓名集合被蓝图实际 direct 集合命中的比例。

    实际 direct 集合 = ``repo_associations`` 中 ``role == "direct"`` 条目的
    ``repository_name`` 集合；命中率 = ``len(expected ∩ actual) / len(expected)``。
    expected 为空返回 1.0（无期望即无缺口）。
    """
    expected = {
        name for name in (expected_direct_repo_names or []) if isinstance(name, str) and name
    }
    if not expected:
        return 1.0
    actual: set[str] = set()
    if isinstance(blueprint, dict):
        for assoc in blueprint.get("repo_associations") or []:
            if not isinstance(assoc, dict) or assoc.get("role") != "direct":
                continue
            name = assoc.get("repository_name")
            if isinstance(name, str) and name:
                actual.add(name)
    return len(expected & actual) / len(expected)


# ---------------------------------------------------------------------------
# DB 统计接口节：占位——数据由 112–114 填充，本相位仅定义签名（CONTEXT 锁定）。
# 实装时按 artifact_id 查 delivery models（函数内懒 import），顶层保持零 ORM。
# ---------------------------------------------------------------------------


def ai_rejection_rate(artifact_id: str) -> float | None:
    """AI 审查打回率：该蓝图被 AI 审查打回的轮次占审查总轮次的比例。

    口径：Phase 114 审查循环落地后，按 ConvergenceSessionEvent 的
    ``blueprint.stage.*`` 事件统计（打回轮次 / ai_reviewing 总轮次）。
    当前无数据源，返回 ``None`` 表示指标不可用。
    """
    # TODO(Phase 114): 懒 import delivery models，按 artifact_id 聚合审查事件。
    return None


def human_edit_volume(artifact_id: str) -> int | None:
    """人审修改量：人工编辑产生的 ArtifactVersion 版本数。

    口径：Phase 114 人工 block 编辑链路落地后，按 created_by_user_id 非系统的
    版本行计数。当前无数据源，返回 ``None`` 表示指标不可用。
    """
    # TODO(Phase 114): 懒 import delivery models，按 artifact_id 统计人工版本。
    return None


def clarification_rounds(artifact_id: str) -> int | None:
    """澄清轮次：该蓝图澄清线程的往返轮次总数。

    口径：Phase 112–114 澄清线程写入落地后，按 BlueprintThread /
    BlueprintThreadMessage 统计（每线程一问一答记一轮）。
    当前无数据源，返回 ``None`` 表示指标不可用。
    """
    # TODO(Phase 112–114): 懒 import delivery models，按 artifact_id 统计线程轮次。
    return None
