"""Deterministic planning service seam for MCP planning tools.

The functions in this module are intentionally pure: they take repository
metadata, indexed paths, and caller-provided chunks, then return structured
artifacts plus model-usage metadata. A real provider-backed implementation can
replace this seam without changing views, persistence, or tests.
"""

from __future__ import annotations

import re
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


def _files_from_requirement(requirement: str, file_paths: list[str], chunks: list[dict[str, Any]]) -> list[str]:
    mentioned = {str(chunk.get("file_path") or "") for chunk in chunks if chunk.get("file_path")}
    words = {
        word.lower()
        for word in re.findall(r"[A-Za-z0-9_./-]{3,}", requirement)
        if not word.startswith("http")
    }
    for path in file_paths:
        lowered = path.lower()
        if any(word in lowered for word in words):
            mentioned.add(path)
    if not mentioned:
        mentioned.update(file_paths[:5])
    return sorted(path for path in mentioned if path)[:12]


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


def build_coding_plan(
    *,
    repository: Repository,
    branch: str,
    requirement: str,
    analysis_summary: dict[str, Any] | None,
    file_paths: list[str],
    context_chunks: list[dict[str, Any]],
    max_steps: int,
) -> PlanningResult:
    """[DEPRECATED — UNIFY-04] 旧确定性单仓 coding plan seam。

    ``create_coding_plan`` 入口已收口到 ``process_runtime`` 统一编排（经
    ``mcp_tools.orchestration_delegate.delegate_process_runtime`` 产 canonical §7
    MergedPlan，再经 ``orchestration_delegate`` 的 canonical→旧字段映射 helper 回旧响应字段）。本函数**保留不删**
    （渲染/兼容 helper、被既有测试引用），但不再作 MCP create_coding_plan 的方案生成路径
    （对齐「seam 被取代但函数保留」）。
    """
    started_at = time.perf_counter()
    chunks = normalize_context_chunks(context_chunks)
    affected_files = _files_from_requirement(requirement, file_paths, chunks)
    title = requirement.strip().splitlines()[0][:120] or f"{repository.name} coding plan"
    test_files = _test_paths(file_paths)
    steps = [
        {
            "order": 1,
            "title": "确认入口与证据",
            "detail": "复核相关文件、GraphRAG chunk 和现有测试边界。",
            "files": affected_files[:3],
        },
        {
            "order": 2,
            "title": "实现最小垂直改动",
            "detail": "按影响文件逐步修改，避免跨模块无关重构。",
            "files": affected_files,
        },
        {
            "order": 3,
            "title": "补齐验证",
            "detail": "添加或更新定向测试，覆盖 request/response、错误码和 trace。",
            "files": test_files[:5],
        },
    ][:max_steps]
    plan = {
        "title": title,
        "repository_id": str(repository.id),
        "repository_name": repository.name,
        "branch": branch,
        "requirement": requirement,
        "problem_statement": requirement,
        "architecture_context": (analysis_summary or {}).get("architecture_summary", ""),
        "affected_files": affected_files,
        "steps": steps,
        "test_plan": test_files[:5]
        or [
            "运行受影响 app 的定向 pytest。",
            "运行 mypy 覆盖新增模块。",
            "运行 schema snapshot 防止 MCP contract 漂移。",
        ],
        "risks": [
            "需求描述可能未覆盖所有调用路径，需要通过检索证据补强。",
            "自动生成方案需在执行前再次确认文件级影响面。",
        ],
        "estimated_change": {
            "size": "medium" if len(affected_files) > 4 else "small",
            "files": len(affected_files),
            "steps": len(steps),
        },
    }
    evidence = [
        {"kind": "file", "file_path": path, "reason": "方案影响文件候选"}
        for path in affected_files
    ]
    evidence.extend(chunks)
    return PlanningResult(
        payload=plan,
        evidence=evidence,
        model_usage=_usage(
            started_at,
            prompt={
                "repo": repository.name,
                "requirement": requirement,
                "analysis": analysis_summary,
                "chunks": chunks,
            },
            completion=plan,
        ),
    )


def improve_coding_plan(
    *,
    repository: Repository,
    branch: str,
    existing_plan: dict[str, Any],
    feedback: str,
    context_chunks: list[dict[str, Any]],
    max_steps: int,
) -> PlanningResult:
    started_at = time.perf_counter()
    chunks = normalize_context_chunks(context_chunks)
    updated = dict(existing_plan)
    previous_steps = list(updated.get("steps") or [])
    next_order = len(previous_steps) + 1
    previous_steps.append(
        {
            "order": next_order,
            "title": "按反馈调整方案",
            "detail": feedback,
            "files": [chunk["file_path"] for chunk in chunks if chunk.get("file_path")][:5],
        }
    )
    updated["steps"] = previous_steps[:max_steps]
    updated["branch"] = branch
    updated["improvement_feedback"] = feedback
    updated["risks"] = list(updated.get("risks") or []) + [
        "方案已按反馈变更，执行前需要对比新旧版本影响面。"
    ]
    risk_delta = {
        "added": ["版本变更后需复核新增步骤的影响范围"],
        "reduced": ["反馈已转化为显式执行步骤"],
    }
    updated["risk_delta"] = risk_delta
    change_summary = f"根据反馈更新方案：{feedback[:240]}"
    evidence = [
        {"kind": "chunk", **chunk, "reason": "改进反馈上下文"}
        for chunk in chunks
    ]
    if not evidence:
        evidence.append(
            {
                "kind": "file",
                "file_path": "",
                "reason": "无额外上下文，基于上一版方案和反馈生成",
            }
        )
    return PlanningResult(
        payload={
            "plan": updated,
            "change_summary": change_summary,
            "risk_delta": risk_delta,
        },
        evidence=evidence,
        model_usage=_usage(
            started_at,
            prompt={
                "repo": repository.name,
                "feedback": feedback,
                "existing_plan": existing_plan,
                "chunks": chunks,
            },
            completion=updated,
        ),
    )
