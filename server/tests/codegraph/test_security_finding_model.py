"""SecurityFinding 模型验收（D-05；归属 127-02）。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from django.db import models

from repositories.models import Repository


@pytest.mark.django_db
def test_security_finding_required_fields() -> None:
    """SecurityFinding 必填字段可持久化（repo/path/rule_id/severity 等）。

    （决策: D-05）
    """
    from codegraph.models import SecurityFinding

    repo = Repository.objects.create(
        name="security-finding-repo",
        git_url="https://example.com/security-finding.git",
        default_branch="main",
    )
    finding = SecurityFinding.objects.create(
        repository=repo,
        branch_name="feature/scan",
        mr_key="mr-42",
        rule_id="python.lang.security.audit.dangerous-system-call",
        severity="ERROR",
        file_path="app/views.py",
        line=12,
        message="dangerous call",
        fingerprint="fp-abc",
        scan_sha="a" * 40,
    )
    finding.refresh_from_db()
    assert finding.status == "open"
    assert finding.rule_id.startswith("python.")
    assert finding.fingerprint == "fp-abc"
    assert finding.scan_sha == "a" * 40
    assert finding.mr_key == "mr-42"
    assert finding.line == 12


def test_security_finding_has_no_symbol_fk() -> None:
    """SecurityFinding 无 Symbol FK（软引用）。

    （决策: D-05）
    """
    from codegraph.models import SecurityFinding, Symbol

    for field in SecurityFinding._meta.get_fields():
        if isinstance(field, models.ForeignKey):
            assert field.related_model is not Symbol

    models_path = Path(__file__).resolve().parents[2] / "codegraph" / "models.py"
    source = models_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "SecurityFinding":
            src = ast.get_source_segment(source, node) or ""
            assert "to=Symbol" not in src
            assert 'to="Symbol"' not in src
            assert "to='Symbol'" not in src
            assert "codegraph.Symbol" not in src
            break
    else:
        pytest.fail("SecurityFinding class missing in models.py")


@pytest.mark.django_db
def test_security_finding_message_expected_redacted_at_write_path() -> None:
    """写入路径过 redact_secrets_in_text——断言 helper 脱敏。

    （决策: D-05；威胁: T-127-01）
    """
    from codegraph.models import SecurityFinding, prepare_finding_message

    raw = "token sk-ant-api03-secretvaluehere000000000000000000000000000000000000"
    redacted = prepare_finding_message(raw)
    assert "sk-ant-" not in redacted
    assert "***REDACTED***" in redacted

    repo = Repository.objects.create(
        name="security-finding-redact-repo",
        git_url="https://example.com/security-finding-redact.git",
        default_branch="main",
    )
    finding = SecurityFinding.objects.create(
        repository=repo,
        branch_name="",
        mr_key="mr-1",
        rule_id="rule.x",
        severity="WARNING",
        file_path="a.py",
        message=prepare_finding_message(raw),
        fingerprint="fp-1",
        scan_sha="b" * 40,
    )
    finding.refresh_from_db()
    assert "sk-ant-" not in finding.message
