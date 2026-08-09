# Phase 121: 内存图服务基座 - Pattern Map

**Mapped:** 2026-08-09
**Files analyzed:** 15（6 新建源文件 + 3 修改点 + 6 测试/文档文件）
**Analogs found:** 14 / 15

> 本文档的每一段代码都是从本仓真实文件复制的，带文件路径与行号。planner 写 PLAN.md 时应直接引用「照抄 X 文件 L**a**–L**b**」，不要重新发明。

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/services/code_graph/__init__.py` | barrel / curated export | — | `server/services/code_intel/__init__.py` | exact |
| `server/services/code_graph/model.py` | model（契约值对象 + 枚举 + 异常） | transform | `server/services/retrieval/types.py` + `server/agents/call_source.py` + `server/agents/core/exceptions.py` | exact（三者组合） |
| `server/services/code_graph/loader.py` | service（ORM 独占 + CPU 装配） | batch read → transform | `server/services/code_intel/local_provider.py` + `server/services/chunk_lookup.py` | role-match |
| `server/services/code_graph/signature.py` | utility（聚合哈希） | batch aggregate read | `server/codegraph/galaxy/cache.py::compute_signature`（L87–104） | exact |
| `server/services/code_graph/cache.py` | service / store（进程内单例 LRU + single-flight） | request-response（带缓存） | `server/codegraph/lsp/volar_pool.py` | exact |
| `server/services/code_graph/access.py` | middleware / guard（fail-closed 收口） | request-response | `server/services/chunk_lookup.py`（L50–74）+ `server/mcp_tools/views.py::_get_indexed_repo`（L363–381） | role-match |
| `server/friday/settings.py`（修改） | config | — | 同文件 codegraph 区块 L858–879 | exact |
| `server/pyproject.toml`（修改） | config | — | 同文件 `[project].dependencies` L6–75 | exact |
| `server/code_relations/tasks.py`（修改，L224–229） | hook / invalidation | event-driven | 同位置既有 `GalaxyGraphCache.refresh_repo` 调用 | exact |
| `server/services/graph_builder.py`（修改，L517–521） | hook / invalidation | event-driven | 同位置既有 `GalaxyGraphCache.refresh_repo` 调用 | exact |
| `server/tests/services/code_graph/__init__.py` | test scaffold | — | `server/tests/services/retrieval/__init__.py` | exact |
| `server/tests/services/code_graph/conftest.py` | test fixture | — | `server/tests/codegraph/conftest.py`（L23–90） | role-match（**须改 `index_status`**） |
| `server/tests/services/code_graph/test_signature.py` | test | — | `server/tests/codegraph/test_galaxy_cache.py`（L55–127） | exact |
| `server/tests/services/code_graph/test_cache.py` | test（LRU / 并发 / 逐出） | — | `server/codegraph/lsp/tests/test_volar_pool.py`（L28–34, 99–141, 233–260） | exact |
| `.planning/observability/LOGGING-SPEC.md` §5（修改） | docs | — | **无代码 analog**（见 §No Analog Found） | none |

---

## Pattern Assignments

### `server/services/code_graph/__init__.py`（barrel）

**Analog:** `server/services/code_intel/__init__.py`（全文 28 行）

这是本相位「架构红线」的机械防线——只 re-export `GraphService` 与 `model.py` 的契约类型，**不导出 `loader` / `cache`**。照抄形态：

```1:28:server/services/code_intel/__init__.py
"""代码智能 Provider 抽象包 (implementation contract / contract..contract).

对外暴露三层 Protocol 与 ``get_provider`` 单例入口；``register_provider`` 仅供
``CodeIntelConfig.ready()`` 使用，web 请求生命周期内调用会因 frozen 标志
raise RuntimeError (per contract)。
"""

from __future__ import annotations

from services.code_intel.protocols import (
    BaseCodeProvider,
    GraphCapableProvider,
    SymbolCapableProvider,
)
from services.code_intel.registry import (
    PROVIDER_REGISTRY,
    get_provider,
    register_provider,
)

__all__ = [
    "BaseCodeProvider",
    "GraphCapableProvider",
    "PROVIDER_REGISTRY",
    "SymbolCapableProvider",
    "get_provider",
    "register_provider",
]
```

**要点（planner 必须写进 plan）：**
- 绝对导入用 `from services.code_graph.model import ...`（本仓 first-party 用绝对路径，不用相对 import）。
- docstring 里显式写「不导出 loader / cache 是架构红线」——与 code_intel docstring 写明 `register_provider` 使用边界同款做法。
- `__all__` 字母序排列（code_intel 与 `retrieval/types.py` L120–125 都如此）。

---

### `server/services/code_graph/model.py`（model, transform）

三个不同的契约形态各有精确 analog。

#### (a) frozen slots dataclass 值对象 — `server/services/retrieval/types.py`

```48:65:server/services/retrieval/types.py
@dataclass(frozen=True, slots=True)
class NeighborMetadata:
    """图谱邻居元数据（implementation 编排器一跳/二跳扩散结构，per contract）。

    `line_start` / `line_end` 允许 None——历史 ChunkRegistry row 未回填行号
    （per implementation contract schema gap），graph_context 渲染必须 fallback 到无
    行号格式。`reason` 由 `_explain_neighbor(edge_type, source_payload)` 生成。
    """

    chunk_id: str
    file_path: str
    line_start: int | None
    line_end: int | None
    edge_type: str
    weight: float
    reason: str
    hop: int
```

模块 docstring 里的这句是本相位 `model.py` 必须复刻的约束声明范式（`types.py` L6–7）：

```6:8:server/services/retrieval/types.py
不导入任何 Django / codegraph 模块；该模块在 Django app loading 之前即可被
import（types 仅为纯 dataclass）。
```

→ `code_graph/model.py` 的对应声明应是：**不泄漏 networkx 具体类型到上层（为 rustworkx 留 adapter seam）**，并把 RESEARCH §Pitfall 10 的 `depth_limit` 纪律写进模块 docstring 传给 Phase 122。

#### (b) 字符串枚举（`EdgeConfidence` / `EdgeKind`）— `server/agents/call_source.py`

```39:44:server/agents/call_source.py
class CallSource(str, Enum):
    """LLM/AI 调用来源受控枚举（LOGGING-SPEC §4.1，44 值，权威照抄）。

    取值刻意收敛为有限集合：作为指标/筛选维度时基数可控；任意字符串经
    :meth:`normalize` 回退默认，杜绝外部输入污染 call_source 维度。
    """
```

`class X(str, Enum)` 是本仓非-ORM 受控枚举的既定写法（ORM 侧用 `models.TextChoices`，见 `server/repositories/models.py`）。`code_graph/model.py` 是 service 层契约、不落库 → 用 `(str, Enum)`。

#### (c) 异常层级 — `server/agents/core/exceptions.py`

```12:14:server/agents/core/exceptions.py
class AgentError(Exception):
    """Base exception for all agent-related errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
```

→ `GraphError` 基类 + `GraphAccessDenied` / `GraphNotIndexed` / `GraphBuildTimeout` 子类，同款「基类带 `details: dict | None`」形态。

---

### `server/services/code_graph/loader.py`（service, batch read → transform）

**Analog A（overlay 分支过滤 + 批量 ORM）:** `server/services/code_intel/local_provider.py`

overlay `branch_filter` 的**权威写法**（RESEARCH Pitfall 3 要求照抄）：

```54:66:server/services/code_intel/local_provider.py
        # base/overlay 合并：空 branch → 仅 base 行；非空 → base + 本分支合并。
        branch_filter = ["", branch_name] if branch_name else [""]

        all_symbols: list[Any] = []
        seen_ids: set[str] = set()

        for term in names:
            exact_matches: list[Any] = await sync_to_async(list)(  # type: ignore[call-arg]
                Symbol.objects.filter(
                    name__iexact=term, repository_id__in=repository_ids,
                    branch_name__in=branch_filter,
                ).select_related("repository"),
            )
```

lazy import ORM 模型的理由（`local_provider.py` L10–11，本相位 loader 同样适用）：

```10:11:server/services/code_intel/local_provider.py
实现走 lazy import：避免 ``services`` 包在 Django app loading 早期触发 ORM 模型导入。
```

⚠️ **偏离点（planner 必须显式记录）：** `local_provider` 用的是 `sync_to_async(list)(qs.select_related(...))`，返回**模型实例**。本相位 10 万级行数下**不能**照抄这一半——按 RESEARCH §Pattern 2 换成 `.values_list(...).iterator(chunk_size=5000)`，且 FK 用 attname（`caller_symbol_id`）。可照抄的是 `branch_filter` 表达式与 lazy import 结构，不是取数形态。

**Analog B（sync_to_async 边界）:** `server/services/chunk_lookup.py` —— public API 全 async，ORM 收进一个 `@sync_to_async` 私有函数：

```84:99:server/services/chunk_lookup.py
@sync_to_async
def _query_covering_chunks(
    repository_id: str, file_path: str, line: int, branch_name: str
) -> list[dict]:
    """同步 ORM 查询：命中覆盖 ``line`` 的 chunk row（经 sync_to_async 在异步上下文调用）。"""
    from code_relations.models import ChunkRegistry

    qs = ChunkRegistry.objects.filter(
        repository_id=repository_id,
        file_path=file_path,
        branch_name=branch_name,
        line_start__isnull=False,
        line_end__isnull=False,
        line_start__lte=line,
        line_end__gte=line,
    ).values("chunk_id", "file_path", "line_start", "line_end", "chunk_index")
```

⚠️ 本相位的差异：`chunk_lookup` 只包了 ORM 一段；本相位要把**锁 + ORM + networkx 装配整段**包进**一次** `sync_to_async`（RESEARCH §Threading Model），让「持锁」与「await」物理上不可能重叠。

---

### `server/services/code_graph/signature.py`（utility, batch aggregate read）

**Analog:** `server/codegraph/galaxy/cache.py`（`_SIGNATURE_SOURCES` L54–63 + `compute_signature` L87–104）

声明式源表清单 + 逐表 `COUNT + MAX(ts)` → 拼串 → SHA256：

```54:63:server/codegraph/galaxy/cache.py
# 签名源表：(label, model, repo 过滤字段, 时间戳字段)
_SIGNATURE_SOURCES: list[tuple[str, Any, str, str]] = [
    ("chunk_registry", ChunkRegistry, "repository_id", "updated_at"),
    ("chunk_edge", ChunkEdge, "repository_id", "created_at"),
    ("symbol", Symbol, "repository_id", "updated_at"),
    ("endpoint", Endpoint, "repository_id", "created_at"),
    ("api_wrapper", ApiWrapper, "repository_id", "created_at"),
    ("api_call_site", ApiCallSite, "repository_id", "created_at"),
    ("cross_repo_api_call", CrossRepoApiCall, "call_site__repository_id", "matched_at"),
]
```

```87:104:server/codegraph/galaxy/cache.py
    @staticmethod
    def compute_signature(repo_ids: list[uuid.UUID] | None) -> str:
        """计算 repo 集合的数据签名（每张源表 COUNT + MAX(时间戳)）。

        任何写入（新增/删除改变行数；rebuild 重写改变最新时间戳）都会使
        签名变化。代价：7 条带索引的聚合查询，与全量聚合相比可忽略。
        """
        parts: list[str] = []
        for label, model, repo_field, ts_field in _SIGNATURE_SOURCES:
            qs = model.objects.all()
            if repo_ids is not None:
                qs = qs.filter(**{f"{repo_field}__in": repo_ids})
            agg = qs.aggregate(_max_ts=Max(ts_field))
            count = qs.count()
            max_ts = agg["_max_ts"]
            parts.append(f"{label}:{count}:{max_ts.isoformat() if max_ts else '-'}")
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()
```

**照抄的是结构**（`parts: list[str]` → `"|".join` → `sha256().hexdigest()`，每个分量带 `label:` 前缀便于排障）。**分量清单不照抄**——本相位换成 RESEARCH §Code Examples 2 的五组分量（水位 / 轨 A `IndexHistory` / 轨 B `GraphBuildHistory` / 计数 / exclusion 指纹）。注意 `CrossRepoApiCall` 按仓过滤必须走 `call_site__repository_id`（上表最后一行就是先例）。

---

### `server/services/code_graph/cache.py`（service / store, request-response）

**Analog:** `server/codegraph/lsp/volar_pool.py` —— 「`OrderedDict` + `threading.Lock` + `move_to_end` + 超限逐出 + 逐出结构化事件 + 模块级单例工厂」的完整同构实现。

**事件名常量声明**（L42–47，本相位的 `code_graph_*` 事件照此声明为 `Final[str]`）：

```42:47:server/codegraph/lsp/volar_pool.py
_EVENT_POOL_GET: Final[str] = "volar_pool_get"
_EVENT_POOL_EVICTED: Final[str] = "volar_pool_evicted"
_EVENT_POOL_SHUTDOWN: Final[str] = "volar_pool_shutdown"
_EVENT_FALLBACK_VUE26: Final[str] = "volar_backend_fallback_vue26"
_EVENT_POOL_EVICT_STOP_ERROR: Final[str] = "volar_pool_evict_stop_error"
_EVENT_POOL_SHUTDOWN_ERROR: Final[str] = "volar_pool_shutdown_error"
```

**状态字段 + 锁**（L57–64）：

```57:64:server/codegraph/lsp/volar_pool.py
    def __init__(self, max_concurrent: int = 4) -> None:
        if max_concurrent <= 0:
            raise ValueError(
                f"max_concurrent 必须 > 0，收到 {max_concurrent}"
            )
        self._max_concurrent = max_concurrent
        self._pool: OrderedDict[Path, LspSupervisor] = OrderedDict()
        self._lock = threading.Lock()
```

**命中 → `move_to_end` + DEBUG；未命中 → 逐出 + INFO**（L102–141，本相位的 `code_graph_cache_hit` 用 DEBUG / `code_graph_cache_evicted` 用 INFO 的级别纪律与此完全一致）：

```102:131:server/codegraph/lsp/volar_pool.py
        normalized = sub_project_path.resolve()
        with self._lock:
            existing = self._pool.get(normalized)
            if existing is not None:
                self._pool.move_to_end(normalized)
                logger.debug(
                    _EVENT_POOL_GET,
                    sub_project_path=str(normalized),
                    result="hit",
                    pool_size=len(self._pool),
                )
                return existing

            if len(self._pool) >= self._max_concurrent:
                evicted_path, evicted_sup = self._pool.popitem(last=False)
                logger.info(
                    _EVENT_POOL_EVICTED,
                    evicted_sub_project=str(evicted_path),
                    new_sub_project=str(normalized),
                    pool_size_after=len(self._pool) + 1,
                )
                try:
                    evicted_sup.call_async_in_loop(evicted_sup.stop, timeout=5.0)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        _EVENT_POOL_EVICT_STOP_ERROR,
                        sub_project_path=str(evicted_path),
                        error_class=type(exc).__name__,
                        error=str(exc),
                    )
```

⚠️ 差异：volar_pool 按**条目数**（`>= max_concurrent`）逐出一次；本相位按**字节预算**循环逐出（`while self._total_bytes > self._max_bytes and self._cache:`），并用 `RLock` 而非 `Lock`（RESEARCH §Code Examples 4）。

**模块级单例工厂 + lazy settings 读取**（L192–204，本相位 `get_graph_service()` 照抄）：

```192:204:server/codegraph/lsp/volar_pool.py
_VOLAR_POOL: VolarPool | None = None
_SINGLETON_LOCK: Final[threading.Lock] = threading.Lock()


def get_volar_pool() -> VolarPool:
    """模块级单例（per work item）；lazy 实例化让 settings 加载顺序安全。"""
    global _VOLAR_POOL
    with _SINGLETON_LOCK:
        if _VOLAR_POOL is None:
            _VOLAR_POOL = VolarPool(
                max_concurrent=int(getattr(settings, "VOLAR_POOL_MAX_CONCURRENT", 4))
            )
        return _VOLAR_POOL
```

**测试重置钩子** — `volar_pool` 没有专门函数（测试直接改 `volar_pool._VOLAR_POOL = None`，见 test 分节）。更规范的先例是 `server/services/background_runner.py` L240–257，本相位应提供显式 `_reset_for_tests()`：

```240:253:server/services/background_runner.py
def _reset_for_tests() -> None:
    """测试钩子：停掉 worker 线程，清空状态，下次调用会重新拉起。

    严禁在生产代码里调用。
    """
    global _loop, _thread
    with _lock:
        loop = _loop
        thread = _thread
        _loop = None
        _thread = None
        _pending.clear()
        _named_futures.clear()
```

---

### `server/services/code_graph/access.py`（middleware / guard, request-response）

**Analog A（fail-closed exclusion 收口）:** `server/services/chunk_lookup.py` L50–74 —— 逐步 fail-closed 的完整范式，本相位 `access.py` 的收口逻辑与之同构：

```50:74:server/services/chunk_lookup.py
    # 1. 构造匹配器（fail-closed：构造失败一律视为排除，不放行）
    try:
        matcher = await build_matcher_for_repo(repository_id)
    except Exception as exc:  # noqa: BLE001 — 构造失败一律 fail-closed（T-25-04，对齐 rag_search）
        logger.warning(
            "chunk_lookup_matcher_build_failed",
            repository_id=repository_id,
            error=str(exc),
        )
        log_exclusion_blocked(
            surface="chunk_at", repository_id=repository_id, rel_path=str(file_path)
        )
        return []

    # 2. 路径归一（越界/绝对路径/非法 → None → 空返回，T-25-07）
    norm_path = normalize_rel_path(file_path)
    if norm_path is None:
        return []

    # 3. 排除判定（is_excluded 自身对判定异常 fail-closed 返回 True）
    if matcher.is_excluded(norm_path):
        log_exclusion_blocked(
            surface="chunk_at", repository_id=repository_id, rel_path=norm_path
        )
        return []
```

⚠️ **本相位的语义偏离（必须写进 plan）：** `chunk_lookup` 的 fail-closed 出口是**返回空列表**；本相位 CONTEXT 明确要求**抛 `GraphAccessDenied`**（空图会被上层误读为「没有影响」）。照抄的是「构造失败 → warning 埋点 + `log_exclusion_blocked` + 绝不放行」这三步结构，出口动作换成 raise。

**Analog B（exclusion 同步侧 API 与规则合并）:** `server/services/exclusion.py`

因为 loader 全同步，用同步的 `_resolve_effective_specs`（L271–305）而非 async 的 `build_matcher_for_repo`（L343–353）。规则集本身就是指纹的最佳来源：

```271:284:server/services/exclusion.py
def _resolve_effective_specs(repository_id: str) -> list[ExclusionRuleSpec]:
    """同步加载有效规则集合：builtin ∪ 全局设置 JSON ∪ per-repo，应用 global override。

    **排除判定的单一真相合并**：匹配器（``build_matcher_for_repo``）与容器下传序列化
    （``serialize_rules_for_repo``）共用本函数，避免两份合并逻辑漂移。

    经 ``sync_to_async`` 在异步上下文调用。``source="global" + enabled=False`` 的
    per-repo 行表示「关闭某条全局默认」的 override 标记，据此从全局集合剔除同 pattern 项。
    """
```

指纹要哈希的字段就是这个 frozen dataclass 的四个字段（L81–88）：

```81:88:server/services/exclusion.py
@dataclass(frozen=True)
class ExclusionRuleSpec:
    """单条排除规则的值对象（序列化形 = SystemSetting JSON 元素）。"""

    pattern: str
    rule_type: RuleType
    enabled: bool = True
    source: str = "user"
```

热路径 `is_excluded` 的 fail-closed 语义（L209–214, 230–236）——本相位按 `file_path` 去重后调用（符号数 >> 文件数）：

```209:214:server/services/exclusion.py
    def is_excluded(self, rel_path: str) -> bool:
        """判定相对路径是否命中任一规则。归一失败 / 运行期异常 → fail-closed（True）。"""
        try:
            norm = normalize_rel_path(rel_path)
            if norm is None:
                return True  # 归一越界 → fail-closed
```

```230:236:server/services/exclusion.py
        except Exception:  # noqa: BLE001 — 运行期任何异常都 fail-closed（T-22-01）
            log_exclusion_blocked(
                surface="exclusion_matcher",
                repository_id=self._repository_id,
                rel_path=str(rel_path),
            )
            return True
```

审计埋点复用（L370–377，`surface` 传 `"code_graph"`）：

```370:377:server/services/exclusion.py
def log_exclusion_blocked(*, surface: str, repository_id: str, rel_path: str) -> None:
    """结构化审计埋点：记录被排除规则拦截的访问（供后续审计里程碑复用）。"""
    logger.info(
        "exclusion.blocked",
        surface=surface,
        repository_id=repository_id,
        rel_path=rel_path,
    )
```

**Analog C（仓库可读性 + 索引态校验）:** `server/mcp_tools/views.py::_get_indexed_repo` L363–381 —— `ensure_repository_readable` 要复刻的正是这两道判定（`is_deleted=False` + `index_status == INDEXED`）：

```363:381:server/mcp_tools/views.py
    async def _get_indexed_repo(
        self,
        repository_id: str,
    ) -> tuple[Repository | None, Response | None]:
        try:
            repo = await Repository.objects.aget(id=repository_id, is_deleted=False)
        except Repository.DoesNotExist:
            return None, error_response(
                "repository_not_found",
                "仓库不存在",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        if repo.index_status != IndexStatus.INDEXED:
            return None, error_response(
                "repository_not_indexed",
                "仓库尚未建立索引",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return repo, None
```

⚠️ 出口形态换掉：`_get_indexed_repo` 返回 DRF `Response`（它在 view 层）；`access.py` 是 service 层、也会被后台任务/工作流调用（**没有 request 对象**），必须抛 `GraphNotIndexed` / `GraphAccessDenied`。ACL 扩展点的注释位置照抄 `server/repositories/permissions.py` L15–16：

```12:17:server/repositories/permissions.py
class RepositoryPermission(BasePermission):
    """校验 URL kwarg repository_id 对应的仓库存在且未被删除。

    配合 IsAuthenticated 使用，任意登录用户均可访问存在的仓库。
    未来若需要引入仓库级 ACL，在此处扩展 ownership 检查。
    """
```

---

### `server/friday/settings.py`（config，新增 `CODE_GRAPH_*` 两项）

**Analog:** 同文件 L858–879（Galaxy 缓存 + 图谱孤儿回收区块）——新配置项紧邻此块追加，命名沿用 `*_CACHE_*` / `*_MAX_*`：

```858:879:server/friday/settings.py
# Galaxy 图谱文件缓存（codegraph/galaxy/cache.py）。
# 全量聚合结果落盘 + 数据签名失效，把数秒的聚合请求降到毫秒级。
# GALAXY_CACHE_ENABLED=False 为逃生舱：直接走实时聚合。
GALAXY_CACHE_ENABLED: bool = env.bool("GALAXY_CACHE_ENABLED", default=True)
# 启动后是否在后台线程对比签名预热各仓库缓存
GALAXY_CACHE_WARM_ON_STARTUP: bool = env.bool(
    "GALAXY_CACHE_WARM_ON_STARTUP", default=True
)
GALAXY_CACHE_DIR = DATA_DIR / "galaxy_cache"

# 图谱构建孤儿行回收：后台构建任务（run_in_background）随进程内存存活，无法
# 跨进程重启幸存。服务进程启动时把"超过该阈值仍处于 RUNNING 的 GraphBuildHistory"
# 视为孤儿 → 标记 FAILED 并把对应 Repository.graph_build_status 由 RUNNING 归位
# FAILED，避免幽灵 RUNNING 行永久卡住「准备中」并挡住 rebuild（graph already running）。
# 设阈值（而非无脑回收所有 RUNNING）是为多 worker 部署留安全边界：刚被另一个
# worker 创建的 RUNNING 行不应被新启动 worker 误杀。设 0 关闭该回收。
GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP: bool = env.bool(
    "GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP", default=True
)
GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES: int = env.int(
    "GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES", default=30
)
```

**要点：** 显式类型注解（`: bool` / `: int`）+ `env.<type>("NAME", default=...)` + 每项上方多行中文注释说明「为什么是这个默认值」。`GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES`（L877–879）**直接复用**做 in-flight 超时判据，不新增配置项（RESEARCH Pitfall 5）。

---

### `server/pyproject.toml`（config，提升 networkx 为直接依赖）

**Analog:** 同文件 `[project].dependencies` L6–75 —— 分组注释 + 版本下界约束：

```34:44:server/pyproject.toml
    "qdrant-client>=1.9.0",
    "llama-index>=0.10.0",
    "llama-index-vector-stores-qdrant>=0.2.0",
    "tree-sitter>=0.21.0",
    "tree-sitter-go>=0.21.0",
    "tree-sitter-javascript>=0.21.0",
    "tree-sitter-python>=0.21.0",
    "tree-sitter-css>=0.21.0",
    "tree-sitter-html>=0.21.0",
    "tree-sitter-json>=0.21.0",
    "claude-agent-sdk>=0.1.58,<0.2",
```

上界约束带解释性注释的先例（L45–48）——`networkx>=3.6,<4` 也应带一行「为什么不锁死」的注释：

```45:48:server/pyproject.toml
    # claude-agent-sdk 只声明 mcp>=0.1.0，但它的 create_sdk_mcp_server 依赖
    # mcp 1.x lowlevel Server 的 @server.list_tools() 装饰器——mcp 2.0 已移除该 API。
    "mcp>=1.25.0,<2",
    "jinja2>=3.1.6,<4.0",
```

加依赖走 `cd server && uv add "networkx>=3.6,<4"`（会同步更新 `uv.lock`），不要手改 toml。

---

### 失效钩子（修改 `code_relations/tasks.py` L224–229 与 `graph_builder.py` L517–521）

两处已有 `GalaxyGraphCache.refresh_repo` 调用，紧邻加一行即可。**照抄注释形态**——两处注释都解释了「主动刷新只是优化，签名兜底才是正确性保证」，本相位的注释必须同样写明这一点（防后人误删签名校验）：

```224:229:server/code_relations/tasks.py
        # 边构建完成 → 主动刷新 Galaxy 文件缓存（refresh_repo 内部吞掉所有异常，
        # 失败时下次请求的签名对比仍会自动重建，不影响主流程）。
        if inserted > 0:
            from codegraph.galaxy.cache import GalaxyGraphCache

            await sync_to_async(GalaxyGraphCache.refresh_repo)(repository_id)
```

```517:521:server/services/graph_builder.py
        # 图谱构建完成 → 主动刷新 Galaxy 文件缓存（refresh_repo 内部吞掉所有
        # 异常，失败时下次请求的签名对比仍会自动重建，不影响主流程）。
        from codegraph.galaxy.cache import GalaxyGraphCache

        await sync_to_async(GalaxyGraphCache.refresh_repo)(repository_id)
```

**要点：** 函数内 lazy import（避免循环依赖）+ `await sync_to_async(...)` + 被调方内部吞异常。`GalaxyGraphCache.refresh_repo` 的「吞掉全部异常」实现（`galaxy/cache.py` L263–294）就是 `invalidate()` 该照抄的形态：

```263:272:server/codegraph/galaxy/cache.py
    @staticmethod
    def refresh_repo(repository_id: str | uuid.UUID) -> None:
        """仓库数据更新后主动刷新：清理含该仓库的过期缓存 + 重建单仓缓存。

        由图谱构建 / 边构建完成钩子调用。所有异常内部吞掉（缓存刷新失败
        不影响主流程，下次请求签名对比仍会自动重建）。
        """
        try:
            repo_uuid = uuid.UUID(str(repository_id))
            GalaxyGraphCache._evict_containing(repo_uuid)
```

⚠️ 本相位的 `invalidate()` 只**驱逐**、**不重建**（重建会在钩子线程上跑 2–4 秒 CPU）。

---

### `server/tests/services/code_graph/conftest.py`（test fixture）

**Analog:** `server/tests/codegraph/conftest.py` L23–58

```23:44:server/tests/codegraph/conftest.py
@pytest.fixture
def graph_repo(db):
    """创建测试用的 Repository。"""
    return Repository.objects.create(
        name="test-graph-repo",
        git_url="https://example.com/test-graph-repo.git",
        default_branch="main",
    )


@pytest.fixture
def seed_symbol(graph_repo):
    """创建种子 Symbol——被其他符号调用的中心函数。"""
    return Symbol.objects.create(
        repository=graph_repo,
        name="process_data",
        symbol_type="FUNCTION",
        file_path="src/core.py",
        start_line=10,
        end_line=25,
        signature="def process_data(input: dict) -> dict",
    )
```

🚨 **必须修改的两点（RESEARCH Pitfall 11）：**
1. 这些 fixture 在 `tests/services/code_graph/` **跨目录不可见**，必须在本目录 conftest 重建（不要写「复用既有 fixture」）。
2. `graph_repo` **没设 `index_status`**（默认 `NOT_INDEXED`），会被 `ensure_repository_readable` 在第一道闸拒掉。本相位的 `indexed_repo` fixture 必须显式 `index_status=IndexStatus.INDEXED`。

**autouse 单例重置 fixture** — 照抄 `test_volar_pool.py` L28–34：

```28:34:server/codegraph/lsp/tests/test_volar_pool.py
@pytest.fixture(autouse=True)
def _reset_volar_pool_singleton() -> None:
    """每测试前后重置模块级单例 + node_check 缓存，避免污染。"""
    volar_pool._VOLAR_POOL = None
    from codegraph.lsp import node_check

    node_check._CACHE = None
```

→ 本相位版本应调 `cache._reset_for_tests()` + `exclusion.invalidate_matcher_cache()`。

**目录 `__init__.py`：** `tests/services/retrieval/__init__.py` 存在、`tests/services/process_runtime/` 没有——两种都能跑，建议加（与 `tests/codegraph/` 一致）。

---

### `server/tests/services/code_graph/test_signature.py`（test）

**Analog:** `server/tests/codegraph/test_galaxy_cache.py` L55–91 —— 「稳定性 / 插入敏感 / 删除敏感 / 跨仓隔离」四件套，本相位的签名测试逐条对应（水位 / 两条边构建轨 / 计数 / exclusion 指纹）：

```55:91:server/tests/codegraph/test_galaxy_cache.py
@pytest.mark.django_db
class TestSignature(TestCase):
    """签名计算：稳定且对写入敏感。"""

    def test_signature_stable_without_changes(self) -> None:
        repo = make_repo()
        make_chunk(repo)
        sig_a = GalaxyGraphCache.compute_signature([repo.id])
        sig_b = GalaxyGraphCache.compute_signature([repo.id])
        assert sig_a == sig_b

    def test_signature_changes_on_insert(self) -> None:
        repo = make_repo()
        make_chunk(repo)
        sig_before = GalaxyGraphCache.compute_signature([repo.id])
        make_chunk(repo, idx=1)
        sig_after = GalaxyGraphCache.compute_signature([repo.id])
        assert sig_before != sig_after

    def test_signature_changes_on_delete(self) -> None:
        repo = make_repo()
        chunk = make_chunk(repo)
        make_chunk(repo, idx=1)
        sig_before = GalaxyGraphCache.compute_signature([repo.id])
        chunk.delete()
        sig_after = GalaxyGraphCache.compute_signature([repo.id])
        assert sig_before != sig_after

    def test_signature_scoped_to_repo(self) -> None:
        repo_a = make_repo("repo-a")
        repo_b = make_repo("repo-b")
        make_chunk(repo_a)
        sig_before = GalaxyGraphCache.compute_signature([repo_a.id])
        # 写入另一个仓库不影响 repo_a 的签名
        make_chunk(repo_b)
        sig_after = GalaxyGraphCache.compute_signature([repo_a.id])
        assert sig_before == sig_after
```

**「命中时不调用 builder」的断言写法**（L110–117，本相位测缓存命中照抄 `mock.patch.object(..., wraps=...)` + `spy.call_count == 0`）：

```110:117:server/tests/codegraph/test_galaxy_cache.py
        # 第二次：签名一致 → 命中，且不再调用全量聚合
        with mock.patch.object(
            GalaxyAggregator, "aggregate", wraps=GalaxyAggregator.aggregate
        ) as spy:
            result_hit = GalaxyGraphCache.aggregate_cached(repo_ids=[repo.id])
            assert spy.call_count == 0
        assert result_hit["meta"]["cache_hit"] is True
        assert {n["id"] for n in result_hit["nodes"]} == {n["id"] for n in result_miss["nodes"]}
```

配置项测试用 `override_settings`（L160–168）——本相位测 `CODE_GRAPH_MAX_GRAPH_BYTES` 降级路径同款：

```160:168:server/tests/codegraph/test_galaxy_cache.py
    def test_cache_disabled_passthrough(self) -> None:
        repo = make_repo()
        make_chunk(repo)
        with override_settings(GALAXY_CACHE_ENABLED=False):
            result = GalaxyGraphCache.aggregate_cached(repo_ids=[repo.id])
            assert result["meta"]["cache_hit"] is False
            assert len(result["nodes"]) == 1
            # 不落盘
            assert list(_cache_dir().glob("*.json")) == []
```

---

### `server/tests/services/code_graph/test_cache.py`（test：LRU / 逐出 / single-flight）

**Analog:** `server/codegraph/lsp/tests/test_volar_pool.py`

**LRU 顺序断言**（L99–114）：

```99:114:server/codegraph/lsp/tests/test_volar_pool.py
def test_get_move_to_end_on_hit(
    mock_node_check_available: None,
    supervisor_factory: list[MagicMock],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    """命中后 OrderedDict 顺序：访问 sub_a 后顺序变 [sub_b, sub_c, sub_a]。"""
    pool = VolarPool(max_concurrent=4)
    sub_a = tmp_path / "a"
    sub_b = tmp_path / "b"
    sub_c = tmp_path / "c"
    for sub in (sub_a, sub_b, sub_c):
        sub.mkdir()
        pool.get(sub, vue_version="2.7.14")
    pool.get(sub_a, vue_version="2.7.14")  # hit + move_to_end
    keys_in_order = list(pool._pool.keys())
    assert keys_in_order == [sub_b.resolve(), sub_c.resolve(), sub_a.resolve()]
```

**逐出断言**（L134–141）：

```134:141:server/codegraph/lsp/tests/test_volar_pool.py
    evicted_sup = supervisor_factory[0]  # sub_a
    evicted_sup.call_async_in_loop.assert_called_once()
    args, _kwargs = evicted_sup.call_async_in_loop.call_args
    assert args[0] is evicted_sup.stop

    assert subs[0].resolve() not in pool._pool
    assert sub_e.resolve() in pool._pool
    assert len(pool._pool) == 4
```

**single-flight 并发测试**（L233–260）——本仓唯一的确定性并发测试范式，`threading.Barrier(N)` + 断言 factory 只被调一次 + 所有返回 `is` 同一对象：

```233:260:server/codegraph/lsp/tests/test_volar_pool.py
def test_concurrent_get_no_double_build(
    mock_node_check_available: None,
    supervisor_factory: list[MagicMock],
    tmp_path: Path,
) -> None:
    """4 个 thread 同时 get(sub_a) → _build_supervisor 仅调一次（threading.Lock 守门）。"""
    pool = VolarPool(max_concurrent=4)
    sub = tmp_path / "race"
    sub.mkdir()
    barrier = threading.Barrier(4)
    results: list[object] = []
    lock = threading.Lock()

    def _worker() -> None:
        barrier.wait()
        sup = pool.get(sub, vue_version="2.7.14")
        with lock:
            results.append(sup)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert len(results) == 4
    assert all(r is results[0] for r in results)
    assert len(supervisor_factory) == 1
```

🚨 **关键差异（RESEARCH §并发用例的确定性写法）：** 这个用例**不碰数据库**。本相位若让 4 个线程同时打 SQLite 测试库必然 flaky——必须 patch builder 成纯内存假实现（`time.sleep(0.05)` + 调用计数），全程不碰 DB。`monkeypatch.setattr(VolarPool, "_build_supervisor", _build)`（L62–68）就是现成的 builder 参数化范式。

---

## Shared Patterns

### 1. structlog 事件三件套 + `duration_ms`

**Source:** `server/services/graph_builder.py`（logger L54；started L388–393；completed L524–537；failed L583–591）
**Apply to:** `cache.py` / `loader.py` / `access.py` 全部生命周期埋点

```388:393:server/services/graph_builder.py
    logger.info(
        "graph_build_started",
        repository_id=repository_id,
        trigger=trigger,
        history_id=str(history.id),
    )
```

```524:537:server/services/graph_builder.py
        logger.info(
            "graph_build_completed",
            repository_id=repository_id,
            trigger=trigger,
            history_id=str(history.id),
            duration_seconds=duration,
            files_total=files_total,
            files_processed=files_processed,
            files_failed=files_failed,
            symbols_count=symbols_count,
            imports_count=imports_count,
            calls_count=calls_count,
            endpoints_count=endpoints_count,
        )
```

```583:591:server/services/graph_builder.py
        logger.error(
            "graph_build_failed",
            repository_id=repository_id,
            trigger=trigger,
            history_id=str(history.id),
            duration_seconds=duration,
            error=str(exc),
            exc_info=True,
        )
```

**照抄的：** `logger = structlog.get_logger(__name__)`（`graph_builder.py:54`）、`time.perf_counter()` 计时、全 kv 字段、失败带 `error` + `error_type`。
**必须补的（本相位规范要求，`graph_builder` 尚未有）：** 每个事件加 `component="code_graph"` + `category="sampling"`；`duration_ms`（不是 `duration_seconds`）；异常文本过 `redact_secrets_in_text`；`initiated_by_user_id`（后台记 `"system"`）。
🚨 **命名冲突：** `graph_build_started/completed/failed` 已被本文件占用，`galaxy_cache_*` 已被 `galaxy/cache.py` 占用 —— 本相位必须保留完整 `code_graph_` 前缀，不得缩写。

### 2. 观测/缓存代码 best-effort，绝不反噬主流程

**Source:** `server/codegraph/galaxy/cache.py` L289–294
**Apply to:** `cache.py::invalidate` / 所有埋点 / 逐出路径

```289:294:server/codegraph/galaxy/cache.py
        except Exception as exc:
            logger.warning(
                "galaxy_cache_refresh_failed",
                repository_id=str(repository_id),
                error=str(exc),
            )
```

同款还有 `volar_pool.py` L166–171 的 shutdown 吞异常声明：

```166:171:server/codegraph/lsp/volar_pool.py
    def shutdown_all(self, timeout: float = 5.0) -> None:
        """串行 stop 全部 supervisor + 清池；吞所有异常防 atexit cascade。

        per Pitfall P-checkpoint：atexit 阶段 background loop 可能已停，
        每 supervisor.stop 单独 try/except + log warning。
        """
```

### 3. 模块导出契约（`__all__` + 模块 docstring 声明边界）

**Source:** `server/services/graph_builder.py` L45–51、`server/services/retrieval/types.py` L120–125、`server/codegraph/galaxy/cache.py` L355
**Apply to:** `code_graph/` 全部模块

```45:51:server/services/graph_builder.py
__all__ = [
    "GraphBuildResult",
    "build_graph_for_repository",
    "reset_repository_graph_progress",
    "mark_repository_graph_terminal",
    "prepare_repo_workdir_async",
]
```

每个模块顶部 `from __future__ import annotations`（本仓所有被读文件 100% 一致），模块 docstring 用中文、说明「问题背景 / 方案 / 边界」三段（`galaxy/cache.py` L1–26、`background_runner.py` L1–37、`exclusion.py` L1–13 都是此结构）。

### 4. `sync_to_async` 默认 `thread_sensitive=True`

**Source:** `server/services/graph_builder.py` L107；`server/code_relations/tasks.py` L229；`server/services/chunk_lookup.py` L84
**Apply to:** `cache.py` 的 async 外壳

```107:107:server/services/graph_builder.py
_acquire_repo_lock_async = sync_to_async(_acquire_repo_lock)
```

全仓 ORM 调用一致使用默认值（不传 `thread_sensitive`），本相位不应例外。`_acquire_repo_lock`（L87–104）还是「同步函数 + 模块级 `sync_to_async(...)` 别名」的写法先例，`cache.py` 的 `_get_graph_sync` 可照此暴露 async 外壳。

### 5. 锁 / 单例的 threading 原语

**Source:** `server/codegraph/lsp/volar_pool.py` L64, L193；`server/services/background_runner.py` L57
**Apply to:** `cache.py`

本仓 11 处模块级 `threading.Lock` 先例，`asyncio` 原语在多 loop 环境下不可用。planner 不需要论证这个选择，直接照抄结构。

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `.planning/observability/LOGGING-SPEC.md` §5 component 登记 | docs | — | 文档任务，无代码 analog。现有注册表只有 `codegraph`（无下划线，指索引/抽取侧 app）；本相位新增服务侧 `code_graph`。这是**强制规范要求的显式任务**，不是可选项。 |

**部分无 analog 的子能力**（有宿主 analog，但内部逻辑本仓首见，planner 的复杂度预算应压在这三处）：

| 子能力 | 宿主文件 | 为什么没有先例 |
|--------|----------|----------------|
| `MultiDiGraph` 装配 + 四档边契约 | `loader.py` | 本仓应用代码零 networkx 使用（仅 llama-index 传递依赖）。RESEARCH §Code Examples 1 的 ORM 查询形状是唯一参照。 |
| 字节预算准入 + 线性估算常数 | `cache.py` | volar_pool 按条目数、Galaxy 按文件，本仓无按字节的缓存。常数取 `NODE_COST=640 / EDGE_COST=560`（RESEARCH §Byte Estimation 实测标定），估算函数必须是可单测的纯函数。 |
| in-flight 边构建判定（两条轨 + 超时兜底） | `signature.py` 或 `cache.py` | Galaxy 只回答「数据变了吗」，不回答「边建完了吗」。RESEARCH §Code Examples 3 是唯一参照，且必须同时躲开 Pitfall 4（PENDING 长鸣）与 Pitfall 5（RUNNING 孤儿）。 |
| 跨仓边端点二次解析（file_path + name → Symbol） | `loader.py` | `CrossRepoApiCall` 两端无 Symbol FK（RESEARCH Pitfall 1）。本仓无同类解析代码。CONTEXT D-05 已裁决：解析失败**丢弃 + 计数上报**，不建虚拟节点。 |

---

## Metadata

**Analog search scope:** `server/services/`、`server/codegraph/`（含 `galaxy/`、`lsp/`）、`server/code_relations/`、`server/repositories/`、`server/mcp_tools/`、`server/agents/`、`server/tests/`
**Files read in full:** `codegraph/galaxy/cache.py`、`codegraph/lsp/volar_pool.py`、`services/chunk_lookup.py`、`services/exclusion.py`、`services/background_runner.py`、`services/code_intel/local_provider.py`、`services/code_intel/__init__.py`、`services/retrieval/types.py`、`repositories/permissions.py`、`tests/codegraph/test_galaxy_cache.py`、`codegraph/lsp/tests/test_volar_pool.py`
**Files read targeted:** `services/graph_builder.py`（L1–120, L380–593）、`friday/settings.py`（L796–895）、`pyproject.toml`（L1–75）、`code_relations/tasks.py`（L200–240）、`mcp_tools/views.py`（L355–390）、`tests/codegraph/conftest.py`（L1–90）、`agents/call_source.py`（L1–45）
**Pattern extraction date:** 2026-08-09
