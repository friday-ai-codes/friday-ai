"""探针：限制到底在谁身上？LLM 摘要成一句话够不够？召回几次？（只读）

Q1 向量长度限制是 embedding 模型/网关的，还是 Qdrant 的 —— 抓上游原始报错定位。
Q2 让系统自己的 LLM（opus 4.8）把语料摘要成一句话再检索，效果如何。
Q3 各方案的召回次数（embedding + Qdrant 往返次数）与覆盖。
"""

from __future__ import annotations

import asyncio
import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from route_eval import GROUND_TRUTH, SPACE_ID, build_features_flat  # noqa: E402


# ---------------- Q1: 限制在谁身上 ----------------

async def probe_raw_embedding_error(corpus: str) -> None:
    """绕开 EmbeddingService 的 except 吞异常，直接打端点看原始状态码/报文。"""
    import httpx

    from services.embedding import EmbeddingService

    cfg = await EmbeddingService.get_config()
    api_url = cfg["api_url"]
    model = cfg["model"]
    api_key = cfg.get("api_key") or ""

    print("\n=== Q1. 长度限制定位：直接打 embedding 端点 ===")
    print(f"    model={model}  dim={cfg.get('dimension')}")
    async with httpx.AsyncClient(timeout=60) as client:
        for n in (6000, 6500, 7000, 8000, 12000):
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            body = EmbeddingService._build_request_body(api_url, model, corpus[:n])
            try:
                resp = await client.post(api_url, json=body, headers=headers)
                if resp.status_code == 200:
                    print(f"    {n:>6} 字符 -> 200 OK")
                else:
                    # 上游报文脱敏后截断（不回显任何凭证）
                    from common.logging import redact_secrets_in_text

                    print(f"    {n:>6} 字符 -> HTTP {resp.status_code}: "
                          f"{redact_secrets_in_text(resp.text)[:240]}")
            except Exception as exc:  # noqa: BLE001
                print(f"    {n:>6} 字符 -> {type(exc).__name__}: {str(exc)[:160]}")

    # Qdrant 侧：向量维度恒为 2560，与源文本长度无关 —— 用两条长度悬殊的文本证明
    print("\n    Qdrant 侧对照（它只见到定长向量，看不到原文长度）：")
    for n in (50, 6000):
        v = await EmbeddingService.generate_embedding(corpus[:n])
        print(f"      源文本 {n:>5} 字符 -> 送进 Qdrant 的向量维度 = {len(v) if v else 'None'}")


# ---------------- Q2: LLM 摘要一句话 ----------------

SUMMARIZE_PROMPT = (
    "你是需求路由助手。下面是一个需求的完整功能清单。"
    "请用**一句话**（不超过 80 字）概括这个需求要动的业务能力，"
    "用于向量检索匹配代码仓库。只输出这句话，不要任何前后缀。"
)


async def llm_one_sentence(corpus: str, *, n: int = 3) -> list[str]:
    """用系统里配置的模型（Stage 1 同款解析路径）生成 n 条一句话摘要。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.call_source import CallSource, use_call_source
    from agents.llm_factory import build_chat_model, content_to_text
    from services.provider_config import (
        ProviderConfigService,
        aget_claude_code_runtime_config,
    )

    resolved = await ProviderConfigService.aresolve_or_error()
    cc = await aget_claude_code_runtime_config()
    model_name = (cc.get("haiku_model") or "").strip() or (
        resolved.extra or {}).get("default_model", "")
    print(f"\n=== Q2. LLM 一句话摘要（model={model_name}）===")
    # 不传 decode 参数：该模型拒收 temperature（400），传了要先失败一次
    llm = build_chat_model(resolved, model_name, streaming=False,
                           timeout_seconds=120, max_retries=0)

    out: list[str] = []
    for i in range(n):
        with use_call_source(CallSource.AUX_REPO_ROUTER):
            resp = await llm.ainvoke([
                SystemMessage(content=SUMMARIZE_PROMPT),
                HumanMessage(content=corpus[:60000]),
            ])
        text = content_to_text(resp.content).strip().replace("\n", " ")
        out.append(text)
        print(f"    摘要 {i + 1} ({len(text)} 字): {text}")
    return out


# ---------------- Q3: 各方案召回次数与覆盖 ----------------

async def stage0(query: str, repo_ids: list[str]) -> dict[str, int]:
    from agents.call_source import CallSource, use_call_source
    from codegraph.services.repo_router_v2 import RepoRouterV2

    with use_call_source(CallSource.AUX_REPO_ROUTER):
        r = await RepoRouterV2.route(query, top_k=30, repository_ids=repo_ids, use_llm=False)
    return {
        GROUND_TRUTH[str(c.repo_id)]: i
        for i, c in enumerate(r.candidates, 1)
        if str(c.repo_id) in GROUND_TRUTH
    }


def report(label: str, ranks: dict[str, int], probes: int) -> None:
    print(f"\n--- {label} ---")
    print(f"    召回次数（embedding + Qdrant 往返）= {probes}")
    for name in sorted(GROUND_TRUTH.values()):
        print(f"    {name:<34} {('#%d' % ranks[name]) if name in ranks else '未进候选'}")
    print(f"    四仓全进候选: {len(ranks) == 4}")


async def main() -> None:
    from asgiref.sync import sync_to_async

    import initiatives.services.repo_association_service as ras
    from initiatives.services.repo_association_service import RepoAssociationService
    from projects.models import Space

    def _load():
        sp = Space.objects.get(id=SPACE_ID)
        return [str(r) for r in sp.repositories.values_list("id", flat=True)]

    repo_ids = await sync_to_async(_load)()
    flat = await sync_to_async(build_features_flat)(include_test_case=False)
    ras._QUERY_CHAR_BUDGET = 10**9
    corpus = RepoAssociationService._build_query(flat)

    await probe_raw_embedding_error(corpus)

    summaries = await llm_one_sentence(corpus, n=3)

    print("\n=== Q3. 各方案：召回次数 vs 四仓覆盖 ===")
    report("基线 A：单条 4000 字符截断 query", await stage0(corpus[:4000], repo_ids), 1)
    for i, s in enumerate(summaries, 1):
        report(f"方案 B{i}：LLM 一句话摘要", await stage0(s, repo_ids), 1)

    # 摘要合并成多探针：一次 LLM 调用产出 N 句，各自检索
    merged: dict[str, int] = {}
    for s in summaries:
        for name, rank in (await stage0(s, repo_ids)).items():
            merged[name] = min(merged.get(name, 999), rank)
    report("方案 C：3 条摘要各检索一次取并集", merged, len(summaries))

    print("\n（方案 D 逐 feature 45 探针的结果见 probe_query_strategy.py：四仓 #1/#5/#6/#7 全进）")


if __name__ == "__main__":
    asyncio.run(main())
