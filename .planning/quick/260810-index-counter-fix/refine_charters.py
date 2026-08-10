"""用 mimo 细化四个目标仓的 owned_domains 到模块粒度 + 补 boundaries。

只读能力树/现有章程/干扰族清单 → mimo 单调用 → 预览（不落库）。
落库走 confirm 视图或单独 apply 步骤，便于人工先看。

用法:
    uv run python ../.planning/quick/260810-index-counter-fix/refine_charters.py
"""
from __future__ import annotations

import asyncio
import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

MIMO_CREDENTIAL_ID = "bcbdd68d-a7b8-4bdf-bb16-66a993588041"
MIMO_MODEL = "mimo-v2.5-pro"

import os as _os
_ONLY = _os.environ.get("REFINE_ONLY", "")
_ALL = {
    "onion-learning": "050e49b2-633a-44ad-96e8-9262546756db",
    "onion-practice": "cee27ee1-cc73-4937-9a9e-730edd6c93b2",
    "study-user-status": "a1bef5cc-b5e4-4869-8a5a-e1c4f5db4663",
    "study-course": "47991a7f-c8e4-4da6-b42c-2ce81d8b137f",
}
TARGETS = {k: v for k, v in _ALL.items() if not _ONLY or k in _ONLY}

# 学习/做题族干扰仓（名字/领域相近，需靠 boundaries 区分）。
SIBLINGS = [
    "study-app", "study-app-native", "study-flow", "study-practice", "study-stream",
    "study-plan", "study-task", "study-growth", "study-community", "study-statistics",
    "study-data-center", "studyspace-service", "primary_school_study", "go-learn",
    "devices-learn", "devices-study-room", "new-course-builder-client",
]

# 高三提分专项的模块粒度（细化目标参照）。
MODULE_GRAIN = [
    "全部功能页入口与权益展示", "单题型学习页与4节点解锁", "真题检测", "知识卡片",
    "视频讲解与答疑", "同型题检验", "完成页与学习结果反馈", "学习进度与掌握程度",
    "新手引导", "重难点培优四级目录",
]


def _flatten_tree(tree, depth=0, out=None):
    out = out if out is not None else []
    nodes = tree if isinstance(tree, list) else tree.get("nodes", [])
    for n in nodes:
        out.append("  " * depth + "- " + (n.get("title") or "") + "：" + (n.get("summary") or "")[:50])
        for c in (n.get("children") or []):
            _flatten_tree([c], depth + 1, out)
    return out


PROMPT_TMPL = """你是仓库职责章程专家。基于下面某仓库的事实信息，把它的「职责领域(owned_domains)」细化到**功能模块粒度**，并补全「职责边界(boundaries)」——用负面清单说清它**不做**什么、与名字相近仓的分界。

## 仓库
{name}（{form} / {audience}）

## 当前定位
{positioning}

## 当前职责领域（过粗，需细化）
{owned_domains}

## 能力树（事实，细化依据）
{tree}

## 需区分的同族仓（名字相近、易被误路由到此）
{siblings}

## 模块粒度参照（该仓涉及的才写，不涉及不要硬凑）
{modules}

## 输出要求（严格 JSON，无其它文字）
{{
  "owned_domains": [{{"domain": "<模块级领域名>", "status": "implemented", "note": "<具体能力点，8-40字>", "citations": []}}, ...],
  "boundaries": [{{"rule": "<本仓不承接的事/与他仓分界，祈使或陈述句>", "decided_by": "架构约定", "citations": []}}, ...]
}}

约束：
- owned_domains 6-12 条，domain 用模块级名词（如「单题型学习页」「真题检测」「重难点培优目录」），note 落到具体能力点；只写能力树里真实存在的。
- boundaries 3-8 条，rule 要可判定（包含能匹配到 query 的关键词），用来排除同族仓的误路由。例如「不提供 XX，XX 归 <他仓>」。
- 不要编造能力树里不存在的功能。"""


async def _mimo_chat(system: str, user: str) -> str:
    """直连 mimo anthropic 兼容端点（build_chat_model 与该网关 auth 方式不匹配，绕开）。

    与 Friday 凭证体系同源：从 ProviderCredential 解密 api_key/base_url，不落明文。
    """
    import httpx

    from asgiref.sync import sync_to_async
    from common.encryption import decrypt_value
    from system.models import ProviderCredential

    def _cred():
        c = ProviderCredential.objects.get(id=MIMO_CREDENTIAL_ID)
        cfg = json.loads(decrypt_value(c.encrypted_config))
        return cfg["api_key"], cfg["base_url"].rstrip("/")

    api_key, base = await sync_to_async(_cred, thread_sensitive=False)()
    async with httpx.AsyncClient(timeout=120) as cli:
        resp = await cli.post(
            f"{base}/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MIMO_MODEL,
                "max_tokens": 8000,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


async def refine_one(name: str, rid: str) -> dict | None:
    from asgiref.sync import sync_to_async

    from repositories.models import Repository

    repo = await Repository.objects.aget(id=rid)

    def _load():
        ch = repo.charter
        tree_lines = _flatten_tree(repo.ai_summary_tree) if repo.ai_summary_tree else []
        owned = json.dumps(
            [{"domain": d.get("domain"), "note": d.get("note")} for d in (ch.owned_domains or [])],
            ensure_ascii=False,
        )
        return ch, tree_lines, owned

    ch, tree_lines, owned = await sync_to_async(_load, thread_sensitive=False)()
    prompt = PROMPT_TMPL.format(
        name=name,
        form=ch.form or "",
        audience=ch.audience or "",
        positioning=ch.positioning or "",
        owned_domains=owned,
        tree="\n".join(tree_lines[:28]),
        siblings="、".join(SIBLINGS),
        modules="、".join(MODULE_GRAIN),
    )

    text = await _mimo_chat("你是仓库职责章程专家，只输出严格 JSON。", prompt)
    return _extract_json(text)


def _extract_json(text: str) -> dict | None:
    """容错提取 JSON：截断时尝试补齐尾部闭合括号。"""
    start = text.find("{")
    if start < 0:
        return None
    end = text.rfind("}")
    candidate = text[start : end + 1] if end > start else text[start:]
    for extra in ("", "]", "}]", "]}", "}]}", "]}}"):
        try:
            return json.loads(candidate + extra)
        except json.JSONDecodeError:
            continue
    # 逐层剥到最后一个完整对象再闭合
    for cut in range(len(candidate), max(start, len(candidate) - 400), -1):
        for extra in ("", "]}", "}]}"):
            try:
                return json.loads(candidate[:cut] + extra)
            except json.JSONDecodeError:
                continue
    return None


async def main() -> None:
    results = {}
    for name, rid in TARGETS.items():
        try:
            out = await refine_one(name, rid)
            results[name] = out
            od = (out or {}).get("owned_domains", [])
            bd = (out or {}).get("boundaries", [])
            print(f"===== {name} =====")
            print(f"  owned_domains {len(od)} 条 / boundaries {len(bd)} 条")
            for d in od:
                print(f"    [D] {d.get('domain')} | {d.get('note','')[:50]}")
            for b in bd:
                print(f"    [B] {b.get('rule','')[:70]}")
        except Exception as exc:  # noqa: BLE001
            print(f"===== {name} ERROR: {type(exc).__name__}: {exc}")
            results[name] = None
    with open("/tmp/charter_refine_preview.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n预览已写 /tmp/charter_refine_preview.json（未落库）")


asyncio.run(main())
