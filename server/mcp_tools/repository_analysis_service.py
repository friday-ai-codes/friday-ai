"""确定性证据采集器（UNIFY-02 随迁模块）。

`build_repository_analysis` 基于仓库元数据、已索引文件路径与调用方提供的 context chunks，
**确定性**采集编排输入证据（模块分组 / 入口点 / 测试路径 / 阅读顺序），非 LLM 生成。
产物经 `analyze_repository` 落 `McpRepositoryAnalysis`，供 Create/Improve coding plan
作为 `extra_evidence` 注入统一编排（`delegate_process_runtime`）消费。

自旧确定性 planning seam 模块随迁（该 seam 已随 create/improve 收敛统一编排而退役删除）；
本模块保留纯函数形态：入参 → 结构化产物 + 模型用量元数据。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from repositories.models import Repository

PROMPT_VERSION = "mcp-planning-v1"
SYSTEM_PROMPT_VERSION = "mcp-planning-system-v1"
LOCAL_PROVIDER = "friday"
LOCAL_MODEL = "deterministic-planning-seam"


@dataclass(frozen=True)
class PlanningResult:
    payload: dict[str, Any]
    evidence: list[dict[str, Any]]
    model_usage: dict[str, Any]


def _token_estimate(*parts: object) -> int:
    text = "\n".join(str(part) for part in parts if part)
    return max(len(text) // 4, 1)


def _usage(started_at: float, *, prompt: object, completion: object) -> dict[str, Any]:
    prompt_tokens = _token_estimate(prompt)
    completion_tokens = _token_estimate(completion)
    return {
        "provider": LOCAL_PROVIDER,
        "model": LOCAL_MODEL,
        "prompt_version": PROMPT_VERSION,
        "system_prompt_version": SYSTEM_PROMPT_VERSION,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "duration_ms": max(int((time.perf_counter() - started_at) * 1000), 0),
    }


def normalize_context_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(chunks[:20]):
        file_path = str(raw.get("file_path") or "").strip()
        content = str(raw.get("content") or "").strip()
        if not file_path and not content:
            continue
        normalized.append(
            {
                "kind": "chunk",
                "chunk_id": str(raw.get("chunk_id") or ""),
                "file_path": file_path,
                "line_start": raw.get("line_start"),
                "line_end": raw.get("line_end"),
                "score": float(raw.get("score") or 0.0),
                "content_preview": content[:500],
                "index": index,
            }
        )
    return normalized


def _module_groups(file_paths: list[str]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = {}
    for path in file_paths:
        module = path.split("/", 1)[0] if "/" in path else "root"
        groups.setdefault(module, []).append(path)
    ranked = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    return [
        {
            "module": module,
            "file_count": len(paths),
            "representative_files": paths[:5],
            "reason": f"{module} 覆盖 {len(paths)} 个已索引文件",
        }
        for module, paths in ranked[:8]
    ]


def _entry_points(file_paths: list[str]) -> list[dict[str, Any]]:
    patterns = (
        "manage.py",
        "main.py",
        "app.py",
        "server.py",
        "wsgi.py",
        "asgi.py",
        "package.json",
        "pyproject.toml",
        "Cargo.toml",
        "go.mod",
    )
    entries: list[dict[str, Any]] = []
    for path in file_paths:
        name = path.rsplit("/", 1)[-1]
        if name in patterns or path.endswith("/routes.py") or path.endswith("/urls.py"):
            entries.append(
                {
                    "file_path": path,
                    "reason": "可能是运行、路由或依赖入口",
                }
            )
    if not entries and file_paths:
        entries.append({"file_path": file_paths[0], "reason": "索引顺序中的首个文件"})
    return entries[:10]


def _test_paths(file_paths: list[str]) -> list[str]:
    return [
        path
        for path in file_paths
        if "test" in path.lower() or path.endswith(".spec.ts") or path.endswith(".test.ts")
    ][:10]


def build_repository_analysis(
    *,
    repository: Repository,
    branch: str,
    focus: str,
    file_paths: list[str],
    context_chunks: list[dict[str, Any]],
) -> PlanningResult:
    started_at = time.perf_counter()
    chunks = normalize_context_chunks(context_chunks)
    modules = _module_groups(file_paths)
    entries = _entry_points(file_paths)
    tests = _test_paths(file_paths)
    reading_order = [
        {"order": index + 1, "file_path": item["file_path"], "reason": item["reason"]}
        for index, item in enumerate(entries)
    ]
    for module in modules[:5]:
        representative = module["representative_files"][0] if module["representative_files"] else ""
        if representative and all(item["file_path"] != representative for item in reading_order):
            reading_order.append(
                {
                    "order": len(reading_order) + 1,
                    "file_path": representative,
                    "reason": f"代表模块 {module['module']}",
                }
            )

    summary = {
        "repository": {
            "repo_id": str(repository.id),
            "name": repository.name,
            "description": repository.overview_text,
            "default_branch": repository.default_branch,
            "branch": branch,
            "index_status": repository.index_status,
        },
        "architecture_summary": (
            f"{repository.name} 当前索引了 {len(file_paths)} 个文件，"
            f"主要模块为 {', '.join(module['module'] for module in modules[:4]) or '未识别'}。"
        ),
        "focus": focus,
        "key_modules": modules,
        "entry_points": entries,
        "risks": [
            "上下文 chunk 不足时，执行前需要补充 GraphRAG 检索证据。",
            "跨入口文件改动应先确认分支索引与默认分支一致。",
        ],
        "test_strategy": {
            "existing_test_files": tests,
            "recommended": tests
            or [
                "补充最小单元测试覆盖受影响服务。",
                "对 MCP 工具调用补 request/response/ledger 回放测试。",
            ],
        },
        "reading_order": reading_order,
    }
    evidence = [
        {
            "kind": "file",
            "file_path": path,
            "reason": "已索引文件样本",
        }
        for path in file_paths[:20]
    ]
    evidence.extend(chunks)
    return PlanningResult(
        payload=summary,
        evidence=evidence,
        model_usage=_usage(
            started_at,
            prompt={"repo": repository.name, "focus": focus, "files": file_paths, "chunks": chunks},
            completion=summary,
        ),
    )
