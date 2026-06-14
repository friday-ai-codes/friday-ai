"""ExclusionMatcher / 统一匹配器单测（Phase 22 fail-closed）。

覆盖：
- dir / glob / regex 三类规则的相对仓库根匹配语义。
- 非法 regex 构造期 fail-loud（InvalidExclusionRuleError）。
- 路径归一越界 / 运行期异常 fail-closed（is_excluded → True）。
- BUILTIN_GLOBAL_DEFAULTS 安全默认覆盖面。
- build_matcher_for_repo 合并 builtin ∪ 全局设置 ∪ per-repo + override + TTL 缓存。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from asgiref.sync import sync_to_async

from services import exclusion
from services.exclusion import (
    BUILTIN_GLOBAL_DEFAULTS,
    ExclusionMatcher,
    ExclusionRuleSpec,
    InvalidExclusionRuleError,
    build_matcher_for_repo,
    invalidate_matcher_cache,
    is_excluded,
    normalize_rel_path,
)


class TestNormalizeRelPath:
    def test_strips_leading_dot_slash_and_posix(self) -> None:
        assert normalize_rel_path("./src/app.py") == "src/app.py"
        assert normalize_rel_path("src\\app.py") == "src/app.py"

    def test_collapses_in_bounds_dotdot(self) -> None:
        assert normalize_rel_path("a/../b.py") == "b.py"

    def test_out_of_bounds_dotdot_returns_none(self) -> None:
        assert normalize_rel_path("../etc/passwd") is None

    def test_absolute_path_returns_none(self) -> None:
        assert normalize_rel_path("/etc/passwd") is None

    def test_empty_returns_none(self) -> None:
        assert normalize_rel_path("") is None
        assert normalize_rel_path("   ") is None


class TestDirRule:
    def test_matches_dir_itself_and_subtree(self) -> None:
        m = ExclusionMatcher([ExclusionRuleSpec(pattern="node_modules/", rule_type="dir")])
        assert m.is_excluded("node_modules") is True
        assert m.is_excluded("node_modules/a/b.js") is True

    def test_does_not_match_sibling_prefix(self) -> None:
        m = ExclusionMatcher([ExclusionRuleSpec(pattern="src/", rule_type="dir")])
        assert m.is_excluded("src_other/x.py") is False
        assert m.is_excluded("README.md") is False


class TestGlobRule:
    def test_root_env_match(self) -> None:
        m = ExclusionMatcher([ExclusionRuleSpec(pattern=".env", rule_type="glob")])
        assert m.is_excluded(".env") is True
        assert m.is_excluded("app.py") is False

    def test_pem_matches_nested(self) -> None:
        m = ExclusionMatcher([ExclusionRuleSpec(pattern="*.pem", rule_type="glob")])
        assert m.is_excluded("certs/x.pem") is True
        assert m.is_excluded("certs/x.txt") is False

    def test_bare_glob_matches_basename_in_any_dir(self) -> None:
        # BL-01：无路径分隔符的 glob 按 basename 命中任意子目录（不止仓库根）。
        m = ExclusionMatcher([ExclusionRuleSpec(pattern=".env", rule_type="glob")])
        assert m.is_excluded(".env") is True
        assert m.is_excluded("server/.env") is True
        assert m.is_excluded("web/.env") is True
        # 仍不误伤同名前缀文件
        assert m.is_excluded("server/.env.example") is False

    def test_glob_with_slash_keeps_path_semantics(self) -> None:
        # 含分隔符的 glob 仍按相对路径语义，不做 basename 兜底。
        m = ExclusionMatcher([ExclusionRuleSpec(pattern="config/*.env", rule_type="glob")])
        assert m.is_excluded("config/app.env") is True
        assert m.is_excluded("other/app.env") is False


class TestRegexRule:
    def test_fullmatch(self) -> None:
        m = ExclusionMatcher([ExclusionRuleSpec(pattern=r"secret/.*\.json", rule_type="regex")])
        assert m.is_excluded("secret/a.json") is True
        # 非全匹配不命中
        assert m.is_excluded("x/secret/a.json") is False

    def test_invalid_regex_raises_at_construction(self) -> None:
        with pytest.raises(InvalidExclusionRuleError):
            ExclusionMatcher([ExclusionRuleSpec(pattern="(", rule_type="regex")])


class TestFailClosed:
    def test_out_of_bounds_path_excluded(self) -> None:
        m = ExclusionMatcher([])
        assert m.is_excluded("../etc/passwd") is True

    def test_runtime_exception_fail_closed_and_logs(self) -> None:
        m = ExclusionMatcher([])
        with (
            patch.object(exclusion, "normalize_rel_path", side_effect=RuntimeError("boom")),
            patch.object(exclusion, "log_exclusion_blocked") as mock_log,
        ):
            assert m.is_excluded("any/path.py") is True
        assert mock_log.called


class TestBuiltinDefaults:
    def test_covers_core_security_patterns(self) -> None:
        pairs = {(s.rule_type, s.pattern) for s in BUILTIN_GLOBAL_DEFAULTS}
        assert ("glob", ".env") in pairs
        assert ("glob", "*.pem") in pairs
        assert ("glob", "id_rsa") in pairs
        assert ("dir", ".git/") in pairs
        assert ("dir", "node_modules/") in pairs

    def test_builtin_matcher_blocks_env(self) -> None:
        m = ExclusionMatcher(BUILTIN_GLOBAL_DEFAULTS)
        assert m.is_excluded(".env") is True
        assert m.is_excluded("node_modules/lib/index.js") is True
        assert m.is_excluded("src/main.py") is False

    def test_builtin_matcher_blocks_subdir_secrets(self) -> None:
        # BL-01：子目录密钥（server/.env、web/.env、子目录私钥）必须被内置默认排除。
        m = ExclusionMatcher(BUILTIN_GLOBAL_DEFAULTS)
        assert m.is_excluded("server/.env") is True
        assert m.is_excluded("web/.env") is True
        assert m.is_excluded("config/.env.production") is True
        assert m.is_excluded("config/id_rsa") is True
        assert m.is_excluded("a/b/id_ed25519") is True
        assert m.is_excluded("deploy/keys/server.pem") is True


class TestBuildMatcherForRepo:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        invalidate_matcher_cache()
        yield
        invalidate_matcher_cache()

    async def test_merges_and_caches(self) -> None:
        repo_id = "11111111-1111-1111-1111-111111111111"
        specs = [
            ExclusionRuleSpec(pattern="*.secret", rule_type="glob", source="user"),
            *BUILTIN_GLOBAL_DEFAULTS,
        ]
        loader = MagicMock(return_value=specs)
        with patch.object(exclusion, "_load_specs_from_db", loader):
            m1 = await build_matcher_for_repo(repo_id)
            m2 = await build_matcher_for_repo(repo_id)
        assert m1 is m2  # 命中缓存
        assert loader.call_count == 1  # ORM 仅查一次
        assert m1.is_excluded("foo.secret") is True
        assert m1.is_excluded(".env") is True  # builtin 生效

    @pytest.mark.django_db(transaction=True)
    async def test_db_merge_with_global_override(self) -> None:
        from repositories.models import RepoExclusionRule, Repository
        from system.models import SettingKeys, SystemSetting

        repo = await sync_to_async(Repository.objects.create)(
            name="excl-repo", git_url="https://example.com/r.git"
        )
        # 全局设置 JSON 追加一条 glob
        await sync_to_async(SystemSetting.objects.create)(
            key=SettingKeys.CODE_INDEX_EXCLUSION_GLOBAL_DEFAULTS,
            value='[{"pattern": "*.token", "rule_type": "glob", "enabled": true, "source": "global"}]',
        )
        # per-repo：新增一条 + 关闭 builtin 的 node_modules/ 默认
        await sync_to_async(RepoExclusionRule.objects.create)(
            repository=repo, pattern="build/", rule_type="dir", source="user"
        )
        await sync_to_async(RepoExclusionRule.objects.create)(
            repository=repo,
            pattern="node_modules/",
            rule_type="dir",
            source="global",
            enabled=False,
        )

        invalidate_matcher_cache(str(repo.id))
        matcher = await build_matcher_for_repo(str(repo.id))

        assert matcher.is_excluded(".env") is True  # builtin
        assert matcher.is_excluded("a.token") is True  # 全局设置
        assert matcher.is_excluded("build/x.o") is True  # per-repo
        # node_modules/ builtin 被 per-repo override 关闭
        assert matcher.is_excluded("node_modules/x.js") is False

    async def test_unified_is_excluded_entry(self) -> None:
        repo_id = "22222222-2222-2222-2222-222222222222"
        loader = MagicMock(return_value=list(BUILTIN_GLOBAL_DEFAULTS))
        with patch.object(exclusion, "_load_specs_from_db", loader):
            assert await is_excluded(repo_id, ".env") is True
            assert await is_excluded(repo_id, "src/app.py") is False
