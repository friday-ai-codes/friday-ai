"""放置单元聚合（Phase 130，UNIT-01；D-04、D-05、D-06）。

将 feature 点按同模块、模块依赖边与正文「复用 X」边聚合为 Placement Units，
避免逐点独立全库检索。``query_text`` 仅含 module+name+description，剔除
acceptance / 测试用例正文。

观测：``placement_units_started/completed/failed``，``category=sampling``，
``component=process_runtime``；禁止需求全文入日志。
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = [
    "PlacementUnit",
    "PlacementUnitsResult",
    "build_placement_units",
    "placement_units_to_dict",
]

_COMPONENT = "process_runtime"

_ACCEPTANCE_KEYS = frozenset(
    {
        "acceptance",
        "acceptance_criteria",
        "acceptances",
        "test_case",
        "test_cases",
        "test_steps",
        "steps",
        "操作步骤",
        "验收",
        "验收项",
    }
)

# 「复用…」短语 → host hint（纯证据标注，不再驱动固定角色加权）
_REUSE_PATTERN = re.compile(
    r"复用\s*([^，,。；;\n]{1,40})",
    re.UNICODE,
)

_HOST_HINT_RULES: list[tuple[tuple[str, ...], str]] = [
    (
        ("做题", "练习", "题库", "practice", "端内做题"),
        "practice_reuse_host",
    ),
    (
        ("播放器", "知识点播放", "player"),
        "player_reuse_host",
    ),
    (
        ("宿主", "host"),
        "reuse_host",
    ),
]


@dataclass
class PlacementUnit:
    """单个放置单元。"""

    unit_id: str
    feature_ids: list[str] = field(default_factory=list)
    module_names: list[str] = field(default_factory=list)
    query_text: str = ""
    reuse_edges: list[dict[str, Any]] = field(default_factory=list)
    reuse_host_hints: list[str] = field(default_factory=list)
    depends_on_units: list[str] = field(default_factory=list)
    feature_names: list[str] = field(default_factory=list)


@dataclass
class PlacementUnitsResult:
    """放置单元聚合结果。"""

    status: str = "ok"
    units: list[PlacementUnit] = field(default_factory=list)
    unit_count: int = 0
    duration_ms: float = 0.0
    degrade_reasons: list[str] = field(default_factory=list)


def placement_units_to_dict(result: PlacementUnitsResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "status": result.status,
        "units": [asdict(u) for u in result.units],
        "unit_count": result.unit_count,
        "duration_ms": result.duration_ms,
        "degrade_reasons": list(result.degrade_reasons),
    }


def _stable_unit_id(module_names: Sequence[str], feature_ids: Sequence[str]) -> str:
    seed = "|".join(sorted(str(m) for m in module_names)) + "#" + "|".join(
        sorted(str(f) for f in feature_ids)
    )
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    label = "-".join(sorted(str(m) for m in module_names if m))[:48] or "unit"
    safe = re.sub(r"[^\w\-]+", "_", label, flags=re.UNICODE).strip("_") or "unit"
    return f"pu_{safe}_{digest}"


def _feature_id(feat: Mapping[str, Any], index: int) -> str:
    for key in ("id", "feature_id", "key", "name"):
        val = str(feat.get(key) or "").strip()
        if val:
            return val
    return f"feat_{index}"


def _module_name(feat: Mapping[str, Any]) -> str:
    for key in ("module", "module_name", "module_title"):
        val = str(feat.get(key) or "").strip()
        if val:
            return val
    return ""


def _parse_depends_on(mod: Mapping[str, Any]) -> list[str]:
    raw = mod.get("depends_on")
    if raw is None:
        raw = mod.get("依赖模块") or mod.get("dependencies")
    if isinstance(raw, str):
        parts = re.split(r"[,，/;；\s]+", raw)
        return [p.strip() for p in parts if p.strip()]
    if isinstance(raw, (list, tuple)):
        out: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("module") or "").strip()
            else:
                name = str(item or "").strip()
            if name:
                out.append(name)
        return out
    return []


def _extract_reuse(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    edges: list[dict[str, Any]] = []
    hints: list[str] = []
    if not text:
        return edges, hints
    seen_targets: set[str] = set()
    for match in _REUSE_PATTERN.finditer(text):
        target = match.group(1).strip()
        if not target or target in seen_targets:
            continue
        seen_targets.add(target)
        edges.append({"phrase": match.group(0).strip(), "target": target})
        lower = target.lower()
        for keywords, hint in _HOST_HINT_RULES:
            if any(kw.lower() in lower or kw.lower() in text.lower() for kw in keywords):
                if hint not in hints:
                    hints.append(hint)
        # 做题语义保底
        if any(tok in text for tok in ("做题", "练习")) and "practice_reuse_host" not in hints:
            if "做题" in target or "练习" in target or "做题" in text:
                hints.append("practice_reuse_host")
    return edges, hints


def _query_parts(feat: Mapping[str, Any], module: str) -> list[str]:
    parts: list[str] = []
    if module:
        parts.append(module)
    name = str(feat.get("name") or feat.get("title") or "").strip()
    if name:
        parts.append(name)
    desc = str(feat.get("description") or feat.get("desc") or "").strip()
    if desc:
        parts.append(desc)
    return parts


def _union_find_parent(parents: dict[str, str], x: str) -> str:
    while parents[x] != x:
        parents[x] = parents[parents[x]]
        x = parents[x]
    return x


def _union(parents: dict[str, str], a: str, b: str) -> None:
    ra, rb = _union_find_parent(parents, a), _union_find_parent(parents, b)
    if ra != rb:
        parents[rb] = ra


def build_placement_units(
    feature_list: Any = None,
    *,
    features_flat: list[dict[str, Any]] | None = None,
    modules: list[dict[str, Any]] | None = None,
    profile: Mapping[str, Any] | None = None,  # noqa: ARG001 — 预留
    reuse_summary: str | None = None,
    merge_depends_on: bool = True,
) -> PlacementUnitsResult:
    """聚合 feature 为 Placement Units（同步纯函数）。"""
    started = time.perf_counter()
    fl = feature_list if isinstance(feature_list, dict) else {}
    mod_list = list(modules) if modules is not None else list(fl.get("modules") or [])
    flat = (
        list(features_flat)
        if features_flat is not None
        else list(fl.get("features_flat") or [])
    )

    logger.info(
        "placement_units_started",
        feature_count=len(flat),
        module_count=len(mod_list),
        category="sampling",
        component=_COMPONENT,
    )

    try:
        # 模块元数据索引
        mod_meta: dict[str, dict[str, Any]] = {}
        for mod in mod_list:
            if not isinstance(mod, dict):
                continue
            name = str(mod.get("name") or mod.get("module") or "").strip()
            if not name:
                continue
            mod_meta[name] = mod

        # 按模块分桶 feature
        by_module: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for idx, feat in enumerate(flat):
            if not isinstance(feat, dict):
                continue
            # 跳过纯 acceptance 条目（若被误塞进 flat）
            keys = {str(k).lower() for k in feat}
            if keys and keys <= _ACCEPTANCE_KEYS:
                continue
            mod = _module_name(feat) or "_unassigned"
            by_module.setdefault(mod, []).append((idx, feat))

        module_names = sorted(by_module.keys())
        parents = {m: m for m in module_names}

        if merge_depends_on:
            for name, meta in mod_meta.items():
                if name not in parents:
                    parents[name] = name
                for dep in _parse_depends_on(meta):
                    if dep not in parents:
                        # 依赖模块无 feature 时也纳入并查集，便于合并后出现在 module_names
                        parents[dep] = dep
                    if name in parents:
                        _union(parents, name, dep)

        # 根 → 模块列表
        clusters: dict[str, list[str]] = {}
        for m in parents:
            root = _union_find_parent(parents, m)
            clusters.setdefault(root, []).append(m)

        units: list[PlacementUnit] = []
        global_reuse_edges: list[dict[str, Any]] = []
        global_hints: list[str] = []

        if reuse_summary:
            e, h = _extract_reuse(reuse_summary)
            global_reuse_edges.extend(e)
            for hint in h:
                if hint not in global_hints:
                    global_hints.append(hint)

        for _root, cluster_mods in sorted(clusters.items(), key=lambda x: sorted(x[1])[0]):
            # 只产出有 feature 的单元
            feats_in: list[tuple[int, dict[str, Any]]] = []
            present_mods: list[str] = []
            for m in sorted(cluster_mods):
                if m in by_module:
                    present_mods.append(m)
                    feats_in.extend(by_module[m])
            if not feats_in:
                continue

            feature_ids: list[str] = []
            feature_names: list[str] = []
            query_chunks: list[str] = []
            reuse_edges: list[dict[str, Any]] = list(global_reuse_edges)
            reuse_hints: list[str] = list(global_hints)
            seen_edge_targets: set[str] = {str(e.get("target") or "") for e in reuse_edges}

            for idx, feat in sorted(feats_in, key=lambda t: t[0]):
                fid = _feature_id(feat, idx)
                feature_ids.append(fid)
                fname = str(feat.get("name") or feat.get("title") or "").strip()
                if fname:
                    feature_names.append(fname)
                mod = _module_name(feat) or "_unassigned"
                query_chunks.extend(_query_parts(feat, mod))
                text_for_reuse = " ".join(
                    [
                        fname,
                        str(feat.get("description") or feat.get("desc") or ""),
                    ]
                )
                edges, hints = _extract_reuse(text_for_reuse)
                for edge in edges:
                    tgt = str(edge.get("target") or "")
                    if tgt and tgt not in seen_edge_targets:
                        seen_edge_targets.add(tgt)
                        reuse_edges.append(edge)
                for hint in hints:
                    if hint not in reuse_hints:
                        reuse_hints.append(hint)

            # 显式剔除 acceptance 键内容（防御）
            query_text = "\n".join(query_chunks)
            for feat in (f for _, f in feats_in):
                for key in _ACCEPTANCE_KEYS:
                    secret = str(feat.get(key) or "").strip()
                    if secret and secret in query_text:
                        query_text = query_text.replace(secret, "")

            unit = PlacementUnit(
                unit_id=_stable_unit_id(present_mods, feature_ids),
                feature_ids=feature_ids,
                module_names=present_mods,
                query_text=query_text.strip(),
                reuse_edges=reuse_edges,
                reuse_host_hints=reuse_hints,
                depends_on_units=[],
                feature_names=feature_names,
            )
            units.append(unit)

        # 若不合并 depends_on，可为依赖模块间写 unit 边
        if not merge_depends_on and len(units) > 1:
            by_mod_unit: dict[str, str] = {}
            for u in units:
                for m in u.module_names:
                    by_mod_unit[m] = u.unit_id
            for name, meta in mod_meta.items():
                src = by_mod_unit.get(name)
                if not src:
                    continue
                for dep in _parse_depends_on(meta):
                    dst = by_mod_unit.get(dep)
                    if dst and dst != src:
                        for u in units:
                            if u.unit_id == src and dst not in u.depends_on_units:
                                u.depends_on_units.append(dst)

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        result = PlacementUnitsResult(
            status="ok",
            units=units,
            unit_count=len(units),
            duration_ms=duration_ms,
            degrade_reasons=[],
        )
        logger.info(
            "placement_units_completed",
            unit_count=result.unit_count,
            feature_count=len(flat),
            duration_ms=duration_ms,
            category="sampling",
            component=_COMPONENT,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.warning(
            "placement_units_failed",
            error=redact_secrets_in_text(str(exc)),
            duration_ms=duration_ms,
            category="sampling",
            component=_COMPONENT,
        )
        return PlacementUnitsResult(
            status="degraded",
            units=[],
            unit_count=0,
            duration_ms=duration_ms,
            degrade_reasons=["placement_units_exception"],
        )
