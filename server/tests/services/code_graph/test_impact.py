"""``services/code_graph/impact.py`` 的内核用例（覆盖 IMPACT-01 / 02 / 04）。

**本文件零数据库**：全部断言跑在 ``known_topology`` / ``hub_topology`` 两个合成冻结图上，
不起 Django ORM、不建库（D-01 的全部意义所在——内核是纯函数，只吃 ``MultiDiGraph``）。
⛔ 后续 plan 往本文件加用例时也不得引入数据库标记，需要库的分支请放 ``test_impact_shell.py``。

Wave 0（Plan 122-01）先落地 fixture 自检这一条真用例；其余用例以 skip 桩占位，由
``122-RESEARCH.md`` §Validation Architecture 表点名的后续 plan 逐条填实。
"""

from __future__ import annotations

import networkx as nx
import pytest

from services.code_graph import EdgeConfidence, EdgeKind, derive_reason
from services.code_graph.impact import (
    DEFAULT_RESULT_LIMIT,
    RISK_THRESHOLDS,
    RiskLevel,
    analyze_impact,
    grade_risk,
)


def _ids(result: dict, depth: int) -> set[str]:
    """某一层的 ``symbol_id`` 集合。"""
    return {item["symbol_id"] for item in result["groups"][depth]}


def _all_ids(result: dict) -> set[str]:
    """全部返回条目的 ``symbol_id`` 集合（跨层）。"""
    return {item["symbol_id"] for item in result["items"]}


def _item(result: dict, symbol_id: str) -> dict:
    """按 ``symbol_id`` 取唯一一条结果（取不到即断言失败，比 ``next()`` 的 StopIteration 可读）。"""
    matches = [item for item in result["items"] if item["symbol_id"] == symbol_id]
    assert len(matches) == 1, f"{symbol_id} 应恰好出现一次，实际 {len(matches)} 次"
    return matches[0]


# 122-VALIDATION.md A1：Wave 0 地基自检。fixture 一旦退化（忘了 freeze、属性个数漂移、
# 少造了观察点），后面九个 plan 的断言会集体失去意义——所以这条必须先于它们绿。
def test_known_topology_fixture_is_frozen(known_topology: nx.MultiDiGraph) -> None:
    """合成图是冻结的 ``MultiDiGraph``，且节点/边属性个数与 Phase 121 的内存契约逐字一致。"""
    # 不冻结的话「内核不修改入参图」这条断言恒真（Phase 121 出图前也是这么冻的）。
    assert nx.is_frozen(known_topology) is True
    # DiGraph 会静默覆盖同一符号对的第二条边，四档边契约会直接失效。
    assert known_topology.is_multigraph() is True

    # A–H 八个 + 等长多解簇 P/Q/R/S 四个 + 只经裸名边可达的观察点 X。
    assert known_topology.number_of_nodes() == 13

    # 节点属性恒 5 个：signature 是 TextField、可长达数 KB，绝不放进节点属性。
    assert set(known_topology.nodes["A"]) == {
        "name",
        "symbol_type",
        "file_path",
        "start_line",
        "end_line",
    }

    # 边属性恒 3 个；cross_repo 档是唯一例外，多一个 match_confidence（原值，不归一化）。
    assert set(known_topology["F"]["A"][0]) == {
        "kind",
        "confidence",
        "line_number",
        "match_confidence",
    }
    assert set(known_topology["B"]["A"][0]) == {"kind", "confidence", "line_number"}


def test_depth_grouping(known_topology: nx.MultiDiGraph) -> None:
    """合成图上 d1/d2/d3 分组逐点正确；同符号多层出现取最浅；方向正确（下游不出现）。

    （Req: IMPACT-01, 决策: D-05）
    """
    strict = analyze_impact(known_topology, "A", min_confidence=1.0)

    # A 的直接调用方里，B / C 走 resolved 边（1.0），F 走 cross_repo(0.7) 被门槛挡掉。
    assert _ids(strict, 1) == {"B", "C"}
    # B 的上游 E；C 的上游 D。C→B 与 X→B 是 bare_name（0.3），进不来。
    assert _ids(strict, 2) == {"E", "D"}
    assert _ids(strict, 3) == set()
    assert "F" not in _all_ids(strict), "0.7 < 1.0 的跨仓边不该参与扩散"

    # 🚨 方向纪律：G 是 A 的**下游**（A --resolved--> G），反向影响面里永不出现。
    # 用最松的一组参数取样——两道闸全开、门槛降到 0 都不该把它放进来。
    loosest = analyze_impact(
        known_topology, "A", min_confidence=0.0, include_low_confidence=True
    )
    assert "G" not in _all_ids(loosest)
    # 顺带确认这组参数确实把闸开到了最大（否则上一条断言可能只是因为压根没走远）。
    assert {"B", "C", "F", "E", "D", "X"} == _all_ids(loosest)

    # 门槛降到 0.7：F 恰好达标，且它那条路径的 path_confidence 就是 0.7（path-min）。
    relaxed = analyze_impact(known_topology, "A", min_confidence=0.7)
    assert _ids(relaxed, 1) == {"B", "C", "F"}
    assert _item(relaxed, "F")["path_confidence"] == 0.7


def test_max_depth_budget(known_topology: nx.MultiDiGraph) -> None:
    """``max_depth`` 生效；超深节点不出现。

    （Req: IMPACT-01, 决策: D-05）
    """
    depth1 = analyze_impact(known_topology, "A", max_depth=1)
    assert set(depth1["groups"]) == {1}
    assert _all_ids(depth1) == {"B", "C"}
    assert "D" not in _all_ids(depth1)

    depth2 = analyze_impact(known_topology, "A", max_depth=2)
    assert "D" in _ids(depth2, 2)

    # C 同时是 A 的 d1（C --resolved--> A）与 d2（C --bare_name--> B --> A）。
    # 无论层预算给多少，它恒在 d1 —— 最浅优先（最坏情况优先）。
    for max_depth in (1, 2, 3, 5):
        result = analyze_impact(
            known_topology,
            "A",
            max_depth=max_depth,
            min_confidence=0.0,
            include_low_confidence=True,
        )
        assert "C" in _ids(result, 1), f"max_depth={max_depth} 时 C 不在 d1"


def test_kernel_does_not_mutate_graph(known_topology: nx.MultiDiGraph) -> None:
    """内核不修改入参图（fixture 已 ``freeze``，就地改必抛）。

    （Req: IMPACT-01, 决策: D-01）
    """
    nodes_before = known_topology.number_of_nodes()
    edges_before = known_topology.number_of_edges()

    # 覆盖会走到各条分支的参数组合：截断、层预算、双闸、遍历软上限。
    for kwargs in (
        {},
        {"min_confidence": 0.0, "include_low_confidence": True},
        {"max_depth": 1},
        {"limit": 1},
        {"max_nodes": 2},
        {"exclude_test_files": True},
    ):
        analyze_impact(known_topology, "A", **kwargs)  # 就地改写会抛 NetworkXError

    assert known_topology.number_of_nodes() == nodes_before
    assert known_topology.number_of_edges() == edges_before
    assert nx.is_frozen(known_topology) is True


def test_edge_confidence_and_reason(known_topology: nx.MultiDiGraph) -> None:
    """每条结果带 ``confidence`` 档 + ``reason``（经 ``derive_reason``）+ ``path_confidence``
    （= path min，D-07）。

    （Req: IMPACT-02, 决策: D-06 / D-07 / D-09）
    """
    result = analyze_impact(
        known_topology, "A", min_confidence=0.0, include_low_confidence=True
    )
    assert _all_ids(result), "样本为空的话下面的逐条断言等于没写"

    for item in result["items"]:
        via = item["via"]
        attrs = known_topology[via["from"]][via["to"]][0]
        # 档位与种类取边属性**原值**，不被折算成数值、不被归一化。
        assert via["confidence"] == attrs["confidence"]
        assert via["kind"] == attrs["kind"]
        assert via["line_number"] == attrs["line_number"]
        # reason 现推不存（D-09）：与直接调 derive_reason 的返回逐字相等。
        assert via["reason"] == derive_reason(
            EdgeKind(attrs["kind"]),
            EdgeConfidence(attrs["confidence"]),
            callee_name=known_topology.nodes[via["to"]]["name"],
            match_confidence=attrs.get("match_confidence"),
        )
        assert 0.0 <= item["path_confidence"] <= 1.0

    # cross_repo 档的 reason 必须带上 match_confidence 原值，agent 才有的核对。
    assert "0.7" in _item(result, "F")["via"]["reason"]

    # path-min（D-07）：X 经 bare_name(0.3) 到 B，再经 resolved(1.0) 到 A ⇒ 取最小值 0.3。
    # ⛔ 平均会是 0.65、乘积会是 0.3 —— 用平均的实现会在这里红。
    assert _item(result, "X")["path_confidence"] == 0.3
    assert _item(result, "B")["path_confidence"] == 1.0


def test_min_confidence_filter(known_topology: nx.MultiDiGraph) -> None:
    """``min_confidence`` 各阈值下结果集单调收缩；``cross_repo`` 用 ``match_confidence``
    原值参与比较（不归一化）。

    ⚠️ 四档阈值走**表内循环**而不是 ``parametrize``：它们断言的是「后一档是前一档的子集」
    这条**跨档**性质，拆成四个独立节点就没法比了。

    （Req: IMPACT-02, 决策: D-06 / D-13）
    """
    previous: set[str] | None = None
    for min_confidence in (0.0, 0.3, 0.7, 1.0):
        current = _all_ids(
            analyze_impact(
                known_topology,
                "A",
                min_confidence=min_confidence,
                include_low_confidence=True,
            )
        )
        if previous is not None:
            assert current <= previous, (
                f"min_confidence={min_confidence} 的结果不是上一档的子集，"
                f"单调收缩被破坏：{current - previous}"
            )
        previous = current

    # F 的那条边是 cross_repo(match_confidence=0.7)。0.7 恰好达标、0.71 就被挡掉
    # —— 证明参与比较的是 match_confidence **原值**，而不是被归一化成某个档位常量
    # （若被归一化成 1.0，0.71 那档 F 还在；若被抹成 0.3，0.7 那档 F 就已经不在了）。
    at_070 = analyze_impact(known_topology, "A", min_confidence=0.7)
    assert "F" in _all_ids(at_070)
    assert _item(at_070, "F")["path_confidence"] == 0.7

    at_071 = analyze_impact(known_topology, "A", min_confidence=0.71)
    assert "F" not in _all_ids(at_071)


def test_bare_name_requires_both_gates(known_topology: nx.MultiDiGraph) -> None:
    """**D-08 双闸**：单开 ``include_low_confidence`` 或单降 ``min_confidence`` 都不足以让
    bare_name 边参与扩散。

    观察点用 ``known_topology`` 的 ``X``——它只有 ``X --bare_name--> B`` 一条出边，两道闸
    没同时开时它必须缺席。⛔ 不要改用 ``C``：``C`` 还有 ``C --resolved--> A``，用它会让本条
    用例恒真。

    （Req: IMPACT-02, 决策: D-08）
    """
    from services.code_graph.impact import _bare_name_allowed

    cases = [
        # (include_low_confidence, min_confidence, X 是否应当出现)
        (False, 0.3, False),  # 装配口径关着：图里本就不该有这一档边
        (True, 1.0, False),   # 查询口径卡在最高档：调用方要的是只看强证据
        (False, 1.0, False),  # 两道都关
        (True, 0.3, True),    # 两道同时开 —— 唯一放行的组合
    ]
    for include_low_confidence, min_confidence, expected in cases:
        result = analyze_impact(
            known_topology,
            "A",
            min_confidence=min_confidence,
            include_low_confidence=include_low_confidence,
        )
        present = "X" in _all_ids(result)
        assert present is expected, (
            f"include_low_confidence={include_low_confidence} / "
            f"min_confidence={min_confidence} 时 X 的在场情况应为 {expected}"
        )
        # 谓词本身与 analyze_impact 的实际行为必须一致，且被如实透出。
        assert result["bare_name_included"] is _bare_name_allowed(
            include_low_confidence=include_low_confidence,
            min_confidence=min_confidence,
        )

    # 谓词可独立单测（它是 D-08 的唯一判据，不该只能经 analyze_impact 间接观察）。
    assert _bare_name_allowed(include_low_confidence=True, min_confidence=0.3) is True
    assert _bare_name_allowed(include_low_confidence=True, min_confidence=0.31) is False
    assert _bare_name_allowed(include_low_confidence=False, min_confidence=0.0) is False


def test_risk_levels() -> None:
    """四级风险分级在阈值边界（d1 = 2/3/7/8/19/20 与穿仓组合）上逐点正确。

    ⚠️ 走**表内循环**而不是 ``parametrize``：本文件的节点数是 122-01 定下的验收口径
    （9 passed / 1 skipped），参数化会把它撑成几十个节点。

    （Req: IMPACT-04, 决策: D-15 / D-29）
    """
    from services.code_graph.impact import _CONFIDENCE_TIER_RANK

    resolved_tier = _CONFIDENCE_TIER_RANK[EdgeConfidence.RESOLVED]

    # (d1_count, crosses_repo) -> 期望等级。best_path_tier 取 RESOLVED 档，不触发封顶。
    expected = {
        (2, False): RiskLevel.LOW,
        (3, False): RiskLevel.MEDIUM,
        (7, False): RiskLevel.MEDIUM,
        (8, False): RiskLevel.HIGH,
        (19, False): RiskLevel.HIGH,
        (20, False): RiskLevel.CRITICAL,
        (2, True): RiskLevel.HIGH,
        (3, True): RiskLevel.HIGH,
        (7, True): RiskLevel.CRITICAL,
        (8, True): RiskLevel.CRITICAL,
        (19, True): RiskLevel.CRITICAL,
        (20, True): RiskLevel.CRITICAL,
    }
    for (d1_count, crosses_repo), level in expected.items():
        assert (
            grade_risk(
                d1_count=d1_count,
                crosses_repo=crosses_repo,
                best_path_tier=resolved_tier,
            )
            is level
        ), f"d1={d1_count} crosses_repo={crosses_repo} 的等级不是 {level}"

    # D-29 封顶：全路径最高档只到 bare_name 时，再大的 d1、再加穿仓也只能是 MEDIUM。
    assert (
        grade_risk(
            d1_count=50,
            crosses_repo=True,
            best_path_tier=_CONFIDENCE_TIER_RANK[EdgeConfidence.BARE_NAME],
        )
        is RiskLevel.MEDIUM
    )
    # 把档位提到 cross_repo，同样的输入立刻回到 CRITICAL —— 证明封顶规则真的在起作用，
    # 而不是那条分支恒假、MEDIUM 只是碰巧从阈值表里掉出来的。
    assert (
        grade_risk(
            d1_count=50,
            crosses_repo=True,
            best_path_tier=_CONFIDENCE_TIER_RANK[EdgeConfidence.CROSS_REPO],
        )
        is RiskLevel.CRITICAL
    )
    # 封顶只降不升：弱证据是压低结论的理由，不是抬高结论的理由。
    assert (
        grade_risk(
            d1_count=0,
            crosses_repo=False,
            best_path_tier=_CONFIDENCE_TIER_RANK[EdgeConfidence.BARE_NAME],
        )
        is RiskLevel.LOW
    )

    assert set(RISK_THRESHOLDS) == {
        "critical_d1",
        "critical_cross_repo_d1",
        "high_d1",
        "medium_d1",
    }


def test_truncation_summary(hub_topology) -> None:
    """截断：``total_found``/``returned``/``truncated_by_depth`` 计数正确；排序键为
    「深度升序 + 置信度降序」且在截断前生效。

    250 扇入取自生产分布（解析边入度 p99 = 25 / max = 2,803）——200 条上限在热点符号上
    必然触发，这条用例测的是会被真实走到的路径，不是理论边界。

    （Req: IMPACT-04, 决策: D-16）
    """
    graph = hub_topology(fan_in=250)

    result = analyze_impact(graph, "hub")
    summary = result["summary"]

    # d1 = 250 个直接调用方，d2 = 250 个二级调用方。
    assert summary["total_found"] >= 250
    assert summary["returned"] == DEFAULT_RESULT_LIMIT == 200
    assert len(result["items"]) == summary["returned"]
    # 三个计数自洽：被截掉的总数 = 找到的 − 返回的。
    assert (
        sum(summary["truncated_by_depth"].values())
        == summary["total_found"] - summary["returned"]
    )
    assert summary["truncated_by_nodes"] is False
    assert summary["result_limit"] == 200
    # 风险等级用的是**截断前**的 d1 全量，不该因为输出被截到 200 条就跟着变小。
    assert result["risk_inputs"]["d1_count"] == 250
    assert result["risk"] == RiskLevel.CRITICAL.value

    # 预留字段位（本相位只占位，Phase 126 / 122-06 分别回填）。
    assert result["affected_processes"] == []
    assert result["cross_repo"] == []

    # limit=10：返回的 10 条**全部**是 d1，且 path_confidence 非递增
    # —— 证明排序在截断之前生效。先截后排的实现会在这里混进 d2 的条目。
    small = analyze_impact(graph, "hub", limit=10)
    assert small["summary"]["returned"] == 10
    assert [item["depth"] for item in small["items"]] == [1] * 10
    confidences = [item["path_confidence"] for item in small["items"]]
    assert confidences == sorted(confidences, reverse=True)
    assert small["summary"]["truncated_by_depth"][1] == 240
    assert small["summary"]["truncated_by_depth"][2] == 250


@pytest.mark.skip(reason="Wave 0 桩：由 122-06 落地")
def test_graph_cross_repo_edges_are_intra_repo() -> None:
    """**反向守护**：图里 ``kind == "cross_repo"`` 的边两端必在同仓，不得被标 ``cross_repo: true``。

    （Req: IMPACT-03, 决策: D-25）
    """
    pytest.fail("Wave 0 桩")
