"""GitOperations 把 Friday 运行时暂存目录 .friday/ 写进 .git/info/exclude 的回归测试。

复现并锁定线上报错「Explore 模式结束后工作区存在未提交变更: ?? .friday/」的根因侧修复：
Friday 会往 /workspace/.friday/ 写 usage.json / answer.json，属自身产物而非用户改动。
setup 阶段把 .friday/ 写入本地 info/exclude 后，它不再出现在 git status，也不会被
git add -A 误提交。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

from git_ops import GitOperations


@pytest.fixture
def real_repo(tmp_path):
    """构造一个含初始提交的真实临时 git 仓库。"""
    repo = Repo.init(tmp_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    (tmp_path / "README.md").write_text("hello\n")
    repo.index.add(["README.md"])
    repo.index.commit("init")
    return repo


@pytest.fixture
def ops_with_real_repo(mock_config, real_repo, tmp_path):
    ops = GitOperations(mock_config)
    ops.workspace = tmp_path
    ops.repo = real_repo
    return ops


def test_friday_scratch_added_to_git_exclude(ops_with_real_repo, tmp_path):
    """写入 .git/info/exclude 后，工作区里的 .friday/ 不出现在 git status。"""
    ops_with_real_repo._ensure_friday_scratch_excluded()

    exclude_file = Path(ops_with_real_repo.repo.git_dir) / "info" / "exclude"
    assert ".friday/" in exclude_file.read_text().split()

    # 模拟 Friday 写入运行时产物
    friday_dir = tmp_path / ".friday"
    friday_dir.mkdir()
    (friday_dir / "usage.json").write_text("{}")

    status = ops_with_real_repo.repo.git.status("--porcelain")
    assert ".friday" not in status


def test_friday_scratch_exclude_idempotent(ops_with_real_repo):
    """重复调用不重复写入 .friday/ 条目。"""
    ops_with_real_repo._ensure_friday_scratch_excluded()
    ops_with_real_repo._ensure_friday_scratch_excluded()

    exclude_file = Path(ops_with_real_repo.repo.git_dir) / "info" / "exclude"
    lines = [line for line in exclude_file.read_text().splitlines() if line.strip() == ".friday/"]
    assert len(lines) == 1


def test_friday_scratch_exclude_noop_without_repo(mock_config):
    """repo 为 None 时安全返回，不抛异常。"""
    ops = GitOperations(mock_config)
    ops.repo = None
    ops._ensure_friday_scratch_excluded()  # 不应抛异常
