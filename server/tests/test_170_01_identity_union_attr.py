"""Test for Task 1: 修复 identity/views.py 中的 union-attr 错误
这个测试验证修复后的代码没有 union-attr type: ignore 注释
"""
import subprocess
import sys
from pathlib import Path
import pytest
SERVER_DIR = str(Path(__file__).resolve.parent.parent)
class TestIdentityViewsUnionAttrFix:
 """测试 identity/views.py 中 union-attr 错误的修复"""
 def test_no_union_attr_type_ignore_in_identity_views(self):
 """测试 identity/views.py 中不应该存在 union-attr type: ignore 注释"""
 result = subprocess.run([
 sys.executable, "-m", "mypy",
 "identity/views.py",
 "--show-error-codes"
 ], capture_output=True, text=True, cwd=SERVER_DIR)
 has_union_attr_errors = "union-attr" in result.stdout or "union-attr" in result.stderr
 with open(Path(SERVER_DIR) / "identity" / "views.py", "r") as f:
 content = f.read
 has_union_attr_ignores = "type: ignore[union-attr]" in content
 assert not has_union_attr_errors, f"identity/views.py 仍有 union-attr 错误:\n{result.stdout}\n{result.stderr}"
 assert not has_union_attr_ignores, "identity/views.py 仍包含 union-attr type: ignore 注释"