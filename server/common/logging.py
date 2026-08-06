"""contract：凭证泄漏防护（structlog processor + Sentry before_send + 业务字符串脱敏 helper）。

implementation 引入。在全局 settings.py 末尾调用 configure_structlog()，全仓库 structlog.get_logger 自动生效。

设计要点：
- 双层脱敏：字段名命中 SENSITIVE_KEY_PATTERN（顶层 + 递归 nested dict/list）+ 字段值
  命中 SENSITIVE_VALUE_PATTERN（兜底 sk-ant-* / sk-* / AIza* / Bearer * / PEM 私钥）。
- structlog processor 必须挂在 ConsoleRenderer / JSONRenderer **之前**（一旦渲染成字符串
  就无法精确脱敏字段名）。
- redact_secrets_in_text 是字符串级业务 helper，被 server/services/provider_health.py 等
  模块直接 import 用于上游 error body 脱敏（security mitigation）。
- sentry_before_send 是纯函数 + 单测预留 hook；本 phase **不引入** sentry-sdk 依赖
  未来可一行接入 sentry_sdk.init(before_send=sentry_before_send)。
- _redact_value 递归处理 dict / list / str（不动 int / bool / None / 其他原始类型）。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, MutableMapping

import structlog
from django.conf import settings

# === 模块级常量 ===

# 敏感字段名模式（不区分大小写）—— 命中即整个 value 替换为 REDACTED
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(api[_-]?key|credential|secret|token|authorization|bearer"
    r"|password|encrypted_config|service_account|private_key|passphrase|pat)"
)

# 敏感值模式（字段名不命中时兜底）—— 覆盖常见 LLM Provider 凭证 + Bearer + PEM 私钥
#
# ⚠️ ``sk-`` 两支前置 ``\b``（词边界）：⛔ 不加会命中**单词内部**的 ``sk-``。真实误伤：
# 容器工作目录名 ``/tmp/friday-task-bp-research-…`` 里的 ``ta|sk-|bp-research-…`` 正好凑成
# 「``sk-`` + 20 个合法字符」，整条路径被打成 ``/tmp/friday-ta***REDACTED***/AGENTS.md``
# —— 而「agent 读了哪个文件」正是过程明细的核心信息。
# ⭐ ``\b`` 只**收窄**匹配到「词首的 sk-」，凭证的真实出现位置（行首 / 空格 / 引号 / ``=``
# / ``:`` 之后）一律仍在边界上 ⇒ 脱敏强度不降。
SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?:\bsk-ant-[A-Za-z0-9_\-]{10,}"  # Anthropic: sk-ant-...
    r"|\bsk-[A-Za-z0-9_\-]{20,}"  # OpenAI: sk-... (>= 20 字符避免误伤短字符串)
    r"|AIza[A-Za-z0-9_\-]{20,}"  # Google: AIza...
    r"|Bearer\s+[A-Za-z0-9._\-]{20,}"  # Bearer token
    r"|friday_pat_[A-Za-z0-9_\-]{20,}"  # Friday Access Token: friday_pat_... (implementation)
    r"|-----BEGIN\s+(?:RSA\s+|EC\s+)?PRIVATE\s+KEY-----[\s\S]+?"
    r"-----END\s+(?:RSA\s+|EC\s+)?PRIVATE\s+KEY-----)"
)

REDACTED = "***REDACTED***"


# === 内部 helper：递归脱敏 ===


def _redact_value(value: Any) -> Any:
    """递归脱敏 dict / list / str。其他类型（int / bool / None）原样返回。"""
    if isinstance(value, dict):
        return {
            k: (REDACTED if SENSITIVE_KEY_PATTERN.search(str(k)) else _redact_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return SENSITIVE_VALUE_PATTERN.sub(REDACTED, value)
    return value


# === structlog processor ===


def redact_credentials(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor：脱敏 event_dict 顶层 + nested 所有敏感字段。

    签名：(logger, method_name, event_dict) —— structlog 25.x 标准。
    event_dict 已由框架预拷贝（mutate 安全）。
    """
    for key in list(event_dict.keys()):
        if SENSITIVE_KEY_PATTERN.search(str(key)):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


# === category / component 地基（LOG-05）===

# LOGGING-SPEC §5 组件清单（component 受控取值）。logger name 首段命中即用，
# 否则留空（不强行污染维度）。存量事件渐进迁移，72+ 增量补全。
_KNOWN_COMPONENTS = frozenset(
    {
        "auth",
        "accounts",
        "mcp",
        "chat",
        "orchestration",
        "workflows",
        "compat",
        "repositories",
        "indexing",
        "codegraph",
        "rag",
        "knowledge",
        "delivery",
        "agents",
        "llm",
        "providers",
        "subagent",
        "runners",
        "task",
        "feishu",
        "webhook",
        "durable",
        "scheduler",
        "system",
        "settings",
        "notifications",
        "audit",
        "access_tokens",
        "health",
        "metrics",
        "logging",
    }
)


def _infer_component(logger_name: str) -> str:
    """从 logger name 推断 component：取模块路径首段，命中 §5 清单则用，否则留空。

    例：``"system.signals"`` → ``"system"``；``"workflows.engine.scheduler"`` →
    ``"workflows"``；推不出（首段不在清单）留空，待业务显式 ``bind(component=...)``。
    """
    if not logger_name:
        return ""
    head = logger_name.split(".", 1)[0]
    return head if head in _KNOWN_COMPONENTS else ""


def bound_logger(name: str, *, component: str | None = None) -> Any:
    """薄包 ``structlog.get_logger(name)``，默认从 logger name 推 component（LOG-05）。

    约定：业务用 ``category=`` 显式传（``caller`` 关键调用全量记录），缺省视为
    ``sampling``（由 ``annotate_category_component`` processor 兜底）。``component`` 可
    显式覆盖；推不出且未传则不 bind component（留 processor 兜底/留空）。
    """
    log = structlog.get_logger(name)
    comp = component if component is not None else _infer_component(name)
    return log.bind(component=comp) if comp else log


def annotate_category_component(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor：为每条事件兜底 ``component`` + ``category``（LOG-05）。

    - 无 ``component`` → 从 ``logger`` / ``logger_name`` 首段推断（命中 §5 清单）。
    - 无 ``category`` → 默认 ``"sampling"``（高频内部步骤默认采样类，per 判断口诀；
      用户可归因调用须由业务显式 ``category="caller"``）。

    挂在 ``redact_credentials`` 之后、``enqueue_system_log`` 之前，保证落库带
    category/component。纯元字段，不引入用户输入原文（脱敏链路不受影响）。
    """
    if not event_dict.get("component"):
        logger_name = str(event_dict.get("logger") or event_dict.get("logger_name") or "")
        comp = _infer_component(logger_name)
        if comp:
            event_dict["component"] = comp
    if not event_dict.get("category"):
        event_dict["category"] = "sampling"
    return event_dict


# === 运行时分组件级别过滤 + 堆栈阈值门控（LOG-06）===


def _event_level_value(event_dict: MutableMapping[str, Any], method_name: str) -> int:
    """从 event_dict / method_name 解析事件级别数值（默认 INFO）。

    ``add_log_level`` processor 已注入 ``level``（小写方法名）；缺省回退 ``method_name``。
    """
    name = str(event_dict.get("level") or method_name or "info").strip().upper()
    return _STRUCTLOG_LEVEL_NAMES.get(name, logging.INFO)


def filter_by_component_level(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor：按 ``LOG_COMPONENT_LEVELS`` 对单个 component 分级过滤（LOG-06）。

    读取 ``SettingKeys.LOG_COMPONENT_LEVELS``（JSON map ``{component: level}``，60s 缓存 +
    signal 失效，热更新即时生效）。命中当前事件 ``component`` 且事件级别 **低于** 该
    component 配置级别时 ``raise structlog.DropEvent`` 丢弃；未配置 / 推不出 component /
    解析失败均放行（回退全局 wrapper 级别，不收紧也不放宽）。

    放在 ``annotate_category_component`` 之后（component 已就位）、``buffer_log`` /
    ``enqueue_system_log`` 之前——尽早丢弃，省掉后续缓冲/落库开销（高频路径保持廉价：
    未配置时 ``get_json_setting`` 命中缓存的空值直接回退 ``{}``，不做 json 解析）。

    注意：分组件级别只能比全局 wrapper **更严**（wrapper 已先于 processor 链按全局级别
    过滤，更宽松的 component 级别无法让已被 wrapper 丢弃的事件复活）。
    """
    try:
        from system.models import SettingKeys
        from system.settings_service import get_json_setting

        comp_levels = get_json_setting(SettingKeys.LOG_COMPONENT_LEVELS)
        if not comp_levels:
            return event_dict
        component = str(event_dict.get("component") or "")
        if not component:
            return event_dict
        raw_threshold = comp_levels.get(component)
        if not raw_threshold:
            return event_dict
        threshold = _STRUCTLOG_LEVEL_NAMES.get(str(raw_threshold).strip().upper())
        if threshold is None:
            return event_dict
        if _event_level_value(event_dict, method_name) < threshold:
            raise structlog.DropEvent
    except structlog.DropEvent:
        raise  # ← 丢弃信号必须冒泡给 structlog，不能被下面 except 吞掉
    except Exception:  # noqa: BLE001 — 过滤异常绝不反噬日志主链路（best-effort）
        pass
    return event_dict


def gate_stack_by_threshold(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor：按 ``LOG_STACK_THRESHOLD`` 门控堆栈 / 异常信息捕获（LOG-06）。

    读取 ``SettingKeys.LOG_STACK_THRESHOLD``（如 ``ERROR``，60s 缓存 + signal 失效）。
    事件级别 **低于** 阈值时，剥除 ``stack_info`` / ``exc_info`` / ``exception`` / ``stack``
    键——使其后的 ``StackInfoRenderer`` / ``format_exc_info`` 不再渲染堆栈/traceback；
    达到/高于阈值则原样保留。未配置阈值 → 不门控（保留既有行为）。

    必须挂在 ``StackInfoRenderer`` / ``format_exc_info`` **之前**（渲染前剥键才有效）。
    best-effort：解析失败静默放行，绝不反噬业务。高频路径廉价（未配置时不剥键直接返回）。
    """
    try:
        from system.models import SettingKeys
        from system.settings_service import get_setting

        raw = get_setting(SettingKeys.LOG_STACK_THRESHOLD, "").strip().upper()
        threshold = _STRUCTLOG_LEVEL_NAMES.get(raw) if raw else None
        if threshold is None:
            return event_dict
        if _event_level_value(event_dict, method_name) < threshold:
            for key in ("stack_info", "exc_info", "exception", "stack"):
                event_dict.pop(key, None)
    except Exception:  # noqa: BLE001 — 门控异常绝不反噬日志主链路（best-effort）
        pass
    return event_dict


# === 内存环形缓冲：运维监控「系统日志」面板数据源 ===


def buffer_log(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor：把（已脱敏的）事件追加到内存环形缓冲。

    必须挂在 ``redact_credentials`` **之后**，保证缓冲里也是脱敏内容；
    返回原 event_dict 不变，不影响后续 renderer。
    """
    try:
        from common.log_buffer import append_log

        append_log(
            {
                "ts": event_dict.get("timestamp"),
                "level": str(event_dict.get("level") or method_name or "info").upper(),
                "logger": str(event_dict.get("logger") or event_dict.get("logger_name") or ""),
                "message": str(event_dict.get("event", "")),
                "source": "app",
            }
        )
    except Exception:  # noqa: BLE001 — 缓冲失败绝不影响日志主链路
        pass
    return event_dict


def enqueue_system_log(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor：把（已脱敏的）业务事件 fan-out 入落库队列（LOG-02）。

    **必须**挂在 ``redact_credentials`` **之后**（与 ``buffer_log`` 同侧、紧随其后），
    保证入队前已脱敏——落库内容绝不含明文凭证（脱敏契约命门）。

    component 暂取 logger name 末段（71-03 会细化 category/component helper）；
    ``user_id`` / ``source`` / ``trace_id`` / ``request_id`` 由 ``merge_contextvars``
    已注入。整体 best-effort（``except: pass``），返回原 event_dict 不变。
    """
    try:
        from system.log_sink import enqueue_system_log as _sink_enqueue

        logger_name = str(event_dict.get("logger") or event_dict.get("logger_name") or "")
        # 优先用 annotate_category_component 注入的 component，缺省回退首段推断。
        component = str(event_dict.get("component") or "") or _infer_component(logger_name)
        level = str(event_dict.get("level") or method_name or "info")
        # 收集除已映射专属列外的剩余字段进 payload（已脱敏）。
        _reserved = {
            "event",
            "level",
            "timestamp",
            "logger",
            "logger_name",
            "component",
            "category",
            "user_id",
            "source",
            "trace_id",
            "request_id",
        }
        payload = {k: v for k, v in event_dict.items() if k not in _reserved}
        _sink_enqueue(
            {
                "ts": event_dict.get("timestamp"),
                "level": level,
                "component": component,
                "category": str(event_dict.get("category") or ""),
                "event": str(event_dict.get("event", "")),
                "message": str(event_dict.get("event", "")),
                "user_id": event_dict.get("user_id"),
                "source": event_dict.get("source"),
                "trace_id": event_dict.get("trace_id"),
                "request_id": event_dict.get("request_id"),
                **payload,
            }
        )
    except Exception:  # noqa: BLE001 — 落库 fan-out 绝不影响日志主链路
        pass
    return event_dict


class RingBufferHandler(logging.Handler):
    """stdlib logging handler：把 django / 第三方日志写入内存环形缓冲 + 落库队列。

    消息体经 ``redact_secrets_in_text`` 兜底脱敏（stdlib 日志不走 structlog 脱敏链）。
    在既有内存环形缓冲之后**同样** fan-out 一份到落库队列（``enqueue_system_log``）。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from datetime import datetime, timezone

            from common.log_buffer import append_log

            ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
            safe_message = redact_secrets_in_text(record.getMessage())
            append_log(
                {
                    "ts": ts,
                    "level": record.levelname,
                    "logger": record.name,
                    "message": safe_message,
                    "source": "system",
                }
            )
            # fan-out 落库（脱敏后）；独立 try 保证 buffer 已写入不被落库异常波及。
            try:
                from system.log_sink import enqueue_system_log as _sink_enqueue

                _sink_enqueue(
                    {
                        "ts": ts,
                        "level": record.levelname,
                        "component": record.name,
                        "event": record.name,
                        "message": safe_message,
                        "source": "system",
                    }
                )
            except Exception:  # noqa: BLE001 — 落库 fan-out 绝不影响 handler
                pass
        except Exception:  # noqa: BLE001 — handler 永不抛
            pass


# === 业务字符串脱敏 helper（被 services/provider_health.py 等业务代码直接 import）===


def redact_secrets_in_text(text: str) -> str:
    """纯函数脱敏：字符串中所有 sk-ant-* / sk-* / AIza* / Bearer * / PEM 私钥
    替换为 ***REDACTED***。

    用例：上游 Provider HTTP 响应 body / Exception str 入库前脱敏（security mitigation 缓解）。
    """
    if not text:
        return text
    return SENSITIVE_VALUE_PATTERN.sub(REDACTED, text)


# === 全局 structlog 配置（settings.py 末尾调用）===


_STRUCTLOG_LEVEL_NAMES: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.CRITICAL,
}


def _resolve_env_structlog_level() -> int:
    """从环境变量解析 structlog 过滤级别（DB 不可用时的回退源）。

    默认 INFO：避免大批量 ``debug`` 事件刷屏 stdout（曾经把 4000+ 文件的
    ``graph_bundle_written`` / ``import_statement_no_modules`` 一起灌出来导致
    UI 卡顿）。生产排错时可以临时设 ``FRIDAY_STRUCTLOG_LEVEL=DEBUG``。
    """
    raw = (
        (os.environ.get("FRIDAY_STRUCTLOG_LEVEL") or os.environ.get("DJANGO_LOG_LEVEL") or "")
        .strip()
        .upper()
    )
    return _STRUCTLOG_LEVEL_NAMES.get(raw, logging.INFO)


def _resolve_structlog_level() -> int:
    """解析 structlog 过滤级别：DB（``SettingKeys.LOG_LEVEL``）优先，env 回退（LOG-06）。

    运行时可热更新——超管在设置页改 ``log.level`` 即经 signal 重设过滤级别、无需重启。
    加载期（settings.py 末尾首次调用）DB / app registry 尚未就绪时局部 import + try/except
    静默回退 env → INFO，绝不反噬启动。
    """
    try:
        from system.models import SettingKeys
        from system.settings_service import get_setting

        raw_db = get_setting(SettingKeys.LOG_LEVEL, "").strip().upper()
        db_level = _STRUCTLOG_LEVEL_NAMES.get(raw_db) if raw_db else None
    except Exception:  # noqa: BLE001 — DB / app registry 未就绪 → 回退 env
        db_level = None
    if db_level is not None:
        return db_level
    return _resolve_env_structlog_level()


def apply_log_level(level_name: str | None = None) -> None:
    """运行时热更新过滤级别：即时生效无需重启（LOG-06）。

    解析级别（显式传入 > DB > env）后：
    - ``logging.getLogger().setLevel(...)`` 调整 stdlib root（影响 RingBufferHandler 等）。
    - 重设 structlog filtering wrapper（structlog 推荐运行时方式：重新
      ``structlog.configure(wrapper_class=make_filtering_bound_logger(level))``，仅覆盖
      wrapper_class、保留既有 processor 链；幂等）。

    best-effort：解析失败 / 配置异常静默吞掉，绝不反噬业务（观测代码永不抛）。
    """
    try:
        if level_name:
            level = _STRUCTLOG_LEVEL_NAMES.get(
                str(level_name).strip().upper(), _resolve_structlog_level()
            )
        else:
            level = _resolve_structlog_level()
        logging.getLogger().setLevel(level)
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(level))
    except Exception:  # noqa: BLE001 — 运行时调级别绝不反噬业务
        pass


def configure_structlog() -> None:
    """全局 structlog 配置。挂载到 settings.py 末尾。

    Processor 顺序关键：
    1. contextvars.merge_contextvars —— 读线程 / 协程上下文
    2. add_log_level / TimeStamper —— 元信息
    3. redact_credentials —— **必须在任何 renderer 之前**（contract 核心）
    4. StackInfoRenderer / format_exc_info —— 异常信息提取
    5. ConsoleRenderer (DEBUG) / JSONRenderer (prod) —— 最后一步

    幂等与列表身份：``cache_logger_on_first_use=True`` 下，已绑定的 logger 会持有
    **当时那个 processors 列表对象的引用**。若重复调用本函数时传入新建的列表，旧
    logger 会永远停在旧链上——与之后对配置的任何改动（包括 ``structlog.testing.
    capture_logs()``，它按官方实现刻意原地改写同一列表以兼容缓存）彻底脱钩。
    因此这里复用已有列表实例、原地替换内容，绝不换对象。
    """
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        redact_credentials,  # ← contract 核心；位置 in front of any renderer
        annotate_category_component,  # ← 脱敏后兜底 category/component（LOG-05，落库前）
        filter_by_component_level,  # ← component 就位后分级过滤；尽早丢弃省后续开销（LOG-06）
        buffer_log,  # ← 在脱敏之后写入内存环形缓冲（运维监控「系统日志」）
        enqueue_system_log,  # ← 在脱敏之后 fan-out 入落库队列（LOG-02，落库内容已脱敏）
        gate_stack_by_threshold,  # ← 渲染堆栈/traceback 前按阈值门控剥键（LOG-06）
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        (
            structlog.dev.ConsoleRenderer()
            if getattr(settings, "DEBUG", False)
            else structlog.processors.JSONRenderer()
        ),
    ]
    configured = structlog.get_config().get("processors")
    if isinstance(configured, list):
        configured[:] = processors
        processors = configured

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(_resolve_structlog_level()),
        cache_logger_on_first_use=True,
    )
    # 末尾用 DB 级别覆盖过滤 wrapper（DB 不可用时 _resolve_structlog_level 已静默回退 env）。
    apply_log_level()


# === Sentry before_send pure function（本 phase 仅预留 + 单测；implementation+ 接入时使用）===


def sentry_before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Sentry SDK before_send hook（本 phase 仅预留 + 契约测试；不引入 sentry-sdk 依赖）。

    过滤：
    - exception.values[].stacktrace.frames[].vars 中的凭证字段
    - event.extra / event.contexts 中的凭证字段
    - event.breadcrumbs.values[].data 中的凭证字段
    """
    # 1. 过滤 exception vars
    for exc in event.get("exception", {}).get("values", []) or []:
        for frame in exc.get("stacktrace", {}).get("frames", []) or []:
            vars_dict = frame.get("vars") or {}
            for k in list(vars_dict.keys()):
                if SENSITIVE_KEY_PATTERN.search(str(k)):
                    vars_dict[k] = REDACTED
                elif isinstance(vars_dict[k], str):
                    vars_dict[k] = SENSITIVE_VALUE_PATTERN.sub(REDACTED, vars_dict[k])

    # 2. 过滤 extra / contexts
    for section_name in ("extra", "contexts"):
        section = event.get(section_name)
        if isinstance(section, dict):
            event[section_name] = _redact_value(section)

    # 3. 过滤 breadcrumbs
    breadcrumbs = event.get("breadcrumbs", {})
    if isinstance(breadcrumbs, dict):
        for bc in breadcrumbs.get("values", []) or []:
            if isinstance(bc, dict) and isinstance(bc.get("data"), dict):
                bc["data"] = _redact_value(bc["data"])

    return event
