"""``services/code_graph/security_scan_report`` MR 段契约（TAINT-02/03；D-06..D-09）。

归属 Plan 127-04：幂等 append、severity 分级、CE/nosemgrep/Pro 诚实文案、stub 脱敏。
"""

from __future__ import annotations

from structlog.testing import capture_logs

from services.code_graph.security_scan_report import (
    SECURITY_SECTION_MARKER,
    append_security_scan,
    build_security_scan_section,
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

    with_impact = "## Custom\n\n## 影响面\n\n_impact_"
    out = append_security_scan(with_impact, section)
    assert "## 影响面" in out
    assert out.count(SECURITY_SECTION_MARKER) == 1
    assert out.count("## 影响面") == 1


def test_security_section_lists_severity_advisory() -> None:
    """ERROR/WARNING/INFO 分级展示；无 blocking raise。

    （Req: TAINT-02, 决策: D-07；威胁: T-127-05）
    """
    findings = [
        {
            "rule_id": "r.error",
            "severity": "ERROR",
            "file_path": "a.py",
            "line": 10,
            "message": "bad",
        },
        {
            "rule_id": "r.warn",
            "severity": "WARNING",
            "file_path": "b.py",
            "line": 2,
            "message": "meh",
        },
        {
            "rule_id": "r.info",
            "severity": "INFO",
            "file_path": "c.py",
            "line": 3,
            "message": "note",
        },
    ]
    section = build_security_scan_section(findings=findings, pro_enabled=False)
    assert SECURITY_SECTION_MARKER in section
    assert "ERROR" in section
    assert "WARNING" in section
    assert "INFO" in section
    assert "advisory" in section.lower() or "不阻断" in section or "仅供参考" in section
    # 不得出现硬门禁措辞
    assert "blocking" not in section.lower()
    assert "merge-gate" not in section.lower()
    assert "禁止合并" not in section


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
    secret = "sgp_live_FAKESECRET_for_test_only"
    abs_path = "/Users/zaneliu/Projects/secret/repo/src/a.py"
    with capture_logs() as events:
        section = build_security_scan_section(
            error_code="timeout",
            error=(
                f"boom token={secret} path={abs_path}\n"
                "Traceback (most recent call last):\n  File ..."
            ),
        )

    assert SECURITY_SECTION_MARKER in section
    assert "`timeout`" in section
    assert "安全扫描未能生成" in section
    assert secret not in section
    assert abs_path not in section
    assert "Traceback" not in section
    blob = " ".join(str(e) for e in events)
    assert secret not in blob
    assert "Traceback" not in blob


def test_pro_token_configured_line_without_hype() -> None:
    """有 token →「Pro 能力已启用」类短句且不夸大；空 token → 纯 CE。

    （Req: TAINT-03, 决策: D-08/D-09）
    """
    ce = build_security_scan_section(findings=[], pro_enabled=False)
    assert "Pro 能力已启用" not in ce
    assert "CE" in ce
    assert "跨文件" not in ce or "不承诺" in ce or "不保证" in ce or "仅函数内" in ce

    pro = build_security_scan_section(findings=[], pro_enabled=True)
    assert "Pro 能力已启用" in pro
    # 不得夸大未验证跨文件覆盖
    assert "全面跨文件" not in pro
    assert "100%" not in pro
    assert "保证跨文件" not in pro
