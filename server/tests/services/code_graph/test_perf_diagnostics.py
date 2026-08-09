"""内存符号图的**一次性诊断交付物**（Phase 121，Plan 121-10）。

本文件不是回归测试，而是**出数用的**：两个用例各自回答一个 RESEARCH 明确留给本
相位的 Gap，结论回填进 ``121-10-SUMMARY.md``，并在源码注释里留痕。

- :func:`test_largest_repo_memory_calibration` —— 假设 A1/A2。用 tracemalloc 与
  RSS **双计量**测本仓最大仓（以及一张 100k/300k 的合成参照图）的真实常驻内存，
  与 ``cache.estimate_graph_bytes`` 的线性估算比对，据此复校
  ``NODE_COST_BYTES`` / ``EDGE_COST_BYTES``。
- :func:`test_callee_symbol_resolution_rate_survey` —— 假设 A5。统计每个已索引
  仓库的 ``callee_symbol`` 解析率分布，据此校准
  ``model.LOW_RESOLUTION_THRESHOLD``。

运行方式
========
``perf`` 标记在 ``pyproject.toml`` 的 ``addopts`` 里被默认排除，常规采样跑不到
这里（大图装配要几秒 + 几百 MB，进 CI 只会拖慢每一次提交）。手动运行::

    cd server && uv run pytest -m perf tests/services/code_graph/ -s

⚠️ 不加 ``-s`` 时 pytest 会吞掉 ``print``，用例通过了也看不到数据表。

为什么内存测量必须开子进程
==========================
pytest 进程已经 import 了 Django + langchain + llama-index 等一大票依赖，堆上留着
**几百 MB 已驻留但已释放**的空闲页。在这样的进程里建一张 167MB 的图，分配器直接
复用那些页，RSS 只涨 36MB —— 首轮实测正是如此（rss/tracemalloc = 0.215，一个物理
上不可能的比值）。RSS 增量在胖进程里是**下界**，而下界恰好是不安全的那个方向。

所以每次测量都 fork 一个干净的 ``sys.executable`` 子进程（:data:`_MEASURE_SCRIPT`，
零 Django、只 import networkx），在其中：

① **两趟测**：第一趟只量 RSS 与耗时，第二趟才开 tracemalloc —— tracemalloc 要为
   每次分配存 traceback，开着它量 RSS 得到的是「图 + tracemalloc 账本」。
② **行数据全程流式**（生成器 / sqlite 游标，与 ``loader`` 的 ``.iterator()`` 同形），
   不预先物化成 list：物化会在测量窗口里多出几十 MB 临时行，把 RSS 增量顶高。
③ **节点-only 与 full 各测一次**，据此把总量拆成「每节点成本」与「每边成本」——
   一个总数没法回答「该上调哪个常数」。

🚨 输出纪律（威胁登记 T-121-诊断数据泄密）：表里只有**仓库名、计数、比率与扩展名**
——⛔ 不打印 ``file_path`` 明细，不打印符号名。
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# 合成参照图的形态：与 RESEARCH §Byte Estimation 的标定点一致（100k 节点 / 300k 边，
# 边:节点 = 3:1），实测值可直接与那张表逐行对照。
_SYNTHETIC_NODES = 100_000
_SYNTHETIC_EDGES = 300_000

# ``rss_retained / tracemalloc_retained`` 超过该值即判定「tracemalloc 显著低估真实
# 常驻」，必须按比值上调字节常数（假设 A1 的闭环判据，见 plan Task 1 复校动作）。
_RSS_RECALIBRATION_TRIGGER = 1.15

_MB = 1024 * 1024
_SUBPROCESS_TIMEOUT_SECONDS = 900

# 按扩展名分桶的语言近似。⚠️ 本仓 ``CallEdge`` / ``Symbol`` **没有** language 字段，
# 这是用 ``caller_file`` 后缀做的近似，不是真实语言标注。
_LANGUAGE_EXTENSIONS = (".py", ".go", ".ts", ".tsx", ".js", ".vue")


# ---------------------------------------------------------------------------
# 子进程测量脚本（零 Django，只 import networkx）
# ---------------------------------------------------------------------------

_MEASURE_SCRIPT = r"""
import gc
import json
import os
import resource
import sqlite3
import subprocess
import sys
import time
import tracemalloc
import uuid


def _maxrss_bytes():
    # macOS/BSD 的 ru_maxrss 以**字节**计，Linux 以 **KB** 计；不换算两个平台差 1024 倍。
    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw if sys.platform == "darwin" else raw * 1024


def _rss_bytes():
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/self/statm") as handle:
                return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        except Exception:
            return None
    if sys.platform == "darwin":
        try:
            done = subprocess.run(
                ["ps", "-o", "rss=", "-p", str(os.getpid())],
                capture_output=True, text=True, timeout=15, check=True,
            )
            return int(done.stdout.strip()) * 1024
        except Exception:
            return None
    return None


def _synthetic_nodes(node_count):
    for index in range(node_count):
        yield (
            str(uuid.UUID(int=index)),
            "symbol_%d" % index,
            "FUNCTION",
            "src/pkg%d/module_%d.py" % (index % 500, index % 97),
            index % 900 + 1,
            index % 900 + 25,
        )


def _synthetic_edges(node_count, edge_count):
    for index in range(edge_count):
        yield (
            str(uuid.UUID(int=index % node_count)),
            str(uuid.UUID(int=(index * 7919 + 13) % node_count)),
            index % 900 + 1,
        )


def _sqlite_nodes(conn, repository_id):
    for row in conn.execute(
        "SELECT id, name, symbol_type, file_path, start_line, end_line "
        "FROM codegraph_symbol WHERE repository_id = ? AND branch_name = ''",
        (repository_id,),
    ):
        yield (str(row[0]), row[1], row[2], row[3], row[4], row[5])


def _sqlite_edges(conn, repository_id):
    for row in conn.execute(
        "SELECT caller_symbol_id, callee_symbol_id, line_number "
        "FROM codegraph_calledge WHERE repository_id = ? AND branch_name = '' "
        "AND caller_symbol_id IS NOT NULL AND callee_symbol_id IS NOT NULL",
        (repository_id,),
    ):
        yield (str(row[0]), str(row[1]), row[2])


def _assemble(spec, nx):
    conn = None
    if spec["kind"] == "sqlite":
        conn = sqlite3.connect("file:%s?mode=ro" % spec["db"], uri=True)
        node_iter = _sqlite_nodes(conn, spec["repo"])
        edge_iter = _sqlite_edges(conn, spec["repo"])
    else:
        node_iter = _synthetic_nodes(spec["nodes"])
        edge_iter = _synthetic_edges(spec["nodes"], spec["edges"])

    graph = nx.MultiDiGraph()
    started = time.perf_counter()
    for node_id, name, symbol_type, file_path, start_line, end_line in node_iter:
        graph.add_node(
            node_id, name=name, symbol_type=symbol_type,
            file_path=file_path, start_line=start_line, end_line=end_line,
        )
    nodes_done = time.perf_counter()
    edge_rows_seen = 0
    if spec["with_edges"]:
        for caller, callee, line_number in edge_iter:
            edge_rows_seen += 1
            # 与 loader 同口径：任一端点不在节点集内则整条边丢弃。
            if caller in graph and callee in graph:
                graph.add_edge(
                    caller, callee, kind="call", confidence="resolved",
                    line_number=line_number,
                )
    edges_done = time.perf_counter()
    if conn is not None:
        conn.close()
    return (
        graph,
        (nodes_done - started) * 1000,
        (edges_done - nodes_done) * 1000,
        edge_rows_seen,
    )


def main():
    spec = json.loads(sys.argv[1])
    import networkx as nx

    gc.collect()
    # 第一趟：RSS + 耗时（tracemalloc 关闭）。
    rss_before = _rss_bytes()
    maxrss_before = _maxrss_bytes()
    graph, add_nodes_ms, add_edges_ms, edge_rows_seen = _assemble(spec, nx)
    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()
    rss_after = _rss_bytes()
    maxrss_after = _maxrss_bytes()
    del graph
    gc.collect()

    # 第二趟：tracemalloc（retained，不是 peak —— 常数要标定的是图留下来的那部分）。
    tracemalloc.start(1)
    try:
        graph, _, _, _ = _assemble(spec, nx)
        traced_retained, traced_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    del graph
    gc.collect()

    json.dump(
        {
            "node_count": node_count,
            "edge_count": edge_count,
            "edge_rows_seen": edge_rows_seen,
            "traced_retained": traced_retained,
            "traced_peak": traced_peak,
            "rss_retained": (
                None if rss_before is None or rss_after is None
                else rss_after - rss_before
            ),
            "maxrss_delta": max(maxrss_after - maxrss_before, 0),
            "add_nodes_ms": add_nodes_ms,
            "add_edges_ms": add_edges_ms,
        },
        sys.stdout,
    )


main()
"""


def _measure(spec: dict[str, Any]) -> dict[str, Any]:
    """在干净子进程里测一张图，返回子进程吐出的 JSON。"""
    done = subprocess.run(
        [sys.executable, "-c", _MEASURE_SCRIPT, json.dumps(spec)],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        check=True,
    )
    return json.loads(done.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# 数据源探测（ORM → 只读 dev 库 → 合成）
# ---------------------------------------------------------------------------


def _dev_sqlite_path() -> Path | None:
    """本地开发库文件路径（存在才返回）。

    pytest 连的是**空的测试库**，真实索引数据在开发库里；诊断要的恰恰是真实数据，
    所以额外探这一级。⛔ 一律 ``mode=ro`` 打开，本文件不写任何一个字节。
    """
    from django.conf import settings

    candidate = Path(getattr(settings, "DATA_DIR", "")) / "friday.db"
    return candidate if candidate.is_file() else None


def _sqlite_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _orm_largest_repo() -> tuple[str, str, int] | None:
    """ORM 侧 ``Symbol`` 行数最多的仓库 ``(repository_id, name, symbol_count)``。

    真实部署里跑本文件时走这条；pytest 的空测试库上返回 ``None``，回落到只读 dev 库。
    """
    try:
        from django.db.models import Count

        from codegraph.models import Symbol
        from repositories.models import Repository

        top = (
            Symbol.objects.filter(branch_name="")
            .values("repository_id")
            .annotate(n=Count("id"))
            .order_by("-n")
            .first()
        )
        if not top or not top["n"]:
            return None
        name = (
            Repository.objects.filter(id=top["repository_id"])
            .values_list("name", flat=True)
            .first()
            or "<unknown>"
        )
        return str(top["repository_id"]), name, int(top["n"])
    except Exception:  # noqa: BLE001 — 空库 / 无 db fixture 都算「这一级没有数据」
        return None


def _sqlite_largest_repo(conn: sqlite3.Connection) -> tuple[str, str, int] | None:
    row = conn.execute(
        """
        SELECT s.repository_id, COALESCE(r.name, '<unknown>'), COUNT(*) AS n
        FROM codegraph_symbol s
        LEFT JOIN repositories r ON r.id = s.repository_id
        WHERE s.branch_name = ''
        GROUP BY s.repository_id
        ORDER BY n DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None or not row[2]:
        return None
    return str(row[0]), str(row[1]), int(row[2])


def _sqlite_raw_edge_count(path: Path, repository_id: str) -> int:
    """该仓 base 分支的**全部** ``CallEdge`` 行数（准入估算用的正是这个口径）。"""
    with _sqlite_ro(path) as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM codegraph_calledge "
                "WHERE repository_id = ? AND branch_name = ''",
                (repository_id,),
            ).fetchone()[0]
        )


# ---------------------------------------------------------------------------
# Task 1：最大仓内存实测与常数复校
# ---------------------------------------------------------------------------


def _decompose(nodes_only: dict[str, Any], full: dict[str, Any]) -> dict[str, float]:
    """从「节点-only」与「full」两次测量里拆出每节点 / 每边的实测字节成本。

    一个总数回答不了「该上调哪个常数」；两次测量的差值才把 node 与 edge 分开。
    """
    node_count = max(full["node_count"], 1)
    edge_count = max(full["edge_count"], 1)
    per_node = nodes_only["traced_retained"] / node_count
    per_edge = (full["traced_retained"] - nodes_only["traced_retained"]) / edge_count
    return {"per_node": per_node, "per_edge": per_edge}


def _ratio(numerator: float | None, denominator: float | None) -> float:
    if not numerator or not denominator:
        return float("nan")
    return numerator / denominator


@pytest.mark.perf
@pytest.mark.django_db
def test_largest_repo_memory_calibration() -> None:
    """最大仓内存实测（tracemalloc + RSS 双计量），驱动字节常数复校。

    断言宽松但非空：**估算值不得低于实测常驻的 90%**。估算是准入判据的唯一依据，
    显著低估意味着「够装」的判断放行了一张装不下的图——那就是 OOM 的形状
    （威胁登记 T-121-OOM）。断言红了不是用例坏了，是常数该上调了。
    """
    from services.code_graph.cache import (
        EDGE_COST_BYTES,
        NODE_COST_BYTES,
        estimate_graph_bytes,
    )

    datasets: list[tuple[str, dict[str, Any]]] = []
    notes: list[str] = []

    real = _orm_largest_repo()
    dev_db = None
    raw_edge_count: int | None = None
    if real is None:
        dev_db = _dev_sqlite_path()
        if dev_db is not None:
            with _sqlite_ro(dev_db) as conn:
                real = _sqlite_largest_repo(conn)
            if real is not None:
                raw_edge_count = _sqlite_raw_edge_count(dev_db, real[0])
                datasets.append(
                    (
                        f"real:{real[1]}",
                        {"kind": "sqlite", "db": str(dev_db), "repo": real[0]},
                    )
                )
    else:  # pragma: no cover — 只有真实部署库跑本文件时才走到
        from codegraph.models import CallEdge

        raw_edge_count = CallEdge.objects.filter(
            repository_id=real[0], branch_name=""
        ).count()
        notes.append(
            "ORM 侧探到真实数据，但本用例的测量在无 Django 的子进程内进行，"
            "ORM 数据源需要 sqlite 直连才能测；本次仅记录其计数，未做内存测量。"
        )

    if not datasets:
        notes.append(
            "未从只读 dev 库探测到含符号数据的真实仓库；真实仓一行属于"
            "「未测量」而非「测得为 0」，⛔ 不以合成数字冒充实测。"
        )

    datasets.append(
        (
            f"synthetic:{_SYNTHETIC_NODES // 1000}k/{_SYNTHETIC_EDGES // 1000}k",
            {"kind": "synthetic", "nodes": _SYNTHETIC_NODES, "edges": _SYNTHETIC_EDGES},
        )
    )

    results: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for label, spec in datasets:
        nodes_only = _measure({**spec, "with_edges": False})
        full = _measure({**spec, "with_edges": True})
        results.append((label, nodes_only, full))

    lines = [
        "",
        "### 121-10 Task 1：内存实测（干净子进程 / tracemalloc retained vs RSS retained）",
        "",
        f"平台 {sys.platform} / Python {sys.version.split()[0]} / "
        f"当前常数 NODE_COST_BYTES={NODE_COST_BYTES} EDGE_COST_BYTES={EDGE_COST_BYTES}",
        "",
        "| graph | nodes | edges | edge:node | tracemalloc MB | tm peak MB | rss MB | "
        "maxrss Δ MB | estimate MB | tm/est | rss/est | rss/tm | add_nodes ms | "
        "add_edges ms |",
        "|" + "---|" * 14,
    ]
    for label, _nodes_only, full in results:
        estimate = estimate_graph_bytes(full["node_count"], full["edge_count"])
        traced = full["traced_retained"]
        rss = full["rss_retained"]
        lines.append(
            f"| {label} | {full['node_count']:,} | {full['edge_count']:,} | "
            f"{full['edge_count'] / max(full['node_count'], 1):.2f} | "
            f"{traced / _MB:.2f} | {full['traced_peak'] / _MB:.2f} | "
            f"{(rss or 0) / _MB:.2f} | {full['maxrss_delta'] / _MB:.2f} | "
            f"{estimate / _MB:.2f} | {_ratio(traced, estimate):.3f} | "
            f"{_ratio(rss, estimate):.3f} | {_ratio(rss, traced):.3f} | "
            f"{full['add_nodes_ms']:.0f} | {full['add_edges_ms']:.0f} |"
        )

    lines.extend(
        [
            "",
            "**每节点 / 每边实测成本（由「节点-only」与「full」两次测量差分得到）**",
            "",
            "| graph | 实测 B/node | 当前 NODE_COST | 实测 B/edge | 当前 EDGE_COST |",
            "|---|---|---|---|---|",
        ]
    )
    for label, nodes_only, full in results:
        parts = _decompose(nodes_only, full)
        lines.append(
            f"| {label} | {parts['per_node']:.0f} | {NODE_COST_BYTES} | "
            f"{parts['per_edge']:.0f} | {EDGE_COST_BYTES} |"
        )

    if real is not None and raw_edge_count is not None:
        graph_edges = results[0][2]["edge_count"] if results[0][0].startswith("real") else 0
        graph_nodes = results[0][2]["node_count"] if results[0][0].startswith("real") else 1
        lines.extend(
            [
                "",
                "**假设 A2（边:节点 = 3:1）复校** —— 本仓两个口径的比值不同，两个都要记："
                f"准入估算口径（`CallEdge` 原始行数 / `Symbol` 行数）= "
                f"{raw_edge_count / max(real[2], 1):.2f}:1；"
                f"实际入图口径（解析边且两端都在节点集内）= "
                f"{graph_edges / max(graph_nodes, 1):.2f}:1。"
                "准入判据用的是**前者**，因此它对实际入图规模是**高估**（安全方向）。",
            ]
        )

    lines.extend(f"\n⚠️ {note}" for note in notes)

    reference = results[-1][2]
    rss_over_traced = _ratio(reference["rss_retained"], reference["traced_retained"])
    lines.extend(
        [
            "",
            f"**假设 A1（RSS > tracemalloc）**：合成参照图 rss/tracemalloc = "
            f"{rss_over_traced:.3f}（上调判据为 > {_RSS_RECALIBRATION_TRIGGER}）。",
            "",
        ]
    )
    print("\n".join(lines))

    # 断言：估算不得显著低估**实测常驻**（每一条测量都要过）。
    #
    # ⛔ 刻意**不**对 RSS 建同样的断言：小图上的 RSS 增量里混着 sqlite 的页缓存与
    #    分配器粒度（study-app 实测 rss 14.47MB vs tracemalloc 10.03MB，多出来的
    #    4.4MB 不是图占的），拿它当断言只会得到一个被无关开销驱动的红。RSS 的用途是
    #    ``rss/tracemalloc`` 比值这条**复校判据**（见上方 A1 输出），而该比值取自规模
    #    足够大、比值才稳定的合成参照图。
    for label, _nodes_only, full in results:
        estimate = estimate_graph_bytes(full["node_count"], full["edge_count"])
        traced = full["traced_retained"]
        assert estimate >= 0.9 * traced, (
            f"{label}：线性估算 {estimate / _MB:.2f}MB 低于实测常驻 "
            f"{traced / _MB:.2f}MB 的 90%，准入判据会放行装不下的图 —— "
            "上调 NODE_COST_BYTES / EDGE_COST_BYTES"
        )


# ---------------------------------------------------------------------------
# Task 2：callee_symbol 解析率统计与阈值校准
# ---------------------------------------------------------------------------


def _extension_of(caller_file: str | None) -> str:
    """``caller_file`` 的语言近似分桶。⚠️ 扩展名近似，不是真实语言标注。"""
    lowered = (caller_file or "").lower()
    for ext in _LANGUAGE_EXTENSIONS:
        if lowered.endswith(ext):
            return ext
    return "other"


def _resolution_rate(resolved: int, bare: int) -> float:
    """与 ``loader._CallEdgeStats.resolution_rate`` **逐字同口径**。

    ⛔ 不要在这里另写一套（比如把分母换成「入图的边数」）：口径一旦不同，这份统计
    就解释不了 loader 的行为，校准阈值也就无从谈起。分母为 0 时同样定义为 ``1.0``。
    """
    total = resolved + bare
    return 1.0 if total == 0 else resolved / total


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """线性插值分位数（与 ``numpy.percentile`` 默认口径一致）。"""
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (position - low) * (
        sorted_values[high] - sorted_values[low]
    )


def _sqlite_resolution_survey(
    path: Path,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    """只读 dev 库的 per-repo 与 per-extension 解析率统计。"""
    per_repo: list[dict[str, Any]] = []
    per_ext: dict[str, dict[str, int]] = {}
    with _sqlite_ro(path) as conn:
        indexed = conn.execute(
            "SELECT id, name FROM repositories WHERE index_status = 'indexed'"
        ).fetchall()
        for repository_id, name in indexed:
            symbols = int(
                conn.execute(
                    "SELECT COUNT(*) FROM codegraph_symbol "
                    "WHERE repository_id = ? AND branch_name = ''",
                    (repository_id,),
                ).fetchone()[0]
            )
            resolved, bare = 0, 0
            for caller_file, callee_symbol_id in conn.execute(
                "SELECT caller_file, callee_symbol_id FROM codegraph_calledge "
                "WHERE repository_id = ? AND branch_name = ''",
                (repository_id,),
            ):
                bucket = per_ext.setdefault(
                    _extension_of(caller_file), {"resolved": 0, "bare": 0}
                )
                if callee_symbol_id is None:
                    bare += 1
                    bucket["bare"] += 1
                else:
                    resolved += 1
                    bucket["resolved"] += 1
            if resolved + bare == 0:
                continue
            per_repo.append(
                {
                    "name": name or "<unknown>",
                    "symbols": symbols,
                    "resolved": resolved,
                    "bare": bare,
                    "rate": _resolution_rate(resolved, bare),
                }
            )
    per_repo.sort(key=lambda item: item["rate"])
    return per_repo, per_ext


@pytest.mark.perf
@pytest.mark.django_db
def test_callee_symbol_resolution_rate_survey(
    indexed_repo, symbols_factory, call_edges_factory
) -> None:
    """per repo / per extension 的 ``callee_symbol`` 解析率分布，校准低解析率阈值。

    先用合成数据把**统计口径**与 ``load_graph(...).meta.resolution_rate`` 交叉验证
    一次（口径对不上的话，后面那张真实分布表解释不了 loader 的任何行为），再去真实
    数据上出分布。
    """
    from services.code_graph.access import build_matcher_and_fingerprint
    from services.code_graph.loader import load_graph
    from services.code_graph.model import LOW_RESOLUTION_THRESHOLD

    # ── 口径交叉验证（合成数据，测试库内） ──────────────────────────────────
    caller = symbols_factory("caller", "src/a.py")
    targets = [
        symbols_factory(f"t{i}", "src/b.py", start_line=10 * i + 1, end_line=10 * i + 5)
        for i in range(3)
    ]
    for target in targets:
        call_edges_factory(caller, target)
    for i in range(7):
        call_edges_factory(caller, None, callee_name=f"bare{i}", callee_file="src/z.py")

    matcher, fingerprint = build_matcher_and_fingerprint(str(indexed_repo.id))
    meta = load_graph(
        str(indexed_repo.id), "", matcher=matcher, exclusion_fingerprint=fingerprint
    ).meta
    assert meta.resolution_rate == pytest.approx(_resolution_rate(3, 7), abs=1e-9), (
        "本用例的统计口径与 loader 的 resolution_rate 不一致，后面的分布表就解释不了 "
        "loader 的行为"
    )

    # ── 真实分布 ────────────────────────────────────────────────────────────
    dev_db = _dev_sqlite_path()
    if dev_db is None:
        pytest.skip(
            "无真实索引数据可统计（pytest 连的是空测试库，且未找到本地 dev 库 "
            "data/friday.db）。解析率分布的全部价值在真实数据，⛔ 不用合成数据顶替。"
        )

    per_repo, per_ext = _sqlite_resolution_survey(dev_db)
    if not per_repo:
        pytest.skip(
            f"本地 dev 库 {dev_db.name} 中没有任何含 CallEdge 的已索引仓库；"
            "⛔ 不编造分布数据。"
        )

    rates = sorted(item["rate"] for item in per_repo)
    p10, p50, p90 = (_percentile(rates, f) for f in (0.10, 0.50, 0.90))
    fired = sum(1 for rate in rates if rate < LOW_RESOLUTION_THRESHOLD)

    lines = [
        "",
        "### 121-10 Task 2：callee_symbol 解析率分布（只读 dev 库，base 分支）",
        "",
        "| repository | symbols | call_edges | resolved | bare_name | rate |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {item['name']} | {item['symbols']:,} | "
        f"{item['resolved'] + item['bare']:,} | {item['resolved']:,} | "
        f"{item['bare']:,} | {item['rate']:.4f} |"
        for item in per_repo
    )
    lines.extend(
        [
            "",
            "**per extension（⚠️ 按 `caller_file` 后缀近似，本仓无 language 字段）**",
            "",
            "| ext | call_edges | resolved | bare_name | rate |",
            "|---|---|---|---|---|",
        ]
    )
    lines.extend(
        f"| {ext} | {counts['resolved'] + counts['bare']:,} | {counts['resolved']:,} | "
        f"{counts['bare']:,} | "
        f"{_resolution_rate(counts['resolved'], counts['bare']):.4f} |"
        for ext, counts in sorted(
            per_ext.items(), key=lambda kv: -(kv[1]["resolved"] + kv[1]["bare"])
        )
    )
    lines.extend(
        [
            "",
            f"**分位数（n={len(rates)} 个已索引且有调用边的仓库）**："
            f"p10={p10:.4f} / p50={p50:.4f} / p90={p90:.4f}",
            f"当前 `LOW_RESOLUTION_THRESHOLD = {LOW_RESOLUTION_THRESHOLD}` 命中 "
            f"{fired}/{len(rates)} 个仓库。",
        ]
    )

    # 阈值判断建议（威胁登记 T-121-长鸣：永远触发与永不触发都等于信号失效）。
    if fired == len(rates):
        verdict = (
            "🔴 阈值**永远触发**：全部仓库都会被判 low_resolution，上层的「解析率偏低」"
            "声明会长鸣到被忽略。建议按本仓分布下调，让它只命中真正落后于本仓常态的仓，"
            "同时要求上层**始终**透出数值 resolution_rate（布尔量再准也表达不出 0.17 与 "
            "0.55 的差别）。"
        )
    elif fired == 0:
        verdict = (
            "🔴 阈值**永不触发**：没有任何仓库会被判 low_resolution，这个标记等于不存在。"
            "建议按本仓分布上调。"
        )
    else:
        verdict = (
            f"🟢 阈值有区分度：命中 {fired}/{len(rates)}，既不长鸣也非永不触发，"
            "维持当前取值。"
        )
    lines.extend(["", verdict, ""])
    print("\n".join(lines))

    # 断言宽松但非空：只守统计逻辑自洽，⛔ 不锁死任何一个具体分布数值
    # （分布随索引进度变化，锁死等于给自己埋一个必然失败的用例）。
    for item in per_repo:
        assert item["resolved"] + item["bare"] > 0
        assert 0.0 <= item["rate"] <= 1.0
        assert item["rate"] == pytest.approx(
            _resolution_rate(item["resolved"], item["bare"]), abs=1e-9
        )
    assert p10 <= p50 <= p90
