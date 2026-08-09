"""符号解析协议的用例（覆盖 D-19：uid 优先 + 重名返回候选列表）。

impact 与 trace **共用同一个解析器**，所以这条协议单独成文件而不是挂在任一内核旁边。
生产库符号重名率 **19.3%**（2,436 个名字对应 >20 个符号），候选列表是**主路径**而非异常
兜底——⛔ 绝不静默取第一个。

用例的数据库口径不同，刻意不给文件级 ``pytestmark``：图内解析的三条是零 DB 的纯协议
断言；``test_ambiguous_returns_candidates`` 要取 ``Symbol.signature``（TextField，不在图
节点属性里，只能回 ORM 补取），必须单独挂库标记。

⚠️ 重名用例**不能**用 ``known_topology``：那张图 13 个节点的 ``name`` 两两不同
（``node_id.lower()``），撞不出歧义；而给它加同名节点会扰动 122-03/04 的深度分组与最短路
断言。所以本文件就地造小图，每条用例自带最小拓扑。
"""

from __future__ import annotations

import networkx as nx
import pytest
from asgiref.sync import sync_to_async

from services.code_graph.symbol_resolve import (
    CANDIDATE_LIMIT,
    resolve_symbol_in_graph,
)
from services.code_graph_tools import CANDIDATE_SIGNATURE_MAX_CHARS


def _graph_with_names(
    entries: list[tuple[str, str, str, int]],
) -> nx.MultiDiGraph:
    """按 ``(symbol_id, name, file_path, start_line)`` 造一张只有节点的冻结图。

    节点属性个数照 Phase 121 的内存契约恒 5 个；⛔ 不加边——本文件断言的是解析协议，
    边与遍历无关，加边只会让「为什么这条用例要有边」变成下一个人的疑问。

    ``nx.freeze``：解析器只读，冻结后任何就地修改会当场抛 ``NetworkXError``，
    「解析不改图」由此成为构造性保证而非口头约定。
    """
    graph = nx.MultiDiGraph()
    for symbol_id, name, file_path, start_line in entries:
        graph.add_node(
            symbol_id,
            name=name,
            symbol_type="FUNCTION",
            file_path=file_path,
            start_line=start_line,
            end_line=start_line + 5,
        )
    nx.freeze(graph)
    return graph


def test_uid_takes_precedence(known_topology: nx.MultiDiGraph) -> None:
    """uid 优先：传 ``symbol_id`` 时不走候选路径。

    （Req: IMPACT-05, 决策: D-19）
    """
    # ① 图里有这个 uid ⇒ 一次命中，零候选。
    hit = resolve_symbol_in_graph(known_topology, symbol_id="A")
    assert hit.resolved == "A"
    assert hit.candidates == ()
    assert hit.total_candidates == 1
    assert hit.truncated is False

    # ② uid 不在图里 ⇒ 明确落空，⛔ 不退化去按名字搜。
    miss = resolve_symbol_in_graph(known_topology, symbol_id="no-such-uid")
    assert miss.resolved is None
    assert miss.candidates == ()
    assert miss.total_candidates == 0

    # ③ 关键的一条：**存在同名节点**时传 uid 也不许冒出候选。
    #    ②/③ 分开是有意的——只测 ② 的话，一个「uid 落空就回落到按 name 搜」的实现
    #    照样能通过（图里没有同名节点，回落也搜不到东西），D-19 的「uid 优先」就白写了。
    dupes = _graph_with_names(
        [
            ("uid-1", "handler", "internal/api/user.go", 10),
            ("uid-2", "handler", "internal/api/order.go", 20),
        ]
    )
    by_uid = resolve_symbol_in_graph(dupes, symbol_id="uid-2", name="handler")
    assert by_uid.resolved == "uid-2"
    assert by_uid.candidates == ()
    assert by_uid.total_candidates == 1


def test_ambiguous_never_silently_picks_first() -> None:
    """重名 ⇒ 返回候选列表并把选择权交回调用方，⛔ 绝不静默取第一个（D-19）。

    （Req: IMPACT-05, 决策: D-19）
    """
    # 插入序刻意与期望的排序结果相反：实现若直接吐 ``graph.nodes`` 的顺序，
    # 下面的 file_path 升序断言会当场红。
    graph = _graph_with_names(
        [
            ("uid-z", "handler", "internal/api/zebra.go", 300),
            ("uid-a", "handler", "internal/api/alpha.go", 100),
        ]
    )

    result = resolve_symbol_in_graph(graph, name="handler")

    assert result.resolved is None, "重名时给出 resolved 等于替调用方做了选择"
    assert result.total_candidates == 2
    assert result.truncated is False
    assert len(result.candidates) == 2

    # 按 (file_path, start_line) 升序稳定排序。
    assert [c.symbol_id for c in result.candidates] == ["uid-a", "uid-z"]
    assert [c.file_path for c in result.candidates] == [
        "internal/api/alpha.go",
        "internal/api/zebra.go",
    ]
    assert [c.start_line for c in result.candidates] == [100, 300]

    # D-19 要求的 file:line + symbol_type 逐条可用；``signature`` 在图内恒为空串
    # （``loader.py:354-356`` 不取 TextField），由壳层回 ORM 补取。
    assert all(c.symbol_type == "FUNCTION" for c in result.candidates)
    assert all(c.signature == "" for c in result.candidates)


def test_candidate_list_is_capped() -> None:
    """候选列表限条数，且截断后仍如实声明总数（D-19 / RESEARCH Pitfall 2 §2）。

    生产有 2,436 个名字对应 >20 个符号——截断是会被真实触发的路径。
    ``total_candidates`` 与 ``truncated`` 是 agent 判断「我看到的是不是全部」的唯一依据。

    （Req: IMPACT-05, 决策: D-19）
    """
    # 倒序插入，顺带守住「截断发生在排序之后」：先截断再排序的实现会留下 f05–f24，
    # 而不是下面断言的 f00–f19。
    graph = _graph_with_names(
        [(f"uid-{i:02d}", "widget", f"pkg/f{i:02d}.go", 10 * (i + 1)) for i in range(24, -1, -1)]
    )

    result = resolve_symbol_in_graph(graph, name="widget")

    assert result.resolved is None
    assert len(result.candidates) == CANDIDATE_LIMIT == 20
    assert result.total_candidates == 25
    assert result.truncated is True
    assert [c.symbol_id for c in result.candidates] == [f"uid-{i:02d}" for i in range(20)]


@pytest.mark.django_db(transaction=True)
async def test_ambiguous_returns_candidates(indexed_repo) -> None:
    """重名 → 候选列表（带 ``file:line``/``symbol_type``/``signature``），⛔ 绝不静默取第一个（D-19）。

    这条走 **ORM** 而不是图：``signature`` 是 TextField，``loader.py:354-356`` 刻意不把它
    取进图节点属性（节点恒 5 个），只能由壳层的 ``resolve_symbol_candidates`` 回 ORM 补取。

    （Req: IMPACT-05, 决策: D-19）
    """
    from services.code_graph_tools import (
        resolution_to_payload,
        resolve_symbol_candidates,
    )

    def _seed() -> None:
        from codegraph.models import Symbol

        # 插入序刻意与期望的排序结果相反。第三条的 signature 长 500 字符，用来验截断。
        rows = [
            ("internal/api/zebra.go", 300, "func handler(w http.ResponseWriter)"),
            ("internal/api/alpha.go", 100, "x" * 500),
            ("internal/api/mango.go", 200, "func handler(ctx context.Context) error"),
        ]
        for file_path, start_line, signature in rows:
            Symbol.objects.create(
                repository=indexed_repo,
                branch_name="",
                name="handler",
                symbol_type="FUNCTION",
                file_path=file_path,
                start_line=start_line,
                end_line=start_line + 5,
                signature=signature,
            )

    await sync_to_async(_seed)()
    repo_id = str(indexed_repo.id)

    result = await resolve_symbol_candidates(
        repository_id=repo_id, branch_names=[""], name="handler"
    )

    assert result.resolved is None, "重名时给出 resolved 等于替调用方做了选择"
    assert result.total_candidates == 3
    assert len(result.candidates) == 3
    assert result.truncated is False

    # 按 (file_path, start_line) 升序稳定排序。
    assert [c.file_path for c in result.candidates] == [
        "internal/api/alpha.go",
        "internal/api/mango.go",
        "internal/api/zebra.go",
    ]
    assert [c.start_line for c in result.candidates] == [100, 200, 300]
    assert all(c.symbol_type == "FUNCTION" for c in result.candidates)

    # D-19 要求的 signature 逐条非空（图内那一半恒为空串，这里必须已经补上）。
    assert all(c.signature for c in result.candidates)

    # 500 字符的那条被截到 200 + 省略号，⛔ 不把几 KB 的 TextField 原样吐给 agent。
    long_one = next(c for c in result.candidates if c.file_path.endswith("alpha.go"))
    assert len(long_one.signature) <= CANDIDATE_SIGNATURE_MAX_CHARS + 1
    assert long_one.signature.endswith("…")

    # 一次收敛：补上 file_path 就不再返回候选（Pitfall 2 §4——能一轮就不要两轮）。
    narrowed = await resolve_symbol_candidates(
        repository_id=repo_id,
        branch_names=[""],
        name="handler",
        file_path="internal/api/mango.go",
    )
    assert narrowed.resolved is not None
    assert narrowed.candidates == ()
    assert narrowed.total_candidates == 1

    # 壳层共用的 dict 形态：歧义时给出**可执行**的下一步，不是一句「不唯一」了事。
    payload = resolution_to_payload(result)
    assert payload["ambiguous"] is True
    assert payload["resolved"] is None
    assert len(payload["candidates"]) == 3
    assert payload["candidates"][0]["signature"]
    assert payload["hint"]
    assert resolution_to_payload(narrowed)["hint"] == ""
