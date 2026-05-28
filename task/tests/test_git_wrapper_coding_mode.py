"""git-wrapper.sh 在 coding / coding_commit 模式下也要拦截写操作。
历史 bug：Go Runner 注入 ``FRIDAY_TASK_TASK_MODE=coding``，但 wrapper 读的是
``FRIDAY_TASK_MODE``（命名不一致），导致 coding 模式下 wrapper 完全放行，
Claude 可以随意 ``git commit / git push / git checkout master`` 把变更推到
错误分支。本测试套件验证修复后的行为：
1. ``entrypoint.sh`` 把 ``FRIDAY_TASK_TASK_MODE`` 别名到 ``FRIDAY_TASK_MODE``
2. wrapper 在 coding / coding_commit 模式下沿用 explore 的白名单（拦写放读）
3. Runner 自己用 ``/usr/bin/git`` 绕过 wrapper（``GIT_PYTHON_GIT_EXECUTABLE``）
"""
from __future__ import annotations
import subprocess
from pathlib import Path
import pytest
WRAPPER = Path(__file__).resolve.parents[1] / "git_ops" / "git-wrapper.sh"
ENTRYPOINT = Path(__file__).resolve.parents[1] / "entrypoint.sh"
def _run_wrapper(mode: str, *args: str) -> subprocess.CompletedProcess[str]:
 """以指定 FRIDAY_TASK_MODE 运行 wrapper；为避免真的执行 git，把 REAL_GIT
 指向 ``/bin/echo``，让放行命令打印参数、拦截命令仍然 exit 128。"""
 env = {
 "PATH": "/usr/bin:/bin",
 "FRIDAY_TASK_MODE": mode,
 }
 # wrapper 内 REAL_GIT 路径硬编码为 /usr/bin/git；这里通过把脚本第一行 sed
 # 替换实现 dry-run。简单做法：直接拼一段临时 wrapper。
 body = WRAPPER.read_text.replace(
 'REAL_GIT="/usr/bin/git"',
 'REAL_GIT="/bin/echo"',
 1,
 )
 return subprocess.run(
 ["bash", "-c", f"{body}\n", "_", *args],
 capture_output=True,
 text=True,
 env=env,
 timeout=5,
 )
class TestWrapperCodingMode:
 """coding 模式下 wrapper 应拦截写操作，放行只读操作。"""
 @pytest.mark.parametrize(
 "argv",
 [
 ("commit", "-m", "x"),
 ("push", "origin", "master"),
 ("checkout", "-b", "feature/x"),
 ("checkout", "master"),
 ("merge", "feature"),
 ("rebase", "main"),
 ("reset", "--hard", "HEAD~1"),
 ("branch", "-D", "feature/x"),
 ("config", "user.email", "x@y.z"),
 ],
 )
 def test_coding_mode_blocks_write_commands(self, argv: tuple[str, ...]):
 """coding 模式下 wrapper 拦截写操作，返回 128。"""
 result = _run_wrapper("coding", *argv)
 assert result.returncode == 128, (
 f"git {' '.join(argv)} 应被拦截，实际 stdout={result.stdout!r} "
 f"stderr={result.stderr!r}"
 )
 assert "forbidden" in result.stderr.lower
 @pytest.mark.parametrize(
 "argv",
 [
 ("status",),
 ("diff",),
 ("log", "--oneline", "-1"),
 ("show", "HEAD"),
 ("branch",),
 ("remote", "-v"),
 ("fetch", "origin"),
 ("rev-parse", "HEAD"),
 ("ls-files",),
 ("config", "--get", "user.email"),
 ],
 )
 def test_coding_mode_allows_read_commands(self, argv: tuple[str, ...]):
 """coding 模式下只读操作应正常放行。"""
 result = _run_wrapper("coding", *argv)
 assert result.returncode == 0, (
 f"git {' '.join(argv)} 应放行，实际 stderr={result.stderr!r}"
 )
 def test_coding_commit_mode_blocks_write_commands(self):
 """coding_commit 模式同样需要拦截写操作。"""
 result = _run_wrapper("coding_commit", "commit", "-m", "x")
 assert result.returncode == 128
 assert "forbidden" in result.stderr.lower
class TestEntrypointAliasesTaskMode:
 """entrypoint.sh 必须把 FRIDAY_TASK_TASK_MODE 别名为 FRIDAY_TASK_MODE。"""
 def test_entrypoint_exports_friday_task_mode_from_task_mode(self):
 """entrypoint.sh 在 FRIDAY_TASK_MODE 未设时复用 FRIDAY_TASK_TASK_MODE。"""
 body = ENTRYPOINT.read_text
 assert "FRIDAY_TASK_TASK_MODE" in body, (
 "entrypoint.sh 必须从 FRIDAY_TASK_TASK_MODE 派生 FRIDAY_TASK_MODE"
 )
 # 把 entrypoint.sh 顶层（``if [ $# -eq 0 ]`` 之前的部分）拷进子 shell 验证：
 # 1) FRIDAY_TASK_MODE 未设时被 export 成 coding
 snippet = body.split("if [ $# -eq 0 ]; then", 1)[0]
 result = subprocess.run(
 [
 "bash",
 "-c",
 f"{snippet}\n"
 'echo "MODE=$FRIDAY_TASK_MODE"',
 ],
 capture_output=True,
 text=True,
 env={"PATH": "/usr/bin:/bin", "FRIDAY_TASK_TASK_MODE": "coding"},
 timeout=5,
 )
 assert "MODE=coding" in result.stdout, (
 f"FRIDAY_TASK_MODE 应被设为 coding，实际 stdout={result.stdout!r} "
 f"stderr={result.stderr!r}"
 )
 # 2) 显式设置过 FRIDAY_TASK_MODE 的不被覆盖（explore 优先级保持）
 result = subprocess.run(
 [
 "bash",
 "-c",
 f"{snippet}\n"
 'echo "MODE=$FRIDAY_TASK_MODE"',
 ],
 capture_output=True,
 text=True,
 env={
 "PATH": "/usr/bin:/bin",
 "FRIDAY_TASK_TASK_MODE": "coding",
 "FRIDAY_TASK_MODE": "explore",
 },
 timeout=5,
 )
 assert "MODE=explore" in result.stdout
class TestRunnerBypassWrapperViaRealGit:
 """Runner 自己的 git 操作必须走 /usr/bin/git，绕过 wrapper。"""
 def test_commit_mode_subprocess_uses_real_git_path(self):
 """``_run_commit_mode`` 通过 subprocess_exec 调用 git 时使用 /usr/bin/git。"""
 source = (
 Path(__file__).resolve.parents[1] / "core" / "runner.py"
 ).read_text
 # 出现的 ``asyncio.create_subprocess_exec("git",`` 写法会被 wrapper 拦截，
 # 必须改成 ``"/usr/bin/git"``。
 assert 'create_subprocess_exec(\n "git"' not in source, (
 "_run_commit_mode 必须使用 /usr/bin/git 绕过 git-wrapper 拦截"
 )
 assert '/usr/bin/git' in source, (
 "_run_commit_mode 至少一处显式指向 /usr/bin/git"
 )
 def test_entrypoint_exports_gitpython_executable_env(self):
 """entrypoint.sh 必须导出 GIT_PYTHON_GIT_EXECUTABLE=/usr/bin/git，
 让 GitPython 也绕过 wrapper。"""
 body = ENTRYPOINT.read_text
 assert "GIT_PYTHON_GIT_EXECUTABLE" in body
 assert "/usr/bin/git" in body
