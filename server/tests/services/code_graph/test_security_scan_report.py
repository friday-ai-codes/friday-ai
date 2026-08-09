"""``services/code_graph/security_scan_report`` formatter / stub / Pro 文案（TAINT-02/03；D-06..D-09）。

归属 Plan 127-04：与 ``impact_report`` 同构；mock findings 边界，不重测 Semgrep CLI。
覆盖 advisory 分级、CE disclaimer、nosemgrep、stub 脱敏、Pro opt-in 短句。
"""

from __future__ import annotations

from typing import Any

from services.code_graph.security_scan_report import (
    SECURITY_SECTION_MARKER,
    append_security_scan,
    build_security_scan_section,
    stub_security_scan_section,
)


def test_append_security_scan_idempotent() -> None:
    """标记头 ``## 安全扫描``；已含则不重复；不覆盖 ``## 影响面``。

    （Req: TAINT-02, 决策: D-06）
    """
    section = f"{SECURITY_SECTION_MARKER}\n\n_stub_"
    base = "hello\n\n## 安全扫描\n\nold"
    assert append_security_scan(base, section) == base
    assert append_security_scan("", section) == section
    assert append_security_scan("desc", "") == "desc"

    with_impact = "## 方案\n\n## 影响面\n\n_impact_"
    out = append_security_scan(with_impact, section)
    assert "## 影响面" in out
    assert out.count(SECURITY_SECTION_MARKER) == 1
    assert out.startswith("## 方案")


def test_security_section_lists_severity_advisory() -> None:
    """ERROR/WARNING/INFO 分级展示；无 blocking raise。

    （Req: TAINT-02, 决策: D-07；威胁: T-127-05）
    """
    findings: list[dict[str, Any]] = [
        {
            "severity": "ERROR",
            "rule_id": "python.lang.security.audit.sqli",
            "file_path": "a.py",
            "line": 10,
            "message": "SQL injection",
        },
        {
            "severity": "WARNING",
            "rule_id": "python.lang.security.audit.xss",
            "file_path": "b.py",
            "line": 3,
            "message": "XSS",
        },
        {
            "severity": "INFO",
            "rule_id": "python.lang.correctness",
            "file_path": "c.py",
            "line": 1,
            "message": "style",
        },
    ]
    section = build_security_scan_section(findings=findings, pro_enabled=False)
    assert SECURITY_SECTION_MARKER in section
    assert "ERROR" in section
    assert "WARNING" in section
    assert "INFO" in section
    assert "advisory" in section.lower() or "建议" in section or "不阻断" in section
    assert "blocking" not in section.lower()
    assert "merge-gate" not in section.lower()


def test_security_section_has_ce_disclaimer() -> None:
    """CE 函数内 taint 边界文案。

    （Req: TAINT-03, 决策: D-08；威胁: T-127-05）
    """
    section = build_security_scan_section(findings=[], pro_enabled=False)
    assert "CE" in section
    assert "函数内" in section


def test_security_section_nosemgrep_mention() -> None:
    """段内说明 ``nosemgrep``。

    （Req: TAINT-02, 决策: D-08）
    """
    section = build_security_scan_section(findings=[], pro_enabled=False)
    assert "nosemgrep" in section


def test_stub_omits_token_stack_and_abs_paths() -> None:
    """token/Traceback/绝对路径不得进 section。

    （Req: TAINT-03, 决策: D-09；威胁: T-127-01）
    """
    fake_token = "sgp_live_ABCDEFG1234567890secret"
    abs_path = "/Users/zaneliu/Projects/secret/repo/src/a.py"
    # 即使传入脏 error_code，stub 也只保留稳定短码
    section = stub_security_scan_section(
        f"timeout token={fake_token} path={abs_path}\nTraceback (most recent call last):\n  File ..."
    )
    assert SECURITY_SECTION_MARKER in section
    assert "安全扫描未能生成" in section
    assert "`timeout`" in section or "`unavailable`" in section
    assert fake_token not in section
    assert abs_path not in section
    assert "Traceback" not in section
    assert "/Users/" not in section


def test_pro_token_configured_line_without_hype() -> None:
    """有 token →「Pro 能力已启用」类短句且不夸大；空 token → 纯 CE。

    （Req: TAINT-03, 决策: D-09/D-10）
    """
    ce = build_security_scan_section(findings=[], pro_enabled=False)
    assert "Pro 能力已启用" not in ce
    assert "CE" in ce
    assert "跨文件" in ce  # disclaimer 明确不承诺

    pro = build_security_scan_section(findings=[], pro_enabled=True)
    assert "Pro 能力已启用" in pro
    # 不得夸大未验证跨文件覆盖
    assert "完整跨文件" not in pro
    assert "保证跨文件" not in pro
    assert "100%" not in pro
