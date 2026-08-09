"""``services/code_graph/trace.py`` 的内核用例（覆盖 IMPACT-05）。

**本文件零数据库**：最短路、等长多解声明与「无路径」显式结构全部跑在 ``known_topology``
合成冻结图上（D-01）。⛔ 不得引入数据库标记——需要库的分支（重名候选要取
``Symbol.signature``）请放 ``test_symbol_resolve.py``。

骨架由 Wave 0（Plan 122-01）落位，三条用例由 122-04 填实，已无 skip 桩。
"""

from __future__ import annotations

from services.code_graph import EdgeConfidence, EdgeKind, derive_reason
from services.code_graph.trace import trace_path


def test_shortest_path_hops(known_topology) -> None:
    """最短路逐跳 ``file:line`` + ``kind`` + ``confidence`` 正确。

    三段断言各守一件事：

    ① 逐跳渲染逐字可核对。``from_file`` / ``from_line`` 取的是**符号定义处**，
       ``call_line`` 取的是**调用点**——两者语义不同，合成一个字段会让 agent 跳过去
       看到函数签名而不是那次调用，且它无从察觉自己看错了。
    ② **方向纪律**：图是有向的，``D → A`` 有解不等于 ``A → D`` 有解。反向必须落到
       显式的 ``no_path``，⛔ 不是异常、也不是空结构。
    ③ **``min_confidence`` 真的在过滤**：``X`` 的唯一出边是 ``bare_name`` 档
       （``known_topology`` 的 docstring 明令不许给它加别的出边），默认门槛下
       ``X → A`` 必须无解；把门槛降到 0.3 立刻有解。只测「默认有解」的话，一个
       根本没建视图的实现照样能过。

    （Req: IMPACT-05, 决策: D-18）
    """
    graph = known_topology

    result = trace_path(graph, "D", "A")
    assert result["found"] is True
    assert result["path"] == ["D", "C", "A"]
    assert len(result["hops"]) == 2

    first = result["hops"][0]
    assert first["from"] == "D"
    assert first["to"] == "C"
    # 定义处（节点属性）与调用点（边属性）是两个不同的行号。
    assert first["from_file"] == graph.nodes["D"]["file_path"]
    assert first["from_line"] == graph.nodes["D"]["start_line"]
    assert first["call_line"] == 41
    assert first["kind"] == "call"
    assert first["confidence"] == "resolved"
    # ⛔ 逐字相等而不是「包含关键字」：reason 现推（D-09），两处各拼一份必然漂移。
    assert first["reason"] == derive_reason(EdgeKind.CALL, EdgeConfidence.RESOLVED)

    # 全 resolved 的路径，path-min 就是 1.0（D-07 同口径）。
    assert result["path_confidence"] == 1.0

    assert trace_path(graph, "E", "A")["path"] == ["E", "B", "A"]

    # ② 反向不可达 —— 有向图的方向就是语义。
    reversed_result = trace_path(graph, "A", "D")
    assert reversed_result["found"] is False
    assert reversed_result["reason"] == "no_path"

    # ③ min_confidence 生效的正反两面。
    assert trace_path(graph, "C", "A", min_confidence=1.0)["path"] == ["C", "A"]
    assert trace_path(graph, "X", "A", min_confidence=1.0)["found"] is False
    relaxed = trace_path(graph, "X", "A", min_confidence=0.3)
    assert relaxed["found"] is True
    assert relaxed["path"] == ["X", "B", "A"]
    # 一条 bare_name + 一条 resolved ⇒ 弱边决定强度。
    assert relaxed["path_confidence"] == 0.3


def test_equal_length_paths_declared(known_topology) -> None:
    """多条等长路径时返回第一条 + ``equal_length_path_count``（D-18）。

    用 ``known_topology`` 的等长多解簇：``P → Q → S`` 与 ``P → R → S`` 两条等长最短路。
    ⛔ 不要拿 ``D → A`` 试——那条只有一条最短路，声明恒为 1，验证不了任何东西。

    三支各守一件事：多解要**声明条数**、单解要**闭嘴**（空串而不是「只有 1 条」的
    废话）、封顶后措辞要从「存在 N 条」切成「存在**至少** N 条」——后者是唯一能让
    agent 知道自己看到的计数不是全貌的信号。

    （Req: IMPACT-05, 决策: D-18）
    """
    graph = known_topology

    multi = trace_path(graph, "P", "S")
    assert multi["found"] is True
    assert len(multi["path"]) == 3
    # 返回的是确定性的「第一条」，两条候选都是合法答案。
    assert multi["path"] in (["P", "Q", "S"], ["P", "R", "S"])
    assert multi["equal_length_path_count"] == 2
    assert multi["equal_length_path_count_capped"] is False
    # ⛔ 只给数字不够：声明字段必须真的把条数说出来，否则渲染层容易整条漏掉。
    assert multi["alternatives_note"] != ""
    assert "2" in multi["alternatives_note"]

    single = trace_path(graph, "D", "A")
    assert single["equal_length_path_count"] == 1
    assert single["equal_length_path_count_capped"] is False
    assert single["alternatives_note"] == ""

    # 封顶分支：cap=1 时实际有 2 条，计数停在 1 且必须显式声明这是个下界。
    capped = trace_path(graph, "P", "S", alt_path_cap=1)
    assert capped["equal_length_path_count"] == 1
    assert capped["equal_length_path_count_capped"] is True
    assert "至少" in capped["alternatives_note"]


def test_no_path_explicit_structure(known_topology) -> None:
    """不可达 → 显式「无路径」结构（含两端解析结果与 ``min_confidence``），⛔ 不是空数组（D-20）。

    两个 ``found is False`` 的分支必须给出**不同**的 ``reason``：「这个符号根本不在图
    里」（参数问题 / 被 exclusion 挡掉）与「两端都在，但确实没有调用关系」（可据以
    决策的结论）是完全不同的两件事。把它们合并成同一个空结果，agent 就只能靠猜。

    （Req: IMPACT-05, 决策: D-20）
    """
    graph = known_topology

    # H 是孤立点：两端都在图里，但确实没有路径。
    result = trace_path(graph, "H", "A")
    assert result["found"] is False
    assert result["reason"] == "no_path"
    # ⛔ 不是空数组、也不是空 dict —— 这正是 D-20 要挡的那两种形态。
    assert result != []
    assert result != {}
    assert {"source", "target", "min_confidence"} <= set(result)
    assert result["source"]["in_graph"] is True
    assert result["source"]["symbol_id"] == "H"
    assert result["source"]["file_path"] == graph.nodes["H"]["file_path"]
    assert result["target"]["in_graph"] is True
    assert result["min_confidence"] == 1.0

    # 不存在的符号走另一个 reason，且描述块只回显调用方传进来的 id
    # （⛔ 不做模糊匹配，那会泄漏被排除文件里符号的存在性）。
    missing = trace_path(graph, "NOPE", "A")
    assert missing["found"] is False
    assert missing["reason"] == "node_not_in_graph"
    assert missing["source"]["in_graph"] is False
    assert missing["source"]["symbol_id"] == "NOPE"
    assert missing["source"]["file_path"] == ""
    assert missing["target"]["in_graph"] is True
    assert missing["min_confidence"] == 1.0
