"""skills 文档工具名 ⊆ snapshot 键集 grep 守卫（Phase 102 UNIFY-04 / PITFALLS P5）。

纯文件读取 + 正则，无 DB。守卫 `skills/skills/*/SKILL.md` 主文档引用的 MCP 工具名
不越出 ``TOOL_SCHEMA_SNAPSHOT``：要么工具没进 snapshot，要么文档写了不存在的工具
（P5 skills 双源漂移之文档面），CI 直接红。

允许集必须并入 snapshot 全部条目的 request/response 字段名——skills 文档会用反引号
引用参数名（如 `create_document` / `create_merge_requests` 是 create_feishu_technical_plan /
execute_work_item_repo_tasks 的请求字段而非工具名），只用键集会误报。
"""

from __future__ import annotations

import re
from pathlib import Path

from mcp_tools.serializers import TOOL_SCHEMA_SNAPSHOT

# server/tests/mcp_tools/ → 上三级 = 仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_FILES = sorted(REPO_ROOT.glob("skills/skills/*/SKILL.md"))

# 只认反引号内、MCP 工具名动词前缀开头的 snake_case token
_TOOL_TOKEN_RE = re.compile(
    r"`((?:search|create|get|list|execute|improve|analyze|summarize|route|find|grep|read|report|lookup|reverse|update)_[a-z0-9_]+)`"
)


def _allowed_tokens() -> set[str]:
    """snapshot 键集 ∪ 全部条目的 request/response 字段名集合。"""
    allowed: set[str] = set(TOOL_SCHEMA_SNAPSHOT)
    for entry in TOOL_SCHEMA_SNAPSHOT.values():
        for side in ("request", "response"):
            fields = entry.get(side) or []
            allowed.update(str(f) for f in fields)  # type: ignore[union-attr]
    return allowed


def test_skill_files_discovered() -> None:
    """防路径解析漂移让主守卫静默空跑假绿：SKILL.md ≥ 4 个。"""
    assert len(SKILL_FILES) >= 4, (
        f"仅发现 {len(SKILL_FILES)} 个 skills/skills/*/SKILL.md（预期 ≥4："
        f"friday / friday-code / friday-feishu / friday-memory）；"
        f"REPO_ROOT 解析可能漂移：{REPO_ROOT}"
    )


def test_tool_token_prefixes_cover_all_snapshot_keys() -> None:
    """前缀表自检（102-REVIEW LO-03）：_TOOL_TOKEN_RE 必须能匹配 snapshot 全部工具名。

    否则新前缀（如 pack_* / apply_* / submit_*）的工具进 snapshot 后，文档里
    引用它的 token 不被主守卫识别——守卫静默失效（漏检而非误报，无 CI 信号）。
    本断言让新前缀工具进 snapshot 时 CI 直接红，提醒扩前缀表。
    """
    unmatched = sorted(
        name for name in TOOL_SCHEMA_SNAPSHOT if not _TOOL_TOKEN_RE.fullmatch(f"`{name}`")
    )
    assert not unmatched, (
        "_TOOL_TOKEN_RE 的动词前缀表未覆盖以下 snapshot 工具名（主守卫会静默漏检"
        f"文档中对它们的引用），请扩展前缀表：{unmatched}"
    )


def test_skill_tool_references_subset_of_snapshot() -> None:
    """skills 文档引用的 MCP 工具名 ⊆ snapshot 键集 ∪ request/response 字段名集。"""
    allowed = _allowed_tokens()
    violations: dict[str, set[str]] = {}
    for skill_file in SKILL_FILES:
        text = skill_file.read_text(encoding="utf-8")
        tokens = set(_TOOL_TOKEN_RE.findall(text))
        out_of_bounds = tokens - allowed
        if out_of_bounds:
            violations[str(skill_file.relative_to(REPO_ROOT))] = out_of_bounds

    detail = "\n".join(
        f"  {path}: {sorted(tokens)}" for path, tokens in sorted(violations.items())
    )
    assert not violations, (
        "skills 文档引用了 snapshot 之外的工具名：要么工具没进 TOOL_SCHEMA_SNAPSHOT，"
        "要么文档写了不存在的工具（P5 文档面漂移）：\n" + detail
    )
