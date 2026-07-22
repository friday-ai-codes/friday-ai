"""AGENT-03 skills 注入测试：hash 一致性（防双源漂移）+ 运行时注入。

两组测试：
1. hash 一致性（PITFALLS P5 核心钉）：task/assets/skills/ 与仓库根
   skills/skills/ 对应目录逐文件 sha256 一致；仓库根不可达（task 独立
   构建上下文）时 skip 并说明。
2. 运行时注入单测：TaskRunner._inject_skills 的拷贝 / 同名跳过不覆盖 /
   源缺失静默降级三条断言。
"""

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core import runner as runner_module
from core.runner import TaskRunner

SKILL_NAMES = ("friday-code", "friday-memory")


def _find_repo_root() -> Path | None:
    """从测试文件向上逐级查找含 skills/skills/friday-code/SKILL.md 的仓库根。"""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "skills" / "skills" / "friday-code" / "SKILL.md").is_file():
            return candidate
    return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_file_map(base: Path) -> dict[str, str]:
    """递归收集 {相对路径: sha256}。"""
    return {str(p.relative_to(base)): _sha256(p) for p in sorted(base.rglob("*")) if p.is_file()}


class TestSkillsHashConsistency:
    """task/assets/skills/ 与 skills/skills/ 逐文件 hash 一致（防双源漂移）。"""

    @pytest.mark.parametrize("skill_name", SKILL_NAMES)
    def test_assets_match_source(self, skill_name):
        repo_root = _find_repo_root()
        if repo_root is None:
            pytest.skip("repo root not reachable — task 独立构建上下文")

        source = repo_root / "skills" / "skills" / skill_name
        assets = repo_root / "task" / "assets" / "skills" / skill_name
        assert source.is_dir(), f"源目录缺失: {source}"
        assert assets.is_dir(), (
            f"assets 目录缺失: {assets}，请跑 python task/scripts/sync_skills.py 重新同步"
        )

        source_map = _relative_file_map(source)
        assets_map = _relative_file_map(assets)

        assert set(source_map) == set(assets_map), (
            f"{skill_name} 文件集合不一致（双源漂移），"
            "请跑 python task/scripts/sync_skills.py 重新同步；"
            f"仅在源: {set(source_map) - set(assets_map)}，"
            f"仅在 assets: {set(assets_map) - set(source_map)}"
        )
        for rel_path, digest in source_map.items():
            assert assets_map[rel_path] == digest, (
                f"{skill_name}/{rel_path} 内容漂移，"
                "请跑 python task/scripts/sync_skills.py 重新同步"
            )


class TestRuntimeInjection:
    """TaskRunner._inject_skills 运行时注入行为。"""

    def _make_runner(self, workspace: Path) -> TaskRunner:
        """构造绕过 __init__ 的 TaskRunner，只挂注入所需依赖。"""
        runner = TaskRunner.__new__(TaskRunner)
        runner.git_ops = MagicMock()
        runner.git_ops.get_workspace_path.return_value = str(workspace)
        return runner

    def _make_fake_image_skills(self, base: Path) -> Path:
        """在 tmp 下构造假镜像 skills 目录（两个技能）。"""
        image_dir = base / "opt-friday-skills"
        for name in SKILL_NAMES:
            (image_dir / name / "references").mkdir(parents=True)
            (image_dir / name / "SKILL.md").write_text(f"# {name}\n镜像版内容")
            (image_dir / name / "references" / "ref.md").write_text("参考")
        return image_dir

    def test_inject_copies_all_skills(self, tmp_path, monkeypatch):
        """(a) 两技能完整拷达 workspace/.claude/skills/。"""
        image_dir = self._make_fake_image_skills(tmp_path)
        monkeypatch.setattr(runner_module, "IMAGE_SKILLS_DIR", image_dir)
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        runner = self._make_runner(workspace)
        runner._inject_skills(MagicMock())

        for name in SKILL_NAMES:
            target = workspace / ".claude" / "skills" / name
            assert (target / "SKILL.md").is_file()
            assert (target / "references" / "ref.md").is_file()

    def test_inject_skips_existing_same_name(self, tmp_path, monkeypatch):
        """(b) workspace 预置同名 friday-code 不被覆盖；friday-memory 正常拷入。"""
        image_dir = self._make_fake_image_skills(tmp_path)
        monkeypatch.setattr(runner_module, "IMAGE_SKILLS_DIR", image_dir)
        workspace = tmp_path / "workspace"
        preexisting = workspace / ".claude" / "skills" / "friday-code"
        preexisting.mkdir(parents=True)
        (preexisting / "SKILL.md").write_text("# 仓库自带版本，不许覆盖")

        runner = self._make_runner(workspace)
        runner._inject_skills(MagicMock())

        # 仓库自带优先，内容原样保留
        assert (preexisting / "SKILL.md").read_text() == "# 仓库自带版本，不许覆盖"
        assert not (preexisting / "references").exists()
        # 另一个技能正常注入
        memory = workspace / ".claude" / "skills" / "friday-memory"
        assert (memory / "SKILL.md").is_file()

    def test_inject_silently_skips_when_source_missing(self, tmp_path, monkeypatch):
        """(c) 镜像无 skills 目录（本地 CLI / 旧镜像）时不抛异常、不创建目标。"""
        monkeypatch.setattr(runner_module, "IMAGE_SKILLS_DIR", tmp_path / "does-not-exist")
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        runner = self._make_runner(workspace)
        runner._inject_skills(MagicMock())  # 不应抛异常

        assert not (workspace / ".claude" / "skills").exists()

    def test_inject_swallows_exceptions(self, tmp_path, monkeypatch):
        """注入 best-effort：内部异常被吞掉只 warning，绝不挂任务。"""
        image_dir = self._make_fake_image_skills(tmp_path)
        monkeypatch.setattr(runner_module, "IMAGE_SKILLS_DIR", image_dir)

        runner = TaskRunner.__new__(TaskRunner)
        runner.git_ops = MagicMock()
        runner.git_ops.get_workspace_path.side_effect = RuntimeError("boom")

        log = MagicMock()
        runner._inject_skills(log)  # 不应抛异常
        log.warning.assert_called_once()
