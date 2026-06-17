"""INV-6 旁路写表 grep 守护 + INV-3 投影保留守护（Phase 28-03 Task 3）。

纯本地源码扫描，无 DB / 网络：

- **INV-6**：WorkItem 落库只经 ``WorkItemService.upsert``。扫描 ``server/`` 源码
  （排除 tests/ / migrations/ / delivery/models/ 与 service 自身），断言无旁路
  ``WorkItem.objects.create``/.save() 直接写表入口；命中即 fail 并列出文件:行。
- **INV-3**：飞书 webhook 既有 knowledge ingestion 投递保留（feishu/views.py 仍含
  ``aschedule_ingestion``）；delivery app 不写 knowledge 模型（不 import knowledge.models）。
"""

from __future__ import annotations

import re
from pathlib import Path

# server/ 根目录（tests/delivery/test_inv6_guard.py → parents[2]）
SERVER_DIR = Path(__file__).resolve().parents[2]

# 遍历时剪掉的目录（venv / 缓存 / 静态产物 / vcs）
_PRUNE_DIRS = {
    ".venv",
    "node_modules",
    "staticfiles",
    "__pycache__",
    ".git",
    "htmlcov",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}

# 唯一允许写 WorkItem 的模块（相对 server/）
_ALLOWED_WRITER = "delivery/services/work_item_service.py"

# 唯一允许写 WorkItemCommentEvent 的模块（相对 server/，CMT-01/INV-6）
_ALLOWED_COMMENT_WRITER = "delivery/services/comment_event_service.py"

# 旁路写表模式（精确锚定，避免误伤 WorkItemService(/WorkItemRelation( 等长符号）：
# A：WorkItem.objects.<write>（紧跟 ".objects" 确保是 WorkItem 类本体，非 WorkItemRelation）
_RE_ORM_WRITE = re.compile(
    r"\bWorkItem\.objects\.(?:create|bulk_create|get_or_create|update_or_create)\b"
)
# B：直接实例化 WorkItem(...)（"\s*\(" 紧跟，天然排除 WorkItemService(/WorkItemRelation(/
#    WorkItemSyncState(/WorkItemStatusEvent(/WorkItemSerializer(/WorkItemIdentity( 等）
_RE_INSTANTIATE = re.compile(r"\bWorkItem\s*\(")
# C：链式实例化 + save（WorkItem(...).save(...)）
_RE_INSTANCE_SAVE = re.compile(r"\bWorkItem\([^)]*\)\.save\(")

# 评论事件旁路写表模式（同款精确锚定，避免误伤更长符号 / 读路径 .filter）：
# A：WorkItemCommentEvent.objects.<write>（紧跟 ".objects" 确保是类本体；
#    case-sensitive 天然排除事件字符串 "WorkitemCommentEvent"（小写 i））
_RE_COMMENT_ORM_WRITE = re.compile(
    r"\bWorkItemCommentEvent\.objects\.(?:create|bulk_create|get_or_create|update_or_create)\b"
)
# B：直接实例化 WorkItemCommentEvent(...)（"\s*\(" 紧跟；.objects.filter 等读路径不命中）
_RE_COMMENT_INSTANTIATE = re.compile(r"\bWorkItemCommentEvent\s*\(")
# C：链式实例化 + save（WorkItemCommentEvent(...).save(...)）
_RE_COMMENT_INSTANCE_SAVE = re.compile(r"\bWorkItemCommentEvent\([^)]*\)\.save\(")

# feishu_chat_id writeback 旁路写表模式（D-6/INV-6/P-5）：
# 唯一允许写 feishu_chat_id 的模块即 WorkItem 唯一 writer（work_item_service.py）。
# 锚 `.feishu_chat_id =` 赋值（排除 ==/!=/>= 等比较，只命中单 `=` 赋值）。
_RE_CHAT_ID_WRITE = re.compile(r"\.feishu_chat_id\s*=\s*[^=]")


def _iter_py_files() -> list[Path]:
    """遍历 server/ 下 .py 文件（剪掉 venv/缓存/静态目录）。"""
    files: list[Path] = []
    for path in SERVER_DIR.rglob("*.py"):
        if any(part in _PRUNE_DIRS for part in path.relative_to(SERVER_DIR).parts):
            continue
        files.append(path)
    return files


def _is_scanned_for_inv6(rel: str) -> bool:
    """INV-6 扫描范围：排除 tests/ / migrations/ / delivery/models/ 与 service 自身。"""
    if rel == _ALLOWED_WRITER:
        return False
    if rel.startswith("tests/") or "/tests/" in rel:
        return False
    if "/migrations/" in rel:
        return False
    if rel.startswith("delivery/models/"):
        return False
    return True


def _is_scanned_for_comment_inv6(rel: str) -> bool:
    """评论 INV-6 扫描范围：排除 tests/ / migrations/ / delivery/models/ 与 service 自身。

    与 WorkItem INV-6 同款剪枝；comment 唯一 writer 为 comment_event_service.py。
    """
    if rel == _ALLOWED_COMMENT_WRITER:
        return False
    if rel.startswith("tests/") or "/tests/" in rel:
        return False
    if "/migrations/" in rel:
        return False
    if rel.startswith("delivery/models/"):
        return False
    return True


def test_inv6_no_bypass_work_item_write() -> None:
    """INV-6：除 WorkItemService 外，server 源码无旁路 WorkItem 写表入口。"""
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned_for_inv6(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # 跳过 class 定义行（class WorkItem(models.Model):）
            if line.lstrip().startswith("class WorkItem"):
                continue
            if (
                _RE_ORM_WRITE.search(line)
                or _RE_INSTANCE_SAVE.search(line)
                or _RE_INSTANTIATE.search(line)
            ):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路 WorkItem 写表（落库只允许经 "
        f"WorkItemService.upsert / {_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


def test_inv6_writer_module_actually_writes() -> None:
    """守护有效性：唯一允许的 writer 确实包含 WorkItem 写表（否则上面的断言形同虚设）。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert "get_or_create" in text and ".save(" in text, (
        "WorkItemService.upsert 应是唯一 WorkItem 写表点，但未检出 get_or_create/.save"
    )


def test_inv6_no_bypass_feishu_chat_id_write() -> None:
    """INV-6/P-5：除 WorkItemService 外，server 源码无旁路写 feishu_chat_id。

    ``feishu_chat_id`` 是 writeback 字段，唯一合规写入路径为
    ``WorkItemService.awriteback_feishu_chat_id``（落点 work_item_service.py）。
    任何其它模块出现 ``.feishu_chat_id =`` 赋值即视为旁路（可能污染 mirror /
    绕过单一入口），命中即 fail 并列出文件:行。
    """
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        # 复用 WorkItem INV-6 剪枝：排除 tests/ / migrations/ / models/ 与唯一 writer
        if not _is_scanned_for_inv6(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _RE_CHAT_ID_WRITE.search(line):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路写 feishu_chat_id（writeback 只允许经 "
        f"WorkItemService.awriteback_feishu_chat_id / {_ALLOWED_WRITER}）：\n"
        + "\n".join(violations)
    )


def test_inv6_feishu_chat_id_writer_actually_writes() -> None:
    """守护有效性：唯一 writer 确实写 feishu_chat_id（否则上面的断言形同虚设）。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert "awriteback_feishu_chat_id" in text, (
        "work_item_service.py 应含 feishu_chat_id writeback 单一入口 "
        "awriteback_feishu_chat_id"
    )
    assert _RE_CHAT_ID_WRITE.search(text), (
        "work_item_service.py 应实际写 .feishu_chat_id（赋值），但未检出"
    )
    assert 'update_fields=["feishu_chat_id"' in text, (
        "feishu_chat_id 写回应显式 save(update_fields=[\"feishu_chat_id\", ...])，"
        "避免污染其它字段"
    )


def test_inv6_no_bypass_comment_event_write() -> None:
    """INV-6：除 CommentEventService 外，server 源码无旁路 WorkItemCommentEvent 写表入口。

    含 webhook 接线（feishu/views.py）、REST、projection 均不写表——评论事件落库
    单一收口为 ``CommentEventService.append_events``（CMT-01）。命中即 fail 并列出文件:行。
    """
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned_for_comment_inv6(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # 跳过模型定义行（class WorkItemCommentEvent(models.Model):）
            if line.lstrip().startswith("class WorkItemCommentEvent"):
                continue
            if (
                _RE_COMMENT_ORM_WRITE.search(line)
                or _RE_COMMENT_INSTANCE_SAVE.search(line)
                or _RE_COMMENT_INSTANTIATE.search(line)
            ):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路 WorkItemCommentEvent 写表（落库只允许经 "
        f"CommentEventService.append_events / {_ALLOWED_COMMENT_WRITER}）：\n"
        + "\n".join(violations)
    )


def test_inv6_comment_writer_module_actually_writes() -> None:
    """守护有效性：评论唯一 writer 确实包含 WorkItemCommentEvent 写表（否则断言形同虚设）。"""
    writer = SERVER_DIR / _ALLOWED_COMMENT_WRITER
    assert writer.exists(), f"{_ALLOWED_COMMENT_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert _RE_COMMENT_ORM_WRITE.search(text), (
        "CommentEventService.append_events 应是唯一 WorkItemCommentEvent 写表点，"
        "但未检出 WorkItemCommentEvent.objects.<write>"
    )


def test_inv3_feishu_ingestion_projection_preserved() -> None:
    """INV-3：飞书 webhook 既有 knowledge ingestion 投递仍在（投影未被 delivery 取代）。"""
    views = SERVER_DIR / "feishu" / "views.py"
    text = views.read_text(encoding="utf-8")
    assert "aschedule_ingestion" in text, (
        "INV-3 违反：feishu/views.py 不再投递 knowledge ingestion（投影被移除）"
    )
    # delivery upsert 与 ingestion 并存（接线点存在）
    assert "WorkItemService" in text, "feishu/views.py 未接线 delivery upsert"
    # INV-3（评论接线）：评论 handler 仍保留既有 approval 调用 + 新增评论 append 接线并存
    assert "FeishuApprovalHandler" in text, (
        "INV-3 违反：feishu/views.py 评论 handler 不再保留既有 approval 处理"
    )
    assert "append_webhook_comment" in text, "feishu/views.py 未接线评论事件后台 append"


def test_inv3_delivery_does_not_write_knowledge_models() -> None:
    """INV-3：delivery app 不 import / 写 knowledge 模型（delivery 是操作态事实源，不双写）。"""
    delivery_dir = SERVER_DIR / "delivery"
    offenders: list[str] = []
    for path in delivery_dir.rglob("*.py"):
        if any(part in _PRUNE_DIRS for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        if "knowledge.models" in text or re.search(r"\bKnowledgeEntity\b", text):
            offenders.append(path.relative_to(SERVER_DIR).as_posix())

    assert not offenders, (
        "INV-3 违反：delivery app 引用/写 knowledge 模型（应保持单向，不双写事实）：\n"
        + "\n".join(offenders)
    )
