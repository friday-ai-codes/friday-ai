"""分支名生成与校验 service。

提供分支类型推断、短描述提取、模板格式拼接、以及多层校验逻辑
（字符集/长度/保护分支/唯一性）。供 coding_tools 和 DispatchTask 使用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

import structlog

from services.git_platform.base import GitPlatformClient

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 关键词集合 — 用于 tech_plan 类型推断
# ---------------------------------------------------------------------------

_FIX_KEYWORDS: set[str] = {
    "修复", "bug", "fix", "bugfix", "hotfix", "错误", "异常", "崩溃",
}

_CHORE_KEYWORDS: set[str] = {
    "重构", "清理", "迁移", "chore", "refactor", "cleanup", "migrate", "ci", "docs",
}

_TEST_KEYWORDS: set[str] = {
    "测试", "单测", "用例", "test", "tests", "testing", "ut", "e2e",
}

# ---------------------------------------------------------------------------
# 保护分支
# ---------------------------------------------------------------------------

# PR 默认目标分支：团队工作流默认并入 develop，而非 master。用户未在前端选择 /
# 旧数据为空时回退到此值。集中定义避免多处 "develop" 字面量漂移。
DEFAULT_TARGET_BRANCH = "develop"

DEFAULT_PROTECTED_BRANCHES: set[str] = {"main", "master", "develop"}

DEFAULT_PROTECTED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^release/"),
    re.compile(r"^hotfix/"),
]

# ---------------------------------------------------------------------------
# 停用词 — 从短描述中过滤
# ---------------------------------------------------------------------------

_STOP_WORDS: set[str] = {
    "a", "an", "the", "is", "are", "to", "for", "of", "in",
    "on", "with", "and", "or", "by", "at", "from", "as",
}

# ---------------------------------------------------------------------------
# 分支名字符集正则
# ---------------------------------------------------------------------------

# 允许中文：Python re 的 \w（默认 Unicode）匹配中文/字母/数字/下划线，再额外允许
# . / -。空格与 git 保留符号（~ ^ : ? * [ ] \ 等）不在白名单内，天然被拒。
_VALID_BRANCH_CHARS = re.compile(r"^[\w./\-]+$", re.UNICODE)

# 分支名片段清洗：去掉空格与 git 保留 / 易出问题的符号（生成简短名时用）。
_BRANCH_SEGMENT_STRIP = re.compile(r"[\s~^:?*\[\]\\@{}()，。、！？；：'\"<>|#$%&+=]+")


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class BranchValidationResult:
    """分支名校验结果。"""

    valid: bool
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 核心函数
# ---------------------------------------------------------------------------


def infer_branch_type(tech_plan: str) -> str:
    """根据 tech_plan 关键词推断分支类型。

    优先级：fix > test > chore > feat（默认）。

    Args:
        tech_plan: 技术方案文本。

    Returns:
        分支类型字符串："feat" | "fix" | "chore" | "test"。
    """
    lower = tech_plan.lower()

    for kw in _FIX_KEYWORDS:
        if kw in lower:
            return "fix"

    for kw in _TEST_KEYWORDS:
        if kw in lower:
            return "test"

    for kw in _CHORE_KEYWORDS:
        if kw in lower:
            return "chore"

    return "feat"


def sanitize_branch_segment(text: str, *, max_chars: int = 10) -> str:
    """把任意文本清洗为分支名可用的简短片段。

    去除空格与 git 保留 / 易出问题符号，按字符截断到 ``max_chars``（中文优先，
    1 个汉字算 1 字）。清洗后为空返回空串，由调用方决定兜底。
    """
    if not text:
        return ""
    # 取首个非空行，剥离常见 markdown 标记
    for raw_line in text.splitlines():
        line = re.sub(r"^#{1,6}\s*", "", raw_line).strip()
        line = line.strip("*`>-_ \t")
        if line:
            text = line
            break
    cleaned = _BRANCH_SEGMENT_STRIP.sub("", text)
    cleaned = cleaned.strip("./-")
    return cleaned[:max_chars]


def generate_short_description(tech_plan: str) -> str:
    """从 tech_plan 规则提取简短名称（中文优先，<=10 字）。

    同步快速路径 / AI 生成失败时的兜底：取首个有意义行清洗截断。无法提取时返回
    "task"。AI 生成走 ``agenerate_short_description``。

    Args:
        tech_plan: 技术方案文本。

    Returns:
        简短名称（中文/字母数字，<=10 字），无内容时 "task"。
    """
    return sanitize_branch_segment(tech_plan, max_chars=10) or "task"


async def agenerate_short_description(tech_plan: str) -> str:
    """用 LLM 从技术方案生成 <=10 字简短中文分支描述；失败回退规则提取。"""
    fallback = generate_short_description(tech_plan)
    if not (tech_plan or "").strip():
        return fallback

    try:
        import anthropic

        from services.provider_config import aget_claude_code_runtime_config

        cc = await aget_claude_code_runtime_config()
        api_key = cc["api_key"]
        if not api_key:
            return fallback
        base_url = cc["base_url"]
        model = (
            cc["haiku_model"]
            or cc["default_model"]
            or cc["sonnet_model"]
            or "claude-haiku-4-5"
        )
        client = (
            anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)
            if base_url
            else anthropic.AsyncAnthropic(api_key=api_key)
        )
        prompt = (
            "根据以下技术方案，生成一个用于 git 分支名的简短中文描述。\n"
            "要求：10 个汉字以内，只概括核心改动，不要标点、不要空格、不要引号、"
            "不要前后缀，只输出描述本身。\n\n"
            f"技术方案：\n{tech_plan[:1500]}"
        )
        resp = await client.messages.create(
            model=model,
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()  # type: ignore[union-attr]
        cleaned = sanitize_branch_segment(text, max_chars=10)
        return cleaned or fallback
    except Exception as exc:  # noqa: BLE001
        logger.warning("branch_short_desc_ai_failed", error=str(exc))
        return fallback


def generate_branch_name(branch_type: str, short_desc: str) -> str:
    """拼接 {type}/{yymmdd}.{desc} 格式分支名。

    示例：``feat/260618.修复若干bug``。

    Args:
        branch_type: 分支类型（feat/fix/chore/test）。
        short_desc: 简短名称（中文优先）。

    Returns:
        格式化的分支名。
    """
    date_str = datetime.now(timezone.utc).strftime("%y%m%d")
    return f"{branch_type}/{date_str}.{short_desc}"


async def validate_branch_name(
    branch_name: str,
    repository_id: UUID,
    *,
    git_client: GitPlatformClient | None = None,
    exclude_session_id: UUID | str | None = None,
) -> BranchValidationResult:
    """多层校验分支名合法性。

    校验顺序：
    1. 空值检查
    2. 字符集正则
    3. '..' 路径遍历检查
    4. 首尾 '.' / '/' 检查
    5. '.lock' 结尾检查
    6. 长度 <= 255 字节
    7. 保护分支检查

    本地校验失败时提前返回，不做唯一性查询。
    唯一性校验（DB + remote）由 Task 2 补全。

    Args:
        branch_name: 待校验的分支名。
        repository_id: 仓库 UUID（唯一性校验使用）。
        git_client: Git 平台客户端（可选，用于 remote 唯一性校验）。
        exclude_session_id: 排除指定 CodingSession 不参与 DB 唯一性比对。

            **典型场景**：confirm 流程在 ``dispatch_coding_task`` 里又调一次
            ``validate_branch_name`` 校验当前 ``coding_session.branch_name``。
            此时**自己**就是一条 active (draft/confirmed) 的 CodingSession，
            会被错误地识别为冲突 —— 报 "分支名 'xxx' 已被活跃的编码会话使用"，
            实际上撞的是自己。caller 传入当前会话 id 把自己从冲突候选里剔除。
    """
    errors: list[str] = []

    # 1. 空值检查
    if not branch_name:
        return BranchValidationResult(valid=False, errors=["分支名不能为空"])

    # 2. 字符集正则
    if not _VALID_BRANCH_CHARS.match(branch_name):
        errors.append(
            "分支名包含非法字符，仅允许字母、数字、'.', '_', '/', '-'"
        )

    # 3. '..' 路径遍历检查
    if ".." in branch_name:
        errors.append("分支名不能包含 '..'（路径遍历风险）")

    # 4. 首尾 '.' / '/' 检查
    if branch_name.startswith("."):
        errors.append("分支名不能以 '.' 开头")
    if branch_name.endswith("/"):
        errors.append("分支名不能以 '/' 结尾")

    # 5. '.lock' 结尾检查
    if branch_name.endswith(".lock"):
        errors.append("分支名不能以 '.lock' 结尾（Git 保留后缀）")

    # 6. 长度 <= 255 字节
    if len(branch_name.encode("utf-8")) > 255:
        errors.append(f"分支名长度超过 255 字节限制（当前 {len(branch_name.encode('utf-8'))} 字节）")

    # 7. 保护分支检查
    if branch_name in DEFAULT_PROTECTED_BRANCHES:
        errors.append(f"'{branch_name}' 是保护分支，不允许直接使用")

    for pattern in DEFAULT_PROTECTED_PATTERNS:
        if pattern.match(branch_name):
            errors.append(f"'{branch_name}' 匹配保护分支模式，不允许直接使用")
            break

    # 本地校验失败时提前返回，不做唯一性查询
    if errors:
        return BranchValidationResult(valid=False, errors=errors)

    # 8. DB 唯一性校验 — 查询活跃状态（非 completed/failed）的同名分支
    from chat.models import CodingSession

    active_statuses = [
        CodingSession.Status.DRAFT,
        CodingSession.Status.CONFIRMED,
        CodingSession.Status.RUNNING,
    ]
    # 唯一性按 (repository, branch_name) 维度：不同仓库允许同名分支（一次技术方案
    # 多仓 fan-out 统一分支名的前提），仅同一仓库内同名活跃会话才算冲突。
    conflict_qs = CodingSession.objects.filter(
        branch_name=branch_name,
        repository_id=repository_id,
        status__in=active_statuses,
    )
    if exclude_session_id is not None:
        conflict_qs = conflict_qs.exclude(id=exclude_session_id)
    db_conflict = await conflict_qs.aexists()
    if db_conflict:
        errors.append(f"分支名 '{branch_name}' 已被该仓库活跃的编码会话使用")

    # 9. Remote refs 唯一性校验
    if git_client is not None:
        try:
            remote_exists = await git_client.branch_exists(branch_name)
            if remote_exists:
                errors.append(f"远程仓库已存在同名分支 '{branch_name}'")
        except Exception as exc:
            logger.warning(
                "remote_branch_check_failed",
                branch_name=branch_name,
                error=str(exc),
            )
            # remote 校验失败不阻塞，仅警告

    if errors:
        return BranchValidationResult(valid=False, errors=errors)

    return BranchValidationResult(valid=True, errors=[])


def generate_default_branch_name(tech_plan: str) -> tuple[str, str, str]:
    """便捷入口（同步）：根据 tech_plan 规则生成默认分支名。

    用于同步调用点（如 mcp_tools），不调用 LLM；简短名走规则提取。
    async 上下文优先用 ``agenerate_default_branch_name`` 拿 AI 生成的中文名。

    Args:
        tech_plan: 技术方案文本。

    Returns:
        (branch_name, branch_type, short_desc) 三元组。
    """
    branch_type = infer_branch_type(tech_plan)
    short_desc = generate_short_description(tech_plan)
    branch_name = generate_branch_name(branch_type, short_desc)
    return branch_name, branch_type, short_desc


async def agenerate_default_branch_name(tech_plan: str) -> tuple[str, str, str]:
    """便捷入口（async）：用 LLM 生成简短中文名拼默认分支名。

    Returns:
        (branch_name, branch_type, short_desc) 三元组。
    """
    branch_type = infer_branch_type(tech_plan)
    short_desc = await agenerate_short_description(tech_plan)
    branch_name = generate_branch_name(branch_type, short_desc)
    return branch_name, branch_type, short_desc
