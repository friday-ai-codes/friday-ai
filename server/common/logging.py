"""：凭证泄漏防护（structlog processor + Sentry before_send + 业务字符串脱敏 helper）。
Phase 引入。在全局 settings.py 末尾调用 configure_structlog，全仓库 structlog.get_logger 自动生效。
设计要点：
- 双层脱敏：字段名命中 SENSITIVE_KEY_PATTERN（顶层 + 递归 nested dict/list）+ 字段值
 命中 SENSITIVE_VALUE_PATTERN（兜底 sk-ant-* / sk-* / AIza* / Bearer * / PEM 私钥）。
- structlog processor 必须挂在 ConsoleRenderer / JSONRenderer **之前**（一旦渲染成字符串
 就无法精确脱敏字段名）。
- redact_secrets_in_text 是字符串级业务 helper，被 server/services/provider_health.py 等
 模块直接 import 用于上游 error body 脱敏（T-）。
- sentry_before_send 是纯函数 + 单测预留 hook；本 phase **不引入** sentry-sdk 依赖
 （D5 / D6 锁死），未来里程碑可一行接入 sentry_sdk.init(before_send=sentry_before_send)。
- _redact_value 递归处理 dict / list / str（不动 int / bool / None / 其他原始类型）。
"""
from __future__ import annotations
import logging
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
SENSITIVE_VALUE_PATTERN = re.compile(
 r"(?:sk-ant-[A-Za-z0-9_\-]{10,}" # Anthropic: sk-ant-...
 r"|sk-[A-Za-z0-9_\-]{20,}" # OpenAI: sk-... (>= 20 字符避免误伤短字符串)
 r"|AIza[A-Za-z0-9_\-]{20,}" # Google: AIza...
 r"|Bearer\s+[A-Za-z0-9._\-]{20,}" # Bearer token
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
 for k, v in value.items
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
 for key in list(event_dict.keys):
 if SENSITIVE_KEY_PATTERN.search(str(key)):
 event_dict[key] = REDACTED
 else:
 event_dict[key] = _redact_value(event_dict[key])
 return event_dict
# === 业务字符串脱敏 helper（被 services/provider_health.py 等业务代码直接 import）===
def redact_secrets_in_text(text: str) -> str:
 """纯函数脱敏：字符串中所有 sk-ant-* / sk-* / AIza* / Bearer * / PEM 私钥
 替换为 ***REDACTED***。
 用例：上游 Provider HTTP 响应 body / Exception str 入库前脱敏（T- 缓解）。
 """
 if not text:
 return text
 return SENSITIVE_VALUE_PATTERN.sub(REDACTED, text)
# === 全局 structlog 配置（settings.py 末尾调用）===
def configure_structlog -> None:
 """全局 structlog 配置。挂载到 settings.py 末尾。
 Processor 顺序关键：
 1. contextvars.merge_contextvars —— 读线程 / 协程上下文
 2. add_log_level / TimeStamper —— 元信息
 3. redact_credentials —— **必须在任何 renderer 之前**（ 核心）
 4. StackInfoRenderer / format_exc_info —— 异常信息提取
 5. ConsoleRenderer (DEBUG) / JSONRenderer (prod) —— 最后一步
 """
 structlog.configure(
 processors=[
 structlog.contextvars.merge_contextvars,
 structlog.processors.add_log_level,
 structlog.processors.TimeStamper(fmt="iso"),
 redact_credentials, # ← 核心；位置 in front of any renderer
 structlog.processors.StackInfoRenderer,
 structlog.processors.format_exc_info,
 (
 structlog.dev.ConsoleRenderer
 if getattr(settings, "DEBUG", False)
 else structlog.processors.JSONRenderer
 ),
 ],
 wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
 cache_logger_on_first_use=True,
 )
# === Sentry before_send pure function（本 phase 仅预留 + 单测；Phase+ 接入时使用）===
def sentry_before_send(
 event: dict[str, Any], hint: dict[str, Any]
) -> dict[str, Any] | None:
 """Sentry SDK before_send hook（本 phase 仅预留 + 契约测试；不引入 sentry-sdk 依赖）。
 过滤：
 - exception.values.stacktrace.frames.vars 中的凭证字段
 - event.extra / event.contexts 中的凭证字段
 - event.breadcrumbs.values.data 中的凭证字段
 """
 # 1. 过滤 exception vars
 for exc in event.get("exception", {}).get("values", ) or:
 for frame in exc.get("stacktrace", {}).get("frames", ) or:
 vars_dict = frame.get("vars") or {}
 for k in list(vars_dict.keys):
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
 for bc in breadcrumbs.get("values", ) or:
 if isinstance(bc, dict) and isinstance(bc.get("data"), dict):
 bc["data"] = _redact_value(bc["data"])
 return event
