"""`apply_qdrant_optimization` 管理命令 —— 对存量 Qdrant collection 套用省内存配置。

新建 collection 已默认 on_disk 原始向量 + int8 标量量化（见 ``QdrantService.create_collection``），
但历史 collection（一仓一 collection，数量可达数百）仍是全内存配置，是 14G 常驻内存与
mmap 压力的主因。本命令对存量 ``code_index_*`` collection 逐个 ``update_collection``：

- 原始向量改 ``on_disk=True``（mmap，不常驻内存）；
- 套用 int8 标量量化（``always_ram=True``，量化向量留内存做快速召回）。

灰度、可中断、幂等：逐个处理、失败跳过并记日志，重复执行只会重复套用同一配置。

    python manage.py apply_qdrant_optimization              # 全部 code_index_* collection
    python manage.py apply_qdrant_optimization --limit 20   # 仅处理前 20 个（灰度）
    python manage.py apply_qdrant_optimization --dry-run    # 只打印将处理的 collection
"""

from __future__ import annotations

import structlog
from django.core.management.base import BaseCommand, CommandParser
from qdrant_client.http import models

from services.qdrant_service import QdrantService, _scalar_quantization, _vectors_on_disk

logger = structlog.get_logger(__name__)

_COLLECTION_PREFIX = "code_index_"


class Command(BaseCommand):
    """对存量 code_index_* collection 套用 on_disk + int8 量化。"""

    help = "Apply on_disk vectors + int8 quantization to existing code_index_* collections"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=0, help="最多处理多少个（0=不限）")
        parser.add_argument("--dry-run", action="store_true", help="只打印不修改")

    def handle(self, *args: object, **options: object) -> None:
        limit = int(options.get("limit") or 0)
        dry_run = bool(options.get("dry_run"))

        client = QdrantClient_or_fail()
        collections = [
            c.name
            for c in client.get_collections().collections
            if c.name.startswith(_COLLECTION_PREFIX)
        ]
        if limit > 0:
            collections = collections[:limit]

        self.stdout.write(f"待处理 collection 数: {len(collections)}（dry_run={dry_run}）")

        quantization = _scalar_quantization()
        on_disk = _vectors_on_disk()

        ok = 0
        failed = 0
        for name in collections:
            if dry_run:
                self.stdout.write(f"  [dry-run] {name}")
                continue
            try:
                info = client.get_collection(name)
                vectors_config = info.config.params.vectors
                # 区分 named-vector（hybrid）与单向量，构造对应的 on_disk diff。
                if isinstance(vectors_config, dict):
                    vectors_diff: object = {
                        vec_name: models.VectorParamsDiff(on_disk=on_disk)
                        for vec_name in vectors_config
                    }
                else:
                    vectors_diff = models.VectorParamsDiff(on_disk=on_disk)

                client.update_collection(
                    collection_name=name,
                    vectors_config=vectors_diff,
                    quantization_config=quantization,
                )
                ok += 1
                logger.info("qdrant_optimization_applied", collection=name)
            except Exception as exc:  # noqa: BLE001 - 灰度容错：失败跳过继续
                failed += 1
                logger.warning("qdrant_optimization_failed", collection=name, error=str(exc))
                self.stderr.write(f"  FAILED {name}: {exc}")

        self.stdout.write(self.style.SUCCESS(f"完成: ok={ok} failed={failed}"))


def QdrantClient_or_fail():  # noqa: N802 - 内部小工具
    """拿到可用的 Qdrant client（复用 QdrantService 单例）。"""
    return QdrantService.get_client()
