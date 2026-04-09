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
# ---------------------------------------------------------------------------
# 保护分支
# ---------------------------------------------------------------------------
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
_VALID_BRANCH_CHARS = re.compile(r"^[a-zA-._/\-]+$")
# 英文关键词提取正则：>= 2 字符的英文词，或单个英文字母
_ENGLISH_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]*[a-zA-]|[a-zA-Z]")
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
 优先级：fix > chore > feat（默认）。
 Args:
 tech_plan: 技术方案文本。
 Returns:
 分支类型字符串："feat" | "fix" | "chore"。
 """
 lower = tech_plan.lower
 for kw in _FIX_KEYWORDS:
 if kw in lower:
 return "fix"
 for kw in _CHORE_KEYWORDS:
 if kw in lower:
 return "chore"
 return "feat"
def generate_short_description(tech_plan: str) -> str:
 """从 tech_plan 提取英文 kebab-case 短描述。
 提取英文关键词，过滤停用词，取前 4 个拼接为 kebab-case。
 编码后截断至 40 字节，在最后一个 '-' 处截断以避免断词。
 无法提取时返回 "task" 作为兜底。
 Args:
 tech_plan: 技术方案文本。
 Returns:
 kebab-case 短描述（仅含 [a-z0-9-]，<= 40 字节）。
 """
 # 提取英文词（>= 2 字符优先，也接受单字母）
 raw_words = _ENGLISH_WORD_RE.findall(tech_plan)
 # 过滤停用词，转小写
 words = [w.lower for w in raw_words if w.lower not in _STOP_WORDS]
 if not words:
 return "task"
 # 取前 4 个拼接
 desc = "-".join(words[:4])
 # 截断至 40 字节
 if len(desc.encode("utf-8")) > 40:
 encoded = desc.encode("utf-8")[:40]
 # 解码回字符串（可能截断在中间，但 kebab-case 只有 ASCII，不会有问题）
 truncated = encoded.decode("utf-8", errors="ignore")
 # 在最后一个 '-' 处截断以避免断词
 last_dash = truncated.rfind("-")
 if last_dash > 0:
 truncated = truncated[:last_dash]
 desc = truncated
 return desc
def generate_branch_name(branch_type: str, short_desc: str) -> str:
 """拼接 {type}{YYYYMMDD}.{desc} 格式分支名。
 Args:
 branch_type: 分支类型（feat/fix/chore）。
 short_desc: kebab-case 短描述。
 Returns:
 格式化的分支名。
 """
 date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
 return f"{branch_type}{date_str}.{short_desc}"
async def validate_branch_name(
 branch_name: str,
 repository_id: UUID,
 *,
 git_client: GitPlatformClient | None = None,
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
 Returns:
 BranchValidationResult 包含校验结果和错误列表。
 """
 errors: list[str] =
 # 1. 空值检查
 if not branch_name:
 return BranchValidationResult(valid=False, errors=["分支名不能为空"])
 # 2. 字符集正则
 if not _VALID_BRANCH_CHARS.match(branch_name):
 errors.append(
 f"分支名包含非法字符，仅允许字母、数字、'.', '_', '/', '-'"
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
 # 本地校验失败时提前返回
 if errors:
 return BranchValidationResult(valid=False, errors=errors)
 # --- 唯一性校验占位（Task 2 补全） ---
 return BranchValidationResult(valid=True, errors=)
def generate_default_branch_name(tech_plan: str) -> tuple[str, str, str]:
 """便捷入口：根据 tech_plan 生成默认分支名。
 Args:
 tech_plan: 技术方案文本。
 Returns:
 (branch_name, branch_type, short_desc) 三元组。
 """
 branch_type = infer_branch_type(tech_plan)
 short_desc = generate_short_description(tech_plan)
 branch_name = generate_branch_name(branch_type, short_desc)
 return branch_name, branch_type, short_desc
