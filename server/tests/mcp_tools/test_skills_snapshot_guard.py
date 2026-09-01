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
    r"`((?:search|create|get|list|execute|improve|analyze|summarize|route|find|grep|read|report|lookup|reverse|update|confirm|answer|approve|request|apply|generate|start|detect|graph|impact|rename|trace)_[a-z0-9_]+)`"
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


def test_capture_and_project_memory_responsibilities_stay_separate() -> None:
    """145-05-01 / D-09：各入口同步声明 Capture 与项目交付记忆的职责边界。"""
    skills_root = REPO_ROOT / "skills" / "skills"
    documents = [
        skills_root / "friday" / "SKILL.md",
        skills_root / "friday-dev" / "SKILL.md",
        skills_root / "friday-memory" / "SKILL.md",
    ]
    for relative in (
        ("friday-dev", "references", "http-fallback.md"),
        ("friday-memory", "references", "http-fallback.md"),
    ):
        document = skills_root.joinpath(*relative)
        if document.exists():
            documents.append(document)

    required_terms = {
        "report_session_knowledge",
        "report_project_knowledge",
        "clean tree",
        "用户可见",
        "最终答案",
        "transcript",
        "隐藏思维链",
        "凭证",
        "职责",
    }
    missing: dict[str, list[str]] = {}
    for document in documents:
        text = document.read_text(encoding="utf-8")
        absent = sorted(term for term in required_terms if term not in text)
        if absent:
            missing[str(document.relative_to(REPO_ROOT))] = absent

    assert not missing, f"会话 Capture 与项目交付记忆职责文档不完整：{missing}"


def test_friday_solution_documents_canonical_blueprint_controller() -> None:
    """主文与 HTTP fallback 都必须保留蓝图人审/CAS/编码门禁完整协议。"""
    solution_dir = REPO_ROOT / "skills" / "skills" / "friday-solution"
    documents = (
        solution_dir / "SKILL.md",
        solution_dir / "references" / "http-fallback.md",
    )
    required_terms = {
        "idempotency_key",
        "blueprint_project_id",
        "get_technical_blueprint",
        "answer_blueprint_clarification",
        "request_technical_blueprint_changes",
        "approve_technical_blueprint",
        "artifact_version_id",
        "content_hash",
        "confirmed",
        "Coding",
        "orphan",
        "cancelled",
    }

    missing: dict[str, list[str]] = {}
    for document in documents:
        text = document.read_text(encoding="utf-8")
        absent = sorted(term for term in required_terms if term not in text)
        if absent:
            missing[str(document.relative_to(REPO_ROOT))] = absent

    assert not missing, f"friday-solution canonical blueprint 协议不完整：{missing}"


def test_friday_solution_separates_project_space_team_route_and_research_roles() -> None:
    """技术方案控制器不得再从 Space 猜 Project/Team，或由 route 预判 direct。"""
    solution_dir = REPO_ROOT / "skills" / "skills" / "friday-solution"
    documents = (
        solution_dir / "SKILL.md",
        solution_dir / "references" / "http-fallback.md",
    )
    required_invariants = {
        "Space-scoped unbound blueprint",
        "不得仅因 Project 缺失而阻断",
        "不能把 Space 全仓当 Team",
        "Team 缺失或存在歧义时",
        "PRD、feature list、测试 case、飞书字段、技术文档与显式仓库名",
        "突破 Top-N 候选预算",
        "route 阶段只产 candidate",
        "逐仓 research 决定",
        "具体 file/API/model 拟修改位置",
        "`unsuitable` 必须归为 `irrelevant`",
    }

    missing: dict[str, list[str]] = {}
    for document in documents:
        text = " ".join(document.read_text(encoding="utf-8").split())
        absent = sorted(term for term in required_invariants if term not in text)
        if absent:
            missing[str(document.relative_to(REPO_ROOT))] = absent

    assert not missing, f"friday-solution 身份、范围与职责边界契约不完整：{missing}"


def test_friday_solution_cancelled_orphan_is_strictly_read_only() -> None:
    """cancelled/orphan 只能对账，不能复活 Issue 或推进 Friday 状态机。"""
    solution_dir = REPO_ROOT / "skills" / "skills" / "friday-solution"
    documents = (
        solution_dir / "SKILL.md",
        solution_dir / "references" / "http-fallback.md",
    )
    required_invariants = {
        "Issue 状态与 Friday artifact 均为只读",
        "禁止把 `cancelled` 改为 `blocked`、`in_progress` 或 `done`",
        "禁止调用 `create_feishu_technical_plan`",
        "禁止调用 `answer_blueprint_clarification`",
        "禁止调用 `approve_technical_blueprint`",
        "禁止调用 `request_technical_blueprint_changes`",
        "禁止调用 `start_repo_research`",
        "禁止派发 Coding",
        "只有宿主策略明确允许时",
        "`metadata` 或评论",
    }

    missing: dict[str, list[str]] = {}
    for document in documents:
        text = " ".join(document.read_text(encoding="utf-8").split())
        absent = sorted(term for term in required_invariants if term not in text)
        if absent:
            missing[str(document.relative_to(REPO_ROOT))] = absent

    assert not missing, f"friday-solution cancelled/orphan 只读不变量不完整：{missing}"


def test_friday_solution_rechecks_cancellation_immediately_before_every_mutation() -> None:
    """写入前必须用 Issue revision/status 做 CAS，关闭运行中取消的 TOCTOU 窗口。"""
    solution_dir = REPO_ROOT / "skills" / "skills" / "friday-solution"
    documents = (
        solution_dir / "SKILL.md",
        solution_dir / "references" / "http-fallback.md",
    )
    required_invariants = {
        "每一次写操作都必须独立执行",
        "紧邻写入前",
        "重新读取宿主 Issue",
        "`status` 与 `revision`",
        "`expected_revision`",
        "CAS",
        "读取与写入之间不得执行其他操作",
        "revision 已变化",
        "立即重新预检",
        "fail-closed",
        "Issue 状态写入",
        "Issue metadata 写入",
        "Issue 评论写入",
        "`create_feishu_technical_plan`",
        "`answer_blueprint_clarification`",
        "`approve_technical_blueprint`",
        "`request_technical_blueprint_changes`",
        "`start_repo_research`",
        "`create_feature_tech_plan`",
        "`confirm_feature_tech_plan`",
    }

    missing: dict[str, list[str]] = {}
    for document in documents:
        text = " ".join(document.read_text(encoding="utf-8").split())
        absent = sorted(term for term in required_invariants if term not in text)
        if absent:
            missing[str(document.relative_to(REPO_ROOT))] = absent

    assert not missing, f"friday-solution 写时取消 preflight/CAS 不变量不完整：{missing}"


def test_friday_solution_repo_confirmation_fails_closed_without_research_evidence() -> None:
    """仓库深调研失败或证据为空时，禁止把候选集包装成人工可确认问题。"""
    solution_dir = REPO_ROOT / "skills" / "skills" / "friday-solution"
    documents = (
        solution_dir / "SKILL.md",
        solution_dir / "references" / "http-fallback.md",
    )
    required_invariants = {
        '`task_status` 为 `failed`',
        "`responsibility` 为空",
        "`fitness.reasons` 为空",
        "`current_state_summary` 为空",
        "不得发布或展示为可回答的 `repo_confirmation`",
        "不得调用 `answer_blueprint_clarification`",
        "必须标记为调研失败",
        "重跑 repo_research",
    }

    missing: dict[str, list[str]] = {}
    for document in documents:
        text = " ".join(document.read_text(encoding="utf-8").split())
        absent = sorted(term for term in required_invariants if term not in text)
        if absent:
            missing[str(document.relative_to(REPO_ROOT))] = absent

    assert not missing, f"friday-solution 仓库确认 fail-closed 不变量不完整：{missing}"
