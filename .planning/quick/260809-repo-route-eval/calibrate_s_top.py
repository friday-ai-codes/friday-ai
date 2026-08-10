"""补上 O-2 遗留的 S_top 余弦校准（只读测量，输出建议值）。

现状：`s_top_c_lo=0.25 / s_top_c_hi=0.55` 是从未校准的占位初值，而
`doubao-embedding-text` 的真实 dense_cos_max 落在 0.71~0.81 —— **全部**在 c_hi
之上，`_clip01((cos-c_lo)/(c_hi-c_lo))` 把每个仓都 clip 成 1.0，text 信号退化成
常数、零区分度。

校准口径：多条**不同主题**的查询各取一次全仓 dense_cos_max 分布，合并后取
分位数。单条查询定窗口会过拟合到那条查询的主题。
"""

from __future__ import annotations

import asyncio
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from route_eval import SPACE_ID, build_features_flat  # noqa: E402

PROBE_QUERIES = [
    "高中数学全部功能页里极速提分营入口的课程包权益鉴权",
    "真题检测页复用端内做题组件、提交后展示答案解析、中途返回弹阻断弹窗",
    "章导学视频与章总结视频的播放器接入、播放完成后解锁下一节点",
    "用户学习进度百分比计算与掌握程度的跨页面状态刷新",
    "课程章节小节结构、课程包与专项课的配置后台",
    "知识卡片大图缩略图切换与全屏双指缩放",
]


def quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


async def main() -> None:
    from asgiref.sync import sync_to_async

    from codegraph.services.repo_router_v2 import (
        COLLECTION_NAME,
        STAGE0_DENSE_K,
        RepoRouterV2,
        _stage0_node_k,
    )
    from codegraph.services.repo_router_config import aload_weight_config
    from initiatives.services.repo_association_service import RepoAssociationService
    from projects.models import Space
    from services.qdrant_service import QdrantService
    from services.query_embedding import embed_query
    from services.sparse_encoder import SparseEncoderService

    repo_ids = await sync_to_async(
        lambda: [str(r) for r in Space.objects.get(id=SPACE_ID).repositories.values_list("id", flat=True)]
    )()
    flat = await sync_to_async(build_features_flat)(include_test_case=True)
    cfg = await aload_weight_config()

    queries = [*PROBE_QUERIES, RepoAssociationService._build_query(flat)]
    all_cos: list[float] = []
    print(f"探测 {len(queries)} 条查询 × {len(repo_ids)} 仓  (dense top_k={STAGE0_DENSE_K})\n")
    for i, q in enumerate(queries, 1):
        emb = await embed_query(q, drop_noise=False)
        sp = await sync_to_async(SparseEncoderService.encode)(q)
        hits = await sync_to_async(QdrantService.hybrid_search_multi_by_name)(
            COLLECTION_NAME, emb.vectors, sp, top_k=_stage0_node_k(),
            prefetch_limit=_stage0_node_k(), filters={"repository_id": repo_ids},
        )
        meta, _ = await RepoRouterV2._load_repo_meta(
            hits, q, emb.primary, cfg, probe_vectors=emb.vectors
        )
        cos = sorted(m["dense_cos_max"] for m in meta.values() if m.get("dense_cos_max"))
        all_cos.extend(cos)
        label = (q[:30] + "…") if len(q) > 30 else q
        print(f"  {i}. {label:<34} {len(cos):>2} 仓  "
              f"min={cos[0]:.4f} 中位={quantile(cos, 0.5):.4f} max={cos[-1]:.4f}")

    all_cos.sort()
    print(f"\n合并样本 n={len(all_cos)}")
    for q in (0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0):
        print(f"  p{int(q * 100):<3} = {quantile(all_cos, q):.4f}")

    c_lo = round(quantile(all_cos, 0.05), 3)
    c_hi = round(quantile(all_cos, 0.95), 3)
    print(f"\n建议校准窗口：s_top_c_lo={c_lo}  s_top_c_hi={c_hi}")
    print(f"（当前值 0.25 / 0.55 —— 窗口整体在真实分布之下，故 100% 饱和）")
    cur = cfg["constants"]
    sat_now = sum(1 for c in all_cos if c >= cur["s_top_c_hi"]) / len(all_cos)
    sat_new = sum(1 for c in all_cos if c >= c_hi) / len(all_cos)
    print(f"饱和率（clip 到 1.0 的占比）：当前 {sat_now:.1%} → 校准后 {sat_new:.1%}")


if __name__ == "__main__":
    asyncio.run(main())
