"""detect_changes 纯交叠内核（Phase 123，DIFF-01 / DIFF-02）。

零 Django / 零 ORM / 零网络：只吃 unified diff 文本与内存 Symbol 记录，
产出按文件分组的受影响符号清单。编排层（``run_detect_changes``）负责
ACL、mirror、取图与 batch ``run_impact``。

行号坐标一律用 **base / old 侧**（D-05）；rename 落单条 ``renamed``
（D-06）；``formatting_only`` 不进 impact 种子（D-07）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

import structlog

logger = structlog.get_logger(__name__)

DETECT_CHANGES_MAX_SYMBOLS_FOR_IMPACT: Final[int] = 100

_HUNK_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"
)
_DIFF_GIT_RE = re.compile(r"^diff --git a/(.*) b/(.*)$")


class ChangeType(str, Enum):
    """受影响符号 / 文件级变更类型（D-15 封闭枚举）。"""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    FORMATTING_ONLY = "formatting_only"


@dataclass(frozen=True)
class SymbolRecord:
    """内存侧符号记录（与 ORM Symbol 字段对齐，本模块不引用模型）。"""

    uid: str
    name: str
    symbol_type: str
    file_path: str
    start_line: int
    end_line: int


@dataclass
class DiffHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    old_lines: list[str] = field(default_factory=list)
    new_lines: list[str] = field(default_factory=list)


@dataclass
class FileChange:
    """单个 ``diff --git`` 文件块（rename 永不拆成 D+A）。"""

    old_path: str | None
    new_path: str | None
    is_rename: bool = False
    is_deleted: bool = False
    is_added: bool = False
    hunks: list[DiffHunk] = field(default_factory=list)

    @property
    def path_for_group(self) -> str:
        if self.is_deleted:
            return self.old_path or ""
        return self.new_path or self.old_path or ""


def ranges_overlap(a0: int, a1: int, b0: int, b1: int) -> bool:
    """闭区间 [a0,a1] 与 [b0,b1] 是否相交。"""
    return a0 <= b1 and b0 <= a1


def symbols_hit_by_old_hunk(
    symbols: Sequence[SymbolRecord],
    hunk_old_start: int,
    hunk_old_count: int,
) -> list[SymbolRecord]:
    """用 old 侧 hunk 行区间命中 Symbol；``count<=0`` 表示纯插入 → 空。"""
    if hunk_old_count <= 0:
        return []
    old_end = hunk_old_start + hunk_old_count - 1
    return [
        sym
        for sym in symbols
        if ranges_overlap(sym.start_line, sym.end_line, hunk_old_start, old_end)
    ]


def is_formatting_only(old_lines: list[str], new_lines: list[str]) -> bool:
    """空白 strip + import 行排序后实质相同 → formatting_only（Discretion A1）。"""

    def _norm(lines: list[str]) -> list[str]:
        body = [ln.strip() for ln in lines if ln.strip()]
        imports = sorted(
            x for x in body if x.startswith(("import ", "from "))
        )
        rest = [x for x in body if not x.startswith(("import ", "from "))]
        return imports + rest

    if not old_lines and not new_lines:
        return False
    return _norm(old_lines) == _norm(new_lines)


def should_skip_batch_impact(affected_count: int) -> bool:
    """符号数超过阈值时编排层应跳过 batch impact（D-08）。"""
    return affected_count > DETECT_CHANGES_MAX_SYMBOLS_FOR_IMPACT


def parse_unified_diff(text: str) -> list[FileChange]:
    """解析 ``git diff --unified=0 --find-renames`` 文本为 FileChange 列表。

    rename 文件**单一** FileChange（D-06 / DIFF-02）；⛔ 不按相似度拆 D+A。
    """
    files: list[FileChange] = []
    current: FileChange | None = None
    current_hunk: DiffHunk | None = None

    def _flush_hunk() -> None:
        nonlocal current_hunk
        if current is not None and current_hunk is not None:
            current.hunks.append(current_hunk)
        current_hunk = None

    for raw_line in text.splitlines():
        git_match = _DIFF_GIT_RE.match(raw_line)
        if git_match:
            _flush_hunk()
            current = FileChange(
                old_path=git_match.group(1),
                new_path=git_match.group(2),
            )
            files.append(current)
            continue

        if current is None:
            continue

        if raw_line.startswith("rename from "):
            current.is_rename = True
            current.old_path = raw_line[len("rename from ") :].strip()
            continue
        if raw_line.startswith("rename to "):
            current.is_rename = True
            current.new_path = raw_line[len("rename to ") :].strip()
            continue
        if raw_line.startswith("deleted file mode"):
            current.is_deleted = True
            continue
        if raw_line.startswith("new file mode"):
            current.is_added = True
            continue
        if raw_line.startswith("--- "):
            path = raw_line[4:].strip()
            if path == "/dev/null":
                current.is_added = True
                current.old_path = None
            else:
                current.old_path = path[2:] if path.startswith("a/") else path
            continue
        if raw_line.startswith("+++ "):
            path = raw_line[4:].strip()
            if path == "/dev/null":
                current.is_deleted = True
                current.new_path = None
            else:
                current.new_path = path[2:] if path.startswith("b/") else path
            continue

        hunk_match = _HUNK_RE.match(raw_line)
        if hunk_match:
            _flush_hunk()
            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2) or "1")
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4) or "1")
            current_hunk = DiffHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
            )
            continue

        if current_hunk is None:
            continue
        if raw_line.startswith("-"):
            current_hunk.old_lines.append(raw_line[1:])
        elif raw_line.startswith("+"):
            current_hunk.new_lines.append(raw_line[1:])
        # context lines (space prefix) ignored under --unified=0

    _flush_hunk()

    try:
        logger.debug(
            "code_graph_diff_parsed",
            category="sampling",
            component="code_graph",
            file_count=len(files),
            rename_count=sum(1 for f in files if f.is_rename),
            hunk_count=sum(len(f.hunks) for f in files),
        )
    except Exception:  # noqa: BLE001 — 观测永不反噬
        pass

    return files


def _affected_symbol_dict(
    sym: SymbolRecord,
    *,
    change_type: ChangeType,
    lines_changed: int,
    impact_seed: bool,
    file_path: str | None = None,
) -> dict[str, Any]:
    path = file_path if file_path is not None else sym.file_path
    return {
        "uid": sym.uid,
        "name": sym.name,
        "symbol_type": sym.symbol_type,
        "file_path": path,
        "changeType": change_type.value,
        "lines_changed": lines_changed,
        "file_line": f"{path}:{sym.start_line}",
        "impact_seed": impact_seed,
    }


def detect_affected_symbols(
    *,
    parsed_diff: Sequence[FileChange],
    symbols_by_path: Mapping[str, Sequence[SymbolRecord]],
) -> dict[str, Any]:
    """对 old 侧 hunk × Symbol 求交，产出按文件分组的受影响清单。

    - 交叠仅用 **old/base 路径** 与 old 侧行号（D-05）
    - 整文件 delete → 该路径全部符号 ``deleted`` 且 ``impact_seed=True``
    - 纯插入无法命中 Symbol → 文件级 ``added`` 摘要，⛔ 不伪造 uid
    - 输入 ``symbols_by_path`` 已不含排除路径时，输出亦不含（T-123-EXCL）
    """
    files_out: list[dict[str, Any]] = []
    affected_count = 0

    for fc in parsed_diff:
        old_key = fc.old_path or ""
        new_key = fc.new_path or ""
        group_path = fc.path_for_group

        if fc.is_deleted and old_key:
            symbols = list(symbols_by_path.get(old_key, ()))
            if not symbols:
                continue
            sym_dicts = [
                _affected_symbol_dict(
                    sym,
                    change_type=ChangeType.DELETED,
                    lines_changed=max(0, sym.end_line - sym.start_line + 1),
                    impact_seed=True,
                    file_path=old_key,
                )
                for sym in symbols
            ]
            affected_count += len(sym_dicts)
            files_out.append(
                {
                    "path": old_key,
                    "change_type": ChangeType.DELETED.value,
                    "old_path": old_key,
                    "new_path": None,
                    "symbols": sym_dicts,
                    "file_summary": {"changeType": ChangeType.DELETED.value},
                }
            )
            continue

        if fc.is_added and not fc.is_rename:
            # 纯新增文件：无 old 侧坐标可交叠 → 文件级摘要
            files_out.append(
                {
                    "path": new_key or group_path,
                    "change_type": ChangeType.ADDED.value,
                    "old_path": None,
                    "new_path": new_key or group_path,
                    "symbols": [],
                    "file_summary": {"changeType": ChangeType.ADDED.value},
                }
            )
            continue

        lookup_path = old_key if old_key else new_key
        symbols = list(symbols_by_path.get(lookup_path, ()))

        if fc.is_rename:
            # 纯 rename（无 hunk）或带内容变更：一律单条 renamed（D-06）
            if not symbols and not fc.hunks:
                # 调用方未提供旧路径符号且无内容 hunk → 仍报文件级 rename
                files_out.append(
                    {
                        "path": new_key or old_key,
                        "change_type": ChangeType.RENAMED.value,
                        "old_path": old_key,
                        "new_path": new_key,
                        "symbols": [],
                        "file_summary": {"changeType": ChangeType.RENAMED.value},
                    }
                )
                continue

            sym_dicts: list[dict[str, Any]] = []
            if not fc.hunks:
                for sym in symbols:
                    sym_dicts.append(
                        _affected_symbol_dict(
                            sym,
                            change_type=ChangeType.RENAMED,
                            lines_changed=0,
                            impact_seed=True,
                            file_path=new_key or old_key,
                        )
                    )
            else:
                hit_uids: set[str] = set()
                all_old: list[str] = []
                all_new: list[str] = []
                for hunk in fc.hunks:
                    all_old.extend(hunk.old_lines)
                    all_new.extend(hunk.new_lines)
                    for sym in symbols_hit_by_old_hunk(
                        symbols, hunk.old_start, hunk.old_count
                    ):
                        hit_uids.add(sym.uid)
                # 有内容 hunk 但未命中任何符号：仅文件级 renamed，不整文件灌种子
                if not hit_uids:
                    files_out.append(
                        {
                            "path": new_key or old_key,
                            "change_type": ChangeType.RENAMED.value,
                            "old_path": old_key,
                            "new_path": new_key,
                            "symbols": [],
                            "file_summary": {"changeType": ChangeType.RENAMED.value},
                        }
                    )
                    continue
                formatting = is_formatting_only(all_old, all_new)
                targets = [s for s in symbols if s.uid in hit_uids]
                for sym in targets:
                    lines_changed = sum(
                        hunk.old_count
                        for hunk in fc.hunks
                        if hunk.old_count > 0
                        and ranges_overlap(
                            sym.start_line,
                            sym.end_line,
                            hunk.old_start,
                            hunk.old_start + hunk.old_count - 1,
                        )
                    )
                    if formatting:
                        ctype = ChangeType.FORMATTING_ONLY
                        seed = False
                    else:
                        ctype = ChangeType.RENAMED
                        seed = True
                    sym_dicts.append(
                        _affected_symbol_dict(
                            sym,
                            change_type=ctype,
                            lines_changed=lines_changed,
                            impact_seed=seed,
                            file_path=new_key or old_key,
                        )
                    )

            if not sym_dicts and not symbols:
                continue
            affected_count += len(sym_dicts)
            files_out.append(
                {
                    "path": new_key or old_key,
                    "change_type": ChangeType.RENAMED.value,
                    "old_path": old_key,
                    "new_path": new_key,
                    "symbols": sym_dicts,
                    "file_summary": {"changeType": ChangeType.RENAMED.value},
                }
            )
            continue

        # 普通修改
        if not symbols:
            # 无符号且非纯插入文件 → 视为调用方已排除，跳过（T-123-EXCL）
            continue

        # 聚合：按符号累计 old 侧变更行，并收集触及该符号的旧/新行
        per_sym_lines: dict[str, int] = {}
        per_sym_old: dict[str, list[str]] = {}
        per_sym_new: dict[str, list[str]] = {}
        pure_insert_only = True

        for hunk in fc.hunks:
            if hunk.old_count > 0:
                pure_insert_only = False
            hits = symbols_hit_by_old_hunk(symbols, hunk.old_start, hunk.old_count)
            for sym in hits:
                per_sym_lines[sym.uid] = (
                    per_sym_lines.get(sym.uid, 0) + max(hunk.old_count, 0)
                )
                per_sym_old.setdefault(sym.uid, []).extend(hunk.old_lines)
                per_sym_new.setdefault(sym.uid, []).extend(hunk.new_lines)

        if pure_insert_only and not per_sym_lines:
            # 文件内纯插入、未命中既有 Symbol → 文件级 added 摘要
            files_out.append(
                {
                    "path": new_key or lookup_path,
                    "change_type": ChangeType.ADDED.value,
                    "old_path": old_key or None,
                    "new_path": new_key or lookup_path,
                    "symbols": [],
                    "file_summary": {"changeType": ChangeType.ADDED.value},
                }
            )
            continue

        if not per_sym_lines:
            continue

        uid_to_sym = {s.uid: s for s in symbols}
        sym_dicts = []
        for uid, lines_changed in per_sym_lines.items():
            sym = uid_to_sym[uid]
            formatting = is_formatting_only(
                per_sym_old.get(uid, []),
                per_sym_new.get(uid, []),
            )
            if formatting:
                ctype = ChangeType.FORMATTING_ONLY
                seed = False
            else:
                ctype = ChangeType.MODIFIED
                seed = True
            sym_dicts.append(
                _affected_symbol_dict(
                    sym,
                    change_type=ctype,
                    lines_changed=lines_changed,
                    impact_seed=seed,
                )
            )

        affected_count += len(sym_dicts)
        # 文件级 change_type：全 formatting → formatting_only，否则 modified
        if sym_dicts and all(
            s["changeType"] == ChangeType.FORMATTING_ONLY.value for s in sym_dicts
        ):
            file_ctype = ChangeType.FORMATTING_ONLY.value
        else:
            file_ctype = ChangeType.MODIFIED.value
        files_out.append(
            {
                "path": new_key or lookup_path,
                "change_type": file_ctype,
                "old_path": old_key or None,
                "new_path": new_key or None,
                "symbols": sym_dicts,
                "file_summary": {"changeType": file_ctype},
            }
        )

    truncated = affected_count > DETECT_CHANGES_MAX_SYMBOLS_FOR_IMPACT
    return {
        "files": files_out,
        "summary": {
            "affected_symbol_count": affected_count,
            "truncated": truncated,
            "not_expanded": truncated,
            "file_count": len(files_out),
        },
    }
