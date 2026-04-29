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
 override_model: str | None = None,
) -> HealthCheckResult:
 """POST /v1/messages/count_tokens —— 稳定轻量端点（比 /v1/models 兼容网关更广）。"""
 start = time.monotonic
 api_key = cfg.get("api_key", "")
 base_url = (
 cfg.get("base_url")
 or PROVIDER_REGISTRY[ProviderType.ANTHROPIC].default_base_url
 ).rstrip("/")
 # default_model 为空时用 fallback（避免 400 unsupported_model）
 model = override_model or cred.default_model or "claude-3-5-haiku-20241022"
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
 override_model: str | None = None,
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
 # 若指定了模型，改走轻量 chat.completions 探活（比 /models 更精确）
 if override_model:
 resp = await client.post(
 f"{base_url}/chat/completions",
 headers={**headers, "Content-Type": "application/json"},
 json={"model": override_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
 )
 else:
 resp = await client.get(f"{base_url}/models", headers=headers)
 latency = int((time.monotonic - start) * 1000)
 if resp.status_code == 200:
 body = resp.json if resp.content else {}
 if override_model:
 if "choices" in body:
 return HealthCheckResult(ok=True, status="ok", latency_ms=latency)
 else:
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
 override_model: str | None = None,
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
 override_model: str | None = None,
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
async def health_check(
 credential: ProviderCredential,
 *,
 override_model: str | None = None,
) -> HealthCheckResult:
 """5 Provider 健康检查统一入口。
 - 5s httpx timeout（HEALTH_CHECK_TIMEOUT_SECONDS）
 - TimeoutException / ConnectError / 任意 Exception 全部 graceful 降级，不抛给 caller
 - 上游 error body 经 _safe_error 脱敏 + 500 字符截断
 - Ollama 路径同次往返将 /api/tags 的 models.name 写入 available_models
 - 单 SQL aupdate 原子写回 last_health_check_at / status / error（Ollama 额外 available_models）
 Args:
 credential: 要检查的凭证。
 override_model: 可选，覆盖 credential.default_model 进行测试。
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
 result = await ping_fn(client, credential, cfg, override_model)
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
# ============================================================================
# Phase：模型清单抽取（fetch_models_for_credential）
# ============================================================================
#
# 与 health_check 分离的原因：
# - health_check 语义是"探活 + 原子写三字段"（last_health_check_*），Ollama 顺带
# 写 available_models 是历史协同；其他 4 Provider 的 available_models
# 需要显式拉取，不能混进 health_check（会污染"探活延迟"指标）。
# - fetch_models_for_credential 不主动 aupdate last_health_check_status，只在失败
# 时把脱敏错误写入 last_health_check_error（调用方 ViewSet @action 统一 save）。
# - 返回 list[dict] 统一形状：[{id, display_name, context_length?}, ...]；
# 前端 ModelSelect 组件消费。
async def fetch_models_for_credential(
 credential: ProviderCredential,
) -> list[dict[str, Any]]:
 """按 provider_type dispatch 拉取模型清单。
 返回统一结构：[{id: str, display_name: str, context_length?: int}, ...]
 失败时返回空 list 并将错误脱敏写入 credential.last_health_check_error（不 raise，
 不更新 last_health_check_status——避免污染健康检查语义）。
 Args:
 credential: 已从 DB 读取的 ProviderCredential 实例。
 """
 # 1. 解密凭证配置
 try:
 cfg = credential.get_decrypted_config
 except Exception as exc:
 logger.warning(
 "fetch_models_decrypt_failed",
 credential_id=str(credential.id),
 )
 credential.last_health_check_error = _safe_error(
 f"decrypt_failed: {type(exc).__name__}"
 )
 return
 # 2. 按 provider_type 分派
 provider_type = credential.provider_type
 try:
 if provider_type == ProviderType.ANTHROPIC.value:
 return await _fetch_models_anthropic(cfg)
 if provider_type in (
 ProviderType.OPENAI_RESPONSES.value,
 ProviderType.OPENAI_CHAT.value,
 ):
 return await _fetch_models_openai(cfg)
 if provider_type == ProviderType.GEMINI.value:
 return await _fetch_models_gemini(cfg)
 if provider_type == ProviderType.OLLAMA.value:
 return await _fetch_models_ollama(cfg)
 except Exception as exc:
 logger.warning(
 "fetch_models_failed",
 credential_id=str(credential.id),
 provider_type=provider_type,
 error_summary=_safe_error(str(exc), 80),
 )
 credential.last_health_check_error = _safe_error(str(exc))
 return
 # 未知 provider_type：返回空清单并记录
 logger.warning(
 "fetch_models_unknown_provider",
 credential_id=str(credential.id),
 provider_type=provider_type,
 )
 credential.last_health_check_error = _safe_error(
 f"unknown_provider_type: {provider_type}"
 )
 return
_FETCH_MODELS_TIMEOUT_SECONDS = 15.0
async def _fetch_models_anthropic(cfg: dict[str, Any]) -> list[dict[str, Any]]:
 """Anthropic /v1/models 端点。"""
 api_key = cfg.get("api_key", "")
 base_url = (
 cfg.get("base_url")
 or PROVIDER_REGISTRY[ProviderType.ANTHROPIC].default_base_url
 ).rstrip("/")
 async with httpx.AsyncClient(timeout=_FETCH_MODELS_TIMEOUT_SECONDS) as client:
 resp = await client.get(
 f"{base_url}/v1/models",
 headers={
 "x-api-key": api_key,
 "anthropic-version": "2023-06-01",
 },
 )
 resp.raise_for_status
 payload = resp.json
 data = payload.get("data", ) if isinstance(payload, dict) else
 return [
 {
 "id": m["id"],
 "display_name": m.get("display_name", m["id"]),
 }
 for m in data
 if isinstance(m, dict) and "id" in m
 ]
async def _fetch_models_openai(cfg: dict[str, Any]) -> list[dict[str, Any]]:
 """OpenAI / Compatible /v1/models 端点（Responses + Chat 两种 API 共用）。"""
 api_key = cfg.get("api_key", "")
 base_url = (
 cfg.get("base_url")
 or PROVIDER_REGISTRY[ProviderType.OPENAI_CHAT].default_base_url
 ).rstrip("/")
 headers = {"Authorization": f"Bearer {api_key}"}
 if cfg.get("organization_id"):
 headers["OpenAI-Organization"] = str(cfg["organization_id"])
 async with httpx.AsyncClient(timeout=_FETCH_MODELS_TIMEOUT_SECONDS) as client:
 resp = await client.get(f"{base_url}/models", headers=headers)
 resp.raise_for_status
 payload = resp.json
 data = payload.get("data", ) if isinstance(payload, dict) else
 return [
 {
 "id": m["id"],
 "display_name": m.get("id", ""),
 }
 for m in data
 if isinstance(m, dict) and "id" in m
 ]
async def _fetch_models_gemini(cfg: dict[str, Any]) -> list[dict[str, Any]]:
 """Gemini /v1beta/models 端点（api_key 在 query string；name 剥 models/ 前缀）。"""
 api_key = cfg.get("api_key", "")
 base_url = PROVIDER_REGISTRY[ProviderType.GEMINI].default_base_url.rstrip("/")
 async with httpx.AsyncClient(timeout=_FETCH_MODELS_TIMEOUT_SECONDS) as client:
 resp = await client.get(
 f"{base_url}/models",
 params={"key": api_key},
 )
 resp.raise_for_status
 payload = resp.json
 models = payload.get("models", ) if isinstance(payload, dict) else
 out: list[dict[str, Any]] =
 for m in models:
 if not isinstance(m, dict):
 continue
 raw_name = m.get("name", "")
 model_id = raw_name.split("/")[-1] if raw_name else ""
 if not model_id:
 continue
 entry: dict[str, Any] = {
 "id": model_id,
 "display_name": m.get("displayName", raw_name),
 }
 if m.get("inputTokenLimit") is not None:
 entry["context_length"] = m["inputTokenLimit"]
 out.append(entry)
 return out
async def _fetch_models_ollama(cfg: dict[str, Any]) -> list[dict[str, Any]]:
 """Ollama /api/tags 本地模型列表 + /api/show 合并 context_length。
 /api/show 对未完全 pull 的模型可能返回 4xx：静默降级为仅 id/display_name。
 """
 base_url = (
 cfg.get("base_url")
 or PROVIDER_REGISTRY[ProviderType.OLLAMA].default_base_url
 ).rstrip("/")
 headers: dict[str, str] = {}
 if cfg.get("bearer_token"):
 headers["Authorization"] = f"Bearer {cfg['bearer_token']}"
 async with httpx.AsyncClient(timeout=_FETCH_MODELS_TIMEOUT_SECONDS) as client:
 resp = await client.get(f"{base_url}/api/tags", headers=headers)
 resp.raise_for_status
 payload = resp.json
 models = payload.get("models", ) if isinstance(payload, dict) else
 out: list[dict[str, Any]] =
 for m in models:
 if not isinstance(m, dict) or "name" not in m:
 continue
 name = m["name"]
 entry: dict[str, Any] = {"id": name, "display_name": name}
 try:
 show_resp = await client.post(
 f"{base_url}/api/show",
 json={"name": name},
 headers=headers,
 )
 show_resp.raise_for_status
 show_data = show_resp.json
 model_info = show_data.get("model_info", {})
 if isinstance(model_info, dict):
 ctx = model_info.get("llama.context_length")
 if ctx is not None:
 entry["context_length"] = ctx
 except Exception:
 # /api/show 失败（未 pull / 网关不支持）时静默降级
 pass
 out.append(entry)
 return out
