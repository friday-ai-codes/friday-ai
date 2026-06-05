"""Pitfall 2 防御 grep gate（per initial implementation contract）。

禁止在 server/code_relations/ 内出现「for ...: ... set_payload(...)」循环单点
set_payload 模式；payload sync 必须走 QdrantService.batch_set_payload（plan 02
交付）+ 底层 client.batch_update_points + SetPayloadOperation。

ripgrep 在 macOS / Linux CI 均可用；项目 251 plan 02 test_migration.py 已确立
subprocess.run(['rg', ...]) 模式，本测试沿用。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET_DIR = REPO_ROOT / "server" / "code_relations"

# 多行匹配：`for X:` 行 + 紧随同行或下一行的 `set_payload(`
SET_PAYLOAD_LOOP_PATTERN = (
    r"for\s+[^\n]+:\s*(?:[^\n]*|\n\s+[^\n]*)\bset_payload\s*\("
)


def test_no_loop_set_payload_in_code_relations() -> None:
    """server/code_relations/ 内不得存在 for ...: ... set_payload(...) 模式。"""
    result = subprocess.run(
        [
            "rg",
            "-U",
            "--multiline-dotall",
            "-P",
            SET_PAYLOAD_LOOP_PATTERN,
            str(TARGET_DIR),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, (
        "Pitfall 2 violation：server/code_relations/ 出现循环单 set_payload 调用。\n"
        "必须改用 QdrantService.batch_set_payload(updates, batch_size=500, "
        "timeout=30.0) 走 batch_update_points + SetPayloadOperation。\n"
        f"ripgrep stdout:\n{result.stdout}"
    )
