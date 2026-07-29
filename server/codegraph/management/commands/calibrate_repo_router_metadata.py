"""O-2 校准：需求文本 × facet 值余弦分布 → c_lo/c_hi 建议 + 逐 facet T2 弃用判定。

Phase 106-04（ROUTE-04）。校准流程按 ROUTING-RANKING §3.2（必做，一次性）：

1. 随机抽 N 组「随机需求文本 × 随机 facet 值」（负样本，默认 200），
   算余弦，取 **p95** 作为 ``c_lo`` 建议；
2. 人工确认匹配的「需求 × facet 值」正样本（``--positives-file``），
   取 **p50** 作为 ``c_hi`` 建议；
3. ``c_hi - c_lo < 0.10`` → 该 embedding 模型无法区分这个 facet，
   **放弃该 facet 的 T2 通道**（建议加入 ``t2_disabled_facets``），只保留 T1。

独立于 ``measure_repo_index_stats``（后者是 O-1/O-3/O-5 的 Qdrant/DB 统计，
职责不同——RESEARCH §6 裁决）。

数据来源
========

- facet 闭集值：语义分面查 ``FacetVocabulary.objects.filter(is_active=True)``，
  技术栈用 ``facet_service._EXT_LANGUAGE_MAP`` 枚举；「未分类」跳过（Pitfall 2）。
- 需求文本（负样本 query 源）：``WorkItem.title``（飞书镜像的真实需求标题）。
- 开发库缺数据 / EmbeddingService 未配置时：``--structural`` 用内置合成
  query/值对 + seed 确定性伪向量跑通全管线（管线正确性与真实分布解耦，
  生产校准数字按 CONTEXT 纪律 deferred）。

CLI 用例
========

::

    # 生产实测（需 EmbeddingService 已配置；正样本须人工先确认 30 组）
    python manage.py calibrate_repo_router_metadata --positives-file /tmp/positives.json

    # 开发库定管线（零网络）
    python manage.py calibrate_repo_router_metadata --structural --format json

``--positives-file`` 为 JSON 数组 ``[{"query": ..., "facet_value": ..., ["facet": ...]}]``
（运维提供的外部文件不可信，命令做严格结构校验——威胁边界见 106-04 threat model）。

结果回填 106-MEASUREMENTS.md O-2 节（数据环境标注纪律）；建议值经
``PUT /api/settings/repo-router/weight-config/`` 写入 ``constants.t2_c_lo`` /
``constants.t2_c_hi`` 与 ``t2_disabled_facets``。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import random
import time
from pathlib import Path
from typing import Any

import structlog
from django.core.management.base import BaseCommand, CommandError

# repo_router_metadata 顶层零 Django import，此处顶层引用安全；
# facet 键名与 DoS 护栏复用 resolver 常量（106-03），契约由代码保证。
from codegraph.services.repo_router_metadata import (
    FACET_STACK,
    MAX_FACET_VALUE_LENGTH,
    UNCLASSIFIED_VALUE,
    normalize_t2_disabled_facets,
)

logger = structlog.get_logger(__name__)

_EVENT_STARTED = "calibrate_repo_router_metadata_started"
_EVENT_COMPLETED = "calibrate_repo_router_metadata_completed"
_EVENT_FAILED = "calibrate_repo_router_metadata_failed"

# management command 由运维手动触发，无请求上下文——按 LOGGING-SPEC
# initiated_by_user_id 标 system。样本 query 文本不入日志（T-106-10），只记计数。
_LOG_KV = {
    "category": "caller",
    "component": "codegraph",
    "initiated_by_user_id": "system",
}

# T2 区分度阈值：c_hi - c_lo < 0.10 → 放弃该 facet 的 T2 通道（§3.2 步骤 3）。
DISCRIMINATION_THRESHOLD = 0.10

# 负样本 query 源最少条数——低于此值说明开发库缺数据，提示 --structural。
_MIN_QUERY_TEXTS = 5

# 判定文案（markdown/json 共用；测试锁定字面）。
_VERDICT_KEEP = "保留 T2"
_VERDICT_DISABLE = "建议加入 t2_disabled_facets（区分度不足）"
_VERDICT_DEFERRED = "需人工正样本，deferred"

# ---------------------------------------------------------------------------
# 结构性样本模式（--structural）：内置合成 query/值对 + seed 确定性伪向量。
# 只用于开发库定管线——数值无分布意义，绝不回填 MEASUREMENTS 占位表。
# ---------------------------------------------------------------------------

_STRUCTURAL_DIM = 32

_STRUCTURAL_QUERIES = (
    "给作业批改流程增加错题自动归因",
    "老师端课堂报表导出超时需要优化",
    "登录页在企业微信内嵌 webview 白屏",
    "新增仓库路由的权重配置管理界面",
    "修复移动端H5支付回调丢单问题",
    "Python 服务升级 Django 版本后定时任务不触发",
    "Go 网关限流规则支持按团队维度配置",
    "前端 Vue 组件库暗色主题适配",
)

# 语义分面在开发库通常无 FacetVocabulary 行——structural 模式用内置值补齐闭集。
_STRUCTURAL_FACET_VALUES: dict[str, tuple[str, ...]] = {
    "业务线/产品线": ("在线教育", "智能批改", "运营平台"),
    "服务对象": ("C端学生", "B端学校", "内部运营"),
    "技术形态": ("移动端H5", "后端服务", "管理后台"),
}


def _structural_vector(text: str) -> list[float]:
    """seed 确定性伪向量：sha256(text) 播种 → 归一化随机向量（零网络）。"""
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    raw = [rng.uniform(-1.0, 1.0) for _ in range(_STRUCTURAL_DIM)]
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [v / norm for v in raw]


def _cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度（stdlib 显式循环，禁第三方数值库）。"""
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def _quantile(sorted_vals: list[float], q: float) -> float:
    """线性插值分位数（与 repo_router_eval._quantile 同口径；stdlib）。

    ``sorted_vals`` 必须已升序且非空。
    """
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _distribution(cosines: list[float]) -> dict[str, Any]:
    """余弦分布统计（min/p50/p95/max + count）。"""
    ordered = sorted(cosines)
    return {
        "count": len(ordered),
        "min": round(ordered[0], 4),
        "p50": round(_quantile(ordered, 0.50), 4),
        "p95": round(_quantile(ordered, 0.95), 4),
        "max": round(ordered[-1], 4),
    }


def _render_markdown(report: dict[str, Any]) -> str:
    """人读输出：逐 facet 分布/建议/判定表 + 回填指引。"""
    lines = [
        "## O-2 校准：需求文本 × facet 值余弦分布",
        "",
        f"- 模式: {report['mode']}"
        + ("（合成样本，仅验证管线，数值无分布意义）" if report["mode"] == "structural" else ""),
        f"- embedding_model_id: {report['embedding_model_id']}",
        f"- 需求文本样本数: {report['queries_available']}；每 facet 负样本数: {report['negatives_per_facet']}",
        "",
        "| facet | 闭集值数 | 负样本 min/p50/p95/max | c_lo 建议（负 p95） "
        "| c_hi 建议（正 p50） | 判定 | 应写入 t2_disabled_facets |",
        "|-------|---------|------------------------|--------------------"
        "|--------------------|------|---------------------------|",
    ]
    for row in report["facets"]:
        if row.get("skipped_reason"):
            lines.append(
                f"| {row['facet']} | {row['value_count']} | — | — | — "
                f"| 跳过：{row['skipped_reason']} | — |"
            )
            continue
        neg = row["negatives"]
        neg_cell = f"{neg['min']}/{neg['p50']}/{neg['p95']}/{neg['max']}"
        c_hi_cell = (
            str(row["c_hi_suggested"]) if row["c_hi_suggested"] is not None else _VERDICT_DEFERRED
        )
        # 「应写入」列给英文 signal 名（t2_disabled_facets 的唯一取值空间，
        # MJ-02）——只给中文维度名会被运维原样填进配置而永不生效。
        disable_cell = row.get("t2_disable_signal") or "—"
        lines.append(
            f"| {row['facet']} | {row['value_count']} | {neg_cell} "
            f"| {row['c_lo_suggested']} | {c_hi_cell} | {row['verdict']} | {disable_cell} |"
        )
    if report.get("skipped_positives"):
        lines += ["", f"- 未归属 facet 的正样本条目（跳过）: {report['skipped_positives']} 条"]
    lines += [
        "",
        "**回填指引**：将建议值经 `PUT /api/settings/repo-router/weight-config/` 写入 "
        "`constants.t2_c_lo` / `constants.t2_c_hi` 与 `t2_disabled_facets`，并同步更新 "
        "`weight_set_version` 与 `embedding_model_id`——换 embedding 模型必须重校准（CONTEXT 锁定）。",
        "",
        "> `t2_disabled_facets` 只接受英文 signal 名（`domain` / `stack`）——按上表"
        "「应写入」列填写；中文维度名由后端归一，未知取值直接 400 拒绝。"
        "`team` 恒不走 T2 通道，无须写入。",
    ]
    if report.get("t2_disabled_facets_suggested"):
        lines += [
            "",
            "**本次判定应停用 T2 的 signal**："
            f"`{report['t2_disabled_facets_suggested']}`",
        ]
    return "\n".join(lines)


class Command(BaseCommand):
    help = (
        "O-2 校准：需求文本 × facet 值余弦分布 → c_lo/c_hi 建议与逐 facet T2 弃用判定"
        "（ROUTING-RANKING §3.2；开发库用 --structural 定管线）"
    )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--facet",
            action="append",
            dest="facets",
            metavar="DIM",
            help="只校准指定 facet 维度（可重复）；默认全部语义分面 + 技术栈",
        )
        parser.add_argument(
            "--negatives",
            type=int,
            default=200,
            help="每 facet 负样本对数（随机需求文本 × 随机 facet 值；上限参数化防 DoS，默认 200）",
        )
        parser.add_argument(
            "--positives-file",
            dest="positives_file",
            help='人工确认正样本 JSON 数组：[{"query": ..., "facet_value": ..., ["facet": ...]}]',
        )
        parser.add_argument(
            "--structural",
            action="store_true",
            dest="structural",
            help="结构性样本模式：内置合成 query/值对 + seed 确定性伪向量（零网络，开发库定管线）",
        )
        parser.add_argument(
            "--format",
            choices=("json", "markdown"),
            default="markdown",
            dest="output_format",
            help="输出格式（默认 markdown，机器可读用 json）",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        start = time.monotonic()
        structural = bool(options["structural"])
        negatives_n = max(1, int(options["negatives"]))
        logger.info(
            _EVENT_STARTED,
            mode="structural" if structural else "embedding",
            negatives_per_facet=negatives_n,
            facet_filter=options.get("facets"),
            **_LOG_KV,
        )
        try:
            report = self._calibrate(
                facet_filter=options.get("facets"),
                negatives_n=negatives_n,
                positives_file=options.get("positives_file"),
                structural=structural,
            )
        except Exception as exc:
            from common.logging import redact_secrets_in_text

            # 异常文本可能含 embedding API 地址/key 片段——手动脱敏兜底（T-106-10）。
            logger.error(
                _EVENT_FAILED,
                error=redact_secrets_in_text(str(exc)),
                duration_ms=int((time.monotonic() - start) * 1000),
                **_LOG_KV,
            )
            raise

        logger.info(
            _EVENT_COMPLETED,
            mode=report["mode"],
            facet_count=len(report["facets"]),
            duration_ms=int((time.monotonic() - start) * 1000),
            **_LOG_KV,
        )
        if options["output_format"] == "json":
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(_render_markdown(report))

    # ------------------------------------------------------------------
    # 校准主流程
    # ------------------------------------------------------------------

    def _calibrate(
        self,
        *,
        facet_filter: list[str] | None,
        negatives_n: int,
        positives_file: str | None,
        structural: bool,
    ) -> dict[str, Any]:
        values_by_facet = self._collect_facet_values(facet_filter, structural)
        if not any(values_by_facet.values()):
            raise CommandError(
                "所有请求的 facet 都无闭集值（开发库通常未配置 FacetVocabulary）——"
                "配置词表后重跑，或用 --structural 以合成样本定管线"
            )

        queries = self._collect_query_texts(structural)
        if len(queries) < _MIN_QUERY_TEXTS:
            raise CommandError(
                f"需求文本样本不足（WorkItem 标题仅 {len(queries)} 条，需 >= {_MIN_QUERY_TEXTS}）——"
                "开发库缺数据时用 --structural 以合成样本定管线"
            )

        positives, skipped_positives = ([], 0)
        if positives_file:
            positives, skipped_positives = self._load_positives(positives_file, values_by_facet)

        # 确定性采样：同库同参数可复现（负样本对在 embedding 前先定下来）。
        rng = random.Random(42)
        negative_pairs: dict[str, list[tuple[str, str]]] = {}
        for facet, values in values_by_facet.items():
            if not values:
                continue
            negative_pairs[facet] = [
                (rng.choice(queries), rng.choice(values)) for _ in range(negatives_n)
            ]

        unique_texts: set[str] = set()
        for pairs in negative_pairs.values():
            for query, value in pairs:
                unique_texts.add(query)
                unique_texts.add(value)
        for entry in positives:
            unique_texts.add(entry["query"])
            unique_texts.add(entry["facet_value"])

        vector_of, model_id = self._embed_unique_texts(sorted(unique_texts), structural)

        facet_rows: list[dict[str, Any]] = []
        for facet, values in values_by_facet.items():
            if not values:
                facet_rows.append(
                    {
                        "facet": facet,
                        "value_count": 0,
                        "negatives": None,
                        "c_lo_suggested": None,
                        "positives": None,
                        "c_hi_suggested": None,
                        "verdict": None,
                        "t2_disable_signal": None,
                        "skipped_reason": "无闭集值（FacetVocabulary 未配置该维度）",
                    }
                )
                continue

            neg_cosines = [
                _cosine(vector_of[query], vector_of[value])
                for query, value in negative_pairs[facet]
            ]
            neg_stats = _distribution(neg_cosines)
            c_lo = neg_stats["p95"]

            pos_entries = [e for e in positives if e["facet"] == facet]
            pos_stats: dict[str, Any] | None = None
            c_hi: float | None = None
            if pos_entries:
                pos_cosines = [
                    _cosine(vector_of[e["query"]], vector_of[e["facet_value"]]) for e in pos_entries
                ]
                pos_stats = _distribution(pos_cosines)
                c_hi = pos_stats["p50"]

            if c_hi is None:
                verdict = _VERDICT_DEFERRED
            elif c_hi - c_lo < DISCRIMINATION_THRESHOLD:
                verdict = _VERDICT_DISABLE
            else:
                verdict = _VERDICT_KEEP

            # 该维度对应的 t2_disabled_facets 取值（英文 signal 名）——只有能映射到
            # signal 的维度（domain/stack）才可停用 T2（MJ-02）。
            disable_signals, _ = normalize_t2_disabled_facets([facet])
            facet_rows.append(
                {
                    "facet": facet,
                    "value_count": len(values),
                    "negatives": neg_stats,
                    "c_lo_suggested": c_lo,
                    "positives": pos_stats,
                    "c_hi_suggested": c_hi,
                    "verdict": verdict,
                    "t2_disable_signal": disable_signals[0] if disable_signals else None,
                    "skipped_reason": None,
                }
            )

        return {
            "mode": "structural" if structural else "embedding",
            "embedding_model_id": model_id,
            "negatives_per_facet": negatives_n,
            "queries_available": len(queries),
            "discrimination_threshold": DISCRIMINATION_THRESHOLD,
            "facets": facet_rows,
            "skipped_positives": skipped_positives,
            # 机器可读的「应写入 t2_disabled_facets 的值」（英文 signal 名，MJ-02）：
            # 判定为区分度不足且该维度确实走 T2 通道的 signal。
            "t2_disabled_facets_suggested": sorted(
                {
                    row["t2_disable_signal"]
                    for row in facet_rows
                    if row["verdict"] == _VERDICT_DISABLE and row.get("t2_disable_signal")
                }
            ),
            "next_steps": (
                "将建议值经 PUT /api/settings/repo-router/weight-config/ 写入 "
                "constants.t2_c_lo/t2_c_hi 与 t2_disabled_facets（取值为英文 signal 名 "
                "domain/stack，见 t2_disabled_facets_suggested），并更新 "
                "weight_set_version 与 embedding_model_id（换模型必须重校准）"
            ),
        }

    # ------------------------------------------------------------------
    # 数据采集
    # ------------------------------------------------------------------

    def _collect_facet_values(
        self, facet_filter: list[str] | None, structural: bool
    ) -> dict[str, list[str]]:
        """facet 闭集值：语义分面查 FacetVocabulary、技术栈枚举 _EXT_LANGUAGE_MAP。

        「未分类」/空串/超长值一律剔除（Pitfall 2 + T-106-06 DoS 护栏）；
        structural 模式下语义分面无词表时用内置合成值补齐闭集。
        """
        from repositories.facet_service import _EXT_LANGUAGE_MAP
        from repositories.models import FacetVocabulary
        from repositories.summary_service import SEMANTIC_FACET_DIMENSIONS

        dims = list(facet_filter) if facet_filter else [*SEMANTIC_FACET_DIMENSIONS, FACET_STACK]

        vocab: dict[str, list[str]] = {}
        for row in FacetVocabulary.objects.filter(is_active=True):
            values = row.values if isinstance(row.values, list) else []
            vocab[row.dimension] = [v for v in values if isinstance(v, str)]

        result: dict[str, list[str]] = {}
        for dim in dims:
            if dim == FACET_STACK:
                candidates = sorted(set(_EXT_LANGUAGE_MAP.values()))
            else:
                candidates = vocab.get(dim, [])
                if not candidates and structural:
                    candidates = list(
                        _STRUCTURAL_FACET_VALUES.get(
                            dim, (f"{dim}示例值A", f"{dim}示例值B", f"{dim}示例值C")
                        )
                    )
            result[dim] = [
                value.strip()
                for value in candidates
                if isinstance(value, str)
                and value.strip()
                and value.strip() != UNCLASSIFIED_VALUE
                and len(value.strip()) <= MAX_FACET_VALUE_LENGTH
            ]
        return result

    def _collect_query_texts(self, structural: bool) -> list[str]:
        """负样本 query 源：structural 用内置合成需求文本，否则取 WorkItem 标题。"""
        if structural:
            return list(_STRUCTURAL_QUERIES)

        from delivery.models import WorkItem

        titles = (
            WorkItem.objects.exclude(title="")
            .order_by("-updated_at")
            .values_list("title", flat=True)[:500]
        )
        return [title.strip() for title in titles if title and title.strip()]

    def _load_positives(
        self, path: str, values_by_facet: dict[str, list[str]]
    ) -> tuple[list[dict[str, str]], int]:
        """加载并严格校验 --positives-file（外部文件不可信，威胁边界）。

        条目形状 ``{"query": 非空 str, "facet_value": 非空 str, ["facet": str]}``；
        无显式 facet 键时按闭集值反查归属维度，无法归属的条目跳过计数。
        """
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CommandError(f"--positives-file 读取/解析失败: {exc}") from exc
        if not isinstance(raw, list):
            raise CommandError(
                '--positives-file 必须是 JSON 数组：[{"query": ..., "facet_value": ...}]'
            )

        value_to_facet: dict[str, str] = {}
        for facet, values in values_by_facet.items():
            for value in values:
                value_to_facet.setdefault(value.casefold(), facet)

        entries: list[dict[str, str]] = []
        skipped = 0
        for index, item in enumerate(raw):
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("query"), str)
                or not item["query"].strip()
                or not isinstance(item.get("facet_value"), str)
                or not item["facet_value"].strip()
            ):
                raise CommandError(
                    f"--positives-file 第 {index} 项结构非法："
                    '需 {"query": 非空字符串, "facet_value": 非空字符串, ["facet": 维度名]}'
                )
            facet_value = item["facet_value"].strip()
            if len(facet_value) > MAX_FACET_VALUE_LENGTH:
                raise CommandError(
                    f"--positives-file 第 {index} 项 facet_value 超长"
                    f"（> {MAX_FACET_VALUE_LENGTH} 字符，DoS 护栏）"
                )
            explicit_facet = item.get("facet")
            if explicit_facet is not None and not isinstance(explicit_facet, str):
                raise CommandError(f"--positives-file 第 {index} 项 facet 必须为字符串")
            facet = explicit_facet or value_to_facet.get(facet_value.casefold())
            if not facet or facet not in values_by_facet:
                skipped += 1  # 无法归属到本次校准的 facet——跳过不猜
                continue
            entries.append(
                {"query": item["query"].strip(), "facet_value": facet_value, "facet": facet}
            )
        return entries, skipped

    # ------------------------------------------------------------------
    # 向量获取
    # ------------------------------------------------------------------

    def _embed_unique_texts(
        self, texts: list[str], structural: bool
    ) -> tuple[dict[str, list[float]], str]:
        """全部唯一文本 → 向量表。

        - structural：seed 确定性伪向量（零网络）；
        - 否则批量走 EmbeddingService（CallSource.EMBEDDING 作用域）；任一条
          失败即报错退出（失败即退不重试轰炸，T-106-11）并提示 --structural。
        """
        if structural:
            return {text: _structural_vector(text) for text in texts}, "structural(伪向量)"

        async def _embed() -> tuple[list[list[float] | None], str]:
            from agents.call_source import CallSource, use_call_source
            from services.embedding import EmbeddingService

            # LOGGING-SPEC §4.1：embedding 调用点必须处于 EMBEDDING call_source 作用域。
            with use_call_source(CallSource.EMBEDDING):
                vectors = await EmbeddingService.generate_embeddings_batch(texts)
            failed = sum(1 for v in vectors if not isinstance(v, list) or not v)
            if failed:
                raise CommandError(
                    f"EmbeddingService 未配置或调用失败（{failed}/{len(texts)} 条无向量）——"
                    "配置 embedding 供应商后重跑，或用 --structural 以合成样本定管线"
                )
            config = await EmbeddingService.get_config()
            return vectors, str(config.get("model", "BAAI/bge-m3"))

        vectors, model_id = asyncio.run(_embed())
        return dict(zip(texts, vectors)), model_id  # type: ignore[arg-type]
