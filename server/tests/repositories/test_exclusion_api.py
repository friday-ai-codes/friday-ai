"""Plan 22-05：排除规则 REST API 测试（CRUD + regex fail-loud + 缓存失效）。

覆盖（对齐 22-05-PLAN acceptance_criteria）：
- GET 返回 global_defaults（含内置默认）+ per-repo rules。
- POST 合法 dir/glob/regex → 201 入库；非法 regex / 空 pattern → 400 不写库（fail-loud，D-02）。
- POST source=global + enabled=False override → 该全局默认从有效集（serialize_rules_for_repo）剔除。
- DELETE per-repo 规则 → 后续不含。
- 任一写操作后 invalidate_matcher_cache 被调用（T-22-18）。
- 权限沿用仓库既有权限（未认证 401/403；不存在仓库 404）。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from asgiref.sync import async_to_sync

from repositories.models import RepoExclusionRule, Repository

pytestmark = pytest.mark.django_db(transaction=True)

EXCL_URL = "/api/repositories/{repo_id}/exclusions/"
EXCL_DETAIL_URL = "/api/repositories/{repo_id}/exclusions/{rule_id}/"


class TestExclusionRulesListView:
    def test_get_returns_global_defaults_and_rules(
        self, authenticated_client, repository: Repository
    ) -> None:
        RepoExclusionRule.objects.create(
            repository=repository, pattern="build/", rule_type="dir", source="user"
        )
        resp = authenticated_client.get(EXCL_URL.format(repo_id=repository.id))
        assert resp.status_code == 200
        data = resp.json()
        assert "global_defaults" in data
        assert "rules" in data
        # 内置全局默认含 .env（不在视图里硬编码，来自 services.exclusion）
        global_patterns = {g["pattern"] for g in data["global_defaults"]}
        assert ".env" in global_patterns
        # 全局默认默认 enabled=True
        env_default = next(g for g in data["global_defaults"] if g["pattern"] == ".env")
        assert env_default["enabled"] is True
        # per-repo 规则被列出
        rule_patterns = {r["pattern"] for r in data["rules"]}
        assert "build/" in rule_patterns

    def test_get_404_missing_repo(self, authenticated_client) -> None:
        resp = authenticated_client.get(
            EXCL_URL.format(repo_id="00000000-0000-0000-0000-000000000001")
        )
        assert resp.status_code == 404

    def test_unauthenticated_blocked(self, api_client, repository: Repository) -> None:
        resp = api_client.get(EXCL_URL.format(repo_id=repository.id))
        assert resp.status_code in (401, 403)


class TestExclusionRulesCreate:
    def test_post_valid_glob_creates_and_invalidates(
        self, authenticated_client, repository: Repository
    ) -> None:
        with patch("repositories.views.invalidate_matcher_cache") as inv:
            resp = authenticated_client.post(
                EXCL_URL.format(repo_id=repository.id),
                {"pattern": "*.secret", "rule_type": "glob"},
                format="json",
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["pattern"] == "*.secret"
        assert body["rule_type"] == "glob"
        assert body["source"] == "user"
        assert "id" in body
        assert RepoExclusionRule.objects.filter(repository=repository, pattern="*.secret").exists()
        inv.assert_called_once()

    def test_post_valid_regex_creates(self, authenticated_client, repository: Repository) -> None:
        resp = authenticated_client.post(
            EXCL_URL.format(repo_id=repository.id),
            {"pattern": r".*\.env$", "rule_type": "regex"},
            format="json",
        )
        assert resp.status_code == 201
        assert RepoExclusionRule.objects.filter(
            repository=repository, rule_type="regex", pattern=r".*\.env$"
        ).exists()

    def test_post_valid_dir_creates(self, authenticated_client, repository: Repository) -> None:
        resp = authenticated_client.post(
            EXCL_URL.format(repo_id=repository.id),
            {"pattern": "dist/", "rule_type": "dir"},
            format="json",
        )
        assert resp.status_code == 201

    def test_post_invalid_regex_failclosed_400(
        self, authenticated_client, repository: Repository
    ) -> None:
        with patch("repositories.views.invalidate_matcher_cache") as inv:
            resp = authenticated_client.post(
                EXCL_URL.format(repo_id=repository.id),
                {"pattern": "[", "rule_type": "regex"},
                format="json",
            )
        assert resp.status_code == 400
        # fail-loud：非法 regex 不写库
        assert not RepoExclusionRule.objects.filter(repository=repository, pattern="[").exists()
        # 校验失败不应触发缓存失效
        inv.assert_not_called()

    def test_post_redos_regex_failclosed_400(
        self, authenticated_client, repository: Repository
    ) -> None:
        # HI-01：嵌套量词 ReDoS 高风险 regex 保存时 fail-loud（不写库）。
        with patch("repositories.views.invalidate_matcher_cache") as inv:
            resp = authenticated_client.post(
                EXCL_URL.format(repo_id=repository.id),
                {"pattern": "(a+)+$", "rule_type": "regex"},
                format="json",
            )
        assert resp.status_code == 400
        assert not RepoExclusionRule.objects.filter(
            repository=repository, pattern="(a+)+$"
        ).exists()
        inv.assert_not_called()

    def test_post_empty_pattern_400(self, authenticated_client, repository: Repository) -> None:
        resp = authenticated_client.post(
            EXCL_URL.format(repo_id=repository.id),
            {"pattern": "   ", "rule_type": "glob"},
            format="json",
        )
        assert resp.status_code == 400

    def test_post_invalid_glob_failclosed_400(
        self, authenticated_client, repository: Repository, monkeypatch
    ) -> None:
        # ME-03：glob 保存时 fail-loud 预校验，非法 glob → 400（不写库）。
        import repositories.serializers as ser

        real = ser.fnmatch.translate
        monkeypatch.setattr(
            ser.fnmatch,
            "translate",
            lambda p: "([unclosed" if p == "BADGLOB" else real(p),
        )
        resp = authenticated_client.post(
            EXCL_URL.format(repo_id=repository.id),
            {"pattern": "BADGLOB", "rule_type": "glob"},
            format="json",
        )
        assert resp.status_code == 400
        assert not RepoExclusionRule.objects.filter(
            repository=repository, pattern="BADGLOB"
        ).exists()

    def test_post_global_override_disables_default(
        self, authenticated_client, repository: Repository
    ) -> None:
        # 关闭内置默认 node_modules/（source=global + enabled=False override 行）
        resp = authenticated_client.post(
            EXCL_URL.format(repo_id=repository.id),
            {
                "pattern": "node_modules/",
                "rule_type": "dir",
                "source": "global",
                "enabled": False,
            },
            format="json",
        )
        assert resp.status_code == 201

        # 有效规则集（与匹配器同源）应不再含 node_modules/
        from services.exclusion import serialize_rules_for_repo

        rules = async_to_sync(serialize_rules_for_repo)(str(repository.id))
        patterns = {r["pattern"] for r in rules}
        assert "node_modules/" not in patterns

        # GET 中该全局默认显示为 enabled=False，并带 override_id 供再次启用
        data = authenticated_client.get(EXCL_URL.format(repo_id=repository.id)).json()
        gd = {g["pattern"]: g for g in data["global_defaults"]}
        assert gd["node_modules/"]["enabled"] is False
        assert gd["node_modules/"]["override_id"]


class TestExclusionRuleDelete:
    def test_delete_removes_rule_and_invalidates(
        self, authenticated_client, repository: Repository
    ) -> None:
        rule = RepoExclusionRule.objects.create(
            repository=repository, pattern="tmp/", rule_type="dir", source="user"
        )
        with patch("repositories.views.invalidate_matcher_cache") as inv:
            resp = authenticated_client.delete(
                EXCL_DETAIL_URL.format(repo_id=repository.id, rule_id=rule.id)
            )
        assert resp.status_code == 204
        assert not RepoExclusionRule.objects.filter(id=rule.id).exists()
        inv.assert_called_once()

    def test_delete_404_missing_rule(self, authenticated_client, repository: Repository) -> None:
        resp = authenticated_client.delete(
            EXCL_DETAIL_URL.format(
                repo_id=repository.id,
                rule_id="00000000-0000-0000-0000-000000000099",
            )
        )
        assert resp.status_code == 404

    def test_delete_other_repo_rule_404(self, authenticated_client, repository: Repository) -> None:
        other = Repository.objects.create(name="other", git_url="https://example.com/other.git")
        rule = RepoExclusionRule.objects.create(
            repository=other, pattern="x/", rule_type="dir", source="user"
        )
        resp = authenticated_client.delete(
            EXCL_DETAIL_URL.format(repo_id=repository.id, rule_id=rule.id)
        )
        assert resp.status_code == 404
        # 不得越仓删除
        assert RepoExclusionRule.objects.filter(id=rule.id).exists()
