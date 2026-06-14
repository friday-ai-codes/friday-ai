"""容器侧排除过滤 + clone 后 prune（Phase 22-04 / EXCL-02，INV-4 fail-closed）。

编码容器内 Claude Code agent 直接读真实工作树文件，被排除文件（密钥/敏感文件）若残留
即对 agent 完全可见。本模块在 clone+checkout 后从工作树**物理删除**命中排除规则的文件，
使其对 agent 不可见（DOMAIN §9.3「task 容器工作树：clone 后过滤」）。

匹配语义与 server ``services/exclusion.py`` 的 ``ExclusionMatcher`` 对齐（dir 相对仓库根
前缀 / glob fnmatch full-string / regex fullmatch），但 task 包独立、**绝不** import server。
规则模式经 ``FRIDAY_TASK_EXCLUDE_PATTERNS`` env（JSON）由 server 两条派发路径下传。

失败模式（关键，T-22-16 fail-closed）：
- 单文件删除失败 → 重试（chmod +w 后重删，最多 N 次）。
- 某被排除文件**持久**删除失败 → ``prune_excluded`` 抛 ``ExclusionPruneError``，由
  ``git_ops.setup`` 向上传播使容器 setup 失败 / 任务标记 failed。**绝不**在被排除文件
  仍可读时让 setup 成功（不允许「log and continue」残留可读文件）。
- 归一化/匹配异常 → 保守判定为命中（删除候选）；删除本身的持久失败按致命处理。

安全边界（T-22-15）：prune **绝不删除 ``.git/`` 目录**——删它会破坏 commit/push。
"""

from __future__ import annotations

import fnmatch
import os
import re
import stat
from pathlib import Path

import structlog

logger = structlog.get_logger()

# 单文件删除重试次数（首次失败后 chmod +w 再重试，覆盖只读位场景）。
_DELETE_MAX_ATTEMPTS = 3

# 永不删除的 VCS 元数据目录名（删除会破坏 git 操作，T-22-15）。
_PROTECTED_DIR_NAMES = frozenset({".git"})


class ExclusionPruneError(RuntimeError):
    """被排除文件持久无法删除（fail-closed）：使容器 setup 失败，绝不让其残留可读。"""

    def __init__(self, failed_paths: list[str]) -> None:
        self.failed_paths = failed_paths
        super().__init__(
            f"prune 无法删除 {len(failed_paths)} 个被排除文件（fail-closed 阻断）: "
            f"{failed_paths[:10]}"
        )


def _normalize_rel_path(path: str) -> str | None:
    """归一为相对仓库根的 POSIX 路径（语义与 server normalize_rel_path 对齐）。

    绝对路径 / ``..`` 越界 / 空 → ``None``（调用方据此 fail-closed 视为命中）。
    """
    if path is None:
        return None
    p = str(path).replace("\\", "/").strip()
    if not p or p.startswith("/"):
        return None
    segments: list[str] = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not segments:
                return None
            segments.pop()
            continue
        segments.append(seg)
    if not segments:
        return None
    return "/".join(segments)


class _ContainerExclusionMatcher:
    """容器侧轻量匹配器：编译一次 / 复用，语义对齐 server ExclusionMatcher。

    无效 regex/glob 规则跳过（规则来自 server 已校验的有效集，理论不应出现）；
    ``is_excluded`` 运行期任何异常 fail-closed（返回 True → 删除候选）。
    """

    def __init__(self, rules: list[dict]) -> None:
        # dir：(归一前缀, 是否大小写不敏感)，语义对齐 server。
        self._dir_prefixes: list[tuple[str, bool]] = []
        # glob：(编译正则, 是否按 basename 兜底匹配任意目录)，语义对齐 server（BL-01）。
        self._glob_regexes: list[tuple[re.Pattern[str], bool]] = []
        self._regexes: list[re.Pattern[str]] = []

        for rule in rules or []:
            try:
                rule_type = rule.get("rule_type")
                pattern = rule.get("pattern")
                source = rule.get("source")
            except AttributeError:
                continue
            if not pattern or not rule_type:
                continue
            # source="global" 的安全默认大小写不敏感匹配（ME-01，与 server 一致）。
            case_insensitive = source == "global"
            if rule_type == "dir":
                norm = _normalize_rel_path(str(pattern).rstrip("/"))
                if norm:
                    self._dir_prefixes.append((norm, case_insensitive))
            elif rule_type == "glob":
                flags = re.IGNORECASE if case_insensitive else 0
                try:
                    rx = re.compile(fnmatch.translate(str(pattern)), flags)
                except re.error:
                    logger.warning("exclusion.bad_glob_skipped", pattern=str(pattern))
                    continue
                # 无路径分隔符的 glob 按 basename 命中任意子目录（BL-01，与 server 一致）。
                self._glob_regexes.append((rx, "/" not in str(pattern)))
            elif rule_type == "regex":
                try:
                    self._regexes.append(re.compile(str(pattern)))
                except re.error:
                    logger.warning("exclusion.bad_regex_skipped", pattern=str(pattern))

    @property
    def has_rules(self) -> bool:
        return bool(self._dir_prefixes or self._glob_regexes or self._regexes)

    def is_excluded(self, rel_path: str) -> bool:
        try:
            norm = _normalize_rel_path(rel_path)
            if norm is None:
                return True  # 归一越界 → fail-closed（保守删除）
            for prefix, ci in self._dir_prefixes:
                n, p = (norm.casefold(), prefix.casefold()) if ci else (norm, prefix)
                if n == p or n.startswith(p + "/"):
                    return True
            base = norm.rsplit("/", 1)[-1]
            for rx, basename_only in self._glob_regexes:
                if rx.match(norm):
                    return True
                if basename_only and base != norm and rx.match(base):
                    return True
            for rx in self._regexes:
                if rx.fullmatch(norm):
                    return True
            return False
        except Exception:  # noqa: BLE001 — 运行期匹配异常 fail-closed（保守删除）
            return True


def _delete_with_retry(abs_path: Path) -> bool:
    """删除单个文件，失败先 chmod +w 再重试。返回是否最终删除（含已不存在）。"""
    for attempt in range(_DELETE_MAX_ATTEMPTS):
        try:
            os.remove(abs_path)
            return True
        except FileNotFoundError:
            return True  # 已不存在视为成功
        except OSError:
            # 只读位 / 权限：chmod +w 后重试（最后一次失败则落入返回 False）。
            if attempt < _DELETE_MAX_ATTEMPTS - 1:
                try:
                    os.chmod(abs_path, stat.S_IWUSR | stat.S_IRUSR)
                except OSError:
                    pass
    return False


def prune_excluded(workspace: Path, rules: list[dict]) -> int:
    """在工作树中删除命中排除规则的文件。返回删除文件数。

    - 跳过 ``.git/``（不删除 VCS 元数据，T-22-15）。
    - 单文件删除失败先重试；任一被排除文件**持久**删除失败 → 抛 ``ExclusionPruneError``
      （fail-closed，T-22-16：被排除文件绝不静默残留可读）。
    - 空规则 → 0，不报错。
    """
    if not workspace:
        return 0
    matcher = _ContainerExclusionMatcher(rules)
    if not matcher.has_rules:
        return 0

    workspace = Path(workspace)
    deleted = 0
    failed: list[str] = []

    for root, dirs, files in os.walk(workspace, topdown=True):
        # 绝不下钻 .git（避免删除 git 元数据破坏 commit/push）。
        dirs[:] = [d for d in dirs if d not in _PROTECTED_DIR_NAMES]
        for fname in files:
            abs_path = Path(root) / fname
            try:
                rel = abs_path.relative_to(workspace).as_posix()
            except ValueError:
                rel = fname
            if not matcher.is_excluded(rel):
                continue
            if _delete_with_retry(abs_path):
                deleted += 1
            else:
                failed.append(rel)

    if failed:
        logger.error("exclusion.prune_failed", failed_count=len(failed))
        raise ExclusionPruneError(failed)

    # 清理被删空的目录（best-effort，非致命；绝不动 .git）。
    for root, dirs, files in os.walk(workspace, topdown=False):
        if Path(root) == workspace:
            continue
        if any(part in _PROTECTED_DIR_NAMES for part in Path(root).relative_to(workspace).parts):
            continue
        try:
            if not os.listdir(root):
                os.rmdir(root)
        except OSError:
            pass

    return deleted
