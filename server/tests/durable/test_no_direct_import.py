"""适配层隔离守护：业务代码绝不直接 import procrastinate（DURABLE-01 核心约束）。

procrastinate 只能藏在 `DurableTaskService` 适配层后面。任何业务代码直接
`import procrastinate` / `from procrastinate ...` 都视为绕过适配层（T-60-02 Tampering）。
本守护用 ripgrep 扫描整个 `server/`，过滤掉允许清单后断言剩余命中为空，
CI 默认 SQLite 套件即跑。
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

# 允许直接 import procrastinate 的清单（相对 server/ 的路径前缀）：
# - durable/backends.py：适配层后端实现，隔离边界本身
# - durable/tasks.py / durable/management/：Plan 60-03 产出（@app.task / worker 命令）
# - friday/settings.py：procrastinate.contrib.django 条件注册点（Plan 60-03）
# - tests/：测试代码可直接 import 验证 procrastinate 行为
# - migrations/ / .venv/：生成代码与第三方库，非业务代码
_ALLOWED_PREFIXES = (
    "durable/backends.py",
    "durable/tasks.py",
    "durable/management/",
    "friday/settings.py",
    "tests/",
    ".venv/",
)

_PROCRASTINATE_IMPORT_RE = r"^\s*(import|from)\s+procrastinate(\.|\s|$)"


def _is_allowed(path: str) -> bool:
    norm = path.lstrip("./")
    if "/migrations/" in norm or norm.startswith("migrations/"):
        return True
    return any(norm.startswith(prefix) for prefix in _ALLOWED_PREFIXES)


def test_no_direct_procrastinate_import_in_business_code() -> None:
    """业务代码（允许清单之外）零直接 import procrastinate。"""
    rg = shutil.which("rg")
    if rg is None:
        pytest.skip("ripgrep (rg) 不可用，跳过 no-direct-import 守护")

    # pytest cwd = server/（pyproject pythonpath=["."]）；扫描整个 server/ 树。
    result = subprocess.run(
        [rg, "-l", "--type", "py", _PROCRASTINATE_IMPORT_RE, "."],
        capture_output=True,
        text=True,
        check=False,
    )
    # rg 退出码：0=有命中，1=无命中，>=2=出错。
    if result.returncode >= 2:
        raise AssertionError(f"ripgrep 扫描失败：{result.stderr.strip()}")

    hits = [line for line in result.stdout.splitlines() if line.strip()]
    offenders = [path for path in hits if not _is_allowed(path)]
    assert not offenders, (
        "DURABLE-01 违反：以下业务代码直接 import procrastinate（应经 "
        f"DurableTaskService 适配层）：\n{offenders}"
    )
