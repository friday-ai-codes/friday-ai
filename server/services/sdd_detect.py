"""SDD（Spec-Driven Development）仓库检测器（Phase 48 Plan 01，SDD-01）。

索引完成钩子在临时克隆目录删除之前 best-effort 调用本模块：命中仓库根 ``openspec/``
目录则把 ``Repository.facets["methodology"]`` 标记为 ``"SDD"``，作为后续 spec 生命周期
治理（Phase 49–52）的入口信号。

设计约束（CONTEXT D-48-2/D-48-3/D-48-5）：
- **纯文件系统探测、零重依赖**：仅 ``os.path.isdir`` 单次 O(1) 判据，不解析 openspec
  内容（内容深度校验留 v2 SDDX-01）；不 import indexer / tree-sitter / LLM / FacetService。
- **单一写入入口**：``detect_and_tag_sdd`` 是 methodology 键的唯一自动写入/清除入口。
- **不误标 + 防漂移**：openspec/ 消失时仅清除**自动写入的 "SDD"**（他值不动）。
- **尊重人工 pin**：``facets["_pinned"]`` 含 ``methodology`` 时跳过，复用 FacetService pin 语义。
- **幂等**：facets 未变则不 ``asave`` —— 因 ``updated_at = auto_now=True``，多余写会漂移时间戳。

methodology 为本 phase 新增**独立语义键**，与 ``FacetService`` 的事实分面键不冲突
（FacetService 不碰 methodology）。
"""

from __future__ import annotations

import os

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["detect_and_tag_sdd"]

# facets 语义键与值（与 DOMAIN-MODEL/vNext 措辞一致）。
_METHODOLOGY_KEY = "methodology"
_SDD_VALUE = "SDD"
_PINNED_KEY = "_pinned"


async def detect_and_tag_sdd(repository_id: str, repo_path: str) -> bool:
    """探测仓库根 ``openspec/`` 并维护 ``facets["methodology"]``；返回是否发生写回。

    判据（D-48-2）：``os.path.isdir(repo_path/"openspec")`` —— 仓库根存在名为 openspec
    的目录即视为 SDD（最小充分信号，不读内容；openspec 为普通文件不算）。

    维护语义（D-48-3）：
    - 命中 openspec/ → ``facets["methodology"]="SDD"``。
    - 未命中且当前 methodology 为自动写入的 ``"SDD"`` → 删除该键（防漂移/陈旧）；他值不动。
    - ``methodology`` 在 ``_pinned`` 列表 → 直接返回 False（尊重人工 pin，不读不写）。
    - 新旧 facets 相等 → 不 ``asave``，直接返回 False（幂等，避免 updated_at 漂移）。

    生命周期（D-48-1）：调用方必须在删除临时克隆目录**之前** await 本协程，确保探测的是
    真实克隆目录而非已删除/空目录。
    """
    from repositories.models import Repository

    repo = await Repository.objects.filter(id=repository_id).afirst()
    if repo is None:
        return False

    facets = dict(repo.facets or {})

    # 尊重人工 pin：含 methodology 则不读不写（复用 FacetService pin 语义）。
    pinned = set(facets.get(_PINNED_KEY, []))
    if _METHODOLOGY_KEY in pinned:
        return False

    present = os.path.isdir(os.path.join(repo_path, "openspec"))
    if present:
        facets[_METHODOLOGY_KEY] = _SDD_VALUE
    elif facets.get(_METHODOLOGY_KEY) == _SDD_VALUE:
        # 仅清除自动写入的 SDD 标记（防漂移）；他值不动。
        del facets[_METHODOLOGY_KEY]

    # 幂等 no-op 守护：facets 未变则不写（避免 updated_at 漂移）。
    if facets == (repo.facets or {}):
        return False

    repo.facets = facets
    await repo.asave(update_fields=["facets", "updated_at"])

    if present:
        logger.info("sdd_detected", repository_id=str(repository_id), methodology=_SDD_VALUE)
    else:
        logger.info("sdd_tag_cleared", repository_id=str(repository_id))
    return True
