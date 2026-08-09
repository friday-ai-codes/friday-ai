"""内存图服务的**读取层闸门** —— 仓库可读性校验与 exclusion 收口（Phase 121，GRAPH-04）。

问题背景
========
图服务会被 MCP 工具、AI 对话、后台任务与工作流四类调用方共用，其中 ``repository_id``
与 ``user`` 都是不可信输入。如果每个调用方各自校验，迟早有一条路径漏掉「已软删」或
「未索引」这两道；更危险的是 exclusion —— ``.env`` / ``*.pem`` / ``id_rsa`` 的符号名与
文件路径一旦漏进图，就会同时泄漏进 Phase 122–127 的**每一个**上层工具输出。

方案（单一校验点 + 装配阶段过滤）
==================================
本模块把两件事各收口成一个函数：

- :func:`ensure_repository_readable` —— 仓库可读性的**唯一**校验点。存在性、软删、
  索引态三道判定合并在这里，per-user ACL 的扩展位也留在这里
  （:func:`_check_user_acl`）。⛔ 未索引仓库抛 :class:`~services.code_graph.model.GraphNotIndexed`，
  **绝不返回空图**：空图会被上层误读为「没有影响」，让 agent 得出「这次改动安全」的
  错误结论。未索引是「不知道」，不是「没有」。
- :func:`build_matcher_and_fingerprint` / :func:`make_path_exclusion_memo` ——
  exclusion 判定的取用面。判定逻辑本身**不在这里实现**，全部复用
  ``services/exclusion.py``（全仓唯一事实源）；本模块只负责把它接进图装配链路，
  并额外算出一份精确的规则指纹供缓存签名比对。

边界与残余风险
==============
① **fail-closed 优先于一切**：matcher 构造失败 → 整仓拒绝（抛
   :class:`~services.code_graph.model.GraphAccessDenied`），⛔ 绝不降级成「不过滤」。
   降级放行等于把被排除文件泄漏进所有图工具的输出，比拒绝服务严重得多。

② **过滤发生在装配阶段，不是输出阶段**：被排除的 ``Symbol.file_path`` 对应的节点
   根本不进节点集，其邻接边随之消失（节点丢弃由 Plan 121-05 落地）。输出阶段过滤
   挡不住计数、深度分组等旁路泄漏。

③ **残余风险（如实记录）**：图缓存是 **per-worker 进程内存**。某用户的权限若在缓存
   建立**之后**被收回，进程里那个图对象本身不会被撤销——但
   :func:`ensure_repository_readable` 在**每次** ``get_graph`` 都执行（不因缓存命中而
   跳过），因此实际访问仍会被拦下。真正的残余风险只存在于「per-user ACL 落地之后、
   精细到符号级的授权」场景，该项已在 121-CONTEXT.md 的 Deferred 列表。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Set as AbstractSet
from typing import TYPE_CHECKING, Any, Callable, Final, Iterator

import structlog

from common.logging import redact_secrets_in_text
from services.code_graph.model import GraphAccessDenied, GraphNotIndexed

if TYPE_CHECKING:
    from services.exclusion import ExclusionMatcher

logger = structlog.get_logger(__name__)

# 事件名常量（形态对齐 ``codegraph/lsp/volar_pool.py`` L42–47）。
# ⚠️ 前缀不得缩写：``graph_build_*`` 已被 ``services/graph_builder.py`` 占用、
#    ``galaxy_cache_*`` 已被 ``codegraph/galaxy/cache.py`` 占用，缩写会让两条链路的
#    日志混在一起筛不开。
_EVENT_ACCESS_DENIED: Final[str] = "code_graph_access_denied"
_EVENT_MATCHER_FAILED: Final[str] = "code_graph_exclusion_matcher_failed"

# matcher + 规则指纹的跨调用 memo：``repository_id -> (过期时刻, matcher, 指纹)``。
#
# 为什么本模块要自建一份：``services/exclusion.py`` 的 ``_matcher_cache`` 只有
# **async** 的 ``build_matcher_for_repo`` 会读，而本相位的取图链路整条跑在
# ``sync_to_async`` 包裹的同步上下文里、走的是同步的 ``_resolve_effective_specs``,
# 那份 TTL 缓存对我们完全够不着。没有 memo 的话，``_resolve_effective_specs``（DB 读）
# 与 ``ExclusionMatcher.__init__``（编译该仓全部 glob/regex）会在**每次** ``get_graph``
# 重跑一遍，包括缓存命中的那些。
#
# ⚠️ 与 ``exclusion.py`` 的无锁裸字典不同，这里必须加锁：本模块的读者来自三类
#    event loop 的执行器线程（ASGI 主循环 / workflow 引擎自建循环 / durable worker）。
_MATCHER_FP_CACHE: dict[str, tuple[float, "ExclusionMatcher", str]] = {}
_MATCHER_FP_LOCK: Final[threading.Lock] = threading.Lock()

# 刻意与 ``services/exclusion.py::_MATCHER_CACHE_TTL_SECONDS`` 对齐：规则变更后
# 最多 60s 才生效的暴露窗口，与全仓既有 exclusion 读取面**完全相同**，不是本相位
# 新引入的弱化。要收窄就两处一起改。主动失效走
# :func:`invalidate_matcher_fingerprint_cache`（Plan 121-09 的 ``GraphService.invalidate``
# 与测试 fixture 都会调）。
_MATCHER_FP_TTL_SECONDS: Final[float] = 60.0

__all__ = [
    "build_matcher_and_fingerprint",
    "ensure_repository_readable",
    "invalidate_matcher_fingerprint_cache",
    "make_path_exclusion_memo",
]


def _initiated_by(user: Any | None) -> str:
    """取触发用户标识；无触发用户（后台/预热路径）记 ``system``（LOGGING-SPEC §3）。"""
    if user is None:
        return "system"
    user_id = getattr(user, "id", None) or getattr(user, "pk", None)
    return str(user_id) if user_id is not None else "system"


def _log_access_denied(*, repository_id: Any, reason: str, user: Any | None) -> None:
    """拒绝出口的结构化埋点。观测 best-effort —— 任何异常吞掉，绝不反噬主流程。"""
    try:
        logger.warning(
            _EVENT_ACCESS_DENIED,
            component="code_graph",
            category="sampling",
            repository_id=str(repository_id),
            reason=reason,
            initiated_by_user_id=_initiated_by(user),
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass


def _check_user_acl(user: Any | None, repo: Any) -> None:
    """per-user 仓库 ACL 的**扩展点**（当前为空实现，恒 ``return None``）。

    本仓当前的仓库层只有「认证 + 存在性」两道（``repositories/permissions.py``：
    「配合 IsAuthenticated 使用，任意登录用户均可访问存在的仓库」）。本相位
    **不发明 ACL 模型**，只把校验点收口——未来若需要引入仓库级 ACL，在此处扩展
    ownership 检查即可，全部图访问自动继承，无需逐个调用方改造。

    落地 ACL 时的出口约定：拒绝一律抛 :class:`GraphAccessDenied`，并在抛出前调
    :func:`_log_access_denied`（``reason="acl_denied"``），与其余三道判定同形。
    """
    return None


async def ensure_repository_readable(user: Any | None, repository_id: str) -> None:
    """仓库可读性的单一校验点。可读则静默返回 ``None``，否则抛异常。

    四道判定，任何一道不过都是**显式异常**，没有「返回空结果」这种出口：

    1. ``repository_id`` 走 :class:`uuid.UUID` 解析（ASVS V5 输入校验），非法即拒。
    2. ``aget(id=..., is_deleted=False)``：``DoesNotExist`` 与软删**合并成同一出口**，
       不向调用方泄漏「这个仓库存在但你看不到」这种存在性差异。
    3. ``index_status != INDEXED`` → :class:`GraphNotIndexed`。⛔ 不返回空图。
    4. :func:`_check_user_acl` 扩展点（当前空实现）。

    :param user: 触发用户（可为 ``None``，表示后台/系统路径），用于埋点归因与未来 ACL。
    :param repository_id: 仓库主键（字符串或 UUID 均可）。
    :raises GraphAccessDenied: ``repository_id`` 非法，或仓库不存在/已软删。
    :raises GraphNotIndexed: 仓库尚未建立索引。
    """
    from repositories.models import IndexStatus, Repository

    try:
        repo_uuid = uuid.UUID(str(repository_id))
    except (ValueError, TypeError, AttributeError):
        _log_access_denied(
            repository_id=repository_id, reason="invalid_repository_id", user=user
        )
        raise GraphAccessDenied(
            "repository_id 非法", {"repository_id": str(repository_id)}
        ) from None

    try:
        repo = await Repository.objects.aget(id=repo_uuid, is_deleted=False)
    except Repository.DoesNotExist:
        # 「不存在」与「已软删」共用同一句文案与同一个异常类型（不泄漏存在性差异）。
        _log_access_denied(
            repository_id=repository_id, reason="not_found_or_deleted", user=user
        )
        raise GraphAccessDenied(
            "仓库不存在或已删除", {"repository_id": str(repository_id)}
        ) from None

    if repo.index_status != IndexStatus.INDEXED:
        _log_access_denied(repository_id=repository_id, reason="not_indexed", user=user)
        raise GraphNotIndexed(
            "仓库尚未建立索引",
            {"repository_id": str(repository_id), "index_status": str(repo.index_status)},
        )

    _check_user_acl(user, repo)


# ── exclusion 收口：matcher 构造 / 规则指纹 / 热路径记忆化 ────────────────────


def _compute_rules_fingerprint(specs: Any) -> str:
    """对**有效规则集**直接哈希，得到 16 位规则指纹（供缓存签名比对）。

    对 ``(rule_type, pattern, enabled, source)`` 四元组排序后 JSON 规范化再取
    sha256 前 16 位。这个口径是免费且精确的——``specs`` 本来就要取，而它同时覆盖
    三个规则来源：per-repo ``RepoExclusionRule``、``SystemSetting`` 的全局 JSON、
    以及 ``BUILTIN_GLOBAL_DEFAULTS`` 的**代码**变更。

    两个被否决的替代方案（RESEARCH Pitfall 9，别再改回去）：

    - ⛔ ``RepoExclusionRule`` 的 ``count + MAX(updated_at)``：漏掉 ``SystemSetting``
      全局 JSON 与 ``BUILTIN_GLOBAL_DEFAULTS`` 的代码变更——升级一次内置默认，
      所有旧图签名照样命中。
    - ⛔ 拿 ``exclusion._matcher_cache`` 的 60s TTL 当版本号：TTL 只控制**何时重建
      matcher**，不产生任何可比对的版本标识；那还是个无锁裸模块字典。
    """
    canonical = sorted(
        (s.rule_type, s.pattern, bool(s.enabled), s.source) for s in specs
    )
    payload = json.dumps(canonical, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_matcher_and_fingerprint(repository_id: str) -> tuple[ExclusionMatcher, str]:
    """同步构造某仓库的 exclusion matcher，并顺带算出其规则指纹。

    同步而非 async：取图链路整条跑在 ``sync_to_async`` 包裹的同步上下文里，
    没必要为了 ``build_matcher_for_repo`` 再折一次线程。判定逻辑全部复用
    ``services/exclusion.py``（全仓唯一事实源），本函数只做接线 + 指纹 + memo。

    命中 60s memo 时直接返回，不重复读 DB、不重复编译 glob/regex。

    🚨 **fail-closed 优先于缓存**：解析或构造抛任何异常 → 埋点 + ``exclusion.blocked``
    审计 + 抛 :class:`GraphAccessDenied` **整仓拒绝**，并且**不写入 memo**、
    **不返回上一轮的旧 matcher**。绝不降级成「不过滤」——那等于把 ``.env`` /
    ``*.pem`` / ``id_rsa`` 的符号名与路径泄漏进每一个上层图工具的输出。

    :returns: ``(matcher, fingerprint)``，指纹为 16 位十六进制串。
    :raises GraphAccessDenied: 有效规则集解析失败或 matcher 构造失败（含
        ``InvalidExclusionRuleError``）。
    """
    key = str(repository_id)

    with _MATCHER_FP_LOCK:
        cached = _MATCHER_FP_CACHE.get(key)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1], cached[2]

    from services.exclusion import (
        ExclusionMatcher,
        _resolve_effective_specs,
        log_exclusion_blocked,
    )

    try:
        specs = _resolve_effective_specs(key)
        fingerprint = _compute_rules_fingerprint(specs)
        matcher = ExclusionMatcher(specs, repository_id=key)
    except Exception as exc:  # noqa: BLE001 — 整仓 fail-closed，见下方 raise
        try:
            logger.warning(
                _EVENT_MATCHER_FAILED,
                component="code_graph",
                category="sampling",
                repository_id=key,
                error=redact_secrets_in_text(str(exc))[:500],
                error_type=type(exc).__name__,
            )
        except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务
            pass
        log_exclusion_blocked(
            surface="code_graph", repository_id=key, rel_path="<repository>"
        )
        raise GraphAccessDenied(
            "exclusion matcher 构造失败，整仓拒绝取图",
            {"repository_id": key, "error_type": type(exc).__name__},
        ) from exc

    with _MATCHER_FP_LOCK:
        _MATCHER_FP_CACHE[key] = (
            time.monotonic() + _MATCHER_FP_TTL_SECONDS,
            matcher,
            fingerprint,
        )
    return matcher, fingerprint


def invalidate_matcher_fingerprint_cache(repository_id: str | None = None) -> None:
    """失效本模块的 matcher/指纹 memo。``None`` 清空全部。

    形态照抄 ``services/exclusion.py::invalidate_matcher_cache``。规则变更后两份
    memo 都要清——只清一份会读到另一份的 60s 旧值。
    """
    with _MATCHER_FP_LOCK:
        if repository_id is None:
            _MATCHER_FP_CACHE.clear()
        else:
            _MATCHER_FP_CACHE.pop(str(repository_id), None)


class _LiveReadOnlySet(AbstractSet):
    """对活动 ``set`` 的只读视图（随底层增长，但调用方改不动）。"""

    __slots__ = ("_backing",)

    def __init__(self, backing: set[str]) -> None:
        self._backing = backing

    def __contains__(self, item: object) -> bool:
        return item in self._backing

    def __iter__(self) -> Iterator[str]:
        return iter(self._backing)

    def __len__(self) -> int:
        return len(self._backing)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({sorted(self._backing)!r})"


def make_path_exclusion_memo(matcher: ExclusionMatcher) -> Callable[[str], bool]:
    """返回一个按 ``file_path`` 记忆化的排除判定闭包。

    为什么要记忆化：``matcher.is_excluded`` 是**每节点一次**的热路径调用（10 万级），
    内部要对该仓每条 dir/glob/regex 规则各跑一遍匹配。而符号数远大于文件数——同一
    文件的所有符号共享同一个判定结果，按 ``file_path`` 去重通常能省掉 90% 以上的
    调用。

    🚨 **不刷屏**：``log_exclusion_blocked`` 是 INFO 级，10 万级循环里 per-item 打点
    会直接违反 ``.cursor/rules/observability-logging.mdc`` 的级别纪律（规范正文点名
    过「4000+ 文件刷爆 stdout」的历史教训）。约定：对**每个新的被排除 file_path**
    至多打一次，命中记忆化时不再打点。

    闭包附带 ``excluded_files`` 只读集合（被排除的 ``file_path`` 去重后的全集），
    供 loader 汇总 ``GraphMeta.excluded_file_count``。

    ``matcher.is_excluded`` 自身对运行期异常已 fail-closed（返回 ``True``），
    路径归一越界与 ``None`` 路径同样视为排除——本闭包直接继承该语义，不再包一层。
    """
    verdicts: dict[str, bool] = {}
    excluded: set[str] = set()
    repository_id = str(getattr(matcher, "_repository_id", "") or "")

    from services.exclusion import log_exclusion_blocked

    def _is_excluded(file_path: str) -> bool:
        key = file_path or ""
        cached = verdicts.get(key)
        if cached is not None:
            return cached

        verdict = matcher.is_excluded(key)
        verdicts[key] = verdict
        if verdict:
            excluded.add(key)
            # 每个被排除文件只审计一次（上面的 memo 短路保证不随符号数增长）。
            log_exclusion_blocked(
                surface="code_graph", repository_id=repository_id, rel_path=key
            )
        return verdict

    _is_excluded.excluded_files = _LiveReadOnlySet(excluded)  # type: ignore[attr-defined]
    return _is_excluded
