"""Graph Expansion 测试共享 fixtures。

implementation（golden snapshot baseline）追加：
- `GOLDEN_QUERIES_REGISTRY`：20 条 parametrize 入口常量（per contract）
- `golden_mock_environment` fixture：确定性 mock 五个外部依赖（per contract）
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any, NamedTuple
from unittest.mock import patch

import pytest

from codegraph.models import CallEdge, Symbol
from codegraph.services.repo_router_v2 import RepoRouteCandidateV2, RepoRouteResultV2
from codegraph.services.repo_summaries_channel import RepoSummaryRouteResult as RepoRouteResult
from repositories.models import Repository


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


@pytest.fixture
def callee_symbol(graph_repo):
    """创建被调用者 Symbol——种子函数调用的函数。"""
    return Symbol.objects.create(
        repository=graph_repo,
        name="validate_input",
        symbol_type="FUNCTION",
        file_path="src/validators.py",
        start_line=5,
        end_line=15,
        signature="def validate_input(data: dict) -> bool",
    )


@pytest.fixture
def caller_symbol(graph_repo):
    """创建调用者 Symbol——调用种子函数的函数。"""
    return Symbol.objects.create(
        repository=graph_repo,
        name="handle_request",
        symbol_type="FUNCTION",
        file_path="src/handler.py",
        start_line=20,
        end_line=40,
        signature="def handle_request(req: Request) -> Response",
    )


@pytest.fixture
def outgoing_call_edge(seed_symbol, callee_symbol, graph_repo):
    """创建出边：seed -> callee。"""
    return CallEdge.objects.create(
        repository=graph_repo,
        caller_symbol=seed_symbol,
        callee_name="validate_input",
        call_type="DIRECT",
        line_number=15,
    )


@pytest.fixture
def incoming_call_edge(caller_symbol, seed_symbol, graph_repo):
    """创建入边：caller -> seed。"""
    return CallEdge.objects.create(
        repository=graph_repo,
        caller_symbol=caller_symbol,
        callee_name="process_data",
        call_type="DIRECT",
        line_number=30,
    )


@pytest.fixture
def second_hop_symbol(graph_repo):
    """创建 2-hop Symbol——被 callee 调用的函数。"""
    return Symbol.objects.create(
        repository=graph_repo,
        name="sanitize_string",
        symbol_type="FUNCTION",
        file_path="src/validators.py",
        start_line=20,
        end_line=28,
        signature="def sanitize_string(s: str) -> str",
    )


@pytest.fixture
def second_hop_edge(callee_symbol, second_hop_symbol, graph_repo):
    """创建 2-hop 出边：callee -> second_hop_symbol。"""
    return CallEdge.objects.create(
        repository=graph_repo,
        caller_symbol=callee_symbol,
        callee_name="sanitize_string",
        call_type="DIRECT",
        line_number=10,
    )


# --- RepoSummaryBuilder 测试 fixtures (implementation) ---


@pytest.fixture
def repo_for_summary(db):
    """创建带 ai_summary 的 Repository，用于 RepoSummaryBuilder 测试。"""
    from repositories.models import AISummaryStatus

    return Repository.objects.create(
        name="summary-test-repo",
        git_url="https://example.com/summary-test.git",
        default_branch="main",
        ai_summary="Test AI summary for repo",
        ai_summary_status=AISummaryStatus.COMPLETED,
    )


@pytest.fixture
def repo_symbols(repo_for_summary):
    """创建多层级 Symbol 用于摘要提取（超过 30 个以验证 Top-30 截断）。"""
    symbols = []
    for i in range(35):
        symbols.append(
            Symbol.objects.create(
                repository=repo_for_summary,
                name=f"func_{i}",
                symbol_type="FUNCTION",
                file_path=f"src/module_{i // 5}.py",
                start_line=i * 10,
                end_line=i * 10 + 5,
            )
        )
    return symbols


@pytest.fixture
def repo_endpoints(repo_for_summary):
    """创建 Endpoint 数据用于 api_domains 提取。"""
    from codegraph.models import Endpoint

    endpoints_data = [
        ("GET", "/api/users/", "get_users", "FUNCTION_VIEW", "src/views.py", 10),
        ("POST", "/api/users/", "create_user", "FUNCTION_VIEW", "src/views.py", 25),
        ("GET", "/api/tasks/", "get_tasks", "FUNCTION_VIEW", "src/tasks.py", 15),
        ("GET", "/admin/health/", "health_check", "FUNCTION_VIEW", "src/admin.py", 5),
    ]
    endpoints = []
    for method, path, handler, vtype, fpath, line in endpoints_data:
        endpoints.append(
            Endpoint.objects.create(
                repository=repo_for_summary,
                http_method=method,
                url_path=path,
                handler_name=handler,
                view_type=vtype,
                file_path=fpath,
                line_number=line,
            )
        )
    return endpoints


@pytest.fixture
def repo_file_indexes(repo_for_summary):
    """创建 FileIndex 记录用于 tech_stack 提取。"""
    import hashlib

    from repositories.models import FileIndex

    files = [
        "src/module_0.py",
        "src/module_1.py",
        "src/module_2.py",
        "src/utils.js",
        "src/types.ts",
        "src/styles.css",
    ]
    indexes = []
    for fp in files:
        indexes.append(
            FileIndex.objects.create(
                repository=repo_for_summary,
                file_path=fp,
                file_hash=hashlib.sha256(fp.encode()).hexdigest(),
            )
        )
    return indexes


# =============================================================================
# Golden Snapshot Baseline fixtures
#
# 锁定 LayeredSearchService.search() 的 final_context 现状行为，作为后续 RAG
# 解耦阶段的"零漂移"门禁（Pitfall 4 requirements §implementation Success Criteria #2）。
#
# 设计要点（per contract / contract / contract）：
# - 所有外部依赖（RepoRouter / Symbol ORM / BranchAwareSearch / Embedding /
#   SparseEncoder / GraphExpansion）全部 mock 成确定性返回值
# - 同一 query 多次执行 → final_context 字节一致
# - 不依赖真实 Qdrant / 真实 embedding model / 真实 DB（无 @django_db）
# =============================================================================


# 1024 维确定性 dense 向量（per contract）
GOLDEN_DENSE_VECTOR: tuple[float, ...] = (0.001,) * 1024

# 默认 sparse encoding
GOLDEN_SPARSE_OK: dict[str, Any] = {"indices": [1, 2, 3], "values": [0.5, 0.3, 0.2]}
GOLDEN_SPARSE_EMPTY: dict[str, Any] = {}


# 长 query（Q08 长 query 边界，约 200 全小写词，全部不触发 Pascal 提取）
GOLDEN_LONG_QUERY: str = " ".join(
    [
        "the system should gracefully handle very long natural language queries",
        "from end users especially when they describe complex scenarios that",
        "involve multiple components and interactions across services databases",
        "caches and message queues without losing important contextual signals",
        "during the embedding generation step or the downstream retrieval phase",
    ]
    * 8
)


@dataclass(frozen=True)
class GoldenQueryEntry:
    """单条 golden snapshot 查询参数（per contract / contract）。"""

    nn: str
    slug: str
    query: str
    repository_ids: tuple[str, ...] | None = None
    project_id: str | None = None
    branch_name: str | None = None
    max_tokens: int = 8000
    top_k: int = 30
    trigger_branch: str = ""


GOLDEN_QUERIES_REGISTRY: tuple[GoldenQueryEntry, ...] = (
    GoldenQueryEntry("01", "l1-single-repo", "find login handler", ("repo-a",), trigger_branch="L1 skipped, single repo, L2/L3"),
    GoldenQueryEntry("02", "l1-multi-repo", "user model", ("repo-a", "repo-b"), trigger_branch="L1 skipped, 跨仓 L3"),
    GoldenQueryEntry("03", "l1-auto-route", "authentication flow", None, trigger_branch="L1 status=ok 走 RepoRouter"),
    GoldenQueryEntry("04", "l2-bm25-keyword", "UserService", ("repo-a",), trigger_branch="L2 精确匹配 + L4 expand"),
    GoldenQueryEntry("05", "l2-bm25-typo", "Userservice", ("repo-a",), trigger_branch="L2 exact 0 → fuzzy icontains"),
    GoldenQueryEntry("06", "l2-bm25-cross-repo", "BaseModel", ("repo-a", "repo-b"), trigger_branch="L2 跨仓符号命中"),
    GoldenQueryEntry("07", "l3-dense-semantic", "how does the system handle errors", ("repo-a",), trigger_branch="L3 dense 主导，L2 skipped"),
    GoldenQueryEntry("08", "l3-dense-long-query", GOLDEN_LONG_QUERY, ("repo-a",), trigger_branch="L3 长 query 不超 token"),
    GoldenQueryEntry("09", "l3-dense-short-query", "db", ("repo-a",), trigger_branch="L3 短 query 边界"),
    GoldenQueryEntry("10", "l4-symbol-function", "ProcessData", ("repo-a",), trigger_branch="L4 expand 1-hop function"),
    GoldenQueryEntry("11", "l4-symbol-class", "OrderManager", ("repo-a",), trigger_branch="L4 expand class methods"),
    GoldenQueryEntry("12", "l4-symbol-cross-file", "ValidateInput", ("repo-a",), trigger_branch="L4 跨 file edges"),
    GoldenQueryEntry("13", "l5-expansion-1hop", "SeedAlpha", ("repo-a",), trigger_branch="L5 hop1 only 子预算"),
    GoldenQueryEntry("14", "l5-expansion-2hop", "SeedBeta", ("repo-a",), trigger_branch="L5 hop2 用 remaining budget"),
    GoldenQueryEntry("15", "l5-truncation", "GiantSeed", ("repo-a",), trigger_branch="L5 _trim_to_token_budget 截断"),
    GoldenQueryEntry("16", "edge-empty-result", "zzzzzz9999", ("repo-a",), trigger_branch="全 5 层 empty / skipped"),
    GoldenQueryEntry("17", "edge-token-overflow", "ProcessData", ("repo-a",), max_tokens=200, trigger_branch="整体裁剪到极小 budget"),
    GoldenQueryEntry("18", "edge-dedup", "DupSeed", ("repo-a",), trigger_branch="L3 seen_keys 去重 + L2/L3 file 去重"),
    GoldenQueryEntry("19", "edge-non-english", "用户登录处理", ("repo-a",), trigger_branch="L2 提取 0 符号，纯 L3"),
    GoldenQueryEntry("20", "edge-injection", "'; DROP TABLE users; --", ("repo-a",), trigger_branch="注入字符不破 query 解析"),
)


@dataclass(frozen=True)
class _GoldenRepoRef:
    """Symbol.repository 替身，仅暴露 `.name`。"""

    name: str


@dataclass(frozen=True)
class _GoldenSymbol:
    """Symbol 替身 dataclass（避免依赖 Django ORM）。

    暴露 LayeredSearchService 实际访问的属性集合：
    id / name / symbol_type / file_path / start_line / end_line / signature /
    repository_id / repository.name
    """

    id: str
    name: str
    symbol_type: str
    file_path: str
    start_line: int
    end_line: int
    signature: str
    repository_id: str
    repository: _GoldenRepoRef


def _sym(
    sid: str,
    name: str,
    symbol_type: str,
    file_path: str,
    start_line: int,
    end_line: int,
    signature: str,
    repo_id: str,
    repo_name: str,
) -> _GoldenSymbol:
    return _GoldenSymbol(
        id=sid,
        name=name,
        symbol_type=symbol_type,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        signature=signature,
        repository_id=repo_id,
        repository=_GoldenRepoRef(name=repo_name),
    )


# Symbol 数据库快照：name.lower() -> [_GoldenSymbol]
# 由 _golden_symbol_filter 用于 iexact / icontains 两种语义
GOLDEN_SYMBOL_DB: dict[str, list[_GoldenSymbol]] = {
    "userservice": [
        _sym("sym-user-service-a", "UserService", "CLASS",
             "src/users/service.py", 10, 80,
             "class UserService:", "repo-a", "alpha-repo"),
    ],
    "basemodel": [
        _sym("sym-basemodel-a", "BaseModel", "CLASS",
             "src/core/base.py", 5, 40,
             "class BaseModel:", "repo-a", "alpha-repo"),
        _sym("sym-basemodel-b", "BaseModel", "CLASS",
             "lib/core.py", 8, 50,
             "class BaseModel(object):", "repo-b", "beta-repo"),
    ],
    "processdata": [
        _sym("sym-process-data-a", "ProcessData", "FUNCTION",
             "src/pipeline/process.py", 12, 45,
             "def ProcessData(payload: dict) -> dict:",
             "repo-a", "alpha-repo"),
    ],
    "ordermanager": [
        _sym("sym-order-manager-a", "OrderManager", "CLASS",
             "src/orders/manager.py", 20, 120,
             "class OrderManager:", "repo-a", "alpha-repo"),
    ],
    "validateinput": [
        _sym("sym-validate-input-a", "ValidateInput", "FUNCTION",
             "src/validators/input.py", 5, 25,
             "def ValidateInput(data: Any) -> bool:",
             "repo-a", "alpha-repo"),
    ],
    "seedalpha": [
        _sym("sym-seed-alpha-a", "SeedAlpha", "FUNCTION",
             "src/seed/alpha.py", 1, 10,
             "def SeedAlpha() -> None:", "repo-a", "alpha-repo"),
    ],
    "seedbeta": [
        _sym("sym-seed-beta-a", "SeedBeta", "FUNCTION",
             "src/seed/beta.py", 1, 10,
             "def SeedBeta() -> None:", "repo-a", "alpha-repo"),
    ],
    "giantseed": [
        _sym("sym-giant-seed-a", "GiantSeed", "FUNCTION",
             "src/giant/seed.py", 1, 5,
             "def GiantSeed() -> None:", "repo-a", "alpha-repo"),
    ],
    "dupseed": [
        _sym("sym-dup-seed-a", "DupSeed", "FUNCTION",
             "src/dup/seed.py", 1, 5,
             "def DupSeed() -> None:", "repo-a", "alpha-repo"),
    ],
}


# L4 GraphExpansion 预置：seed.name -> {"nodes": [...], "edges": [...]}
# nodes 中的 symbol 直接复用 _GoldenSymbol 实例（保证 L5 渲染稳定）
def _node(symbol: _GoldenSymbol, depth: int, relationship: str) -> dict[str, Any]:
    return {"symbol": symbol, "depth": depth, "relationship": relationship}


# 为 L4 expand 构造若干"邻居" symbol
_NEIGH_PROCESS_HOP1_A = _sym(
    "sym-process-hop1-a", "validateInput", "FUNCTION",
    "src/pipeline/validators.py", 50, 70,
    "def validateInput(x): ...", "repo-a", "alpha-repo",
)
_NEIGH_PROCESS_HOP1_B = _sym(
    "sym-process-hop1-b", "writeResult", "FUNCTION",
    "src/pipeline/io.py", 12, 30,
    "def writeResult(r): ...", "repo-a", "alpha-repo",
)
_NEIGH_PROCESS_HOP2_A = _sym(
    "sym-process-hop2-a", "normalizePayload", "FUNCTION",
    "src/pipeline/validators.py", 80, 95,
    "def normalizePayload(x): ...", "repo-a", "alpha-repo",
)

_NEIGH_ORDER_METHOD1 = _sym(
    "sym-order-method-1", "create_order", "METHOD",
    "src/orders/manager.py", 50, 70,
    "def create_order(self, payload): ...", "repo-a", "alpha-repo",
)
_NEIGH_ORDER_METHOD2 = _sym(
    "sym-order-method-2", "cancel_order", "METHOD",
    "src/orders/manager.py", 80, 100,
    "def cancel_order(self, oid): ...", "repo-a", "alpha-repo",
)

_NEIGH_VALIDATE_X1 = _sym(
    "sym-validate-x1", "sanitize_string", "FUNCTION",
    "src/validators/sanitize.py", 5, 20,
    "def sanitize_string(s): ...", "repo-a", "alpha-repo",
)
_NEIGH_VALIDATE_X2 = _sym(
    "sym-validate-x2", "log_validation", "FUNCTION",
    "src/audit/log.py", 100, 110,
    "def log_validation(name): ...", "repo-a", "alpha-repo",
)
_NEIGH_VALIDATE_X3 = _sym(
    "sym-validate-x3", "format_error", "FUNCTION",
    "src/validators/errors.py", 20, 35,
    "def format_error(code): ...", "repo-a", "alpha-repo",
)

_NEIGH_USER_HOP1 = _sym(
    "sym-user-hop1", "get_by_id", "METHOD",
    "src/users/service.py", 90, 110,
    "def get_by_id(self, uid): ...", "repo-a", "alpha-repo",
)

# Q15 GiantSeed: 大量 hop1 + hop2 节点用于撑爆 token budget
_GIANT_HOP1: list[_GoldenSymbol] = [
    _sym(
        f"sym-giant-hop1-{i:02d}",
        f"giant_callee_{i:02d}",
        "FUNCTION",
        f"src/giant/callees/m_{i:02d}.py",
        i * 10 + 1,
        i * 10 + 20,
        f"def giant_callee_{i:02d}(payload): ...",
        "repo-a",
        "alpha-repo",
    )
    for i in range(40)
]


GOLDEN_L4_EXPAND: dict[str, dict[str, Any]] = {
    "UserService": {
        "nodes": [_node(_NEIGH_USER_HOP1, 1, "callee")],
        "edges": [{"source": "sym-user-service-a", "target": "sym-user-hop1", "call_type": "DIRECT"}],
    },
    "BaseModel": {
        "nodes": [],
        "edges": [],
    },
    "ProcessData": {
        "nodes": [
            _node(_NEIGH_PROCESS_HOP1_A, 1, "callee"),
            _node(_NEIGH_PROCESS_HOP1_B, 1, "callee"),
            _node(_NEIGH_PROCESS_HOP2_A, 2, "callee"),
        ],
        "edges": [
            {"source": "sym-process-data-a", "target": "sym-process-hop1-a", "call_type": "DIRECT"},
            {"source": "sym-process-data-a", "target": "sym-process-hop1-b", "call_type": "DIRECT"},
            {"source": "sym-process-hop1-a", "target": "sym-process-hop2-a", "call_type": "DIRECT"},
        ],
    },
    "OrderManager": {
        "nodes": [
            _node(_NEIGH_ORDER_METHOD1, 1, "method"),
            _node(_NEIGH_ORDER_METHOD2, 1, "method"),
        ],
        "edges": [],
    },
    "ValidateInput": {
        "nodes": [
            _node(_NEIGH_VALIDATE_X1, 1, "callee"),
            _node(_NEIGH_VALIDATE_X2, 1, "caller"),
            _node(_NEIGH_VALIDATE_X3, 2, "callee"),
        ],
        "edges": [],
    },
    "SeedAlpha": {
        "nodes": [
            _node(_NEIGH_PROCESS_HOP1_A, 1, "callee"),
        ],
        "edges": [],
    },
    "SeedBeta": {
        "nodes": [
            _node(_NEIGH_PROCESS_HOP1_A, 1, "callee"),
            _node(_NEIGH_PROCESS_HOP1_B, 1, "callee"),
            _node(_NEIGH_PROCESS_HOP2_A, 2, "callee"),
        ],
        "edges": [],
    },
    "GiantSeed": {
        "nodes": [_node(s, 1, "callee") for s in _GIANT_HOP1],
        "edges": [],
    },
    "DupSeed": {
        "nodes": [],
        "edges": [],
    },
}


# L3 BranchAwareSearchService 预置：(query, repo_id) -> [ {"score":..., "payload":{...}} ]
def _pl(
    file_path: str,
    content: str,
    chunk_index: int = 0,
    language: str = "python",
    start_line: int = 1,
    end_line: int = 20,
) -> dict[str, Any]:
    return {
        "file_path": file_path,
        "content": content,
        "language": language,
        "chunk_index": chunk_index,
        "start_line": start_line,
        "end_line": end_line,
    }


def _r(score: float, payload: dict[str, Any]) -> dict[str, Any]:
    return {"score": score, "payload": payload}


# Q15 GiantSeed: L3 也返回 30 条长 content 用于撑爆 L3_TOKEN_BUDGET=3000
_GIANT_CHUNK_CONTENT = "\n".join(
    [
        f"line {i:03d}: synthetic chunk content for token budget exhaustion testing"
        for i in range(60)
    ]
)


GOLDEN_L3_PAYLOADS: dict[tuple[str, str], list[dict[str, Any]]] = {
    ("find login handler", "repo-a"): [
        _r(0.82, _pl("src/auth/login.py", "def login(req):\n    return authenticate(req.user)", 0)),
        _r(0.71, _pl("src/auth/handlers.py", "class LoginHandler:\n    def post(self):\n        ...", 1)),
    ],
    ("user model", "repo-a"): [
        _r(0.78, _pl("src/users/models.py", "class User(BaseModel):\n    name = ...", 0)),
    ],
    ("user model", "repo-b"): [
        _r(0.74, _pl("lib/user.py", "class User:\n    pass", 0)),
    ],
    ("authentication flow", "repo-auto-1"): [
        _r(0.81, _pl("src/auth/flow.py", "def run_auth_flow():\n    pass", 0)),
    ],
    ("authentication flow", "repo-auto-2"): [
        _r(0.66, _pl("src/oauth/handler.py", "def oauth_callback():\n    ...", 0)),
    ],
    ("UserService", "repo-a"): [
        _r(0.92, _pl("src/users/service.py", "class UserService:\n    def list(self): ...", 0)),
        _r(0.71, _pl("src/users/api.py", "def list_users():\n    return UserService().list()", 0)),
    ],
    ("Userservice", "repo-a"): [
        _r(0.70, _pl("src/users/api.py", "def list_users():\n    return UserService().list()", 0)),
    ],
    ("BaseModel", "repo-a"): [
        _r(0.88, _pl("src/core/base.py", "class BaseModel:\n    pk = ...", 0)),
    ],
    ("BaseModel", "repo-b"): [
        _r(0.80, _pl("lib/core.py", "class BaseModel(object):\n    id = ...", 0)),
    ],
    ("how does the system handle errors", "repo-a"): [
        _r(0.83, _pl("src/errors/handler.py", "class ErrorHandler:\n    def handle(self): ...", 0)),
        _r(0.74, _pl("src/middleware/errors.py", "def error_middleware(req): ...", 0)),
    ],
    (GOLDEN_LONG_QUERY, "repo-a"): [
        _r(0.65, _pl("src/long/match.py", "def match_long_query():\n    pass", 0)),
    ],
    ("db", "repo-a"): [
        _r(0.55, _pl("src/db/conn.py", "def get_connection(): ...", 0)),
    ],
    ("ProcessData", "repo-a"): [
        _r(0.79, _pl("src/pipeline/process.py", "def ProcessData(payload):\n    ...", 0)),
        _r(0.68, _pl("src/pipeline/runner.py", "result = ProcessData(payload)", 0)),
    ],
    ("OrderManager", "repo-a"): [
        _r(0.85, _pl("src/orders/manager.py", "class OrderManager:\n    pass", 0)),
    ],
    ("ValidateInput", "repo-a"): [
        _r(0.81, _pl("src/validators/input.py", "def ValidateInput(data):\n    return True", 0)),
        _r(0.62, _pl("src/api/routes.py", "ValidateInput(payload)", 0)),
    ],
    ("SeedAlpha", "repo-a"): [
        _r(0.60, _pl("src/seed/alpha.py", "def SeedAlpha():\n    pass", 0)),
    ],
    ("SeedBeta", "repo-a"): [
        _r(0.60, _pl("src/seed/beta.py", "def SeedBeta():\n    pass", 0)),
    ],
    ("GiantSeed", "repo-a"): [
        _r(0.95 - i * 0.01, _pl(f"src/giant/chunk_{i:02d}.py", _GIANT_CHUNK_CONTENT, i))
        for i in range(30)
    ],
    ("zzzzzz9999", "repo-a"): [],
    # Q17 token overflow: 复用 ProcessData L3 数据
    ("DupSeed", "repo-a"): [
        _r(0.90, _pl("src/dup/seed.py", "def DupSeed():\n    return 1", 0)),
        _r(0.80, _pl("src/dup/seed.py", "def DupSeed():\n    return 1", 0)),  # 完全 dup → seen_keys 去重
        _r(0.75, _pl("src/dup/other.py", "callee()", 0)),
    ],
    ("用户登录处理", "repo-a"): [
        _r(0.72, _pl("src/auth/zh_login.py", "def login_cn():\n    pass", 0)),
    ],
    ("'; DROP TABLE users; --", "repo-a"): [
        _r(0.40, _pl("src/safety/escape.py", "def sanitize(q): ...", 0)),
    ],
}


# RepoRouter 路由表：query -> [RepoRouteResult]（per Q3 auto-route）
GOLDEN_ROUTE_TABLE: dict[str, list[RepoRouteResult]] = {
    "authentication flow": [
        RepoRouteResult(
            repo_id="repo-auto-1",
            repo_name="auto-repo-1",
            bm25_score=0.80,
            embedding_score=0.70,
            final_score=0.75,
            match_reason="matched: auth",
        ),
        RepoRouteResult(
            repo_id="repo-auto-2",
            repo_name="auto-repo-2",
            bm25_score=0.60,
            embedding_score=0.60,
            final_score=0.60,
            match_reason="matched: flow",
        ),
    ],
}


class _NoExclusionMatcher:
    """no-op 排除匹配器替身（golden 环境 = 无排除规则配置，永不命中）。"""

    def is_excluded(self, _rel_path: str) -> bool:
        return False


class _GoldenFakeQuerySet:
    """Symbol QuerySet 替身：支持 `.select_related(...)` 链与 list() 迭代/切片。"""

    __slots__ = ("_items",)

    def __init__(self, items: list[_GoldenSymbol]) -> None:
        self._items = list(items)

    def select_related(self, *_args: Any, **_kwargs: Any) -> "_GoldenFakeQuerySet":
        return self

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, slice):
            return _GoldenFakeQuerySet(self._items[key])
        return self._items[key]

    def __len__(self) -> int:
        return len(self._items)


class GoldenMockEnv(NamedTuple):
    """golden_mock_environment fixture 暴露的 mock 句柄集合。"""

    route_calls: list[tuple[str, int]]
    symbol_filter_calls: list[dict[str, Any]]
    symbol_get_calls: list[str]
    branch_search_calls: list[tuple[str, str]]
    embedding_calls: list[str]
    sparse_calls: list[str]
    expand_calls: list[str]


@contextlib.contextmanager
def golden_mock_environment_context():
    """`golden_mock_environment` fixture 的底层上下文管理器实现。

    抽出来是为了让 `_generate_golden_fixtures.py` 一次性脚本可以直接复用同一套
    确定性 mock，而无需走 pytest fixture 调用链。

    yields: GoldenMockEnv —— 与 fixture 同结构的 mock 句柄记录。
    """
    route_calls: list[tuple[str, int]] = []
    symbol_filter_calls: list[dict[str, Any]] = []
    symbol_get_calls: list[str] = []
    branch_search_calls: list[tuple[str, str]] = []
    embedding_calls: list[str] = []
    sparse_calls: list[str] = []
    expand_calls: list[str] = []

    current_query_state: dict[str, str] = {"value": ""}

    async def _golden_route(
        query: str, *, top_k: int = 3, use_llm: bool = False,
    ) -> RepoRouteResultV2:
        route_calls.append((query, top_k))
        return RepoRouteResultV2(
            candidates=[
                RepoRouteCandidateV2(
                    repo_id=item.repo_id,
                    repo_name=item.repo_name,
                    score=item.final_score,
                    confidence="medium",
                    reasoning=item.match_reason,
                )
                for item in list(GOLDEN_ROUTE_TABLE.get(query, []))
            ],
            router_version="v2_stage0_only",
            auto_selected=False,
            degraded=True,
        )

    def _golden_symbol_filter(**kwargs: Any) -> _GoldenFakeQuerySet:
        symbol_filter_calls.append(dict(kwargs))
        repo_ids = list(kwargs.get("repository_id__in", []) or [])
        if "name__iexact" in kwargs:
            term: str = kwargs["name__iexact"]
            candidates = GOLDEN_SYMBOL_DB.get(term.lower(), [])
            return _GoldenFakeQuerySet([s for s in candidates if s.repository_id in repo_ids])
        if "name__icontains" in kwargs:
            term = kwargs["name__icontains"]
            needle = term.lower()
            matched: list[_GoldenSymbol] = []
            for syms in GOLDEN_SYMBOL_DB.values():
                for s in syms:
                    if needle in s.name.lower() and s.repository_id in repo_ids:
                        matched.append(s)
            return _GoldenFakeQuerySet(matched)
        return _GoldenFakeQuerySet([])

    def _golden_symbol_get(*_args: Any, **kwargs: Any) -> _GoldenSymbol:
        sid = kwargs.get("id")
        symbol_get_calls.append(str(sid))
        for syms in GOLDEN_SYMBOL_DB.values():
            for s in syms:
                if s.id == sid:
                    return s
        raise Symbol.DoesNotExist(f"Symbol matching query {sid!r} does not exist.")

    async def _golden_embedding(query: str) -> list[float]:
        current_query_state["value"] = query
        embedding_calls.append(query)
        if not query:
            return []
        return list(GOLDEN_DENSE_VECTOR)

    def _golden_sparse(query: str) -> dict[str, Any]:
        sparse_calls.append(query)
        if not query.strip():
            return dict(GOLDEN_SPARSE_EMPTY)
        return dict(GOLDEN_SPARSE_OK)

    async def _golden_branch_search(
        repository_id: str,
        _query_dense: list[float],
        *,
        query_sparse: dict[str, Any] | None = None,
        branch_name: str | None = None,
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        q = current_query_state["value"]
        branch_search_calls.append((q, repository_id))
        results = GOLDEN_L3_PAYLOADS.get((q, repository_id), [])
        return [
            {"score": r["score"], "payload": dict(r["payload"])}
            for r in results
        ]

    async def _golden_expand(seed_symbol: Any, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        expand_calls.append(seed_symbol.name)
        result = GOLDEN_L4_EXPAND.get(seed_symbol.name, {"nodes": [], "edges": []})
        return {
            "nodes": [dict(n) for n in result["nodes"]],
            "edges": [dict(e) for e in result["edges"]],
        }

    # Phase 22 EXCL-02：search_rag / hybrid_search 现在经 build_matcher_for_repo 过滤被排除
    # 文件。golden 环境等价「无排除规则配置」——注入 no-op 匹配器，保证既有 byte-eq 不漂移
    # （golden fixtures 的 file_path 均为良性，本就不命中内置默认）。
    async def _golden_build_matcher(_repository_id: str) -> Any:
        return _NoExclusionMatcher()

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch(
            "codegraph.services.repo_router_v2.RepoRouterV2.route",
            new=_golden_route,
        ))
        stack.enter_context(patch.object(
            Symbol.objects, "filter", new=_golden_symbol_filter,
        ))
        stack.enter_context(patch.object(
            Symbol.objects, "get", new=_golden_symbol_get,
        ))
        stack.enter_context(patch(
            "services.branch_search.BranchAwareSearchService.search",
            new=_golden_branch_search,
        ))
        stack.enter_context(patch(
            "services.embedding.EmbeddingService.generate_embedding",
            new=_golden_embedding,
        ))
        stack.enter_context(patch(
            "services.sparse_encoder.SparseEncoderService.encode",
            new=_golden_sparse,
        ))
        stack.enter_context(patch(
            "codegraph.services.graph_expansion.GraphExpansionService.expand",
            new=_golden_expand,
        ))
        stack.enter_context(patch(
            "services.retrieval.rag_search.build_matcher_for_repo",
            new=_golden_build_matcher,
        ))
        stack.enter_context(patch(
            "services.retrieval.hybrid_search.build_matcher_for_repo",
            new=_golden_build_matcher,
        ))

        yield GoldenMockEnv(
            route_calls=route_calls,
            symbol_filter_calls=symbol_filter_calls,
            symbol_get_calls=symbol_get_calls,
            branch_search_calls=branch_search_calls,
            embedding_calls=embedding_calls,
            sparse_calls=sparse_calls,
            expand_calls=expand_calls,
        )


@pytest.fixture
def golden_mock_environment():
    """注入确定性 mock 五件套，让 LayeredSearchService.search() 输出字节稳定。

    per contract / implementation plan Task 1。同一 query 多次跑 final_context 一致。

    Patches:
      1. codegraph.services.repo_router_v2.RepoRouterV2.route
      2. codegraph.models.Symbol.objects.filter / .get
      3. services.branch_search.BranchAwareSearchService.search
      4. services.embedding.EmbeddingService.generate_embedding
      5. services.sparse_encoder.SparseEncoderService.encode
      6. codegraph.services.graph_expansion.GraphExpansionService.expand

    Yields:
      GoldenMockEnv —— mock 调用日志，供测试断言（路由次数 / 命中 repo 等）。
    """
    with golden_mock_environment_context() as env:
        yield env
