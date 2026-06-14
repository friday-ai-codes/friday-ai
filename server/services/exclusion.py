"""排除配置的单一匹配器（Phase 22 fail-closed，INV-4）。

本模块是排除判定的**唯一事实源**：所有读取/暴露面（索引扫描、MCP get_file/grep、
RAG 检索、agent 工具、编码容器过滤）都只调用 ``is_excluded(repository_id, rel_path)``，
不得各自另写一套过滤逻辑，以保证判定一致与 fail-closed。

安全边界（DOMAIN §9.1）：仅承诺「被排除文件对 Friday 不可见」，**不承诺** git object
物理消失。

失败模式严格区分：
- **构造期** 非法 regex → 抛 ``InvalidExclusionRuleError``（fail-loud，供保存校验复用，Plan 05）。
- **运行期** 路径归一越界 / 匹配异常 → 视为命中（fail-closed，返回 True），并埋审计日志。
"""

from __future__ import annotations

import fnmatch
import json
import re
import time
from dataclasses import dataclass
from typing import Iterable, Literal

import structlog
from asgiref.sync import sync_to_async

logger = structlog.get_logger(__name__)

RuleType = Literal["dir", "glob", "regex"]

# 匹配器 TTL 缓存：repository_id -> (expires_at_monotonic, ExclusionMatcher)。
# 60s 足够覆盖一次读取面的连续访问；规则变更后由 Plan 05 调 invalidate_matcher_cache。
_MATCHER_CACHE_TTL_SECONDS: float = 60.0
_matcher_cache: dict[str, tuple[float, "ExclusionMatcher"]] = {}


class InvalidExclusionRuleError(ValueError):
    """非法排除规则（如无法编译的 regex）。构造期 fail-loud，供保存 API 校验。"""


@dataclass(frozen=True)
class ExclusionRuleSpec:
    """单条排除规则的值对象（序列化形 = SystemSetting JSON 元素）。"""

    pattern: str
    rule_type: RuleType
    enabled: bool = True
    source: str = "user"


# === 内置全局默认（开箱即用的安全默认；即使无任何配置也生效，per D-04 / T-22-04）===
# 覆盖常见密钥/敏感文件与无意义目录。措辞与 DOMAIN §9.1 安全边界一致。
BUILTIN_GLOBAL_DEFAULTS: list[ExclusionRuleSpec] = [
    # 环境变量 / 密钥文件
    ExclusionRuleSpec(pattern=".env", rule_type="glob", source="global"),
    ExclusionRuleSpec(pattern=".env.*", rule_type="glob", source="global"),
    ExclusionRuleSpec(pattern="*.pem", rule_type="glob", source="global"),
    ExclusionRuleSpec(pattern="*.key", rule_type="glob", source="global"),
    ExclusionRuleSpec(pattern="*.p12", rule_type="glob", source="global"),
    ExclusionRuleSpec(pattern="*.keystore", rule_type="glob", source="global"),
    ExclusionRuleSpec(pattern="*.pfx", rule_type="glob", source="global"),
    # SSH 私钥
    ExclusionRuleSpec(pattern="id_rsa", rule_type="glob", source="global"),
    ExclusionRuleSpec(pattern="id_dsa", rule_type="glob", source="global"),
    ExclusionRuleSpec(pattern="id_ed25519", rule_type="glob", source="global"),
    # 凭证 / 密钥命名约定
    ExclusionRuleSpec(pattern="*credentials*", rule_type="glob", source="global"),
    ExclusionRuleSpec(pattern="*secret*.json", rule_type="glob", source="global"),
    # 敏感 / 无意义目录
    ExclusionRuleSpec(pattern=".git/", rule_type="dir", source="global"),
    ExclusionRuleSpec(pattern="node_modules/", rule_type="dir", source="global"),
    ExclusionRuleSpec(pattern=".ssh/", rule_type="dir", source="global"),
    ExclusionRuleSpec(pattern="secrets/", rule_type="dir", source="global"),
]


def normalize_rel_path(path: str, base: str | None = None) -> str | None:
    """把路径归一为相对仓库根的 POSIX 路径（口径与 qdrant file_path payload 对齐）。

    - 转 POSIX、折叠 ``.`` 段、在界内折叠 ``..``。
    - 绝对路径 / ``..`` 越界 / 空路径 → 返回 ``None``（调用方据此 fail-closed）。
    - 大小写敏感跟随既有索引行为（不强制 lower）。

    ``base`` 形参为未来 clone 侧绝对路径相对化预留，本阶段未使用。
    """
    if path is None:
        return None
    p = str(path).replace("\\", "/").strip()
    if not p:
        return None
    # 绝对路径 → fail-closed（T-22-02 路径归一绕过）
    if p.startswith("/"):
        return None
    segments: list[str] = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not segments:
                # 越出仓库根 → 非法
                return None
            segments.pop()
            continue
        segments.append(seg)
    if not segments:
        return None
    return "/".join(segments)


class ExclusionMatcher:
    """编译一次 / 复用的排除匹配器。

    构造期按 ``rule_type`` 编译规则；非法 regex 立即抛 ``InvalidExclusionRuleError``。
    ``is_excluded`` 在运行期对任意异常 fail-closed（返回 True + 审计埋点）。
    """

    def __init__(self, rules: Iterable[ExclusionRuleSpec], repository_id: str = "") -> None:
        self._repository_id = repository_id
        # dir：归一化为不含尾 "/" 的相对根前缀；匹配目录本身与其子树。
        self._dir_prefixes: list[str] = []
        # glob：fnmatch.translate 编译为 full-string 匹配正则（相对仓库根，大小写敏感）。
        self._glob_regexes: list[re.Pattern[str]] = []
        # regex：对相对路径 fullmatch。
        self._regexes: list[re.Pattern[str]] = []

        for spec in rules:
            if not spec.enabled:
                continue
            if spec.rule_type == "dir":
                norm = normalize_rel_path(spec.pattern.rstrip("/"))
                if norm:
                    self._dir_prefixes.append(norm)
            elif spec.rule_type == "glob":
                self._glob_regexes.append(re.compile(fnmatch.translate(spec.pattern)))
            elif spec.rule_type == "regex":
                try:
                    self._regexes.append(re.compile(spec.pattern))
                except re.error as exc:
                    raise InvalidExclusionRuleError(
                        f"非法 regex 排除规则: {spec.pattern!r} ({exc})"
                    ) from exc
            else:
                raise InvalidExclusionRuleError(f"未知规则类型: {spec.rule_type!r}")

    def is_excluded(self, rel_path: str) -> bool:
        """判定相对路径是否命中任一规则。归一失败 / 运行期异常 → fail-closed（True）。"""
        try:
            norm = normalize_rel_path(rel_path)
            if norm is None:
                return True  # 归一越界 → fail-closed
            for prefix in self._dir_prefixes:
                if norm == prefix or norm.startswith(prefix + "/"):
                    return True
            for rx in self._glob_regexes:
                if rx.match(norm):
                    return True
            for rx in self._regexes:
                if rx.fullmatch(norm):
                    return True
            return False
        except Exception:  # noqa: BLE001 — 运行期任何异常都 fail-closed（T-22-01）
            log_exclusion_blocked(
                surface="exclusion_matcher",
                repository_id=self._repository_id,
                rel_path=str(rel_path),
            )
            return True


def _resolve_effective_specs(repository_id: str) -> list[ExclusionRuleSpec]:
    """同步加载有效规则集合：builtin ∪ 全局设置 JSON ∪ per-repo，应用 global override。

    **排除判定的单一真相合并**：匹配器（``build_matcher_for_repo``）与容器下传序列化
    （``serialize_rules_for_repo``）共用本函数，避免两份合并逻辑漂移。

    经 ``sync_to_async`` 在异步上下文调用。``source="global" + enabled=False`` 的
    per-repo 行表示「关闭某条全局默认」的 override 标记，据此从全局集合剔除同 pattern 项。
    """
    from repositories.models import RepoExclusionRule
    from system.models import SettingKeys, SystemSetting

    global_specs: list[ExclusionRuleSpec] = list(BUILTIN_GLOBAL_DEFAULTS)

    setting = SystemSetting.objects.filter(
        key=SettingKeys.CODE_INDEX_EXCLUSION_GLOBAL_DEFAULTS
    ).first()
    if setting and setting.value:
        try:
            for item in json.loads(setting.value) or []:
                global_specs.append(
                    ExclusionRuleSpec(
                        pattern=item["pattern"],
                        rule_type=item["rule_type"],
                        enabled=bool(item.get("enabled", True)),
                        source=item.get("source", "global"),
                    )
                )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            # 全局默认配置损坏 → 记录但不致命（builtin 仍生效，保持 fail-closed）
            logger.warning("exclusion.global_defaults_parse_failed", error=str(exc))

    repo_rules = list(RepoExclusionRule.objects.filter(repository_id=repository_id))

    # per-repo 关闭的全局默认（override 标记）
    disabled_globals = {
        (r.rule_type, r.pattern) for r in repo_rules if r.source == "global" and not r.enabled
    }

    effective = [s for s in global_specs if (s.rule_type, s.pattern) not in disabled_globals]

    for r in repo_rules:
        # source=global 仅作 override 标记，不作为实际规则加入
        if r.source == "global" or not r.enabled:
            continue
        effective.append(
            ExclusionRuleSpec(
                pattern=r.pattern,
                rule_type=r.rule_type,
                enabled=True,
                source=r.source,
            )
        )
    return effective


# 向后兼容别名：既有调用点 / 测试 patch 仍用 ``_load_specs_from_db`` 这个名字，
# 它与 ``_resolve_effective_specs`` 指向同一实现（单一真相合并）。
_load_specs_from_db = _resolve_effective_specs


async def serialize_rules_for_repo(repository_id: str) -> list[dict[str, str]]:
    """导出某仓库的有效排除规则（可 JSON 序列化），供编码容器下传过滤。

    返回合并后的有效规则（builtin ∪ 全局设置 ∪ per-repo，已应用 global override），
    每项 ``{"pattern", "rule_type"}``，与匹配器使用的有效规则集同源
    （``_resolve_effective_specs``），避免双份真相。

    **绝不返回空列表**：即便解析异常或无任何配置，也回退到 ``BUILTIN_GLOBAL_DEFAULTS``。
    容器面默认 fail-closed —— 不下传 = 容器内不过滤，被排除文件对 agent 裸奔（T-22-14）。
    """
    try:
        specs = await sync_to_async(_resolve_effective_specs)(repository_id)
    except Exception:  # noqa: BLE001 — 合并/DB 异常也须给出内置默认（fail-closed，不裸奔）
        logger.warning("exclusion.serialize_failed", repository_id=str(repository_id))
        specs = list(BUILTIN_GLOBAL_DEFAULTS)

    rules = [{"pattern": s.pattern, "rule_type": s.rule_type} for s in specs if s.enabled]
    if not rules:
        rules = [{"pattern": s.pattern, "rule_type": s.rule_type} for s in BUILTIN_GLOBAL_DEFAULTS]
    return rules


async def build_matcher_for_repo(repository_id: str) -> ExclusionMatcher:
    """构造（或命中缓存返回）某仓库的有效匹配器。ORM 访问经 sync_to_async。"""
    now = time.monotonic()
    cached = _matcher_cache.get(repository_id)
    if cached and cached[0] > now:
        return cached[1]

    specs = await sync_to_async(_load_specs_from_db)(repository_id)
    matcher = ExclusionMatcher(specs, repository_id=repository_id)
    _matcher_cache[repository_id] = (now + _MATCHER_CACHE_TTL_SECONDS, matcher)
    return matcher


def invalidate_matcher_cache(repository_id: str | None = None) -> None:
    """失效匹配器缓存。``None`` 清空全部（Plan 05 规则变更后调用）。"""
    if repository_id is None:
        _matcher_cache.clear()
    else:
        _matcher_cache.pop(repository_id, None)


async def is_excluded(repository_id: str, rel_path: str) -> bool:
    """统一判定入口：所有读取/暴露面唯一调用点。fail-closed 由 matcher 保证。"""
    matcher = await build_matcher_for_repo(repository_id)
    return matcher.is_excluded(rel_path)


def log_exclusion_blocked(*, surface: str, repository_id: str, rel_path: str) -> None:
    """结构化审计埋点：记录被排除规则拦截的访问（供后续审计里程碑复用）。"""
    logger.info(
        "exclusion.blocked",
        surface=surface,
        repository_id=repository_id,
        rel_path=rel_path,
    )
