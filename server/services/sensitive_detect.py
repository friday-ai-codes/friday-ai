"""敏感文件确定性检测器（Phase 24 Plan 01，EXCL-03）。

本模块是本阶段「始终启用」的确定性检测段：在索引阶段扫描仓库工作区，识别疑似
含密钥 / 敏感信息的文件，产出 ``SensitiveFileSuggestion`` 建议名单（status=pending），
供用户确认后接入 Phase 22 ``RepoExclusionRule``——**绝不静默删除 / 绝不自动建规则**。

策略（混合，确定性为主，DOMAIN §9 D-01）：
1. **独立有界遍历**：自走候选文件，**不**复用 indexer 的扩展名白名单扫描（其按扩展名白名单
   过滤，恰会漏掉 ``.env`` / ``id_rsa`` / ``*.pem`` 等无扩展名/被排除的敏感文件）。
2. **文件名启发式**：复用 Phase 22 ``BUILTIN_GLOBAL_DEFAULTS`` 的 glob 基线判断文件名是否敏感。
3. **内容级密钥扫描**：私钥块 / AWS / GitHub / Slack token / 通用密钥赋值 / 高熵串。

隐私边界（DOMAIN §9 D-04，T-24-01）：检测产物**绝不**记录或泄漏密钥本体——``reason``
只描述命中类型与行号，由 ``_redact_reason`` 从「类型 + 行号」结构化构造，不回填任何命中
文本；审计事件 ``sensitive.detected`` 仅含计数 / severity，不含路径敏感内容或密钥值。

可用性边界（T-24-02 / T-24-04）：遍历跳过 ``.git`` / ``node_modules`` 结构性目录、超大文件
（> 1 MiB）与二进制文件（NUL 嗅探）；逐文件 ``try/except`` 隔离，单文件读/解码失败不致命。
所有 ORM 访问经原生异步 ORM（``aupdate_or_create`` / ``afirst``）。
"""

from __future__ import annotations

import fnmatch
import math
import os
import re
from dataclasses import dataclass

import structlog

from services.exclusion import BUILTIN_GLOBAL_DEFAULTS, normalize_rel_path

logger = structlog.get_logger(__name__)

__all__ = ["SuggestionCandidate", "detect_sensitive_files"]

# severity 字面值（与 SensitiveFileSuggestion.Severity 对齐；本模块不导入模型以保持纯函数）。
_REAL_SECRET = "real_secret"
_LIKELY_SENSITIVE = "likely_sensitive"
_CONFIG_REVIEW = "config_review"

# severity 由高到低的合并序（同文件多命中取最高）。
_SEVERITY_RANK = {_REAL_SECRET: 3, _LIKELY_SENSITIVE: 2, _CONFIG_REVIEW: 1}

# detector 字面值。
_DETECTOR_HEURISTIC = "heuristic"
_DETECTOR_CONTENT = "content"

# 遍历安全上限（T-24-02：避免遍历/读爆内存）。
_MAX_FILE_BYTES = 1 * 1024 * 1024  # 单文件 1 MiB 上限
_BINARY_SNIFF_BYTES = 8192  # NUL 嗅探的前缀字节数
_MAX_SCAN_LINE_BYTES = 4096  # 单行扫描上限，避免极长单行（minified）拖垮正则

# 结构性目录：纯噪声 / 体量巨大，跳过遍历。
#
# 注意（偏离 PLAN 措辞，Rule 1）：**不**把 ``BUILTIN_GLOBAL_DEFAULTS`` 中 dir 型默认
# （``.ssh/`` / ``secrets/``）纳入跳过集——那恰是要主动「识别」的敏感目录，跳过会让检测器
# 漏掉 ``secrets/app.pem`` 等目标文件（与 behavior 守护测试冲突，亦违背检测器目的）。
# 仅跳过 ``.git`` / ``node_modules`` 这类与敏感识别无关的结构性目录。
_SKIP_DIRS = frozenset({".git", "node_modules"})


@dataclass(frozen=True)
class SuggestionCandidate:
    """单个敏感文件建议候选（字段全脱敏，绝不含密钥本体）。"""

    path: str
    severity: str
    detector: str
    reason: str


# === 内容扫描正则集（模块级常量，编译一次复用）=========================================
# 每项：(编译正则, severity, 中文命中类型标签)。标签经 _redact_reason 结构化为「检测到X（行N）」，
# 绝不回填命中文本（group(0)/group 值一律不入 reason）。
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_AWS_ACCESS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_AWS_SECRET_ASSIGN_RE = re.compile(r"AWS_SECRET_ACCESS_KEY\s*[:=]")
_GITHUB_TOKEN_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")
_SLACK_TOKEN_RE = re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")
_GENERIC_ASSIGN_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*\S{8,}"
)

# (正则, severity, 类型标签)。顺序仅影响 reason 拼接，severity 合并取最高。
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (_PRIVATE_KEY_RE, _REAL_SECRET, "私钥块"),
    (_AWS_ACCESS_KEY_RE, _REAL_SECRET, "AWS Access Key 格式"),
    (_AWS_SECRET_ASSIGN_RE, _REAL_SECRET, "AWS 密钥赋值"),
    (_GITHUB_TOKEN_RE, _REAL_SECRET, "GitHub Token 格式"),
    (_SLACK_TOKEN_RE, _REAL_SECRET, "Slack Token 格式"),
    (_GENERIC_ASSIGN_RE, _REAL_SECRET, "疑似密钥赋值"),
]

# 高熵候选 token：长度 ≥ 40 的 base64/hex/url-safe 串。
_HIGH_ENTROPY_TOKEN_RE = re.compile(r"[A-Za-z0-9+/=_\-]{40,}")
_HIGH_ENTROPY_THRESHOLD = 4.0  # Shannon 熵（bits/char）阈值，保守避免误报普通长串。
# 注释行前缀：高熵串若在注释行内（示例/文档）降噪，不单独触发。
_COMMENT_PREFIXES = ("#", "//", "*", "<!--", ";")


def _redact_reason(kind: str, line_no: int) -> str:
    """从「命中类型 + 行号」结构化构造脱敏 reason（T-24-01）。

    这是 reason 的**唯一构造入口**：只接受类型标签与行号，从源头杜绝把命中文本 /
    密钥本体写入 reason 的可能。
    """
    return f"检测到{kind}（行 {line_no}）"


def _shannon_entropy(s: str) -> float:
    """计算字符串的 Shannon 熵（bits/char），用于高熵密钥串判定。"""
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _build_filename_globs() -> list[re.Pattern[str]]:
    """从 ``BUILTIN_GLOBAL_DEFAULTS`` 抽取 glob 基线，编译为 basename 命中正则。

    仅承载 glob 型默认（``.env`` / ``*.pem`` / ``id_rsa`` 等），按 basename 语义命中
    任意深度子目录（与 ExclusionMatcher 的 BL-01 一致）；大小写不敏感（ME-01，防
    大小写 FS 绕过）。dir 型默认不用于「识别」（见 _SKIP_DIRS 注释）。
    """
    patterns: list[re.Pattern[str]] = []
    for spec in BUILTIN_GLOBAL_DEFAULTS:
        if spec.rule_type != "glob":
            continue
        try:
            patterns.append(re.compile(fnmatch.translate(spec.pattern), re.IGNORECASE))
        except re.error:
            continue
    return patterns


_FILENAME_GLOBS = _build_filename_globs()


def _filename_severity(rel_path: str) -> str | None:
    """文件名启发式：命中敏感文件名基线返回 ``config_review``，否则 ``None``。"""
    base = rel_path.rsplit("/", 1)[-1]
    for rx in _FILENAME_GLOBS:
        if rx.match(rel_path) or rx.match(base):
            return _CONFIG_REVIEW
    return None


def _scan_content(text: str) -> list[tuple[str, str]]:
    """逐行扫描正文，返回 ``[(severity, reason), ...]``（reason 已脱敏，仅类型+行号）。"""
    hits: list[tuple[str, str]] = []
    for idx, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line[:_MAX_SCAN_LINE_BYTES]
        if not line.strip():
            continue
        for rx, severity, kind in _SECRET_PATTERNS:
            if rx.search(line):
                hits.append((severity, _redact_reason(kind, idx)))
        stripped = line.lstrip()
        is_comment = stripped.startswith(_COMMENT_PREFIXES)
        if not is_comment:
            for token in _HIGH_ENTROPY_TOKEN_RE.findall(line):
                if _shannon_entropy(token) >= _HIGH_ENTROPY_THRESHOLD:
                    hits.append((_LIKELY_SENSITIVE, _redact_reason("高熵疑似密钥串", idx)))
                    break
    return hits


def _is_binary(prefix: bytes) -> bool:
    """二进制嗅探：前缀含 NUL 字节即判为二进制（跳过，避免误扫与读爆）。"""
    return b"\x00" in prefix


def _walk_candidate_files(repo_path: str) -> list[tuple[str, str]]:
    """独立有界遍历候选文件，返回 ``[(abs_path, rel_path), ...]``。

    - 跳过 ``_SKIP_DIRS`` 结构性目录（``.git`` / ``node_modules``）。
    - 跳过超大文件（> 1 MiB）与二进制文件（NUL 嗅探）。
    - rel_path 经 ``normalize_rel_path`` 归一；归一失败的路径跳过（fail-safe）。
    - **不**应用扩展名白名单、**不**用 ExclusionMatcher 过滤候选——被排除的恰是要识别的目标。
    """
    candidates: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            abs_path = os.path.join(dirpath, name)
            try:
                if os.path.islink(abs_path):
                    continue
                size = os.path.getsize(abs_path)
            except OSError:
                continue
            if size > _MAX_FILE_BYTES:
                continue
            rel = os.path.relpath(abs_path, repo_path)
            norm = normalize_rel_path(rel)
            if norm is None:
                continue
            candidates.append((abs_path, norm))
    return candidates


def _classify_file(abs_path: str, rel_path: str) -> SuggestionCandidate | None:
    """对单文件做文件名启发式 + 内容扫描，合并为单个候选（无命中返回 None）。"""
    severity: str | None = _filename_severity(rel_path)
    reasons: list[str] = []
    detector = _DETECTOR_HEURISTIC
    if severity is not None:
        reasons.append(f"敏感文件名命中（{rel_path.rsplit('/', 1)[-1]}）")

    try:
        with open(abs_path, "rb") as fh:
            prefix = fh.read(_BINARY_SNIFF_BYTES)
            if _is_binary(prefix):
                return _finalize(rel_path, severity, detector, reasons)
            rest = fh.read(_MAX_FILE_BYTES)
        text = (prefix + rest).decode("utf-8", errors="replace")
    except OSError:
        # 读失败：退回到文件名启发式结果（若有）。
        return _finalize(rel_path, severity, detector, reasons)

    content_hits = _scan_content(text)
    if content_hits:
        detector = _DETECTOR_CONTENT
        for hit_severity, reason in content_hits:
            severity = _merge_severity(severity, hit_severity)
            reasons.append(reason)

    return _finalize(rel_path, severity, detector, reasons)


def _merge_severity(current: str | None, candidate: str) -> str:
    """合并 severity，取等级更高者。"""
    if current is None:
        return candidate
    return current if _SEVERITY_RANK[current] >= _SEVERITY_RANK[candidate] else candidate


def _finalize(
    rel_path: str, severity: str | None, detector: str, reasons: list[str]
) -> SuggestionCandidate | None:
    """组装候选；无 severity（既无文件名命中也无内容命中）返回 None。"""
    if severity is None:
        return None
    reason = "；".join(dict.fromkeys(reasons)) if reasons else _redact_reason("敏感文件", 0)
    return SuggestionCandidate(
        path=rel_path, severity=severity, detector=detector, reason=reason
    )


async def _upsert_suggestion(repository_id: str, candidate: SuggestionCandidate) -> None:
    """upsert 单条建议（单一持久化入口，经 ``aupdate_or_create``）。

    dismissed 复扰策略（DOMAIN §9 D-02）：已 ``dismissed`` 的行仅当**升级为 real_secret**
    （旧 severity 非 real_secret）才重新置 ``pending`` 打扰；否则保留 ``dismissed`` 不复扰。
    已 ``accepted`` 的行保留 accepted（用户已建规则，不重复打扰）。
    """
    from repositories.models import SensitiveFileSuggestion

    existing = await SensitiveFileSuggestion.objects.filter(
        repository_id=repository_id, path=candidate.path
    ).afirst()

    status = SensitiveFileSuggestion.Status.PENDING
    if existing is not None:
        if existing.status == SensitiveFileSuggestion.Status.DISMISSED:
            upgraded = (
                candidate.severity == _REAL_SECRET and existing.severity != _REAL_SECRET
            )
            status = (
                SensitiveFileSuggestion.Status.PENDING
                if upgraded
                else SensitiveFileSuggestion.Status.DISMISSED
            )
        elif existing.status == SensitiveFileSuggestion.Status.ACCEPTED:
            status = SensitiveFileSuggestion.Status.ACCEPTED

    await SensitiveFileSuggestion.objects.aupdate_or_create(
        repository_id=repository_id,
        path=candidate.path,
        defaults={
            "severity": candidate.severity,
            "detector": candidate.detector,
            "reason": candidate.reason,
            "status": status,
        },
    )


async def detect_sensitive_files(repository_id: str, repo_path: str) -> int:
    """检测器入口：遍历仓库工作区 → 分类 → upsert 建议，返回入库/更新条数。

    逐文件 ``try/except`` 隔离（T-24-04）：单文件分类异常仅记 warning，不中断整仓检测。
    审计事件仅含计数 / severity，无路径敏感内容、无密钥本体（T-24-01）。
    """
    candidates: list[SuggestionCandidate] = []
    for abs_path, rel_path in _walk_candidate_files(repo_path):
        try:
            candidate = _classify_file(abs_path, rel_path)
        except Exception:  # noqa: BLE001 — 单文件失败隔离，不中断整仓（T-24-04）
            logger.warning("sensitive.classify_failed", repository_id=str(repository_id))
            continue
        if candidate is not None:
            candidates.append(candidate)

    for candidate in candidates:
        await _upsert_suggestion(repository_id, candidate)

    real_secret = sum(1 for c in candidates if c.severity == _REAL_SECRET)
    likely_sensitive = sum(1 for c in candidates if c.severity == _LIKELY_SENSITIVE)
    logger.info(
        "sensitive.detected",
        repository_id=str(repository_id),
        count=len(candidates),
        real_secret=real_secret,
        likely_sensitive=likely_sensitive,
    )
    return len(candidates)
