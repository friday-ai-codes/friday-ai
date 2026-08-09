"""``services/code_graph/detect_changes.py`` 纯内核用例（DIFF-01 / DIFF-02）。

**本文件零数据库**：交叠 / rename 分类 / formatting / 阈值形状全部用字符串
fixture 与纯值断言，不起 Django ORM、不建库。
"""

from __future__ import annotations

from services.code_graph.detect_changes import (
    DETECT_CHANGES_MAX_SYMBOLS_FOR_IMPACT,
    ChangeType,
    SymbolRecord,
    detect_affected_symbols,
    is_formatting_only,
    parse_unified_diff,
    ranges_overlap,
    should_skip_batch_impact,
    symbols_hit_by_old_hunk,
)


def _sym(
    uid: str,
    *,
    path: str,
    start: int,
    end: int,
    name: str = "fn",
    symbol_type: str = "function",
) -> SymbolRecord:
    return SymbolRecord(
        uid=uid,
        name=name,
        symbol_type=symbol_type,
        file_path=path,
        start_line=start,
        end_line=end,
    )


def test_ranges_overlap() -> None:
    """闭区间相交真值表（D-05）。"""
    assert ranges_overlap(1, 5, 5, 10) is True
    assert ranges_overlap(1, 5, 6, 10) is False
    assert ranges_overlap(10, 20, 1, 9) is False
    assert ranges_overlap(10, 20, 15, 16) is True
    assert ranges_overlap(3, 3, 3, 3) is True


def test_symbols_hit_by_old_hunk() -> None:
    """@@ -start,count @@ 与 symbol 行区间求交；count=0 → 无命中（D-05）。"""
    symbols = [
        _sym("u1", path="a.py", start=1, end=10),
        _sym("u2", path="a.py", start=20, end=30),
        _sym("u3", path="a.py", start=40, end=50),
    ]
    hit = symbols_hit_by_old_hunk(symbols, hunk_old_start=8, hunk_old_count=5)
    assert {s.uid for s in hit} == {"u1"}

    assert symbols_hit_by_old_hunk(symbols, 25, 0) == []
    assert symbols_hit_by_old_hunk(symbols, 100, 2) == []


def test_pure_insert_hunk_no_fake_uid() -> None:
    """纯新增 hunk → 文件级 added 摘要，不伪造 uid（D-05）。"""
    diff = """\
diff --git a/new_file.py b/new_file.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/new_file.py
@@ -0,0 +1,3 @@
+def brand_new():
+    return 42
+
"""
    parsed = parse_unified_diff(diff)
    result = detect_affected_symbols(parsed_diff=parsed, symbols_by_path={})
    files = result["files"]
    assert len(files) == 1
    group = files[0]
    assert group["change_type"] == ChangeType.ADDED.value
    assert group["symbols"] == []
    assert "uid" not in group.get("file_summary", {})
    assert group.get("file_summary", {}).get("changeType") == ChangeType.ADDED.value


def test_rename_single_entry_not_delete_add() -> None:
    """纯 rename → 仅 renamed 一条，无 deleted+added 双列表（D-06）。"""
    diff = """\
diff --git a/old_name.py b/new_name.py
similarity index 100%
rename from old_name.py
rename to new_name.py
"""
    parsed = parse_unified_diff(diff)
    assert len(parsed) == 1
    assert parsed[0].is_rename is True
    assert parsed[0].old_path == "old_name.py"
    assert parsed[0].new_path == "new_name.py"

    symbols = {
        "old_name.py": [_sym("sym-old", path="old_name.py", start=1, end=5, name="foo")],
    }
    result = detect_affected_symbols(parsed_diff=parsed, symbols_by_path=symbols)
    types = [f["change_type"] for f in result["files"]]
    assert types == [ChangeType.RENAMED.value]
    assert not any(t in types for t in (ChangeType.DELETED.value, ChangeType.ADDED.value))
    assert len(result["files"][0]["symbols"]) == 1
    assert result["files"][0]["symbols"][0]["changeType"] == ChangeType.RENAMED.value


def test_formatting_only_not_impact_seed() -> None:
    """formatting_only 不进入 impact 种子集（D-07）。"""
    old = ["import os\n", "import sys\n", "\n", "def f():\n", "    return 1\n"]
    new = ["import sys\n", "import os\n", "\n", "def f():\n", "    return 1\n"]
    assert is_formatting_only(old, new) is True

    diff = """\
diff --git a/fmt.py b/fmt.py
index 1111111..2222222 100644
--- a/fmt.py
+++ b/fmt.py
@@ -1,2 +1,2 @@
-import os
-import sys
+import sys
+import os
"""
    parsed = parse_unified_diff(diff)
    symbols = {"fmt.py": [_sym("fmt-fn", path="fmt.py", start=4, end=5, name="f")]}
    # hunk 只改 1-2 行 import；符号在 4-5 → 不交叠；用整文件旧/新行测 heuristic
    # 构造会命中符号的 formatting hunk：改符号行内空白
    diff2 = """\
diff --git a/fmt.py b/fmt.py
index 1111111..2222222 100644
--- a/fmt.py
+++ b/fmt.py
@@ -4,2 +4,2 @@
-def f():
-    return 1
+def f():
+     return 1
"""
    parsed2 = parse_unified_diff(diff2)
    result = detect_affected_symbols(parsed_diff=parsed2, symbols_by_path=symbols)
    syms = result["files"][0]["symbols"]
    assert len(syms) == 1
    assert syms[0]["changeType"] == ChangeType.FORMATTING_ONLY.value
    assert syms[0]["impact_seed"] is False


def test_deleted_file_symbols_are_seeds() -> None:
    """整文件 delete → 旧路径符号 deleted，仍可作为 impact 种子（D-08）。"""
    diff = """\
diff --git a/gone.py b/gone.py
deleted file mode 100644
index 1111111..0000000
--- a/gone.py
+++ /dev/null
@@ -1,3 +0,0 @@
-def doomed():
-    return 0
-
"""
    parsed = parse_unified_diff(diff)
    symbols = {
        "gone.py": [
            _sym("d1", path="gone.py", start=1, end=3, name="doomed"),
        ],
    }
    result = detect_affected_symbols(parsed_diff=parsed, symbols_by_path=symbols)
    assert result["files"][0]["change_type"] == ChangeType.DELETED.value
    sym = result["files"][0]["symbols"][0]
    assert sym["changeType"] == ChangeType.DELETED.value
    assert sym["impact_seed"] is True
    assert sym["uid"] == "d1"


def test_threshold_file_summary_shape() -> None:
    """>100 符号 → truncated / not_expanded 字段形状（D-08）。"""
    assert DETECT_CHANGES_MAX_SYMBOLS_FOR_IMPACT == 100
    assert should_skip_batch_impact(100) is False
    assert should_skip_batch_impact(101) is True

    # 构造 >100 个被命中符号（同一文件多个小符号 + 覆盖 hunk）
    symbols = [
        _sym(f"u{i}", path="big.py", start=i * 2 + 1, end=i * 2 + 2)
        for i in range(101)
    ]
    # hunk 覆盖整个文件行范围
    last_end = symbols[-1].end_line
    diff = f"""\
diff --git a/big.py b/big.py
index 1111111..2222222 100644
--- a/big.py
+++ b/big.py
@@ -1,{last_end} +1,{last_end} @@
"""
    # 手工拼 hunk：每行都有变更标记以便 parser 收集
    lines = []
    for i in range(1, last_end + 1):
        lines.append(f"-old{i}")
        lines.append(f"+new{i}")
    # 简化：用 parse + 强制大 count；改用 detect 直接喂大量 symbols 于 deleted 文件
    del_diff = """\
diff --git a/big.py b/big.py
deleted file mode 100644
index 1111111..0000000
--- a/big.py
+++ /dev/null
@@ -1,1 +0,0 @@
-x
"""
    parsed = parse_unified_diff(del_diff)
    result = detect_affected_symbols(
        parsed_diff=parsed,
        symbols_by_path={"big.py": symbols},
    )
    summary = result["summary"]
    assert summary["affected_symbol_count"] == 101
    assert summary["truncated"] is True
    assert summary["not_expanded"] is True
    assert should_skip_batch_impact(summary["affected_symbol_count"]) is True


def test_affected_symbol_min_fields() -> None:
    """受影响符号六字段 + file:line + changeType 枚举（D-15）。"""
    diff = """\
diff --git a/mod.py b/mod.py
index 1111111..2222222 100644
--- a/mod.py
+++ b/mod.py
@@ -2,1 +2,1 @@
-    return 1
+    return 2
"""
    parsed = parse_unified_diff(diff)
    symbols = {
        "mod.py": [_sym("uid-1", path="mod.py", start=1, end=4, name="calc")],
    }
    result = detect_affected_symbols(parsed_diff=parsed, symbols_by_path=symbols)
    sym = result["files"][0]["symbols"][0]
    for key in ("uid", "name", "symbol_type", "file_path", "changeType", "lines_changed"):
        assert key in sym, f"missing {key}"
    assert sym["uid"] == "uid-1"
    assert sym["name"] == "calc"
    assert sym["changeType"] == ChangeType.MODIFIED.value
    assert isinstance(sym["lines_changed"], int)
    assert "file_line" in sym or "file:line" in sym
    loc = sym.get("file_line") or sym.get("file:line")
    assert str(loc).startswith("mod.py:")


def test_exclusion_paths_absent() -> None:
    """交叠输入已过滤后输出亦不含排除路径（T-123-EXCL）。"""
    diff = """\
diff --git a/src/ok.py b/src/ok.py
index 1111111..2222222 100644
--- a/src/ok.py
+++ b/src/ok.py
@@ -1,1 +1,1 @@
-x
+y
diff --git a/secrets/.env b/secrets/.env
index 1111111..2222222 100644
--- a/secrets/.env
+++ b/secrets/.env
@@ -1,1 +1,1 @@
-SECRET=1
+SECRET=2
"""
    parsed = parse_unified_diff(diff)
    # 调用方已排除 secrets/.env —— 内核不再二次查库
    symbols = {
        "src/ok.py": [_sym("ok", path="src/ok.py", start=1, end=1)],
    }
    result = detect_affected_symbols(parsed_diff=parsed, symbols_by_path=symbols)
    paths = {f["path"] for f in result["files"]}
    assert "secrets/.env" not in paths
    # 排除路径上的 file_summary 也不应出现（无 symbols 且无调用方路径时跳过）
    for f in result["files"]:
        assert "secrets" not in f["path"]
        for s in f["symbols"]:
            assert "secrets" not in s["file_path"]
