"""仓库路由权重配置 loader/校验单点（Phase 106-02，ROUTE-06）。

「配置 loader 单点 + 参数注入」模式（106-RESEARCH Pattern 2）：
- **纯函数模块不读配置**——``repo_router_scoring`` 零 I/O、零 Django import；
- router 层（106-06）/ replay（106-07）经本模块读取配置后**以参数注入**打分核心；
- 本模块是权重配置进入打分链路的唯一入口，校验逻辑也在此单点维护
  （``RepoRouterWeightConfigView`` PUT 与 loader 二次校验共用
  :func:`validate_weight_config`，view 与 loader 不各写一份）。

生效语义（ROUTE-06「保存即生效」）：读取走 ``settings_service.get_json_setting``
（60s 进程内缓存），写入路径经 ``system/signals.py`` 的 post_save/post_delete
receiver 即时失效缓存——superuser 保存后下一次路由立即按新值打分，无需发版/重启。

防御语义（T-106-04）：DB 行非法（直写绕过 view / JSON 损坏 / 校验失败）时
loader 回退 ``DEFAULT_WEIGHT_CONFIG`` 深拷贝并记 warning——恶意/错误权重
永不反噬路由（不产出全错排序或除零）。

校验口径（106-CONTEXT 裁决）：C_crit 不进加性和，加性权重表为 5 信号且
**绝对和无须为 1**（相对权重经缺失重归一化生效）——因此不校验 Σw=1，改为：
(a) 每个权重落在离散网格 ``WEIGHT_GRID``（防过拟合四道闸之一）；
(b) 文本主导不变量 INV-R2 的相对形式
    ``fsum(domain, stack, team) <= 0.5 * fsum(全部 5 权重)``；
(c) 常数范围逐项校验。
CONTEXT ROUTE-06 节的「Σw=1」字面被同文档 ROUTE-04 节的 C_crit 裁决取代。

async 侧统一 ``sync_to_async(thread_sensitive=False)`` 包装整个 loader
（RESEARCH Pitfall 7：单 JSON 键一次读取，禁逐键 aget——那会绕过
60s 缓存且放大 DB round-trip）。
"""

from __future__ import annotations

import copy
import math
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from codegraph.services.repo_router_scoring import (
    DEFAULT_WEIGHT_CONFIG,
    SIGNAL_ACTIVITY,
    SIGNAL_DOMAIN,
    SIGNAL_STACK,
    SIGNAL_TEAM,
    SIGNAL_TEXT,
)
from system.models import SettingKeys
from system.settings_service import get_json_setting

logger = structlog.get_logger(__name__)

# 权重离散网格（防过拟合四道闸之一，per 106-CONTEXT ROUTE-06）。
# 浮点比较容差：网格判定用 `any(abs(v - g) < _GRID_TOL for g in WEIGHT_GRID)`
# ——JSON 往返 / 前端序列化产生的 1e-16 级误差不应导致合法值被拒。
WEIGHT_GRID = (0, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.30, 0.40, 0.55)

_GRID_TOL = 1e-9

# 加性权重键集合必须恰为 5 信号（C_crit 不进加性和，per CONTEXT 裁决）。
_WEIGHT_KEYS = frozenset(
    {SIGNAL_TEXT, SIGNAL_DOMAIN, SIGNAL_ACTIVITY, SIGNAL_STACK, SIGNAL_TEAM}
)
# INV-R2 相对形式的分子：元数据三信号。
_META_WEIGHT_KEYS = (SIGNAL_DOMAIN, SIGNAL_STACK, SIGNAL_TEAM)

# N_r 快照缺失/非法时的空形状（106-06 消费方按此形状降级 denom_size=1.0）。
_EMPTY_NR_SNAPSHOT: dict[str, Any] = {
    "n_r_by_repo": {},
    "n_bar": None,
    "generated_at": None,
}


def _is_number(value: Any) -> bool:
    """数值判定（bool 是 int 子类，显式排除）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _on_grid(value: float) -> bool:
    return any(abs(value - g) < _GRID_TOL for g in WEIGHT_GRID)


def _validate_weights(raw: Any, normalized: dict[str, Any], errors: list[str]) -> None:
    """weights 段：键集合恰为 5 信号 + 每个值落在离散网格。"""
    if not isinstance(raw, dict):
        errors.append("weights 必须是对象（信号名 → 权重）")
        return
    missing = _WEIGHT_KEYS - raw.keys()
    unknown = raw.keys() - _WEIGHT_KEYS
    if missing:
        errors.append(f"weights 缺少信号键: {', '.join(sorted(missing))}")
    if unknown:
        errors.append(f"weights 含未知信号键: {', '.join(sorted(unknown))}")
    if missing or unknown:
        return
    result: dict[str, float] = {}
    for key in sorted(_WEIGHT_KEYS):
        value = raw[key]
        if not _is_number(value):
            errors.append(f"weights.{key} 必须是数值")
            continue
        value = float(value)
        if not _on_grid(value):
            errors.append(
                f"weights.{key}={value} 不在离散网格 {list(WEIGHT_GRID)} 内（防过拟合约束）"
            )
            continue
        result[key] = value
    if len(result) != len(_WEIGHT_KEYS):
        return
    # INV-R2 相对形式：元数据权重和 ≤ 0.5×全部权重和（文本主导不变量）。
    meta_sum = math.fsum(result[key] for key in _META_WEIGHT_KEYS)
    total_sum = math.fsum(result.values())
    if meta_sum > 0.5 * total_sum + _GRID_TOL:
        errors.append(
            "INV-R2 违反：元数据权重相对和"
            f"（domain+stack+team={meta_sum:.4f}）超过全部权重和的一半"
            f"（0.5×{total_sum:.4f}={0.5 * total_sum:.4f}）——文本信号必须保持主导"
        )
        return
    normalized["weights"] = result


# 常数范围校验表：key → (谓词, 中文规则描述)。
# n_bar 单列（允许 None）；s_top/t2 的 c_lo<c_hi 是跨键约束，同样单列。
_CONSTANT_RULES: dict[str, tuple[Any, str]] = {
    "p": (lambda v: v >= 1.0, "p 必须 >= 1"),
    "b": (lambda v: 0.0 <= v <= 1.0, "b 必须在 [0, 1]"),
    "n_cap": (lambda v: v >= 1.0, "n_cap 必须 >= 1"),
    "lam": (lambda v: 0.0 <= v <= 1.0, "lam 必须在 [0, 1]"),
    "half_life_days": (lambda v: v > 0.0, "half_life_days 必须 > 0"),
    "offset_days": (lambda v: v >= 0.0, "offset_days 必须 >= 0"),
    "activity_floor": (lambda v: 0.0 <= v <= 1.0, "activity_floor 必须在 [0, 1]"),
    "deprecated_cap": (lambda v: 0.0 <= v <= 1.0, "deprecated_cap 必须在 [0, 1]"),
    "crit_band": (lambda v: 0.0 < v <= 0.1, "crit_band 必须在 (0, 0.1]"),
}


def _validate_constants(raw: Any, normalized: dict[str, Any], errors: list[str]) -> None:
    """constants 段：键为 DEFAULT 白名单子集 + 逐项范围校验（缺键补默认）。"""
    if raw is None:
        return
    if not isinstance(raw, dict):
        errors.append("constants 必须是对象（常数名 → 数值）")
        return
    whitelist = set(DEFAULT_WEIGHT_CONFIG["constants"])
    unknown = raw.keys() - whitelist
    if unknown:
        errors.append(f"constants 含未知键: {', '.join(sorted(unknown))}")
    merged: dict[str, Any] = dict(normalized["constants"])
    for key, value in raw.items():
        if key in unknown:
            continue
        if key == "n_bar":
            # n_bar 允许 None（缺失 → denom_size=1.0 降级路径）
            if value is None:
                merged[key] = None
            elif _is_number(value) and float(value) > 0.0:
                merged[key] = float(value)
            else:
                errors.append("constants.n_bar 必须为 null 或正数")
            continue
        if not _is_number(value):
            errors.append(f"constants.{key} 必须是数值")
            continue
        value = float(value)
        rule = _CONSTANT_RULES.get(key)
        if rule is not None and not rule[0](value):
            errors.append(f"constants.{key}={value} 非法：{rule[1]}")
            continue
        merged[key] = value
    # 跨键约束：affine clip 校准区间必须非空（c_lo < c_hi），否则除零/全 clip。
    if merged["s_top_c_lo"] >= merged["s_top_c_hi"]:
        errors.append(
            f"constants.s_top_c_lo={merged['s_top_c_lo']} 必须 < s_top_c_hi={merged['s_top_c_hi']}"
        )
    if merged["t2_c_lo"] >= merged["t2_c_hi"]:
        errors.append(
            f"constants.t2_c_lo={merged['t2_c_lo']} 必须 < t2_c_hi={merged['t2_c_hi']}"
        )
    if not errors:
        normalized["constants"] = merged
    else:
        # 有错时不落任何部分覆盖——调用方（loader）整体回退 DEFAULT。
        pass


def validate_weight_config(raw: Any) -> tuple[dict[str, Any], list[str]]:
    """校验并规范化权重配置。

    返回 ``(规范化配置, 错误列表)``：
    - 错误列表为空 → 规范化配置为「raw 与 DEFAULT merge」的可落库形态
      （缺键补默认，数值统一 float）；
    - 错误列表非空 → 第一元素仍为可用的规范化尝试（view 只在列表空时落库，
      loader 拿到非空列表时整体回退 DEFAULT）。
    """
    normalized: dict[str, Any] = copy.deepcopy(DEFAULT_WEIGHT_CONFIG)
    errors: list[str] = []

    if not isinstance(raw, dict):
        return normalized, ["配置必须是 JSON 对象"]

    known_top = set(DEFAULT_WEIGHT_CONFIG)
    unknown_top = raw.keys() - known_top
    if unknown_top:
        errors.append(f"含未知顶层键: {', '.join(sorted(unknown_top))}")

    if "weights" in raw:
        _validate_weights(raw["weights"], normalized, errors)
    if "constants" in raw:
        _validate_constants(raw["constants"], normalized, errors)

    if "weight_set_version" in raw:
        version = raw["weight_set_version"]
        if not isinstance(version, str) or not version.strip():
            errors.append("weight_set_version 必须为非空字符串")
        else:
            normalized["weight_set_version"] = version

    if "criticality_anchors" in raw:
        anchors = raw["criticality_anchors"]
        if not isinstance(anchors, dict) or not all(
            isinstance(k, str) and _is_number(v) and 0.0 <= float(v) <= 1.0
            for k, v in anchors.items()
        ):
            errors.append("criticality_anchors 必须是 {档位: 锚点值} 对象且值域 [0, 1]")
        else:
            normalized["criticality_anchors"] = {k: float(v) for k, v in anchors.items()}

    if "crit_weight_reserved" in raw:
        reserved = raw["crit_weight_reserved"]
        if not _is_number(reserved) or not 0.0 <= float(reserved) <= 1.0:
            errors.append("crit_weight_reserved 必须是 [0, 1] 数值")
        else:
            normalized["crit_weight_reserved"] = float(reserved)

    if "t2_disabled_facets" in raw:
        facets = raw["t2_disabled_facets"]
        if not isinstance(facets, list) or not all(isinstance(f, str) for f in facets):
            errors.append("t2_disabled_facets 必须是字符串列表")
        else:
            normalized["t2_disabled_facets"] = list(facets)

    for optional_str_key in ("embedding_model_id", "calibrated_at"):
        if optional_str_key in raw:
            value = raw[optional_str_key]
            if value is not None and not isinstance(value, str):
                errors.append(f"{optional_str_key} 必须为 null 或字符串")
            else:
                normalized[optional_str_key] = value

    return normalized, errors


def load_weight_config() -> dict[str, Any]:
    """读取当前生效的权重配置（sync）。

    - SystemSetting 无行 / JSON 损坏 → ``DEFAULT_WEIGHT_CONFIG`` 深拷贝
      （``get_json_setting`` 坏 JSON 回退空 dict，与无行同路径）；
    - 行内校验失败 → 回退默认 + warning（T-106-04 第二道防线，永不反噬路由）；
    - 合法 → 规范化配置（缺键补默认，merge 语义）。
    """
    raw = get_json_setting(SettingKeys.REPO_ROUTER_WEIGHT_CONFIG, {})
    if not raw:
        return copy.deepcopy(DEFAULT_WEIGHT_CONFIG)
    normalized, errors = validate_weight_config(raw)
    if errors:
        # 观测 best-effort：记录失败绝不阻断路由（观测代码永不反噬业务）。
        try:
            logger.warning(
                "repo_router_weight_config_invalid",
                errors=errors[:5],
                error_count=len(errors),
                category="sampling",
                component="codegraph",
            )
        except Exception:
            pass
        return copy.deepcopy(DEFAULT_WEIGHT_CONFIG)
    return normalized


def load_nr_snapshot() -> dict[str, Any]:
    """读取 N_r/N̄ 快照（sync）。

    形状契约：``{"n_r_by_repo": {rid: int}, "n_bar": float|None, "generated_at": str|None}``。
    缺失/坏 JSON/结构非法 → 空形状（消费方 106-06 走 denom_size=1.0 降级路径）；
    合法行 → 原值透传（``n_bar`` 强转 float）。
    """
    raw = get_json_setting(SettingKeys.REPO_ROUTER_NR_SNAPSHOT, {})
    if not raw:
        return dict(_EMPTY_NR_SNAPSHOT)
    n_r_by_repo = raw.get("n_r_by_repo")
    if not isinstance(n_r_by_repo, dict):
        return dict(_EMPTY_NR_SNAPSHOT)
    n_bar = raw.get("n_bar")
    if n_bar is not None:
        if not _is_number(n_bar) or float(n_bar) <= 0.0:
            return dict(_EMPTY_NR_SNAPSHOT)
        n_bar = float(n_bar)
    generated_at = raw.get("generated_at")
    return {
        "n_r_by_repo": n_r_by_repo,
        "n_bar": n_bar,
        "generated_at": generated_at if isinstance(generated_at, str) else None,
    }


# async 侧：整个 loader 包一层（单 JSON 键一次读取，禁逐键 aget——
# RESEARCH Pitfall 7）。thread_sensitive=False：loader 只读 DB + cache，
# 无共享可变状态，无需串行到主线程。
aload_weight_config = sync_to_async(load_weight_config, thread_sensitive=False)
aload_nr_snapshot = sync_to_async(load_nr_snapshot, thread_sensitive=False)


__all__ = [
    "WEIGHT_GRID",
    "aload_nr_snapshot",
    "aload_weight_config",
    "load_nr_snapshot",
    "load_weight_config",
    "validate_weight_config",
]
