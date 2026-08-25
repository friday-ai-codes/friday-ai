"""blueprint_repo_alias —— 仓库别名 → 关联 UUID 的确定性解析（纯函数）。

RepoPlan / 融合起草可能写出 ``support_repository_id`` 的短名或全路径（``onion-learning``、
``frontend/onion-learning``），而 ``repo_associations`` 权威键是 ``repository_id``（UUID）。
``reconcile_cross_repo_apis``、``check_api_closure`` 与 merge 落库前的 canonicalize **必须**
共享本模块口径，否则会出现「仓已在关联清单里却被判缺协作仓」的假阳性。

解析顺序（保守、可复现）：

1. 去首尾空白；空串 → 未解析。
2. **精确 UUID**：与某条 ``repository_id`` 全等（大小写敏感）。
3. **精确全名**：与某条 ``repository_name`` 全等（大小写敏感、仅 strip）。
4. **唯一 basename**：``repository_name`` 的路径末段（``/`` 后）与 alias 的 basename 全等；
   恰好一条关联命中 → 该 UUID；零条或多条 → 未解析（歧义 basename 不猜）。

不做大小写折叠、不做 fuzzy match —— 误解析比漏解析更糟（会把缺仓静默吞掉）。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "resolve_repository_alias",
    "is_resolvable_repository_alias",
    "canonicalize_repository_alias",
    "canonicalize_contract_support_repository_ids",
    "support_alias_is_ignored",
]


def resolve_repository_alias(associations: Any, alias: Any) -> str | None:
    """把别名解析为 ``repo_associations[].repository_id``；无法唯一确定时返回 ``None``。"""
    text = str(alias or "").strip()
    if not text:
        return None
    index = _build_index(associations)
    if text in index["ids"]:
        return text
    if text in index["full_names"]:
        return index["full_names"][text]
    basename = _basename(text)
    if not basename:
        return None
    matches = index["basename_to_ids"].get(basename) or []
    if len(matches) == 1:
        return matches[0]
    return None


def is_resolvable_repository_alias(associations: Any, alias: Any) -> bool:
    """别名能否唯一映射到关联清单里的 UUID（含已是 UUID 的情况）。"""
    return resolve_repository_alias(associations, alias) is not None


def canonicalize_repository_alias(associations: Any, alias: Any) -> str:
    """可解析则返回 UUID，否则返回 strip 后的原值（便于下游继续报缺仓）。"""
    text = str(alias or "").strip()
    if not text:
        return ""
    resolved = resolve_repository_alias(associations, text)
    return resolved if resolved else text


def support_alias_is_ignored(alias: Any, ignored: Any) -> bool:
    """操作员排除的协作仓别名是否命中 ``alias``。

    匹配口径（与解析器一样保守、大小写敏感）：

    - 精确全等（strip 后）；
    - 或双方 basename（``/`` 末段）全等。

    这样 ``course-business`` 与 ``backend/course-business`` 视为同一排除项；
    空串、非序列 ``ignored`` 一律不命中。
    """
    text = str(alias or "").strip()
    if not text:
        return False
    tokens = ignored if isinstance(ignored, (list, tuple, set, frozenset)) else []
    exact: set[str] = set()
    basenames: set[str] = set()
    for item in tokens:
        token = str(item or "").strip()
        if not token:
            continue
        exact.add(token)
        basename = _basename(token)
        if basename:
            basenames.add(basename)
    if text in exact:
        return True
    basename = _basename(text)
    return bool(basename) and basename in basenames


def canonicalize_contract_support_repository_ids(contracts: Any, associations: Any) -> int:
    """就地 canonicalize ``api_contracts[].data_source.support_repository_id``；返回改写条数。"""
    changed = 0
    for contract in contracts if isinstance(contracts, list) else []:
        if not isinstance(contract, dict):
            continue
        data_source = contract.get("data_source")
        if not isinstance(data_source, dict):
            continue
        support_id = str(data_source.get("support_repository_id") or "").strip()
        if not support_id:
            continue
        canonical = canonicalize_repository_alias(associations, support_id)
        if canonical and canonical != support_id:
            data_source["support_repository_id"] = canonical
            changed += 1
    return changed


def _build_index(associations: Any) -> dict[str, Any]:
    ids: set[str] = set()
    full_names: dict[str, str] = {}
    basename_to_ids: dict[str, list[str]] = {}
    for assoc in associations if isinstance(associations, list) else []:
        if not isinstance(assoc, dict):
            continue
        repository_id = str(assoc.get("repository_id") or "").strip()
        if not repository_id:
            continue
        ids.add(repository_id)
        repository_name = str(assoc.get("repository_name") or "").strip()
        if repository_name:
            if repository_name not in full_names:
                full_names[repository_name] = repository_id
            basename = _basename(repository_name)
            if basename:
                bucket = basename_to_ids.setdefault(basename, [])
                if repository_id not in bucket:
                    bucket.append(repository_id)
    return {"ids": ids, "full_names": full_names, "basename_to_ids": basename_to_ids}


def _basename(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    if "/" in text:
        return text.rsplit("/", 1)[-1].strip()
    return text
