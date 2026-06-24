"""Phase 22-04 Task 2 守卫：编码容器侧 clone 后 prune 被排除文件（fail-closed）。

覆盖（T-22-13 / T-22-15 / T-22-16）：
- prune_excluded 删除命中 dir/glob/regex 的工作树文件，保留正常文件。
- ``.git/`` 目录不被删除（git 元数据完整）。
- TaskConfig 从 FRIDAY_TASK_EXCLUDE_PATTERNS（JSON）解析出 exclude_patterns。
- 空规则/未设置 → 不删任何文件且不报错。
- 持久删除失败 → 重试后抛 ExclusionPruneError（被排除文件绝不静默残留可读）。
- 可恢复失败（首次失败、chmod 后第二次成功）→ 文件最终被删除，不抛。
- git_ops.setup 在 clone+checkout 后调用 prune，持久失败向上传播使 setup 失败。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def _write(workspace: Path, rel: str, content: str = "x") -> Path:
    p = workspace / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def _rules(*pairs: tuple[str, str]) -> list[dict]:
    return [{"pattern": pat, "rule_type": rt} for pat, rt in pairs]


class TestPruneExcluded:
    def test_deletes_dir_glob_regex_keeps_normal(self, tmp_path: Path) -> None:
        from core.exclusion import prune_excluded

        _write(tmp_path, ".env", "SECRET=1")
        _write(tmp_path, "secrets/x.json", "{}")
        _write(tmp_path, "certs/server.pem", "key")
        _write(tmp_path, "custom/leak.token", "tok")
        keep_main = _write(tmp_path, "src/main.py", "print()")
        keep_readme = _write(tmp_path, "README.md", "# hi")

        rules = _rules(
            (".env", "glob"),
            ("secrets/", "dir"),
            ("*.pem", "glob"),
            (r"custom/.*\.token", "regex"),
        )
        deleted = prune_excluded(tmp_path, rules)

        assert not (tmp_path / ".env").exists()
        assert not (tmp_path / "secrets" / "x.json").exists()
        assert not (tmp_path / "certs" / "server.pem").exists()
        assert not (tmp_path / "custom" / "leak.token").exists()
        assert keep_main.exists()
        assert keep_readme.exists()
        assert deleted == 4

    def test_bare_glob_prunes_subdir_secrets(self, tmp_path: Path) -> None:
        # BL-01：无分隔符 glob 按 basename 命中任意子目录，子目录密钥也被 prune。
        from core.exclusion import prune_excluded

        _write(tmp_path, "server/.env", "SECRET=1")
        _write(tmp_path, "web/.env", "SECRET=2")
        _write(tmp_path, "deploy/id_rsa", "key")
        keep = _write(tmp_path, "server/.env.example", "TEMPLATE")

        deleted = prune_excluded(tmp_path, _rules((".env", "glob"), ("id_rsa", "glob")))

        assert not (tmp_path / "server" / ".env").exists()
        assert not (tmp_path / "web" / ".env").exists()
        assert not (tmp_path / "deploy" / "id_rsa").exists()
        assert keep.exists()
        assert deleted == 3

    def test_redos_regex_skipped_no_hang(self, tmp_path: Path) -> None:
        # HI-01：嵌套量词 regex 被跳过（不编译进 walk 热路径，避免卡死）。
        from core.exclusion import prune_excluded

        keep = _write(tmp_path, "aaaa", "x")
        # 高风险 regex 被跳过 → 该文件不被该规则命中（fail-open 单条，换取不挂起）。
        deleted = prune_excluded(tmp_path, [{"pattern": "(a+)+$", "rule_type": "regex"}])
        assert deleted == 0
        assert keep.exists()

    def test_global_glob_case_insensitive_prune(self, tmp_path: Path) -> None:
        # ME-01：source="global" 安全默认大小写不敏感，挡住 .ENV / ID_RSA 变体。
        from core.exclusion import prune_excluded

        _write(tmp_path, "server/.ENV", "SECRET=1")
        _write(tmp_path, "deploy/ID_RSA", "key")
        rules = [
            {"pattern": ".env", "rule_type": "glob", "source": "global"},
            {"pattern": "id_rsa", "rule_type": "glob", "source": "global"},
        ]
        deleted = prune_excluded(tmp_path, rules)

        assert not (tmp_path / "server" / ".ENV").exists()
        assert not (tmp_path / "deploy" / "ID_RSA").exists()
        assert deleted == 2

    def test_git_dir_preserved(self, tmp_path: Path) -> None:
        from core.exclusion import prune_excluded

        # 模拟 git 元数据
        _write(tmp_path, ".git/HEAD", "ref: refs/heads/main")
        _write(tmp_path, ".git/config", "[core]")
        _write(tmp_path, ".env", "SECRET=1")

        # 即便规则含 .git/ dir，prune 也绝不删除 .git（否则破坏 commit/push）。
        rules = _rules((".git/", "dir"), (".env", "glob"))
        prune_excluded(tmp_path, rules)

        assert (tmp_path / ".git" / "HEAD").exists()
        assert (tmp_path / ".git" / "config").exists()
        assert not (tmp_path / ".env").exists()

    def test_empty_rules_no_deletion(self, tmp_path: Path) -> None:
        from core.exclusion import prune_excluded

        f = _write(tmp_path, ".env", "SECRET=1")
        assert prune_excluded(tmp_path, []) == 0
        assert f.exists()

    def test_persistent_delete_failure_raises_and_file_remains(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import exclusion
        from core.exclusion import ExclusionPruneError, prune_excluded

        env = _write(tmp_path, ".env", "SECRET=1")

        def _always_fail(path: str | os.PathLike) -> None:
            raise OSError("EACCES persistent")

        monkeypatch.setattr(exclusion.os, "remove", _always_fail)

        with pytest.raises(ExclusionPruneError):
            prune_excluded(tmp_path, _rules((".env", "glob")))

        # fail-closed：被排除文件不允许在“成功”路径上残留——这里删不掉就必须抛。
        assert env.exists()

    def test_recoverable_delete_failure_then_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import exclusion
        from core.exclusion import prune_excluded

        env = _write(tmp_path, ".env", "SECRET=1")
        real_remove = os.remove
        calls = {"n": 0}

        def _flaky(path: str | os.PathLike) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("first attempt fails")
            real_remove(path)

        monkeypatch.setattr(exclusion.os, "remove", _flaky)

        deleted = prune_excluded(tmp_path, _rules((".env", "glob")))

        assert deleted == 1
        assert not env.exists()
        assert calls["n"] >= 2


class TestTaskConfigExcludePatterns:
    def test_parses_exclude_patterns_from_env(
        self, monkeypatch: pytest.MonkeyPatch, temp_session_dir: str
    ) -> None:
        from core import TaskConfig

        payload = json.dumps(
            [{"pattern": ".env", "rule_type": "glob"}, {"pattern": "secrets/", "rule_type": "dir"}]
        )
        monkeypatch.setenv("FRIDAY_TASK_EXCLUDE_PATTERNS", payload)

        config = TaskConfig(
            task_id="t1",
            task_description="desc",
            git_repo_url="git@github.com:test/repo.git",
            session_dir=temp_session_dir,
        )

        assert config.exclude_patterns == [
            {"pattern": ".env", "rule_type": "glob"},
            {"pattern": "secrets/", "rule_type": "dir"},
        ]

    def test_default_empty(self, monkeypatch: pytest.MonkeyPatch, temp_session_dir: str) -> None:
        from core import TaskConfig

        monkeypatch.delenv("FRIDAY_TASK_EXCLUDE_PATTERNS", raising=False)
        config = TaskConfig(
            task_id="t1",
            task_description="desc",
            git_repo_url="git@github.com:test/repo.git",
            session_dir=temp_session_dir,
        )
        assert config.exclude_patterns == []


class TestGitOpsSetupPrune:
    @pytest.mark.asyncio
    async def test_setup_propagates_prune_error(
        self, monkeypatch: pytest.MonkeyPatch, temp_session_dir: str
    ) -> None:
        """setup 在 clone+checkout 后 prune；持久删除失败 → ExclusionPruneError 传播（setup 失败）。"""
        from core import TaskConfig
        from core import exclusion
        from core.exclusion import ExclusionPruneError
        from git_ops.operations import GitOperations

        config = TaskConfig(
            task_id="prune-setup",
            task_description="desc",
            git_repo_url="https://git.example.com/x.git",
            git_access_token="",
            session_dir=temp_session_dir,
            exclude_patterns=[{"pattern": ".env", "rule_type": "glob"}],
        )
        ops = GitOperations(config)

        async def _fake_clone() -> None:
            # 模拟 clone：往 setup 创建的 workspace 写入一个被排除文件。
            assert ops.workspace is not None
            (ops.workspace / ".env").write_text("SECRET=1")

        async def _fake_checkout() -> None:
            return None

        monkeypatch.setattr(ops, "_clone_repo", _fake_clone)
        monkeypatch.setattr(ops, "_checkout_branch", _fake_checkout)
        monkeypatch.setattr(
            exclusion.os, "remove", lambda _p: (_ for _ in ()).throw(OSError("nope"))
        )

        with pytest.raises(ExclusionPruneError):
            await ops.setup()

        # 被排除文件删不掉 → setup 必须失败（不静默成功）
        assert ops.workspace is not None
        assert (ops.workspace / ".env").exists()
        ops.cleanup()

    @pytest.mark.asyncio
    async def test_setup_prunes_on_success(
        self, monkeypatch: pytest.MonkeyPatch, temp_session_dir: str
    ) -> None:
        from core import TaskConfig
        from git_ops.operations import GitOperations

        config = TaskConfig(
            task_id="prune-ok",
            task_description="desc",
            git_repo_url="https://git.example.com/x.git",
            session_dir=temp_session_dir,
            exclude_patterns=[{"pattern": ".env", "rule_type": "glob"}],
        )
        ops = GitOperations(config)

        async def _fake_clone() -> None:
            assert ops.workspace is not None
            (ops.workspace / ".env").write_text("SECRET=1")
            (ops.workspace / "main.py").write_text("print()")

        async def _fake_checkout() -> None:
            return None

        monkeypatch.setattr(ops, "_clone_repo", _fake_clone)
        monkeypatch.setattr(ops, "_checkout_branch", _fake_checkout)

        await ops.setup()

        assert ops.workspace is not None
        assert not (ops.workspace / ".env").exists()
        assert (ops.workspace / "main.py").exists()
        ops.cleanup()

    @pytest.mark.asyncio
    async def test_setup_failclosed_on_empty_workspace(
        self, monkeypatch: pytest.MonkeyPatch, temp_session_dir: str
    ) -> None:
        """clone 后工作区除 .git 外为空 → setup 必须 fail-closed（防 agent 越界分析 /app）。"""
        from core import TaskConfig
        from git_ops.operations import GitOperations

        config = TaskConfig(
            task_id="empty-ws",
            task_description="desc",
            git_repo_url="https://git.example.com/x.git",
            session_dir=temp_session_dir,
        )
        ops = GitOperations(config)

        async def _fake_clone() -> None:
            # 模拟「clone 没就位」：只建出 .git 元数据目录，无任何工作树文件。
            assert ops.workspace is not None
            (ops.workspace / ".git").mkdir()

        async def _fake_checkout() -> None:
            return None

        monkeypatch.setattr(ops, "_clone_repo", _fake_clone)
        monkeypatch.setattr(ops, "_checkout_branch", _fake_checkout)

        with pytest.raises(RuntimeError, match="empty"):
            await ops.setup()
        ops.cleanup()
