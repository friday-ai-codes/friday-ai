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
import json
import math
import os
import re
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

import structlog

from services.exclusion import BUILTIN_GLOBAL_DEFAULTS, normalize_rel_path
from services.provider_config import ProviderConfigService

logger = structlog.get_logger(__name__)

__all__ = [
    "AmbiguousCandidate",
    "SuggestionCandidate",
    "classify_ambiguous_files",
    "detect_sensitive_files",
]

# severity 字面值（与 SensitiveFileSuggestion.Severity 对齐；本模块不导入模型以保持纯函数）。
_REAL_SECRET = "real_secret"
_LIKELY_SENSITIVE = "likely_sensitive"
_CONFIG_REVIEW = "config_review"

# severity 由高到低的合并序（同文件多命中取最高）。
_SEVERITY_RANK = {_REAL_SECRET: 3, _LIKELY_SENSITIVE: 2, _CONFIG_REVIEW: 1}

# detector 字面值。
_DETECTOR_HEURISTIC = "heuristic"
_DETECTOR_CONTENT = "content"
_DETECTOR_LLM = "llm"

# 遍历安全上限（T-24-02：避免遍历/读爆内存）。
_MAX_FILE_BYTES = (
    1 * 1024 * 1024
)  # 内容扫描上限：仅读取/扫描文件前 1 MiB（ME-01：大文件不整体跳过）
_BINARY_SNIFF_BYTES = 8192  # NUL 嗅探的前缀字节数
_MAX_SCAN_LINE_BYTES = 4096  # 单行扫描上限，避免极长单行（minified）拖垮正则

# 自走遍历全局护栏（ME-02：防超大 monorepo 上 runaway IO/CPU/内存）。
# 超限即停止遍历并记一次 ``sensitive.walk_truncated`` 可观测事件（best-effort，不报错）。
_MAX_WALK_FILES = 200_000  # 最多访问（stat）的文件数
_MAX_CANDIDATES = 5_000  # 最多累积的确定性候选数
_WALK_TIME_BUDGET_SECONDS = 60.0  # 软时间预算（自遍历开始计）

# 结构性目录：纯噪声 / 体量巨大，跳过遍历。
#
# 注意（偏离 PLAN 措辞，Rule 1）：**不**把 ``BUILTIN_GLOBAL_DEFAULTS`` 中 dir 型默认
# （``.ssh/`` / ``secrets/``）纳入跳过集——那恰是要主动「识别」的敏感目录，跳过会让检测器
# 漏掉 ``secrets/app.pem`` 等目标文件（与 behavior 守护测试冲突，亦违背检测器目的）。
# 仅跳过与敏感识别无关的结构性 / 构建产物 / 依赖目录（ME-02：纳入 dist/build/vendor/.venv 等）。
_SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "dist",
        "build",
        "vendor",
        ".venv",
        "venv",
        "target",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".gradle",
        ".idea",
    }
)

# 可选 LLM 二分类候选的扩展名白名单：确定性段未命中、但「可疑」的配置/文档类文件
# （ME-03：把这类子集组装为 AmbiguousCandidate 交可选 LLM 复判）。
_AMBIGUOUS_EXTS = frozenset(
    {
        "cfg",
        "conf",
        "config",
        "ini",
        "env",
        "yaml",
        "yml",
        "toml",
        "properties",
        "json",
        "txt",
        "md",
        "xml",
        "tfvars",
    }
)
_MAX_AMBIGUOUS = 50  # 送可选 LLM 的最大模糊候选数（单次请求上限，控成本）
_AMBIGUOUS_SAMPLE_BYTES = 4096  # 模糊候选采样字节数（仅供本地抽取布尔特征，绝不外送）


@dataclass(frozen=True)
class SuggestionCandidate:
    """单个敏感文件建议候选（字段全脱敏，绝不含密钥本体）。"""

    path: str
    severity: str
    detector: str
    reason: str


@dataclass(frozen=True)
class AmbiguousCandidate:
    """送入可选 LLM 二分类的「模糊」候选（启发式未覆盖但可疑的配置/文档文件）。

    ``sample_text`` 仅供本模块**内部**抽取最小化布尔特征（如是否含 key/secret 关键字）；
    它**绝不**随 LLM 请求外送（T-24-06）——见 ``_build_llm_feature``。
    """

    path: str
    severity: str | None = None
    sample_text: str = field(default="", repr=False)


# === 内容扫描正则集（模块级常量，编译一次复用）=========================================
# 每项：(编译正则, severity, 中文命中类型标签)。标签经 _redact_reason 结构化为「检测到X（行N）」，
# 绝不回填命中文本（group(0)/group 值一律不入 reason）。
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_AWS_ACCESS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_AWS_SECRET_ASSIGN_RE = re.compile(r"AWS_SECRET_ACCESS_KEY\s*[:=]")
_GITHUB_TOKEN_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")
_SLACK_TOKEN_RE = re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")
_GENERIC_ASSIGN_RE = re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*\S{8,}")

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


def _candidate_from_abs(repo_path: str, abs_path: str) -> tuple[str, str, int] | None:
    """对单个绝对路径做 fail-safe 校验，返回 ``(abs_path, rel_path, size)`` 或 ``None``。

    跳过软链接 / stat 失败 / 路径归一失败的项。**不**按文件大小跳过（ME-01：大文件仍
    需跑文件名启发式；体量约束只作用于内容扫描，见 ``_classify_file``）。
    """
    try:
        if os.path.islink(abs_path):
            return None
        if not os.path.isfile(abs_path):
            return None
        size = os.path.getsize(abs_path)
    except OSError:
        return None
    rel = os.path.relpath(abs_path, repo_path)
    norm = normalize_rel_path(rel)
    if norm is None:
        return None
    return (abs_path, norm, size)


def _walk_candidate_files(
    repo_path: str, only_paths: Iterable[str] | None = None
) -> Iterator[tuple[str, str, int]]:
    """独立有界遍历候选文件，逐个 yield ``(abs_path, rel_path, size)``。

    - ``only_paths`` 非空时（HI-01 增量/diff 路径）：仅遍历这些仓库相对路径对应的文件，
      不做整仓 ``os.walk``（避免每次增量全仓重扫）。
    - 否则整仓 ``os.walk``，跳过 ``_SKIP_DIRS`` 结构性 / 构建 / 依赖目录。
    - **不**按文件大小跳过（ME-01）；二进制 / 内容上限约束由 ``_classify_file`` 处理。
    - rel_path 经 ``normalize_rel_path`` 归一；归一失败的路径跳过（fail-safe）。
    - **不**应用扩展名白名单、**不**用 ExclusionMatcher 过滤候选——被排除的恰是要识别的目标。

    注：全局护栏（文件数 / 时间 / 候选数）由调用方 ``_scan_repository`` 施加。
    """
    if only_paths is not None:
        seen: set[str] = set()
        for rel in only_paths:
            norm = normalize_rel_path(rel)
            if norm is None or norm in seen:
                continue
            seen.add(norm)
            abs_path = os.path.join(repo_path, norm)
            item = _candidate_from_abs(repo_path, abs_path)
            if item is not None:
                yield item
        return

    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            abs_path = os.path.join(dirpath, name)
            item = _candidate_from_abs(repo_path, abs_path)
            if item is not None:
                yield item


def _classify_file(
    abs_path: str, rel_path: str, size: int
) -> tuple[SuggestionCandidate | None, AmbiguousCandidate | None]:
    """对单文件做文件名启发式 + （有界）内容扫描。

    返回 ``(candidate, ambiguous)``：
    - ``candidate``：确定性命中（文件名启发式或内容扫描）的脱敏建议，无命中为 ``None``。
    - ``ambiguous``：确定性未命中但属「可疑配置/文档类」的可选 LLM 复判候选（ME-03），
      否则为 ``None``。两者互斥——确定性命中则不再视为 ambiguous。

    ME-01：文件名启发式对**所有**文件执行（不受大小限制）；内容扫描仅读取并扫描文件前
    ``_MAX_FILE_BYTES`` 字节（大文件读「有界前缀」而非整体跳过），既覆盖大型 ``.pem`` /
    凭据转储的文件名命中，又约束读取体量。
    """
    severity: str | None = _filename_severity(rel_path)
    reasons: list[str] = []
    detector = _DETECTOR_HEURISTIC
    if severity is not None:
        reasons.append(f"敏感文件名命中（{rel_path.rsplit('/', 1)[-1]}）")

    text: str | None = None
    try:
        with open(abs_path, "rb") as fh:
            prefix = fh.read(_BINARY_SNIFF_BYTES)
            if _is_binary(prefix):
                # 二进制：仅依赖文件名启发式，不内容扫描、不作 ambiguous。
                return _finalize(rel_path, severity, detector, reasons), None
            # 仅读取前 _MAX_FILE_BYTES 字节（有界前缀）——大文件不整体读、不整体跳过。
            rest = fh.read(max(_MAX_FILE_BYTES - len(prefix), 0))
        text = (prefix + rest).decode("utf-8", errors="replace")
    except OSError:
        # 读失败：退回到文件名启发式结果（若有）。
        return _finalize(rel_path, severity, detector, reasons), None

    content_hits = _scan_content(text)
    if content_hits:
        detector = _DETECTOR_CONTENT
        for hit_severity, reason in content_hits:
            severity = _merge_severity(severity, hit_severity)
            reasons.append(reason)

    candidate = _finalize(rel_path, severity, detector, reasons)
    if candidate is not None:
        return candidate, None

    # 确定性未命中：若是「可疑配置/文档类」文件，组装为可选 LLM 复判候选（ME-03）。
    ambiguous = _maybe_ambiguous(rel_path, text)
    return None, ambiguous


def _maybe_ambiguous(rel_path: str, text: str | None) -> AmbiguousCandidate | None:
    """确定性未命中时，判断是否为「可疑配置/文档类」文件并组装 ambiguous 候选。

    ``sample_text`` 仅供 ``_build_llm_feature`` 在本地抽取布尔特征，**绝不**随 LLM 请求外送。
    """
    base = rel_path.rsplit("/", 1)[-1]
    _, ext = os.path.splitext(base)
    ext = ext.lstrip(".").lower()
    if ext not in _AMBIGUOUS_EXTS:
        return None
    sample = (text or "")[:_AMBIGUOUS_SAMPLE_BYTES]
    return AmbiguousCandidate(path=rel_path, severity=None, sample_text=sample)


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
    return SuggestionCandidate(path=rel_path, severity=severity, detector=detector, reason=reason)


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
            upgraded = candidate.severity == _REAL_SECRET and existing.severity != _REAL_SECRET
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


def _scan_repository(
    repository_id: str,
    repo_path: str,
    only_paths: Iterable[str] | None = None,
) -> tuple[list[SuggestionCandidate], list[AmbiguousCandidate]]:
    """纯只读扫描：遍历 + 分类，返回 ``(确定性候选, 可选 LLM 模糊候选)``。

    **关键（BL-01）**：本函数为同步只读，**必须在仓库工作区目录仍存活时**被调用并跑完
    （文件读取全部发生在此）；调用方应在删除临时克隆目录之前 join 本扫描结果。

    全局护栏（ME-02）：访问文件数 / 累计候选数 / 软时间预算任一超限即停止遍历，并记一次
    ``sensitive.walk_truncated`` 可观测事件。逐文件 ``try/except`` 隔离（T-24-04）。
    """
    candidates: list[SuggestionCandidate] = []
    ambiguous: list[AmbiguousCandidate] = []
    files_seen = 0
    started = time.monotonic()
    truncated = False

    for abs_path, rel_path, size in _walk_candidate_files(repo_path, only_paths):
        files_seen += 1
        if files_seen > _MAX_WALK_FILES:
            truncated = True
            break
        if time.monotonic() - started > _WALK_TIME_BUDGET_SECONDS:
            truncated = True
            break
        try:
            candidate, amb = _classify_file(abs_path, rel_path, size)
        except Exception:  # noqa: BLE001 — 单文件失败隔离，不中断整仓（T-24-04）
            logger.warning("sensitive.classify_failed", repository_id=str(repository_id))
            continue
        if candidate is not None:
            candidates.append(candidate)
            if len(candidates) >= _MAX_CANDIDATES:
                truncated = True
                break
        elif amb is not None and len(ambiguous) < _MAX_AMBIGUOUS:
            ambiguous.append(amb)

    if truncated:
        logger.warning(
            "sensitive.walk_truncated",
            repository_id=str(repository_id),
            files_seen=files_seen,
            candidates=len(candidates),
            max_files=_MAX_WALK_FILES,
            max_candidates=_MAX_CANDIDATES,
            time_budget_seconds=_WALK_TIME_BUDGET_SECONDS,
        )
    return candidates, ambiguous


async def detect_sensitive_files(
    repository_id: str,
    repo_path: str,
    *,
    only_paths: Iterable[str] | None = None,
    enable_llm: bool = True,
    node_config: dict | None = None,
) -> int:
    """检测器入口：遍历仓库工作区 → 分类 → upsert 建议，返回入库/更新条数。

    - ``only_paths``（HI-01）：非空时仅检测这些仓库相对路径（增量/diff 路径只扫本次变更
      文件，避免全仓重扫）；为 ``None`` 时整仓扫描（全量索引）。
    - ``enable_llm``（ME-03）：默认启用可选 LLM 二分类对「确定性未命中但可疑」的配置/文档
      子集复判；provider 缺失或调用失败一律 graceful 退化（确定性结果不受影响，T-24-07）。

    生命周期（BL-01）：本协程的文件读取发生在同步 ``_scan_repository`` 中；调用方必须在临时
    克隆目录删除**之前** await 本协程，确保检测读到真实文件而非已删除/空目录。

    逐文件 ``try/except`` 隔离（T-24-04）：单文件分类异常仅记 warning，不中断整仓检测。
    审计事件仅含计数 / severity，无路径敏感内容、无密钥本体（T-24-01）。
    """
    candidates, ambiguous = _scan_repository(repository_id, repo_path, only_paths)

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
        ambiguous=len(ambiguous),
    )

    # ME-03：可选 LLM 二分类（gated + graceful-degrade）。已在 _scan_repository 内（目录存活时）
    # 采样 sample_text，故此处即便目录已删除也不再读盘。任何异常一律不冒泡（T-24-07）。
    if enable_llm and ambiguous:
        try:
            await classify_ambiguous_files(repository_id, ambiguous, node_config=node_config)
        except Exception:  # noqa: BLE001 — 可选增强失败绝不影响确定性结果（T-24-07）
            logger.warning("sensitive.llm_stage_failed", repository_id=str(repository_id))

    return len(candidates)


# === 可选 LLM 二分类段（Plan 24-02，D-01 增强）======================================
# 确定性段「始终启用」；本段仅对「启发式未覆盖但可疑」的配置/文档子集**可选**调用：
# provider 缺失 / 调用失败一律 graceful 退化为空增量，确定性结果绝不依赖 LLM 成功
# （T-24-07）。强密钥（real_secret）绝不进候选、绝不外送；送 LLM 的仅「文件名 + 最小化
# 布尔特征」，绝不含密钥本体（T-24-06）。

# 最小化特征关键字：仅用于产出布尔信号，关键字命中与否本身不泄漏密钥值。
_FEATURE_KEYWORDS = ("key", "secret", "token", "password", "credential", "passwd")

_LLM_SYSTEM_PROMPT = (
    "你是敏感文件审查助手。基于给定的文件名与最小化特征（扩展名、是否含密钥类关键字），"
    "判断每个文件是否可能包含敏感信息（密钥/口令/凭据等）。"
    "严格输出 JSON 数组，每项含：path（原样回传）、sensitive（布尔）、reason（中文一句，"
    "**绝不**回显任何密钥值或文件内容）。除 JSON 外不要输出其他内容。"
)


def _build_llm_feature(candidate: AmbiguousCandidate) -> dict[str, object]:
    """构造送 LLM 的最小化特征：仅文件名 + 扩展名 + 关键字布尔，**绝不含**正文/密钥值。

    ``sample_text`` 只在此处用于计算布尔信号（是否含密钥类关键字），其原文不进入返回值。
    """
    base = candidate.path.rsplit("/", 1)[-1]
    _, ext = os.path.splitext(base)
    lowered = f"{base}\n{candidate.sample_text or ''}".lower()
    has_keyword = any(kw in lowered for kw in _FEATURE_KEYWORDS)
    return {
        "path": candidate.path,
        "ext": ext.lstrip("."),
        "has_sensitive_keyword": has_keyword,
    }


def _parse_llm_verdicts(raw: str) -> list[dict]:
    """解析 LLM 输出为判定数组；非 JSON / 非数组时尝试截取，失败抛由上层退化。"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", raw)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, list):
        raise ValueError("LLM 输出必须是 JSON array")
    return data


def _redact_llm_reason(reason: str) -> str:
    """LLM 中文理由兜底脱敏：截断长度 + 去除可能回显的高熵/密钥样 token。

    即便 prompt 已要求不回显密钥，仍做服务端兜底——把疑似密钥/高熵串替换为占位，
    确保入库 reason 绝不含密钥本体（T-24-06 纵深防御）。
    """
    text = (reason or "").strip()[:200]
    if not text:
        return "LLM 判定为疑似敏感"

    def _scrub(match: re.Match[str]) -> str:
        token = match.group(0)
        if _shannon_entropy(token) >= _HIGH_ENTROPY_THRESHOLD:
            return "[已脱敏]"
        return token

    text = _HIGH_ENTROPY_TOKEN_RE.sub(_scrub, text)
    for rx, _sev, _kind in _SECRET_PATTERNS:
        text = rx.sub("[已脱敏]", text)
    return text


async def classify_ambiguous_files(
    repository_id: str,
    candidates: list[AmbiguousCandidate],
    *,
    node_config: dict | None = None,
) -> int:
    """可选 LLM 二分类：对模糊配置/文档候选判定是否疑似敏感，命中入库，返回新增条数。

    fail-safe / 隐私不变量：
    - ``real_secret`` 强命中显式排除，**绝不**进候选、绝不外送（T-24-06）。
    - provider 缺失（``ProviderMissingError``）或任何调用/解析异常 → 返回 0，不冒泡，
      确定性段结果不受影响（T-24-07）。
    - 送 LLM 的 human 内容仅「文件名 + 最小化布尔特征」，不含密钥本体（T-24-06）。
    - 仅产 ``likely_sensitive`` 的 pending 建议，绝不建规则 / 删数据（T-24-08）。
    """
    ambiguous = [c for c in candidates if c.severity != _REAL_SECRET]
    if not ambiguous:
        return 0

    try:
        from services.provider_config import ProviderMissingError

        resolved = await ProviderConfigService.aresolve_or_error(node_config)
        if isinstance(resolved, ProviderMissingError):
            logger.info(
                "sensitive.llm_skipped_no_provider",
                repository_id=str(repository_id),
                count=len(ambiguous),
            )
            return 0

        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            logger.info(
                "sensitive.llm_skipped_no_model",
                repository_id=str(repository_id),
            )
            return 0

        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.llm_factory import build_chat_model, content_to_text

        features = [_build_llm_feature(c) for c in ambiguous]
        system = SystemMessage(content=_LLM_SYSTEM_PROMPT)
        human = HumanMessage(content=json.dumps(features, ensure_ascii=False))

        model = build_chat_model(resolved, model_name, streaming=False)
        response = await model.ainvoke([system, human])
        verdicts = _parse_llm_verdicts(content_to_text(response.content))
    except Exception as exc:  # noqa: BLE001 — 任何异常一律 graceful 退化（T-24-07）
        # LO-02：只记异常类型，不记 str(exc)——JSONDecodeError 文本可能带回被解析文档片段。
        logger.warning(
            "sensitive_llm_classify_failed",
            repository_id=str(repository_id),
            error_type=type(exc).__name__,
        )
        return 0

    by_path = {c.path: c for c in ambiguous}
    applied = 0
    for verdict in verdicts:
        if not isinstance(verdict, dict):
            continue
        path = str(verdict.get("path", ""))
        if path not in by_path or not bool(verdict.get("sensitive")):
            continue
        candidate = SuggestionCandidate(
            path=path,
            severity=_LIKELY_SENSITIVE,
            detector=_DETECTOR_LLM,
            reason=_redact_llm_reason(str(verdict.get("reason", ""))),
        )
        try:
            await _upsert_suggestion(repository_id, candidate)
            applied += 1
        except Exception:  # noqa: BLE001 — 单条入库失败不中断其余（fail-safe）
            logger.warning("sensitive.llm_upsert_failed", repository_id=str(repository_id))

    logger.info(
        "sensitive.llm_classified",
        repository_id=str(repository_id),
        candidates=len(ambiguous),
        applied=applied,
    )
    return applied
