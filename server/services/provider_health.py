"""5 Provider 健康检查 dispatch + 原子写入 ProviderCredential 三字段。
设计要点（CONTEXT D4 锁死）：
- Anthropic 用 POST /v1/messages/count_tokens（稳定轻量；兼容网关支持度最好）
- OpenAI Chat / Responses 两种走 GET /v1/models
- Gemini 走 GET /v1beta/models?key=...（key 作为 query string）
- Ollama 走 GET /api/tags（同次往返解析 models.name 写入 available_models， 协同）
- 同步阻塞 + 5s timeout + httpx AsyncClient
- 4 个 _ping_* 与 health_check 异常分支的 error 字段必须经 redact_secrets_in_text
 脱敏 + 500 字符截断后才入库（T- 缓解契约；共 5 处调用点）
- 所有 logger 调用仅传 credential_id / provider / latency_ms，**不传** api_key /
 decrypted_config（T- 缓解）；全局 configure_structlog 的 redact_credentials
 processor 兜底
- 原子 aupdate 单 SQL 写回 last_health_check_at/status/error 三字段（避免 race condition）
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Any
import httpx
import structlog
from django.utils import timezone
from common.logging import redact_secrets_in_text
from services.provider_config import PROVIDER_REGISTRY, ProviderType
from system.models import ProviderCredential
logger = structlog.get_logger(__name__)
HEALTH_CHECK_TIMEOUT_SECONDS = 5.0
ERROR_TRUNCATE_LIMIT = 500
@dataclass(frozen=True)
class HealthCheckResult:
 """健康检查结果。
 available_models 仅 Ollama 路径填充（其他 Provider 保持 None）；
 Phase refresh-models 端点会另行拉取其他 Provider 的模型清单。
 """
 ok: bool
 status: str # "ok" | "error"
 latency_ms: int
 error: str = ""
 available_models: list[str] | None = None
def _safe_error(text: str, limit: int = ERROR_TRUNCATE_LIMIT) -> str:
 """统一脱敏 + 截断（T- 缓解契约）。
 所有 error 字段入库前必须经此 helper 过滤；helper 内部委托
 redact_secrets_in_text（common.logging 提供）完成 sk-ant-* / sk-* / AIza* /
 Bearer * / PEM 私钥五类正则脱敏。
 调用点（本文件）：
 - _ping_anthropic 错误分支 → redact_secrets_in_text
 - _ping_openai 错误分支 → redact_secrets_in_text
 - _ping_gemini 错误分支 → redact_secrets_in_text
 - _ping_ollama 错误分支 → redact_secrets_in_text
 - health_check decrypt_failed / unknown_provider_type / ConnectError /
 Exception 兜底分支 → redact_secrets_in_text
 """
 return redact_secrets_in_text(str(text))[:limit]
# ============================================================================
# 5 Provider _ping_* helper（签名统一：client + credential + decrypted cfg）
# ============================================================================
async def _ping_anthropic(
 client: httpx.AsyncClient,
 cred: ProviderCredential,
 cfg: dict[str, Any],
) -> HealthCheckResult:
 """POST /v1/messages/count_tokens —— 稳定轻量端点（比 /v1/models 兼容网关更广）。"""
 start = time.monotonic
 api_key = cfg.get("api_key", "")
 base_url = (
 cfg.get("base_url")
 or PROVIDER_REGISTRY[ProviderType.ANTHROPIC].default_base_url
 ).rstrip("/")
 # default_model 为空时用 fallback（避免 400 unsupported_model）
 model = cred.default_model or "claude-3-5-haiku-20241022"
 resp = await client.post(
 f"{base_url}/v1/messages/count_tokens",
 headers={
 "x-api-key": api_key,
 "anthropic-version": "2023-06-01",
 "content-type": "application/json",
 },
 json={"model": model, "messages": [{"role": "user", "content": "ping"}]},
 )
 latency = int((time.monotonic - start) * 1000)
 if resp.status_code == 200:
 body = resp.json if resp.content else {}
 if body.get("input_tokens", -1) >= 0:
 return HealthCheckResult(ok=True, status="ok", latency_ms=latency)
 return HealthCheckResult(
 ok=False,
 status="error",
 latency_ms=latency,
 error=_safe_error(f"{resp.status_code} {resp.text}"),
 )
async def _ping_openai(
 client: httpx.AsyncClient,
 cred: ProviderCredential,
 cfg: dict[str, Any],
) -> HealthCheckResult:
 """GET /v1/models —— OpenAI Chat Completions 与 Responses API 共享。"""
 start = time.monotonic
 api_key = cfg.get("api_key", "")
 base_url = (
 cfg.get("base_url")
 or PROVIDER_REGISTRY[ProviderType.OPENAI_CHAT].default_base_url
 ).rstrip("/")
 headers = {"Authorization": f"Bearer {api_key}"}
 if cfg.get("organization_id"):
 headers["OpenAI-Organization"] = str(cfg["organization_id"])
 resp = await client.get(f"{base_url}/models", headers=headers)
 latency = int((time.monotonic - start) * 1000)
 if resp.status_code == 200:
 body = resp.json if resp.content else {}
 if isinstance(body.get("data"), list) and len(body["data"]) > 0:
 return HealthCheckResult(ok=True, status="ok", latency_ms=latency)
 return HealthCheckResult(
 ok=False,
 status="error",
 latency_ms=latency,
 error=_safe_error(f"{resp.status_code} {resp.text}"),
 )
async def _ping_gemini(
 client: httpx.AsyncClient,
 cred: ProviderCredential,
 cfg: dict[str, Any],
) -> HealthCheckResult:
 """GET /v1beta/models?key=... —— AI Studio 路径，key 走 query string。"""
 start = time.monotonic
 api_key = cfg.get("api_key", "")
 base_url = PROVIDER_REGISTRY[ProviderType.GEMINI].default_base_url.rstrip("/")
 resp = await client.get(f"{base_url}/models", params={"key": api_key})
 latency = int((time.monotonic - start) * 1000)
 if resp.status_code == 200:
 body = resp.json if resp.content else {}
 if isinstance(body.get("models"), list) and len(body["models"]) > 0:
 return HealthCheckResult(ok=True, status="ok", latency_ms=latency)
 return HealthCheckResult(
 ok=False,
 status="error",
 latency_ms=latency,
 error=_safe_error(f"{resp.status_code} {resp.text}"),
 )
async def _ping_ollama(
 client: httpx.AsyncClient,
 cred: ProviderCredential,
 cfg: dict[str, Any],
) -> HealthCheckResult:
 """GET /api/tags —— 同次往返解析 models.name 填充 available_models。"""
 start = time.monotonic
 base_url = (
 cfg.get("base_url")
 or PROVIDER_REGISTRY[ProviderType.OLLAMA].default_base_url
 ).rstrip("/")
 headers: dict[str, str] = {}
 if cfg.get("bearer_token"):
 headers["Authorization"] = f"Bearer {cfg['bearer_token']}"
 resp = await client.get(f"{base_url}/api/tags", headers=headers)
 latency = int((time.monotonic - start) * 1000)
 if resp.status_code == 200:
 body = resp.json if resp.content else {}
 if isinstance(body.get("models"), list):
 model_names = [
 m["name"]
 for m in body["models"]
 if isinstance(m, dict) and "name" in m
 ]
 return HealthCheckResult(
 ok=True,
 status="ok",
 latency_ms=latency,
 available_models=model_names,
 )
 return HealthCheckResult(
 ok=False,
 status="error",
 latency_ms=latency,
 error=_safe_error(f"{resp.status_code} {resp.text}"),
 )
# 5 ProviderType -> _ping_* 函数分派表（Phase 新增 Provider 时仅在此表登记）
_PING_DISPATCH = {
 ProviderType.ANTHROPIC: _ping_anthropic,
 ProviderType.OPENAI_RESPONSES: _ping_openai,
 ProviderType.OPENAI_CHAT: _ping_openai,
 ProviderType.GEMINI: _ping_gemini,
 ProviderType.OLLAMA: _ping_ollama,
}
# ============================================================================
# 主入口：5s timeout + graceful 降级 + 原子 aupdate 三字段
# ============================================================================
async def health_check(credential: ProviderCredential) -> HealthCheckResult:
 """5 Provider 健康检查统一入口。
 - 5s httpx timeout（HEALTH_CHECK_TIMEOUT_SECONDS）
 - TimeoutException / ConnectError / 任意 Exception 全部 graceful 降级，不抛给 caller
 - 上游 error body 经 _safe_error 脱敏 + 500 字符截断
 - Ollama 路径同次往返将 /api/tags 的 models.name 写入 available_models
 - 单 SQL aupdate 原子写回 last_health_check_at / status / error（Ollama 额外 available_models）
 返回：HealthCheckResult（值对象；同时 DB 端三字段已更新）。
 """
 result: HealthCheckResult
 # 1. 解密凭证配置
 try:
 cfg = credential.get_decrypted_config
 except Exception as e:
 result = HealthCheckResult(
 ok=False,
 status="error",
 latency_ms=0,
 error=_safe_error(f"decrypt_failed: {type(e).__name__}"),
 )
 else:
 # 2. 解析 ProviderType
 try:
 pt = ProviderType(credential.provider_type)
 except ValueError:
 result = HealthCheckResult(
 ok=False,
 status="error",
 latency_ms=0,
 error=_safe_error(
 f"unknown_provider_type: {credential.provider_type}"
 ),
 )
 else:
 # 3. 分派到对应 _ping_*
 ping_fn = _PING_DISPATCH.get(pt)
 if ping_fn is None:
 result = HealthCheckResult(
 ok=False,
 status="error",
 latency_ms=0,
 error=f"no_dispatch_for_provider: {pt}",
 )
 else:
 async with httpx.AsyncClient(
 timeout=HEALTH_CHECK_TIMEOUT_SECONDS
 ) as client:
 try:
 result = await ping_fn(client, credential, cfg)
 except httpx.TimeoutException:
 result = HealthCheckResult(
 ok=False,
 status="error",
 latency_ms=int(HEALTH_CHECK_TIMEOUT_SECONDS * 1000),
 error="Connection timeout (5s)",
 )
 except httpx.ConnectError as e:
 result = HealthCheckResult(
 ok=False,
 status="error",
 latency_ms=0,
 error=f"Connection failed: {_safe_error(str(e), 400)}",
 )
 except Exception as e:
 result = HealthCheckResult(
 ok=False,
 status="error",
 latency_ms=0,
 error=_safe_error(str(e), 400),
 )
 # 4. 原子 aupdate 三字段（Ollama 路径额外写 available_models）
 update_kwargs: dict[str, Any] = {
 "last_health_check_at": timezone.now,
 "last_health_check_status": result.status,
 "last_health_check_error": result.error,
 }
 if result.available_models is not None:
 update_kwargs["available_models"] = result.available_models
 await ProviderCredential.objects.filter(id=credential.id).aupdate(**update_kwargs)
 # 5. 结构化日志（T- 缓解：仅 credential_id / provider / latency_ms，不传 cfg）
 if result.ok:
 logger.info(
 "provider_health_check_ok",
 credential_id=str(credential.id),
 provider=credential.provider_type,
 latency_ms=result.latency_ms,
 )
 else:
 logger.warning(
 "provider_health_check_error",
 credential_id=str(credential.id),
 provider=credential.provider_type,
 latency_ms=result.latency_ms,
 # error 已由 _safe_error 脱敏；再次 80 字符截断 + processor 兜底
 error_summary=result.error[:80],
 )
 return result
