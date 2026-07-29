"""Qdrant vector database client service."""

import asyncio
import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

import httpx
import structlog
from django.conf import settings
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from system.models import SettingKeys, SystemSetting

logger = structlog.get_logger(__name__)
T = TypeVar("T")

# Qdrant httpx client 超时（秒）。改这里同时更新 get_client() 与可观测性日志字段。
_QDRANT_CLIENT_TIMEOUT_S: float = 60.0


def _vectors_on_disk() -> bool:
    """原始向量是否落盘（mmap，不常驻内存）。

    大量 collection（一仓一 collection）场景下，把原始向量放磁盘可将常驻内存
    从 GB 级降到很低；检索精度靠 int8 量化向量 + rescore 读原始向量保证。
    可用 settings.QDRANT_VECTORS_ON_DISK=false 关闭（回退全内存）。
    """
    return bool(getattr(settings, "QDRANT_VECTORS_ON_DISK", True))


def _scalar_quantization() -> models.ScalarQuantization | None:
    """int8 标量量化配置：量化向量常驻内存（always_ram）做快速召回。

    内存约降至原始的 1/4；检索时默认 rescore 读原始向量重排，召回几乎无损。
    可用 settings.QDRANT_QUANTIZATION_ENABLED=false 关闭。
    """
    if not bool(getattr(settings, "QDRANT_QUANTIZATION_ENABLED", True)):
        return None
    return models.ScalarQuantization(
        scalar=models.ScalarQuantizationConfig(
            type=models.ScalarType.INT8,
            quantile=0.99,
            always_ram=True,
        )
    )

# upsert 可观测性：跨调用统计在飞 upsert 数与累计字节数。
# 仅用于日志，不参与限流，所以用最轻的 threading.Lock 即可。
_upsert_obs_lock = threading.Lock()
_upsert_inflight_count: int = 0
_upsert_total_calls: int = 0


def _estimate_payload_bytes(points: list[dict[str, Any]]) -> int:
    """估算 points payload JSON 序列化后的字节数；失败返回 -1。

    仅供日志，使用 default=str 兜底任意不可序列化对象，避免抛错影响主路径。
    """
    try:
        return sum(
            len(json.dumps(p.get("payload", {}), default=str, ensure_ascii=False).encode("utf-8"))
            for p in points
        )
    except Exception:
        return -1


def _estimate_vector_bytes(points: list[dict[str, Any]]) -> tuple[int, int]:
    """返回 (vector_bytes_total, vector_dim)。假设 float32。

    第一个点的维度作为代表维度（同一批 upsert 维度必然一致）。
    """
    if not points:
        return 0, 0
    first_vec = points[0].get("vector") or []
    dim = len(first_vec) if isinstance(first_vec, list) else 0
    total = sum(
        (len(p.get("vector") or []) if isinstance(p.get("vector"), list) else 0) * 4
        for p in points
    )
    return total, dim


class QdrantService:
    """Service for interacting with Qdrant vector database."""

    _client: QdrantClient | None = None
    _client_url: str | None = None

    @classmethod
    def _get_config_sync(cls) -> dict[str, Any]:
        """Get Qdrant configuration (sync, for client init)。

        解析优先级（与 PostgreSQL 一致的"env 锁定"模型）：环境变量 > SystemSetting(DB) > 默认。
        部署（helm/compose）注入 QDRANT_URL 时即为权威值，DB 中的旧值被忽略，前端据此锁定配置。
        """
        config = {}

        env_url = os.environ.get("QDRANT_URL", "").strip()
        if env_url:
            config["url"] = env_url
        else:
            url_setting = SystemSetting.objects.filter(key=SettingKeys.QDRANT_URL).first()
            config["url"] = url_setting.value if url_setting else "http://localhost:6333"

        env_api_key = os.environ.get("QDRANT_API_KEY", "").strip()
        if env_api_key:
            config["api_key"] = env_api_key
        else:
            api_key_setting = SystemSetting.objects.filter(key=SettingKeys.QDRANT_API_KEY).first()
            if api_key_setting and api_key_setting.value:
                from common.encryption import decrypt_value

                config["api_key"] = decrypt_value(api_key_setting.value)

        return config

    @classmethod
    async def get_config(cls) -> dict[str, Any]:
        """Get Qdrant configuration (async)。优先级：环境变量 > SystemSetting(DB) > 默认。"""
        config = {}

        env_url = os.environ.get("QDRANT_URL", "").strip()
        if env_url:
            config["url"] = env_url
        else:
            url_setting = await SystemSetting.objects.filter(key=SettingKeys.QDRANT_URL).afirst()
            config["url"] = url_setting.value if url_setting else "http://localhost:6333"

        env_api_key = os.environ.get("QDRANT_API_KEY", "").strip()
        if env_api_key:
            config["api_key"] = env_api_key
        else:
            api_key_setting = await SystemSetting.objects.filter(
                key=SettingKeys.QDRANT_API_KEY
            ).afirst()
            if api_key_setting and api_key_setting.value:
                from common.encryption import decrypt_value

                config["api_key"] = decrypt_value(api_key_setting.value)

        return config

    @classmethod
    def get_client(cls) -> QdrantClient:
        """Get or create Qdrant client."""
        if cls._client is None:
            import os

            config = cls._get_config_sync()
            url = config.get("url", "http://localhost:6333")
            proxy_vars = {k: v for k, v in os.environ.items() if "proxy" in k.lower()}
            logger.debug("qdrant_client_init", url=url, proxy_env=proxy_vars)
            cls._client = QdrantClient(
                url=url,
                api_key=config.get("api_key"),
                # 禁止 httpx 自动加载系统/环境代理（macOS 系统代理、HTTP(S)_PROXY 等）。
                # Qdrant 通常部署在内网 / Tailscale，走代理会被反代成 502。
                trust_env=False,
                # 关闭启动时的版本兼容探测，避免走系统代理失败时产生噪音警告。
                check_compatibility=False,
                # qdrant-client SDK 默认 timeout=5s，对大 batch upsert 太短：
                # 100 个点 + hybrid sparse + dense 512+ 维 → 单次写入轻易超 5s，
                # 触发 httpx.ReadTimeout / socket.timeout → indexer 顶层 catch
                # → index_status=FAILED & error="timed out"，灾难性后果。
                # 设 _QDRANT_CLIENT_TIMEOUT_S 给冷启动 & 偶发抖动留余量。
                timeout=_QDRANT_CLIENT_TIMEOUT_S,
            )
            cls._client_url = url
            cls._disable_keepalive_reuse(cls._client)
        return cls._client

    @staticmethod
    def _disable_keepalive_reuse(client: QdrantClient) -> None:
        """关闭 httpx 连接池的 keepalive 复用。

        历史事故：httpx ConnectionPool 默认 ``keepalive_expiry=5s``、
        ``max_keepalive_connections=20``。Qdrant 服务端（actix）keepalive
        也约 5s。两端齐平 → 存在时间窗：连接已被服务端 FIN（socket 进入
        CLOSE_WAIT），客户端连接池仍判定可用 → 下次拿出来 write 半关闭
        socket 成功、read response 永远收不到 → 等满 60s 抛
        ``ResponseHandlingException("timed out")`` → indexer 大型仓库索引
        几乎必现的 "写入向量库失败或超时"。

        修复：把 keepalive 上限拍到 0 ——每次 HTTP 请求新建 TCP 连接、用完
        立刻关。代价是每次 upsert 多一次 TCP 握手（本地 docker ~µs，远端
        Tailscale ~45ms），相对于动辄数秒的 upsert 耗时可以忽略。

        失败容忍：拿到不熟悉的 qdrant-client / httpx 版本时（结构变了）
        不应让 ``get_client()`` 崩，只记录 warning。
        """
        try:
            httpx_client = client.http.client._client  # type: ignore[attr-defined]
            pool = httpx_client._transport._pool  # type: ignore[attr-defined]
            pool._max_keepalive_connections = 0  # type: ignore[attr-defined]
            pool._keepalive_expiry = 0.0  # type: ignore[attr-defined]
            logger.info("qdrant_client_keepalive_disabled")
        except AttributeError as exc:
            logger.warning(
                "qdrant_client_keepalive_disable_failed",
                error=str(exc),
                hint="qdrant-client / httpx internals changed; investigate",
            )

    @classmethod
    def reset_client(cls) -> None:
        """Reset client (useful when config changes)."""
        if cls._client is not None:
            try:
                cls._client.close()
            except Exception as exc:
                logger.warning("qdrant_client_close_failed", error=str(exc))
            finally:
                cls._client = None
                cls._client_url = None

    @staticmethod
    def _is_bad_file_descriptor(exc: OSError) -> bool:
        return getattr(exc, "errno", None) == 9 or "Bad file descriptor" in str(exc)

    @classmethod
    def _classify_failure(cls, exc: BaseException) -> str:
        text = str(exc).lower()
        if isinstance(exc, OSError) and cls._is_bad_file_descriptor(exc):
            return "bad_file_descriptor"
        if "timed out" in text or "timeout" in text:
            return "timeout"
        if isinstance(exc, ConnectionError):
            return "connection_error"
        if isinstance(exc, OSError) and getattr(exc, "errno", None) in {
            54,  # ECONNRESET
            32,  # EPIPE
            104,  # ECONNRESET on Linux
            61,  # ECONNREFUSED
            111,  # ECONNREFUSED on Linux
        }:
            return "connection_error"
        if isinstance(exc, httpx.HTTPError):
            return "http_error"
        if isinstance(exc, UnexpectedResponse):
            return "unexpected_response"
        if isinstance(exc, ResponseHandlingException):
            return "response_handling_error"
        return "unknown"

    # upsert 软错误重试白名单。bad_file_descriptor / timeout / connection_error /
    # response_handling_error / http_error 这五类都对应"客户端连接已坏 / 半关闭 /
    # idle 期被对端 FIN" 的死连接症状，统一靠 reset_client + 重试一次 兜底。
    # unexpected_response 是 Qdrant 业务错误（维度不匹配、collection 不存在等），
    # 重试无意义，必须立刻失败让上层感知。
    _UPSERT_RETRYABLE_REASONS = frozenset({
        "bad_file_descriptor",
        "timeout",
        "connection_error",
        "response_handling_error",
        "http_error",
    })

    @classmethod
    def _call_with_upsert_retry(
        cls,
        operation: str,
        fn: Callable[[QdrantClient], T],
        on_retry: Callable[[str, BaseException], None] | None = None,
    ) -> T:
        """upsert 路径专用：软错误时 reset client + 重试一次。

        触发重试的错误（见 ``_UPSERT_RETRYABLE_REASONS``）都对应"连接已死但
        客户端不知道"的症状（idle 期对端 FIN、bad fd、半关闭 socket 等）。
        关键修复点：必须 ``reset_client()`` 让下次 ``get_client()`` 重建
        TCP 连接池，否则重试仍命中同一条死连接。
        """
        client = cls.get_client()
        try:
            return fn(client)
        except (OSError, httpx.HTTPError, ResponseHandlingException) as exc:
            reason = cls._classify_failure(exc)
            if reason not in cls._UPSERT_RETRYABLE_REASONS:
                raise
            if on_retry is not None:
                on_retry(reason, exc)
            logger.warning(
                "qdrant_upsert_soft_retry",
                operation=operation,
                reason=reason,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            cls.reset_client()
            return fn(cls.get_client())

    @classmethod
    def _call_with_bad_fd_retry(
        cls,
        operation: str,
        fn: Callable[[QdrantClient], T],
    ) -> T:
        """执行一次 Qdrant 操作；坏 fd 时重建 client 并重试一次。"""
        try:
            return fn(cls.get_client())
        except OSError as exc:
            if not cls._is_bad_file_descriptor(exc):
                raise
            logger.warning(
                "qdrant_bad_fd_retry",
                operation=operation,
                reason="bad_file_descriptor",
                error=str(exc),
            )
            cls.reset_client()
            return fn(cls.get_client())

    @classmethod
    def ping_liveness(cls) -> dict[str, Any]:
        """轻量存活探测：只 GET ``/healthz``，不枚举 collection。

        健康检查只应回答"服务是否存活、能否连上",不该调 ``get_collections``——
        一仓一 collection 时它会遍历数百个 collection，在并发/IO 抖动下把 Qdrant 的
        actix worker 占满，反而把健康检查自己拖成超时（曾导致右上角常驻"异常"）。
        ``/healthz`` 是 Qdrant 免鉴权的 liveness 端点，毫秒级返回。
        """
        config = cls._get_config_sync()
        url = str(config.get("url", "http://localhost:6333")).rstrip("/")
        try:
            resp = httpx.get(f"{url}/healthz", timeout=3.0, trust_env=False)
        except Exception as exc:
            return {"status": "unhealthy", "error": str(exc)}
        if resp.status_code == 200:
            return {"status": "healthy"}
        return {"status": "unhealthy", "error": f"HTTP {resp.status_code}"}

    @classmethod
    def health_check(cls) -> dict[str, Any]:
        """Check Qdrant service health.

        关键不变量：**绝不能在 health 路径上 reset 已缓存的 client**。
        历史事故：定期健康检查触发 reset_client() → 关掉了正在 upsert 的
        httpx 连接池 → 在飞中的 PUT /points 已被 Qdrant 200 返回，但 Python
        端连接已死 → httpx 等满 60s 抛 ResponseHandlingException("timed out")，
        最终在 indexer 顶层显示成"写入向量库失败或超时"。

        正确做法：复用缓存 client；只有在 get_collections 抛连接级错误时
        才尝试 reset + 重建一次。配置变更通过 SystemSetting post_save
        signal 显式调用 reset_client()，而不是靠 health_check 兜底。
        """
        try:
            client = cls.get_client()
            info = client.get_collections()
            return {
                "status": "healthy",
                "collections_count": len(info.collections),
            }
        except Exception as e:
            reason = cls._classify_failure(e)
            logger.warning(
                "qdrant_health_check_first_attempt_failed",
                reason=reason,
                error=str(e),
                error_type=type(e).__name__,
            )
            # 仅在连接级错误时 reset+重试，避免对正在 upsert 的 client 误伤
            if reason in {
                "bad_file_descriptor",
                "connection_error",
                "timeout",
                "http_error",
                "response_handling_error",
            }:
                cls.reset_client()
                try:
                    client = cls.get_client()
                    info = client.get_collections()
                    return {
                        "status": "healthy",
                        "collections_count": len(info.collections),
                    }
                except Exception as retry_exc:
                    logger.error(
                        "qdrant_health_check_failed",
                        reason=cls._classify_failure(retry_exc),
                        error=str(retry_exc),
                        error_type=type(retry_exc).__name__,
                    )
                    return {
                        "status": "unhealthy",
                        "error": str(retry_exc),
                    }

            logger.error("qdrant_health_check_failed", error=str(e))
            return {
                "status": "unhealthy",
                "error": str(e),
            }

    @staticmethod
    def health_check_with_config(
        url: str | None = None, api_key: str | None = None
    ) -> dict[str, Any]:
        """Check Qdrant health with provided config (before saving)."""
        target_url = url or "http://localhost:6333"
        try:
            client = QdrantClient(
                url=target_url,
                api_key=api_key or None,
                trust_env=False,
                check_compatibility=False,
            )
            info = client.get_collections()
            client.close()
            return {
                "status": "healthy",
                "message": "Qdrant 连接成功",
                "collections_count": len(info.collections),
            }
        except Exception as e:
            reason = QdrantService._classify_failure(e)
            logger.error(
                "qdrant_health_check_with_config_failed",
                url=target_url,
                reason=reason,
                error=str(e),
                error_type=type(e).__name__,
            )
            return {
                "status": "unhealthy",
                "message": f"{type(e).__name__}: {e}",
                "error": str(e),
                "reason": reason,
            }

    @classmethod
    def get_collection_name(cls, repository_id: str) -> str:
        """Generate collection name for a repository."""
        return f"code_index_{repository_id}"

    @classmethod
    def create_collection(
        cls,
        repository_id: str,
        vector_size: int = 1024,
        hybrid: bool = False,
    ) -> bool:
        """Create a collection for repository code index.

        Args:
            repository_id: Repository ID
            vector_size: Dense vector dimension
            hybrid: 是否启用混合检索（同时存储 dense + sparse vectors）
        """
        client = cls.get_client()
        collection_name = cls.get_collection_name(repository_id)

        try:
            # Check if collection exists
            collections = client.get_collections()
            existing_names = [c.name for c in collections.collections]

            if collection_name in existing_names:
                # 检测现有 collection 是否需要重建（维度变化或 hybrid 模式变化）
                collection_info = client.get_collection(collection_name)
                vectors_config = collection_info.config.params.vectors

                # 判断现有 collection 类型
                if isinstance(vectors_config, dict):
                    # Named vectors 模式（hybrid）
                    existing_hybrid = True
                    existing_size = vectors_config.get(
                        "dense", models.VectorParams(size=0, distance=models.Distance.COSINE)
                    ).size
                else:
                    # 单向量模式（非 hybrid）
                    existing_hybrid = False
                    existing_size = vectors_config.size  # type: ignore[union-attr]

                need_recreate = existing_size != vector_size or existing_hybrid != hybrid
                if need_recreate:
                    logger.debug(
                        "collection_config_mismatch",
                        collection_name=collection_name,
                        existing_size=existing_size,
                        new_size=vector_size,
                        existing_hybrid=existing_hybrid,
                        new_hybrid=hybrid,
                    )
                    client.delete_collection(collection_name=collection_name)
                    logger.debug("collection_deleted_for_recreate", collection_name=collection_name)
                else:
                    logger.debug("collection_already_exists", collection_name=collection_name)
                    return True

            # Create collection
            # 大量 collection 场景省内存：原始向量 on_disk（mmap）+ int8 量化常驻内存。
            on_disk = _vectors_on_disk()
            quantization_config = _scalar_quantization()
            if hybrid:
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config={
                        "dense": models.VectorParams(
                            size=vector_size,
                            distance=models.Distance.COSINE,
                            on_disk=on_disk,
                        ),
                    },
                    sparse_vectors_config={
                        "sparse": models.SparseVectorParams(),
                    },
                    quantization_config=quantization_config,
                )
                logger.debug("collection_created_hybrid", collection_name=collection_name)
            else:
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                        on_disk=on_disk,
                    ),
                    quantization_config=quantization_config,
                )
                logger.debug("collection_created", collection_name=collection_name)

            # Create payload index for filtering
            client.create_payload_index(
                collection_name=collection_name,
                field_name="file_path",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            client.create_payload_index(
                collection_name=collection_name,
                field_name="file_hash",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            client.create_payload_index(
                collection_name=collection_name,
                field_name="language",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )

            return True

        except UnexpectedResponse as e:
            logger.error("create_collection_failed", error=str(e))
            return False

    @classmethod
    def create_branch_payload_index(cls, collection_name: str) -> bool:
        """为指定 collection 创建 branch_name keyword payload index。"""
        client = cls.get_client()
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name="branch_name",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            return True
        except UnexpectedResponse:
            logger.warning(
                "branch_payload_index_may_exist",
                collection_name=collection_name,
            )
            return False

    @classmethod
    def create_snapshot(cls, repository_id: str) -> str | None:
        """Create a snapshot for repository's collection. Returns snapshot filename."""
        client = cls.get_client()
        collection_name = cls.get_collection_name(repository_id)
        try:
            result = client.create_snapshot(collection_name=collection_name)
            return result.name if result else None
        except UnexpectedResponse as e:
            logger.error("create_snapshot_failed", error=str(e))
            return None

    @classmethod
    def delete_collection(cls, repository_id: str) -> bool:
        """Delete a collection for repository."""
        client = cls.get_client()
        collection_name = cls.get_collection_name(repository_id)

        try:
            client.delete_collection(collection_name=collection_name)
            logger.debug("collection_deleted", collection_name=collection_name)
            return True
        except UnexpectedResponse as e:
            logger.error("delete_collection_failed", error=str(e))
            return False

    @classmethod
    def get_stored_file_hashes(cls, repository_id: str) -> dict[str, str]:
        """Get all stored file paths and their hashes from collection."""
        collection_name = cls.get_collection_name(repository_id)

        try:
            def _read_hashes(client: QdrantClient) -> dict[str, str]:
                file_hashes: dict[str, str] = {}
                # Scroll through all points to get file_path and file_hash
                offset = None
                while True:
                    result = client.scroll(
                        collection_name=collection_name,
                        scroll_filter=None,
                        limit=1000,
                        offset=offset,
                        with_payload=["file_path", "file_hash"],
                        with_vectors=False,
                    )

                    points, next_offset = result

                    for point in points:
                        if point.payload:
                            file_path = point.payload.get("file_path")
                            file_hash = point.payload.get("file_hash")
                            if file_path and file_hash:
                                file_hashes[file_path] = file_hash

                    if next_offset is None:
                        break
                    offset = next_offset

                return file_hashes

            return cls._call_with_bad_fd_retry("get_stored_file_hashes", _read_hashes)

        except UnexpectedResponse:
            # Collection might not exist
            return {}
        except OSError as e:
            logger.error("get_stored_file_hashes_os_failed", error=str(e))
            return {}

    @classmethod
    def update_file_path(cls, repository_id: str, old_path: str, new_path: str) -> bool:
        """更新指定文件的路径元数据（用于 rename 不重新索引）。"""
        client = cls.get_client()
        collection_name = cls.get_collection_name(repository_id)
        try:
            client.set_payload(
                collection_name=collection_name,
                payload={"file_path": new_path},
                points=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="file_path",
                            match=models.MatchValue(value=old_path),
                        )
                    ]
                ),
            )
            return True
        except UnexpectedResponse as e:
            logger.error(
                "update_file_path_failed", error=str(e), old_path=old_path, new_path=new_path
            )
            return False

    @classmethod
    def get_collection_stats(cls, repository_id: str) -> dict[str, Any]:
        """获取仓库索引集合的统计信息（chunk 数、语言分布）。"""
        collection_name = cls.get_collection_name(repository_id)

        try:
            def _collect(client: QdrantClient) -> dict[str, Any]:
                # 检查 collection 是否存在
                collections = client.get_collections()
                existing_names = [c.name for c in collections.collections]
                if collection_name not in existing_names:
                    return {"exists": False, "points_count": 0, "language_distribution": {}}

                # 精确计数
                count_result = client.count(collection_name=collection_name, exact=True)
                points_count = count_result.count

                # 遍历所有 points 统计语言分布
                language_counts: dict[str, int] = {}
                indexed_files: set[str] = set()
                offset = None
                while True:
                    points, next_offset = client.scroll(
                        collection_name=collection_name,
                        scroll_filter=None,
                        limit=1000,
                        offset=offset,
                        with_payload=["language", "file_path"],
                        with_vectors=False,
                    )
                    for point in points:
                        if point.payload:
                            lang = point.payload.get("language", "unknown")
                            language_counts[lang] = language_counts.get(lang, 0) + 1
                            fp = point.payload.get("file_path")
                            if fp:
                                indexed_files.add(fp)
                    if next_offset is None:
                        break
                    offset = next_offset

                return {
                    "exists": True,
                    "points_count": points_count,
                    "language_distribution": language_counts,
                    "indexed_files_count": len(indexed_files),
                }

            return cls._call_with_bad_fd_retry("get_collection_stats", _collect)
        except UnexpectedResponse as e:
            logger.error("get_collection_stats_failed", error=str(e))
            return {"exists": False, "points_count": 0, "language_distribution": {}}
        except OSError as e:
            logger.error("get_collection_stats_os_failed", error=str(e))
            return {"exists": False, "points_count": 0, "language_distribution": {}}

    @classmethod
    def check_collection_health(cls, repository_id: str) -> dict[str, Any]:
        """校验仓库索引集合的健康状态。"""
        collection_name = cls.get_collection_name(repository_id)

        try:
            def _check(client: QdrantClient) -> dict[str, Any]:
                collections = client.get_collections()
                existing_names = [c.name for c in collections.collections]
                if collection_name not in existing_names:
                    return {
                        "status": "unhealthy",
                        "collection_exists": False,
                        "points_count": 0,
                    }

                count_result = client.count(collection_name=collection_name, exact=True)
                return {
                    "status": "healthy",
                    "collection_exists": True,
                    "points_count": count_result.count,
                }

            return cls._call_with_bad_fd_retry("check_collection_health", _check)
        except UnexpectedResponse as e:
            logger.error("check_collection_health_failed", error=str(e))
            return {
                "status": "unhealthy",
                "collection_exists": False,
                "points_count": 0,
                "error": str(e),
            }
        except OSError as e:
            logger.error("check_collection_health_os_failed", error=str(e))
            return {
                "status": "unhealthy",
                "collection_exists": False,
                "points_count": 0,
                "error": str(e),
            }

    @staticmethod
    def _is_collection_not_found(exc: UnexpectedResponse) -> bool:
        """判定 UnexpectedResponse 是否为「collection 不存在」（404）。

        删除路径据此把「collection 不存在」识别为幂等 no-op（待删数据本就不存在），
        而非真实删除失败——否则对「从未索引 / 已清净」的仓库重复 purge 会误报失败
        （ME-01：违反 ``purge_file`` 幂等契约）。
        """
        if getattr(exc, "status_code", None) == 404:
            return True
        text = str(exc).lower()
        return "doesn't exist" in text or "not found" in text or "not exist" in text

    @classmethod
    def delete_by_file_path(cls, repository_id: str, file_path: str) -> bool:
        """Delete all vectors for a specific file path.

        幂等语义（ME-01）：collection 不存在视为成功 no-op（无残留可删），不计删除失败。
        """
        client = cls.get_client()
        collection_name = cls.get_collection_name(repository_id)

        try:
            client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="file_path",
                                match=models.MatchValue(value=file_path),
                            )
                        ]
                    )
                ),
            )
            return True
        except UnexpectedResponse as e:
            if cls._is_collection_not_found(e):
                logger.info(
                    "delete_by_file_path_collection_absent",
                    collection_name=collection_name,
                    file_path=file_path,
                )
                return True  # 幂等 no-op：collection 不存在即无残留可删
            logger.error("delete_by_file_path_failed", error=str(e), file_path=file_path)
            return False

    @classmethod
    def upsert_vectors(
        cls,
        repository_id: str,
        points: list[dict[str, Any]],
    ) -> bool:
        """Upsert vectors to collection.

        Args:
            repository_id: Repository ID
            points: List of points with id, vector, and payload

        可观测性：
            每次调用都打 ``upsert_vectors_call_start`` / ``_success`` / ``_*_failed``，
            共享同一个 ``call_id``，便于把单次 upsert 的发起、耗时、字节数、
            在飞并发数串起来做统计。失败日志一定带 ``elapsed_ms``，方便区分
            "立刻失败"（连接问题）vs "等到 timeout"（写入阻塞）。
        """
        global _upsert_inflight_count, _upsert_total_calls

        collection_name = cls.get_collection_name(repository_id)
        call_id = uuid.uuid4().hex[:8]
        points_count = len(points)
        vector_bytes, vector_dim = _estimate_vector_bytes(points)
        payload_bytes = _estimate_payload_bytes(points)
        total_bytes = vector_bytes + max(payload_bytes, 0)

        with _upsert_obs_lock:
            _upsert_inflight_count += 1
            _upsert_total_calls += 1
            in_flight_at_start = _upsert_inflight_count
            call_seq = _upsert_total_calls

        # 兜底用 "unknown"，避免为了日志去查 DB（也避免在单测里强引 SystemSetting）。
        qdrant_url = cls._client_url or "unknown"

        start_monotonic = time.monotonic()
        logger.info(
            "upsert_vectors_call_start",
            call_id=call_id,
            call_seq=call_seq,
            repository_id=repository_id,
            collection_name=collection_name,
            points_count=points_count,
            vector_dim=vector_dim,
            vector_bytes=vector_bytes,
            payload_bytes=payload_bytes,
            total_bytes=total_bytes,
            in_flight=in_flight_at_start,
            qdrant_url=qdrant_url,
            client_timeout_s=_QDRANT_CLIENT_TIMEOUT_S,
        )

        def _elapsed_ms() -> float:
            return round((time.monotonic() - start_monotonic) * 1000, 2)

        def _log_fail(event: str, exc: BaseException) -> None:
            logger.error(
                event,
                call_id=call_id,
                call_seq=call_seq,
                repository_id=repository_id,
                collection_name=collection_name,
                points_count=points_count,
                vector_dim=vector_dim,
                vector_bytes=vector_bytes,
                payload_bytes=payload_bytes,
                total_bytes=total_bytes,
                in_flight=in_flight_at_start,
                qdrant_url=qdrant_url,
                client_timeout_s=_QDRANT_CLIENT_TIMEOUT_S,
                elapsed_ms=_elapsed_ms(),
                reason=cls._classify_failure(exc),
                error=str(exc),
                error_type=type(exc).__name__,
            )

        retry_state: dict[str, Any] = {"attempted": False, "first_reason": None}

        def _on_retry(reason: str, exc: BaseException) -> None:
            retry_state["attempted"] = True
            retry_state["first_reason"] = reason
            logger.warning(
                "upsert_vectors_first_attempt_failed",
                call_id=call_id,
                call_seq=call_seq,
                repository_id=repository_id,
                collection_name=collection_name,
                points_count=points_count,
                total_bytes=total_bytes,
                elapsed_ms=_elapsed_ms(),
                reason=reason,
                error=str(exc),
                error_type=type(exc).__name__,
            )

        try:
            qdrant_points = [
                models.PointStruct(
                    id=p["id"],
                    vector=p["vector"],
                    payload=p["payload"],
                )
                for p in points
            ]

            def _upsert(client: QdrantClient) -> bool:
                client.upsert(
                    collection_name=collection_name,
                    points=qdrant_points,
                )
                return True

            result = cls._call_with_upsert_retry(
                "upsert_vectors", _upsert, on_retry=_on_retry,
            )
            logger.info(
                "upsert_vectors_call_success",
                call_id=call_id,
                call_seq=call_seq,
                repository_id=repository_id,
                collection_name=collection_name,
                points_count=points_count,
                total_bytes=total_bytes,
                elapsed_ms=_elapsed_ms(),
                in_flight_at_start=in_flight_at_start,
                retry_attempted=retry_state["attempted"],
                first_attempt_reason=retry_state["first_reason"],
            )
            return result
        except UnexpectedResponse as e:
            _log_fail("upsert_vectors_failed", e)
            return False
        except ResponseHandlingException as e:
            _log_fail("upsert_vectors_response_handling_failed", e)
            return False
        except httpx.HTTPError as e:
            # 网络层异常（timeout / connect refused / read error）：
            # 不让单次 batch 抖动炸掉整次索引（这是 indexer 'timed out' 失败的元凶）。
            # 调用方需要感知失败并跳过 FileIndex 锚点写入，避免数据丢失被静默吞掉。
            _log_fail("upsert_vectors_network_failed", e)
            return False
        except OSError as e:
            _log_fail("upsert_vectors_os_failed", e)
            return False
        finally:
            with _upsert_obs_lock:
                _upsert_inflight_count -= 1

    @classmethod
    def search(
        cls,
        repository_id: str,
        query_vector: list[float],
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar vectors.

        Args:
            repository_id: Repository ID
            query_vector: Query embedding vector
            top_k: Number of results to return
            filters: Optional filters (language, file_pattern)

        Returns:
            List of search results with score and payload
        """
        client = cls.get_client()
        collection_name = cls.get_collection_name(repository_id)

        # Build filter conditions
        filter_conditions = []
        if filters:
            if "language" in filters:
                filter_conditions.append(
                    models.FieldCondition(
                        key="language",
                        match=models.MatchValue(value=filters["language"]),
                    )
                )

        query_filter = None
        if filter_conditions:
            query_filter = models.Filter(must=filter_conditions)

        try:
            results = client.query_points(
                collection_name=collection_name,
                query=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )

            return [
                {
                    "id": str(r.id),
                    "score": r.score,
                    "payload": r.payload,
                }
                for r in results.points
            ]
        except UnexpectedResponse as e:
            logger.error("search_failed", error=str(e))
            return []

    @classmethod
    def get_configured_embedding_dimension(cls) -> int:
        """读取系统设置中的 embedding 维度（与 indexer 建 code_index 时同源）。

        ensure_repo_summaries_collection 等"派生 collection"必须与 code_index
        使用同一维度，否则 upsert 会因维度不匹配静默失败（历史 bug：写死 1024
        而 embedding 模型实际输出 2560，repo_summaries 永远为空 →
        route_repositories 永远返回空列表）。
        """
        setting = SystemSetting.objects.filter(key=SettingKeys.EMBEDDING_DIMENSION).first()
        return int(setting.value) if setting and setting.value else 1024

    @classmethod
    def create_collection_by_name(
        cls,
        collection_name: str,
        vector_size: int = 1024,
        hybrid: bool = False,
        recreate_on_mismatch: bool = False,
    ) -> bool:
        """创建指定名称的 collection（用于 overlay branch collection）。

        与 create_collection 逻辑一致但接受 collection_name 而非 repository_id。

        Args:
            recreate_on_mismatch: 已存在 collection 的维度 / hybrid 模式与期望不符时，
                是否删除重建。仅适用于**可从源数据完整重建**的派生 collection
                （repo_summaries / repo_index_nodes / overlay 分支索引）；
                不可重建的数据（如 delivery_knowledge）必须保持 False，
                由调用方自行处理不一致。
        """
        client = cls.get_client()
        try:
            collections = client.get_collections()
            existing_names = [c.name for c in collections.collections]

            if collection_name in existing_names:
                if not recreate_on_mismatch:
                    logger.info("collection_already_exists", collection_name=collection_name)
                    return True

                # 与 create_collection 相同的配置漂移检测：维度或 hybrid 模式
                # 不一致就删除重建，否则后续 upsert 全部 400（维度错误）被静默吞掉。
                collection_info = client.get_collection(collection_name)
                vectors_config = collection_info.config.params.vectors
                if isinstance(vectors_config, dict):
                    existing_hybrid = True
                    existing_size = vectors_config.get(
                        "dense", models.VectorParams(size=0, distance=models.Distance.COSINE)
                    ).size
                else:
                    existing_hybrid = False
                    existing_size = vectors_config.size  # type: ignore[union-attr]

                if existing_size == vector_size and existing_hybrid == hybrid:
                    logger.info("collection_already_exists", collection_name=collection_name)
                    return True

                logger.warning(
                    "collection_config_mismatch_recreate",
                    collection_name=collection_name,
                    existing_size=existing_size,
                    new_size=vector_size,
                    existing_hybrid=existing_hybrid,
                    new_hybrid=hybrid,
                )
                client.delete_collection(collection_name=collection_name)

            if hybrid:
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config={
                        "dense": models.VectorParams(
                            size=vector_size,
                            distance=models.Distance.COSINE,
                        ),
                    },
                    sparse_vectors_config={
                        "sparse": models.SparseVectorParams(),
                    },
                )
            else:
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                    ),
                )

            for field in ("file_path", "file_hash", "language", "branch_name"):
                client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )

            logger.debug("overlay_collection_created", collection_name=collection_name)
            return True
        except UnexpectedResponse as e:
            logger.error("create_collection_by_name_failed", error=str(e))
            return False

    @classmethod
    def ensure_repo_summaries_collection(cls, vector_size: int | None = None) -> bool:
        """确保 repo_summaries collection 存在（hybrid 模式，幂等）。

        vector_size 缺省时从系统设置 EMBEDDING_DIMENSION 解析，保证与 code_index
        同维度；已存在但维度 / 模式漂移时自动重建（repo_summaries 可随时由
        rebuild_repo_summaries 全量回填，删除无数据丢失风险）。
        """
        if vector_size is None:
            vector_size = cls.get_configured_embedding_dimension()
        return cls.create_collection_by_name(
            "repo_summaries", vector_size=vector_size, hybrid=True, recreate_on_mismatch=True
        )

    @classmethod
    def ensure_repo_index_nodes_collection(cls, vector_size: int | None = None) -> bool:
        """确保 repo_index_nodes collection 存在（能力树节点级索引，hybrid，幂等）。

        与 ensure_repo_summaries_collection 同策略：维度跟随系统设置，
        漂移自动重建（节点向量可由 RepoIndexTreeService 重新生成）。
        """
        if vector_size is None:
            vector_size = cls.get_configured_embedding_dimension()
        created = cls.create_collection_by_name(
            "repo_index_nodes", vector_size=vector_size, hybrid=True, recreate_on_mismatch=True
        )
        if created:
            # repository_id / node_type 是路由与浏览的主过滤字段
            client = cls.get_client()
            for field in ("repository_id", "node_type", "sub_project"):
                try:
                    client.create_payload_index(
                        collection_name="repo_index_nodes",
                        field_name=field,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )
                except UnexpectedResponse:
                    pass  # 已存在
        return created

    @classmethod
    def delete_by_payload_field(
        cls, collection_name: str, field: str, value: str
    ) -> bool:
        """按 payload 字段等值条件删除 points（如重建某仓库的全部树节点）。"""
        client = cls.get_client()
        try:
            client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key=field,
                                match=models.MatchValue(value=value),
                            )
                        ]
                    )
                ),
            )
            return True
        except UnexpectedResponse as e:
            if cls._is_collection_not_found(e):
                logger.info(
                    "delete_by_payload_field_collection_absent",
                    collection_name=collection_name,
                    field=field,
                )
                return True  # 幂等 no-op：collection 不存在即无残留可删（ME-01）
            logger.warning(
                "delete_by_payload_field_failed",
                collection_name=collection_name,
                field=field,
                error=str(e),
            )
            return False

    @classmethod
    def delete_collection_by_name(cls, collection_name: str) -> bool:
        """按名称删除 collection（用于清理 overlay branch collection）。"""
        client = cls.get_client()
        try:
            client.delete_collection(collection_name=collection_name)
            logger.debug("overlay_collection_deleted", collection_name=collection_name)
            return True
        except UnexpectedResponse as e:
            logger.error("delete_collection_by_name_failed", error=str(e))
            return False

    @classmethod
    def upsert_vectors_by_name(
        cls,
        collection_name: str,
        points: list[dict[str, Any]],
    ) -> bool:
        """向指定名称的 collection upsert points。"""
        try:
            qdrant_points = [
                models.PointStruct(
                    id=p["id"],
                    vector=p["vector"],
                    payload=p["payload"],
                )
                for p in points
            ]

            def _upsert(client: QdrantClient) -> bool:
                logger.debug(
                    "upsert_vectors_by_name_start",
                    collection_name=collection_name,
                    points_count=len(qdrant_points),
                )
                client.upsert(
                    collection_name=collection_name,
                    points=qdrant_points,
                )
                logger.debug(
                    "upsert_vectors_by_name_complete",
                    collection_name=collection_name,
                    points_count=len(qdrant_points),
                )
                return True

            return cls._call_with_bad_fd_retry(
                "upsert_vectors_by_name",
                _upsert,
            )
        except UnexpectedResponse as e:
            logger.error(
                "upsert_vectors_by_name_failed",
                collection_name=collection_name,
                points_count=len(points),
                reason=cls._classify_failure(e),
                error=str(e),
                error_type=type(e).__name__,
            )
            return False
        except ResponseHandlingException as e:
            logger.error(
                "upsert_vectors_by_name_response_handling_failed",
                points_count=len(points),
                reason=cls._classify_failure(e),
                error=str(e), error_type=type(e).__name__,
                collection_name=collection_name,
            )
            return False
        except httpx.HTTPError as e:
            logger.error(
                "upsert_vectors_by_name_network_failed",
                points_count=len(points),
                reason=cls._classify_failure(e),
                error=str(e), error_type=type(e).__name__,
                collection_name=collection_name,
            )
            return False
        except OSError as e:
            logger.error(
                "upsert_vectors_by_name_os_failed",
                points_count=len(points),
                reason=cls._classify_failure(e),
                error=str(e), error_type=type(e).__name__,
                collection_name=collection_name,
            )
            return False

    @classmethod
    def _build_filter(cls, filters: dict[str, Any] | None) -> models.Filter | None:
        """构建 Qdrant 查询过滤条件。

        通用规则：值为 list → MatchAny（任一匹配）；标量 → MatchValue 等值。
        """
        filter_conditions = []
        if filters:
            for key, value in filters.items():
                if isinstance(value, (list, tuple, set)):
                    values = [v for v in value if v is not None]
                    if not values:
                        continue
                    filter_conditions.append(
                        models.FieldCondition(
                            key=key,
                            match=models.MatchAny(any=list(values)),
                        )
                    )
                elif value is not None:
                    filter_conditions.append(
                        models.FieldCondition(
                            key=key,
                            match=models.MatchValue(value=value),
                        )
                    )
        if filter_conditions:
            return models.Filter(must=filter_conditions)
        return None

    @classmethod
    def search_by_name(
        cls,
        collection_name: str,
        query_vector: list[float],
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """按 collection 名称搜索（用于 overlay / 任意已知 collection）。

        与 search() 逻辑相同但直接接受 collection_name。
        collection 不存在时返回空列表。
        """
        client = cls.get_client()
        query_filter = cls._build_filter(filters)

        try:
            results = client.query_points(
                collection_name=collection_name,
                query=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )

            return [
                {
                    "id": str(r.id),
                    "score": r.score,
                    "payload": r.payload,
                }
                for r in results.points
            ]
        except UnexpectedResponse as e:
            logger.warning("search_by_name_failed", collection_name=collection_name, error=str(e))
            return []

    @classmethod
    def hybrid_search_by_name(
        cls,
        collection_name: str,
        query_dense: list[float],
        query_sparse: dict[str, Any],
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """按 collection 名称混合检索（dense + sparse RRF 融合）。

        与 hybrid_search() 逻辑相同但直接接受 collection_name。
        collection 不存在时返回空列表。
        """
        client = cls.get_client()
        query_filter = cls._build_filter(filters)

        try:
            sparse_vector = models.SparseVector(
                indices=query_sparse["indices"],
                values=query_sparse["values"],
            )

            results = client.query_points(
                collection_name=collection_name,
                prefetch=[
                    models.Prefetch(
                        query=query_dense,
                        using="dense",
                        limit=top_k,
                        filter=query_filter,
                    ),
                    models.Prefetch(
                        query=sparse_vector,
                        using="sparse",
                        limit=top_k,
                        filter=query_filter,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )

            return [
                {
                    "id": str(r.id),
                    "score": r.score,
                    "payload": r.payload,
                }
                for r in results.points
            ]
        except UnexpectedResponse as e:
            # 老 collection 缺 named "dense"/"sparse" 向量配置（早期单匿名向量
            # 索引格式遗留）→ Qdrant 返回 400 "Not existing vector name"。
            # 静默返回 [] 会让上游看到"0 结果"误判为索引为空，因此自动降级到
            # 纯 dense search 并响亮 warning，提示该 collection 需要重建。
            if cls._is_missing_named_vector_error(e):
                logger.warning(
                    "hybrid_search_by_name_fallback_to_dense",
                    collection_name=collection_name,
                    reason="collection_missing_named_vectors",
                    hint="rebuild index to enable hybrid search",
                )
                return cls.search_by_name(
                    collection_name, query_dense, top_k=top_k, filters=filters,
                )
            logger.warning(
                "hybrid_search_by_name_failed",
                collection_name=collection_name,
                error=str(e),
            )
            return []

    @staticmethod
    def _is_missing_named_vector_error(error: UnexpectedResponse) -> bool:
        """识别 Qdrant "Not existing vector name" 类错误。

        触发场景：collection 是旧的"单匿名 dense 向量"格式，但 hybrid_search
        以 ``using="dense"`` / ``using="sparse"`` 命名向量方式查询。错误文案
        来自 Qdrant 源码 (见 `qdrant/qdrant` 仓库 `lib/collection/src/operations/types.rs`)，
        形如 ``"Wrong input: Not existing vector name error: sparse"``。
        """
        msg = str(error)
        return "Not existing vector name" in msg

    @classmethod
    def dense_search_by_name(
        cls,
        collection_name: str,
        query_dense: list[float],
        *,
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """dense-only 命名向量查询（O-3 口径：返回分即 COSINE 相似度）。

        与 :meth:`hybrid_search_by_name` 同层对称，但只查 ``using="dense"``
        单路——``FusionQuery(RRF)`` 融合分不回传 per-prefetch 余弦，取余弦
        必须单独 dense 查询（写法同 ``measure_repo_index_stats._verify_cosine``
        探针）。repo_router_v2 用它复用已算好的 query_dense 归仓取
        ``dense_cos_max``（零额外 embedding）。

        失败语义：任何异常（collection 缺失 / 命名向量缺失 / 连接失败）一律
        返回空列表不抛——调用方按「dense 余弦不可用」降级（S_top 回退 RRF
        s_hat），路由绝不因该查询失败而中断。
        """
        try:
            client = cls.get_client()
            query_filter = cls._build_filter(filters)
            results = client.query_points(
                collection_name=collection_name,
                query=query_dense,
                using="dense",
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
            return [
                {
                    "id": str(r.id),
                    "score": r.score,
                    "payload": r.payload,
                }
                for r in results.points
            ]
        except Exception as e:  # noqa: BLE001 — 失败返回空列表，调用方降级
            # 异常文本可能带上游响应体（Qdrant UnexpectedResponse 会回显 body），
            # 手动过一遍脱敏；category/component 按 LOGGING-SPEC 必填项补齐。
            from common.logging import redact_secrets_in_text

            logger.warning(
                "dense_search_by_name_failed",
                collection_name=collection_name,
                error=redact_secrets_in_text(str(e)),
                error_type=type(e).__name__,
                category="sampling",
                component="qdrant",
            )
            return []

    @classmethod
    def hybrid_search(
        cls,
        repository_id: str,
        query_dense: list[float],
        query_sparse: dict[str, Any],
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """混合检索：利用 Qdrant prefetch 机制融合 dense + sparse 结果。

        Args:
            repository_id: Repository ID
            query_dense: Dense query vector
            query_sparse: Sparse query vector {"indices": [...], "values": [...]}
            top_k: Number of results to return
            filters: Optional filters

        Returns:
            List of search results with score and payload
        """
        client = cls.get_client()
        collection_name = cls.get_collection_name(repository_id)

        # Build filter
        filter_conditions = []
        if filters:
            if "language" in filters:
                filter_conditions.append(
                    models.FieldCondition(
                        key="language",
                        match=models.MatchValue(value=filters["language"]),
                    )
                )

        query_filter = None
        if filter_conditions:
            query_filter = models.Filter(must=filter_conditions)

        try:
            sparse_vector = models.SparseVector(
                indices=query_sparse["indices"],
                values=query_sparse["values"],
            )

            results = client.query_points(
                collection_name=collection_name,
                prefetch=[
                    models.Prefetch(
                        query=query_dense,
                        using="dense",
                        limit=top_k,
                        filter=query_filter,
                    ),
                    models.Prefetch(
                        query=sparse_vector,
                        using="sparse",
                        limit=top_k,
                        filter=query_filter,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )

            return [
                {
                    "id": str(r.id),
                    "score": r.score,
                    "payload": r.payload,
                }
                for r in results.points
            ]
        except UnexpectedResponse as e:
            if cls._is_missing_named_vector_error(e):
                logger.warning(
                    "hybrid_search_fallback_to_dense",
                    repository_id=repository_id,
                    collection_name=collection_name,
                    reason="collection_missing_named_vectors",
                    hint="rebuild index to enable hybrid search",
                )
                return cls.search(
                    repository_id, query_dense, top_k=top_k, filters=filters,
                )
            logger.error("hybrid_search_failed", error=str(e))
            return []

    @classmethod
    async def batch_set_payload(
        cls,
        repository_id: str,
        updates: list[tuple[str, dict[str, Any]]],
        *,
        batch_size: int = 500,
        timeout: float = 30.0,
    ) -> None:
        """批量为 Qdrant points 设置 payload（per implementation contract / contract）。

        Pitfall 2 防御核心 API：禁止循环单 set_payload；唯一写入路径是
        client.batch_update_points + SetPayloadOperation。

        Args:
            repository_id: 推导 collection_name（QdrantService.get_collection_name）
            updates: list of (point_id, payload_dict)。SetPayloadOperation 仅 set
                自身 key，既有 payload 其他字段保留（不是 overwrite 语义）
            batch_size: 单次 batch_update_points 提交的 SetPayloadOperation 数量上限
            timeout: 单次 batch wall-clock 上限（秒）；asyncio.wait_for 超时 catch
                + structlog error 不重抛（与 upsert_vectors 同语义，让 indexer 主路
                径继续）

        异常对称 upsert_vectors：UnexpectedResponse / ResponseHandlingException /
        httpx.HTTPError / OSError / TimeoutError 全 catch 并 structlog error 不重抛。
        """
        if not updates:
            return

        collection_name = cls.get_collection_name(repository_id)
        total = len(updates)
        batches = [updates[i : i + batch_size] for i in range(0, total, batch_size)]

        for batch_idx, batch in enumerate(batches):
            ops = [
                models.SetPayloadOperation(
                    set_payload=models.SetPayload(
                        payload=payload,
                        points=[point_id],
                    ),
                )
                for point_id, payload in batch
            ]

            def _do_batch(client: QdrantClient, _ops: list[Any] = ops) -> None:
                client.batch_update_points(
                    collection_name=collection_name,
                    update_operations=_ops,
                    wait=False,
                )

            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        cls._call_with_bad_fd_retry, "batch_set_payload", _do_batch
                    ),
                    timeout=timeout,
                )
            except TimeoutError:
                logger.error(
                    "batch_set_payload_timeout",
                    collection_name=collection_name,
                    batch_index=batch_idx,
                    batch_size=len(batch),
                    timeout_seconds=timeout,
                )
            except UnexpectedResponse as e:
                logger.error(
                    "batch_set_payload_failed",
                    collection_name=collection_name,
                    batch_index=batch_idx,
                    batch_size=len(batch),
                    reason=cls._classify_failure(e),
                    error=str(e),
                )
            except ResponseHandlingException as e:
                logger.error(
                    "batch_set_payload_response_handling_failed",
                    collection_name=collection_name,
                    batch_index=batch_idx,
                    reason=cls._classify_failure(e),
                    error=str(e),
                )
            except httpx.HTTPError as e:
                logger.error(
                    "batch_set_payload_network_failed",
                    collection_name=collection_name,
                    batch_index=batch_idx,
                    reason=cls._classify_failure(e),
                    error=str(e),
                )
            except OSError as e:
                logger.error(
                    "batch_set_payload_os_failed",
                    collection_name=collection_name,
                    batch_index=batch_idx,
                    reason=cls._classify_failure(e),
                    error=str(e),
                )

        logger.info(
            "batch_set_payload_complete",
            collection_name=collection_name,
            total_updates=total,
            batches=len(batches),
        )
