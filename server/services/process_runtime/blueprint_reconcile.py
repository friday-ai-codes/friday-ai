"""blueprint_reconcile —— 跨仓 API 对账（Phase 113-05，FLOW-06）。

三段契约（改动前先读）：

1. **本模块只有纯函数节**：无 IO / 无 ORM / 无 LLM，stdlib only；顶层零 ORM import
   （唯一的跨模块依赖是同样零依赖的 ``blueprint_repo_waves``）。形态照
   ``blueprint_quality.py`` 的纯函数节。
2. **输入是半可信的装配产物**（LLM 分节起草 + 确定性投影的混合体，或 golden fixture）：
   逐字段 ``.get`` 防御、逐层 ``isinstance`` 检查，**绝不外抛**——对账结论是编排层
   「开澄清还是落版本」的判据，抛异常会把「有矛盾」升级成「整轮失败」。
3. **跨仓 API 对账不用 LLM 自查**（113-CONTEXT 锁定）：判定必须可复现、可单测、
   可解释。矛盾一律如实上报双方取值，**绝不静默拍板取其一**。

可用性口径（B4，与 111 冻结 schema 同源）：``api_contracts[]`` **没有顶层可用性字段**，
数据可用性与协作仓一律在 ``data_source`` 下（``data_source.availability`` 枚举只有
``existing`` / ``needs_support``，``data_source.support_repository_id`` 指出配合仓）。
本模块的读写**一律走 ``data_source.*`` 路径**：顶层同名键即便存在也一概不读——111
schema 里没有那个键，按它判定等于把结论建在幻觉字段上，而 114/115 会按 schema 路径
读不到、让 SC-4 表面通过实际失效。
"""

from __future__ import annotations

from typing import Any

from services.process_runtime.blueprint_repo_waves import match_api

__all__ = ["reconcile_cross_repo_apis"]

# 逐字段比对的契约字段。``direction`` 不在其中：provided / consumed 的分组本身就由它
# 完成，同一条契约不可能既是 provider 又是 consumer（形状矛盾在 schema 层已排除）。
_CONFLICT_FIELDS = ("method", "path", "request_schema", "response_schema")

_NEEDS_SUPPORT = "needs_support"

# 单类结论的上界：对账结果会进澄清问题文本与日志，无界列表会把 HITL 面板刷爆。
_MAX_FINDINGS = 50


def reconcile_cross_repo_apis(blueprint: Any) -> dict:
    """跨仓 API 对账：消费方是否找到提供方、字段是否一致、协作仓是否在关联清单里。

    Args:
        blueprint: **完整蓝图 content dict**（不是片段）。只读两个键：
            ``repo_associations``（取 ``repository_id`` 集合作协作仓白名单）与
            ``api_contracts``（按 ``direction`` 分 provided / consumed 两组）。
            非 dict / 缺键 / 类型错乱一律按「无该信息」处理。

    Returns:
        **恒定三键形状**（下游无需判空分支，对齐 ``blueprint_route`` 的约定）::

            {
              "gaps": [{"repository_id", "api", "reason": "no_provider"}],
              "conflicts": [{"api", "provider_repository_id", "consumer_repository_id",
                             "field", "provider_value", "consumer_value"}],
              "missing_support_repos": [{"repository_id", "api", "support_repository_id"}],
            }

        - ``gaps``：consumed 契约找不到任何 provider。调用方应据此把该条的
          ``data_source.availability`` 置 ``needs_support`` 并补
          ``data_source.support_repository_id``（B4）。
        - ``conflicts``：找到 provider 但契约字段不一致，**带双方取值**便于澄清问题直接
          引用。绝不静默取其一。
        - ``missing_support_repos``：该条已标 ``data_source.availability ==
          "needs_support"``，但 ``data_source.support_repository_id`` 为空、或指向一个
          **不在 ``repo_associations`` 里**的仓 —— 语义 = 缺协作仓，调用方抛澄清。
          ``data_source`` 缺失视为「未标注可用性」，**不触发**本检查（但若同时无
          provider 仍会进 ``gaps``）。

        零输入 / 非法输入 → ``{"gaps": [], "conflicts": [], "missing_support_repos": []}``。
    """
    result: dict[str, list[dict]] = {"gaps": [], "conflicts": [], "missing_support_repos": []}
    try:
        contracts = _contract_items(blueprint)
        if not contracts:
            return result
        association_ids = _association_ids(blueprint)
        provided = [item for item in contracts if _direction(item) == "provided"]
        for item in contracts:
            if _direction(item) != "consumed":
                continue
            consumer_id = str(item.get("repository_id") or "")
            api_name = _api_label(item)
            provider = _find_provider(item, provided, consumer_id=consumer_id)
            if provider is None:
                _append(
                    result["gaps"],
                    {"repository_id": consumer_id, "api": api_name, "reason": "no_provider"},
                )
            else:
                for entry in _field_conflicts(
                    item, provider, api_name=api_name, consumer_id=consumer_id
                ):
                    _append(result["conflicts"], entry)
            # 可用性判定只认 `data_source.*`（B4）：顶层同名键一概不读。
            data_source = (
                item.get("data_source") if isinstance(item.get("data_source"), dict) else None
            )
            if data_source is None:
                continue
            if str(data_source.get("availability") or "") != _NEEDS_SUPPORT:
                continue
            support_id = str(data_source.get("support_repository_id") or "").strip()
            if not support_id or support_id not in association_ids:
                _append(
                    result["missing_support_repos"],
                    {
                        "repository_id": consumer_id,
                        "api": api_name,
                        "support_repository_id": support_id,
                    },
                )
    except Exception:  # noqa: BLE001 — 半可信输入恒不抛：抛了会把「有矛盾」升级成「整轮失败」
        return result
    return result


# ── 内部纯函数 ────────────────────────────────────────────────────────────


def _contract_items(blueprint: Any) -> list[dict]:
    """取 ``api_contracts`` 的 dict 元素（非 dict 蓝图 / 非 list / 非 dict 元素一律剔除）。"""
    if not isinstance(blueprint, dict):
        return []
    raw = blueprint.get("api_contracts")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _association_ids(blueprint: Any) -> set[str]:
    """``repo_associations[].repository_id`` 集合（协作仓白名单）。"""
    if not isinstance(blueprint, dict):
        return set()
    raw = blueprint.get("repo_associations")
    if not isinstance(raw, list):
        return set()
    ids = set()
    for assoc in raw:
        if not isinstance(assoc, dict):
            continue
        repository_id = str(assoc.get("repository_id") or "")
        if repository_id:
            ids.add(repository_id)
    return ids


def _direction(item: dict) -> str:
    return str(item.get("direction") or "").strip().lower()


def _api_label(item: dict) -> str:
    """澄清问题里用来指认一条契约的短标签（name 优先，回落 path，再回落 id）。"""
    for key in ("name", "path", "id"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _find_provider(consumed: dict, provided: list[dict], *, consumer_id: str) -> dict | None:
    """定位 consumed 的 provider 契约：**与波次预排同一匹配口径**。

    复用 :func:`blueprint_repo_waves.match_api`（`(method, path)` 全等 → 否则 `name` 全等）
    并同样**跳过同仓自产自消**——两处口径漂移会导致「预排说有 provider、对账说没有」的
    自相矛盾（那种矛盾无法被任何一侧的测试逮住）。
    """
    for candidate in provided:
        if consumer_id and str(candidate.get("repository_id") or "") == consumer_id:
            continue
        if match_api(consumed, candidate):
            return candidate
    return None


def _field_conflicts(
    consumed: dict, provider: dict, *, api_name: str, consumer_id: str
) -> list[dict]:
    """逐字段比对 provider / consumer 契约；不一致即产一条带双值的冲突条目。

    一侧缺值（None / 空串 / 空 dict）视为「未声明」，**不算矛盾**——半成品契约在阶段 2
    是常态，把「还没写」当成「写错了」会让澄清线程刷满噪声。
    """
    conflicts: list[dict] = []
    for field in _CONFLICT_FIELDS:
        provider_value = provider.get(field)
        consumer_value = consumed.get(field)
        if _absent(provider_value) or _absent(consumer_value):
            continue
        if _normalized(field, provider_value) == _normalized(field, consumer_value):
            continue
        conflicts.append(
            {
                "api": api_name,
                "provider_repository_id": str(provider.get("repository_id") or ""),
                "consumer_repository_id": consumer_id,
                "field": field,
                "provider_value": provider_value,
                "consumer_value": consumer_value,
            }
        )
    return conflicts


def _absent(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (dict, list)):
        return not value
    return False


def _normalized(field: str, value: Any) -> Any:
    """比对前归一：``method`` 大小写不敏感、字符串去首尾空白，其余原样比对。"""
    if isinstance(value, str):
        text = value.strip()
        return text.upper() if field == "method" else text
    return value


def _append(bucket: list[dict], entry: dict) -> None:
    """有界追加（超出 :data:`_MAX_FINDINGS` 静默丢弃：结论已足够开澄清）。"""
    if len(bucket) < _MAX_FINDINGS:
        bucket.append(entry)
