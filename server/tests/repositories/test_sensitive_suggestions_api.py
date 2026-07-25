"""Plan 24-03：敏感文件 AI 建议 REST API 测试（list / accept / dismiss 守护）。

覆盖（对齐 24-03-PLAN acceptance_criteria + 威胁缓解）：
- list 默认仅 pending，且按 severity 排序（real_secret 优先）。
- accept → 创建 RepoExclusionRule(source="ai_suggested", rule_type="glob", pattern=<path>)
  且 suggestion.status=="accepted"；断言**无**任何删除/清理副作用（无 CleanupRun、无 purge）。
- accept 幂等：同一 path 二次 accept 不抛 500、规则不重复创建（T-24-12）。
- dismiss → status=="dismissed" 且无 RepoExclusionRule 创建（不建规则、不删数据）。
- 越仓 suggestion_id → 404（T-24-09）；非法 action → 400。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from repositories.models import (
    CleanupRun,
    RepoExclusionRule,
    Repository,
    SensitiveFileSuggestion,
)

pytestmark = pytest.mark.django_db(transaction=True)

LIST_URL = "/api/repositories/{repo_id}/sensitive-suggestions/"
ACTION_URL = "/api/repositories/{repo_id}/sensitive-suggestions/{suggestion_id}/action/"


def _make_suggestion(
    repository: Repository,
    path: str,
    severity: str = SensitiveFileSuggestion.Severity.CONFIG_REVIEW,
    detector: str = SensitiveFileSuggestion.Detector.HEURISTIC,
    status: str = SensitiveFileSuggestion.Status.PENDING,
    reason: str = "命中类型 config（行 1）",
) -> SensitiveFileSuggestion:
    return SensitiveFileSuggestion.objects.create(
        repository=repository,
        path=path,
        severity=severity,
        detector=detector,
        status=status,
        reason=reason,
    )


class TestSensitiveSuggestionsList:
    """list 端点按 #11 收口：敏感信息仅空间管理员/系统管理员可见，故用管理员客户端。"""

    def test_list_returns_pending_sorted_real_secret_first(
        self, authenticated_admin_client, repository: Repository
    ) -> None:
        _make_suggestion(
            repository, "config/app.yaml", SensitiveFileSuggestion.Severity.CONFIG_REVIEW
        )
        _make_suggestion(
            repository, ".env", SensitiveFileSuggestion.Severity.REAL_SECRET,
            detector=SensitiveFileSuggestion.Detector.CONTENT,
        )
        _make_suggestion(
            repository, "data.bak", SensitiveFileSuggestion.Severity.LIKELY_SENSITIVE
        )
        # dismissed 不出现在默认列表
        _make_suggestion(
            repository, "old.tmp", SensitiveFileSuggestion.Severity.REAL_SECRET,
            status=SensitiveFileSuggestion.Status.DISMISSED,
        )

        resp = authenticated_admin_client.get(LIST_URL.format(repo_id=repository.id))
        assert resp.status_code == 200
        items = resp.json()["suggestions"]
        # 默认仅 pending（3 条），dismissed 的 old.tmp 不在
        paths = [s["path"] for s in items]
        assert "old.tmp" not in paths
        assert len(items) == 3
        # real_secret 排第一
        assert items[0]["path"] == ".env"
        assert items[0]["severity"] == "real_secret"
        # severity 优先级顺序
        severities = [s["severity"] for s in items]
        assert severities == ["real_secret", "likely_sensitive", "config_review"]

    def test_list_status_all_includes_dismissed(
        self, authenticated_admin_client, repository: Repository
    ) -> None:
        _make_suggestion(repository, ".env", SensitiveFileSuggestion.Severity.REAL_SECRET)
        _make_suggestion(
            repository, "old.tmp", SensitiveFileSuggestion.Severity.CONFIG_REVIEW,
            status=SensitiveFileSuggestion.Status.DISMISSED,
        )
        resp = authenticated_admin_client.get(
            LIST_URL.format(repo_id=repository.id) + "?status=all"
        )
        assert resp.status_code == 200
        paths = {s["path"] for s in resp.json()["suggestions"]}
        assert paths == {".env", "old.tmp"}

    def test_list_reason_is_redacted_no_secret_body(
        self, authenticated_admin_client, repository: Repository
    ) -> None:
        # reason 脱敏：序列化输出只回显既定字段，reason 不含密钥本体（T-24-11）。
        _make_suggestion(
            repository, ".env", SensitiveFileSuggestion.Severity.REAL_SECRET,
            reason="命中类型 aws_secret_key（行 3）",
        )
        items = authenticated_admin_client.get(
            LIST_URL.format(repo_id=repository.id)
        ).json()["suggestions"]
        assert set(items[0].keys()) == {
            "id",
            "path",
            "severity",
            "detector",
            "reason",
            "status",
            "detected_at",
            "updated_at",
        }

    def test_list_404_missing_repo(self, authenticated_client) -> None:
        resp = authenticated_client.get(
            LIST_URL.format(repo_id="00000000-0000-0000-0000-000000000001")
        )
        assert resp.status_code == 404

    def test_unauthenticated_blocked(self, api_client, repository: Repository) -> None:
        resp = api_client.get(LIST_URL.format(repo_id=repository.id))
        assert resp.status_code in (401, 403)

    def test_non_admin_blocked_and_leaks_nothing(
        self, authenticated_client, repository: Repository
    ) -> None:
        """#11：非空间管理员的已登录用户不得查看敏感建议，且响应不泄漏任何条目。"""
        _make_suggestion(
            repository, ".env", SensitiveFileSuggestion.Severity.REAL_SECRET,
            reason="命中类型 aws_secret_key（行 3）",
        )
        resp = authenticated_client.get(LIST_URL.format(repo_id=repository.id))
        assert resp.status_code == 403
        assert "suggestions" not in resp.json()
        assert ".env" not in resp.content.decode()


class TestSensitiveSuggestionAccept:
    def test_accept_creates_ai_suggested_rule_and_marks_accepted(
        self, authenticated_admin_client, repository: Repository
    ) -> None:
        s = _make_suggestion(
            repository, ".env", SensitiveFileSuggestion.Severity.REAL_SECRET
        )
        with patch("repositories.views.invalidate_matcher_cache") as inv:
            resp = authenticated_admin_client.post(
                ACTION_URL.format(repo_id=repository.id, suggestion_id=s.id),
                {"action": "accept"},
                format="json",
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["suggestion"]["status"] == "accepted"
        assert body["rule"]["pattern"] == ".env"
        assert body["rule"]["rule_type"] == "glob"
        assert body["rule"]["source"] == "ai_suggested"
        # DB 真出现该规则
        assert RepoExclusionRule.objects.filter(
            repository=repository,
            pattern=".env",
            rule_type="glob",
            source="ai_suggested",
        ).exists()
        # suggestion 标 accepted
        s.refresh_from_db()
        assert s.status == "accepted"
        # 缓存失效被调用
        inv.assert_called_once()

    def test_accept_never_deletes_data_no_cleanup_run(
        self, authenticated_admin_client, repository: Repository
    ) -> None:
        # NEVER silent-delete：accept 绝不触发任何删除/清理（T-24-10）。
        s = _make_suggestion(
            repository, "secrets/app.pem", SensitiveFileSuggestion.Severity.REAL_SECRET
        )
        cleanup_before = CleanupRun.objects.count()
        with patch("services.purge_reconcile.run_cleanup") as run_cleanup_mock:
            resp = authenticated_admin_client.post(
                ACTION_URL.format(repo_id=repository.id, suggestion_id=s.id),
                {"action": "accept"},
                format="json",
            )
        assert resp.status_code == 200
        # 无 CleanupRun 被创建
        assert CleanupRun.objects.count() == cleanup_before
        # 无 purge / cleanup 被派发
        run_cleanup_mock.assert_not_called()

    def test_accept_is_idempotent(
        self, authenticated_admin_client, repository: Repository
    ) -> None:
        s = _make_suggestion(
            repository, ".env", SensitiveFileSuggestion.Severity.REAL_SECRET
        )
        url = ACTION_URL.format(repo_id=repository.id, suggestion_id=s.id)
        r1 = authenticated_admin_client.post(url, {"action": "accept"}, format="json")
        r2 = authenticated_admin_client.post(url, {"action": "accept"}, format="json")
        assert r1.status_code == 200
        # 二次 accept 不抛 500
        assert r2.status_code == 200
        # 规则不重复创建
        assert (
            RepoExclusionRule.objects.filter(
                repository=repository, pattern=".env", source="ai_suggested"
            ).count()
            == 1
        )


class TestSensitiveSuggestionDismiss:
    def test_dismiss_marks_dismissed_no_rule(
        self, authenticated_admin_client, repository: Repository
    ) -> None:
        s = _make_suggestion(
            repository, "config/app.yaml", SensitiveFileSuggestion.Severity.CONFIG_REVIEW
        )
        with patch("repositories.views.invalidate_matcher_cache") as inv:
            resp = authenticated_admin_client.post(
                ACTION_URL.format(repo_id=repository.id, suggestion_id=s.id),
                {"action": "dismiss"},
                format="json",
            )
        assert resp.status_code == 200
        assert resp.json()["suggestion"]["status"] == "dismissed"
        s.refresh_from_db()
        assert s.status == "dismissed"
        # 不建规则
        assert not RepoExclusionRule.objects.filter(repository=repository).exists()
        # dismiss 不应触发缓存失效（无规则变更）
        inv.assert_not_called()


class TestSensitiveSuggestionActionGuards:
    def test_cross_repo_suggestion_404(
        self, authenticated_admin_client, repository: Repository
    ) -> None:
        other = Repository.objects.create(
            name="other", git_url="https://example.com/other.git"
        )
        s = _make_suggestion(other, ".env", SensitiveFileSuggestion.Severity.REAL_SECRET)
        resp = authenticated_admin_client.post(
            ACTION_URL.format(repo_id=repository.id, suggestion_id=s.id),
            {"action": "accept"},
            format="json",
        )
        assert resp.status_code == 404
        # 越仓 suggestion 未被改动
        s.refresh_from_db()
        assert s.status == "pending"
        assert not RepoExclusionRule.objects.filter(pattern=".env").exists()

    def test_invalid_action_400(
        self, authenticated_admin_client, repository: Repository
    ) -> None:
        s = _make_suggestion(
            repository, ".env", SensitiveFileSuggestion.Severity.REAL_SECRET
        )
        resp = authenticated_admin_client.post(
            ACTION_URL.format(repo_id=repository.id, suggestion_id=s.id),
            {"action": "nuke"},
            format="json",
        )
        assert resp.status_code == 400
        s.refresh_from_db()
        assert s.status == "pending"

    def test_non_admin_action_blocked_no_side_effect(
        self, authenticated_client, repository: Repository
    ) -> None:
        """#11：非空间管理员不得操作敏感建议——列表侧已管控，动作侧不得成为旁路。

        accept 既变更索引范围（建 RepoExclusionRule）又回显 path/reason，
        故守卫强度必须与列表端点一致；被拒时不得有任何副作用、不得泄漏路径。
        """
        s = _make_suggestion(
            repository,
            ".env",
            SensitiveFileSuggestion.Severity.REAL_SECRET,
            reason="命中类型 aws_secret_key（行 3）",
        )
        resp = authenticated_client.post(
            ACTION_URL.format(repo_id=repository.id, suggestion_id=s.id),
            {"action": "accept"},
            format="json",
        )
        assert resp.status_code == 403
        # 无副作用：建议状态不变、未建任何排除规则
        s.refresh_from_db()
        assert s.status == "pending"
        assert not RepoExclusionRule.objects.filter(repository=repository).exists()
        # 不泄漏敏感字段
        body = resp.content.decode()
        assert ".env" not in body
        assert "aws_secret_key" not in body

    def test_action_404_missing_repo(self, authenticated_client) -> None:
        resp = authenticated_client.post(
            ACTION_URL.format(
                repo_id="00000000-0000-0000-0000-000000000001",
                suggestion_id="00000000-0000-0000-0000-000000000002",
            ),
            {"action": "accept"},
            format="json",
        )
        assert resp.status_code == 404
