"""调研 prompt「模块摘要」段（MOD-04 / D-16）。"""

from __future__ import annotations

from services.process_runtime.artifact_injection import render_module_summaries_section


def test_empty_module_summaries_omits_section() -> None:
    """``module_summaries`` 为空时省略整段，不留空标题。

    （Req: MOD-04, 决策: D-16）
    """
    assert render_module_summaries_section([], query="错题本导出") == ""
    assert render_module_summaries_section(None, query="错题本导出") == ""  # type: ignore[arg-type]


def test_budget_truncation_marks_truncated() -> None:
    """超 token 预算截断并标记 truncated。

    （Req: MOD-04, 决策: D-16, 威胁: T-125-04）
    """
    # 每条责任很长 → 超过 2000 字符预算后应截断并标注
    long = "鉴权与错题本导出链路说明" * 80
    summaries = [
        {
            "community_key": f"mod-{i}",
            "text": f"## 模块摘要\n### 职责\n{long}",
            "responsibility": long,
            "relevance": 1.0 - i * 0.01,
        }
        for i in range(8)
    ]
    out = render_module_summaries_section(
        summaries, query="错题本导出", max_chars=2000, max_items=5
    )
    assert "模块摘要" in out
    assert "truncated" in out.lower()
    assert len(out) <= 2200  # 预算 + 截断标注余量


def test_relevance_sort_before_truncate() -> None:
    """截断前先按相关度排序，保留更相关社区摘要。

    （Req: MOD-04, 决策: D-16）
    """
    summaries = [
        {
            "community_key": "unrelated",
            "text": "## 模块摘要\n### 职责\n日志采集与指标上报",
            "responsibility": "日志采集与指标上报",
            "relevance": 0.0,
        },
        {
            "community_key": "export",
            "text": "## 模块摘要\n### 职责\n错题本导出与格式转换",
            "responsibility": "错题本导出与格式转换",
            "relevance": 0.0,
        },
    ]
    out = render_module_summaries_section(
        summaries, query="改造错题本导出", max_chars=2000, max_items=1
    )
    assert "export" in out
    assert "unrelated" not in out
