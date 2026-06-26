"""INV-6 守护（83-02）：``DocSyncService`` 不旁路写表。

``doc_sync_service.py`` 是同步编排层，**绝不**直接写 ``ProjectDoc`` / ``ProjectDocBlockMap`` /
``ProjectDocBlockRevision`` / ``ProjectMemory`` / ``ProjectMemoryRevision``——结构化写一律经
``ProjectDocService``、记忆写一律经 ``MemoryService``。本测试纯源码扫描（无 DB / 网络），命中
旁路写表入口即 fail。``test_project_doc_inv6_guard``（全仓扫描）从全局守 ProjectDoc 三模型；
本测试再就近守 doc_sync_service.py 同时不旁路 MEMORY 两模型，并正向断言写确实经 service。
"""

from __future__ import annotations

import re
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2]
_MODULE = SERVER_DIR / "initiatives" / "services" / "doc_sync_service.py"

# 同步编排禁止旁路直写的模型（结构化经 ProjectDocService，记忆经 MemoryService）。
_FORBIDDEN_MODELS = (
    "ProjectDoc",
    "ProjectDocBlockMap",
    "ProjectDocBlockRevision",
    "ProjectMemory",
    "ProjectMemoryRevision",
)
_RE_ORM_WRITE = {
    m: re.compile(
        rf"\b{m}\.objects\.(?:create|bulk_create|get_or_create|update_or_create|update|delete)\b"
    )
    for m in _FORBIDDEN_MODELS
}
# 直接实例化 Model(...)（紧跟 "(" 排除更长符号误伤，如 ProjectDocBlockMap( 命 ProjectDoc）。
_RE_INSTANTIATE = {m: re.compile(rf"\b{m}\s*\(") for m in _FORBIDDEN_MODELS}


def test_doc_sync_service_exists() -> None:
    assert _MODULE.exists(), "doc_sync_service.py 不存在"


def test_doc_sync_service_no_bypass_writes() -> None:
    """DocSyncService 源码无旁路写表/实例化（写收口于 ProjectDocService / MemoryService）。"""
    violations: list[str] = []
    for lineno, line in enumerate(_MODULE.read_text(encoding="utf-8").splitlines(), 1):
        for m in _FORBIDDEN_MODELS:
            # ProjectDoc 命中时跳过 ProjectDocBlockMap/Revision 实例化误报。
            if m == "ProjectDoc" and (
                _RE_INSTANTIATE["ProjectDocBlockMap"].search(line)
                or _RE_INSTANTIATE["ProjectDocBlockRevision"].search(line)
            ):
                continue
            if m == "ProjectMemory" and _RE_INSTANTIATE["ProjectMemoryRevision"].search(line):
                continue
            if _RE_ORM_WRITE[m].search(line) or _RE_INSTANTIATE[m].search(line):
                violations.append(f"{lineno}: {line.strip()}")
                break

    assert not violations, (
        "INV-6 违反：DocSyncService 旁路写表（结构化写须经 ProjectDocService，"
        "记忆写须经 MemoryService）：\n" + "\n".join(violations)
    )


def test_doc_sync_service_writes_through_services() -> None:
    """正向守护：写确实经写入收口 service（防守护形同虚设）。"""
    text = _MODULE.read_text(encoding="utf-8")
    assert "ProjectDocService" in text, "结构化写应经 ProjectDocService"
    assert "MemoryService" in text, "MEMORY 写应经 MemoryService"
    # 飞书正文/异常文本入日志前脱敏（T-83-02-INFO）。
    assert "redact_secrets_in_text" in text, "飞书正文/异常入日志前须脱敏"


def test_doc_sync_service_logs_no_token_plaintext() -> None:
    """日志只记 doc_id/doc_type/op/计数/reason，绝不落 token / 文档正文明文。

    扫描每个 ``logger.*(...)`` 调用体（含跨行），禁止其字段携带正文 / token 明文
    （``content=`` / ``markdown=`` / ``feishu_doc_token=`` 等）。注意：``content=d.content``
    出现在 ``capture_block_revision``（写入收口 service 调用）属合法 DB 留痕，不在 logger 调用内。
    """
    text = _MODULE.read_text(encoding="utf-8")
    forbidden = re.compile(
        r"logger\.(?:info|warning|debug)\((?:[^()]|\([^()]*\))*"
        r"(?:feishu_doc_token=|doc_token=|markdown=|content=|snapshot=)",
        re.DOTALL,
    )
    assert not forbidden.search(text), "日志不得落飞书 token / 文档正文明文"
