"""wave_layering 拓扑分层纯函数单测（Phase 44-02，WAVE-01）。

覆盖 5 场景：空依赖零回归 / 线性链 / 菱形 / 环 fail-fast / 同仓取 max。
纯函数测试，无 ``django_db``、无 IO。
"""

from __future__ import annotations

from services.process_runtime import build_repo_dep_edges, build_repo_waves


def _task(tid: str, repo: str, deps: list[str] | None = None) -> dict:
    return {"id": tid, "repository_id": repo, "dependencies": deps or []}


def test_empty_deps_single_wave():
    """3 仓各 1 task 无依赖 → 全仓 wave=0；跨仓边为空（零回归命门）。"""
    plan = [
        _task("t1", "repoA"),
        _task("t2", "repoB"),
        _task("t3", "repoC"),
    ]
    repo_wave, cycle = build_repo_waves(plan)
    assert cycle is None
    assert repo_wave == {"repoA": 0, "repoB": 0, "repoC": 0}
    assert build_repo_dep_edges(plan) == {}


def test_linear_chain():
    """taskA(repoA) ← taskB(repoB) ← taskC(repoC) → wave 0/1/2，边逐级跨仓。"""
    plan = [
        _task("tA", "repoA"),
        _task("tB", "repoB", ["tA"]),
        _task("tC", "repoC", ["tB"]),
    ]
    repo_wave, cycle = build_repo_waves(plan)
    assert cycle is None
    assert repo_wave == {"repoA": 0, "repoB": 1, "repoC": 2}
    assert build_repo_dep_edges(plan) == {"repoB": ["repoA"], "repoC": ["repoB"]}


def test_diamond():
    """菱形：A←B,A←C,B←D,C←D → repo(A)=0, repo(B)=repo(C)=1, repo(D)=2。"""
    plan = [
        _task("tA", "repoA"),
        _task("tB", "repoB", ["tA"]),
        _task("tC", "repoC", ["tA"]),
        _task("tD", "repoD", ["tB", "tC"]),
    ]
    repo_wave, cycle = build_repo_waves(plan)
    assert cycle is None
    assert repo_wave == {"repoA": 0, "repoB": 1, "repoC": 1, "repoD": 2}
    assert build_repo_dep_edges(plan) == {
        "repoB": ["repoA"],
        "repoC": ["repoA"],
        "repoD": ["repoB", "repoC"],
    }


def test_cycle_fail_fast():
    """A←B, B←A → fail-fast 返回 ({}, {reason: dependency_cycle})，不分层。"""
    plan = [
        _task("tA", "repoA", ["tB"]),
        _task("tB", "repoB", ["tA"]),
    ]
    repo_wave, cycle = build_repo_waves(plan)
    assert repo_wave == {}
    assert cycle is not None
    assert cycle["reason"] == "dependency_cycle"
    assert cycle["detail"]


def test_same_repo_max_wave():
    """同仓 repoX 有 wave0 task 与依赖他仓 wave0 的 wave1 task → repoX 取 max=1。

    同仓内部依赖不产生 repoX 自环边。
    """
    plan = [
        _task("x0", "repoX"),  # wave 0
        _task("y0", "repoY"),  # wave 0
        _task("x1", "repoX", ["y0", "x0"]),  # 依赖他仓 wave0 → wave 1；并含同仓内部依赖
    ]
    repo_wave, cycle = build_repo_waves(plan)
    assert cycle is None
    assert repo_wave == {"repoX": 1, "repoY": 0}
    edges = build_repo_dep_edges(plan)
    assert edges == {"repoX": ["repoY"]}
    assert "repoX" not in edges.get("repoX", [])
