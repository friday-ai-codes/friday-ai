"""Test for Task 1: 修复 identity/views.py 中的 union-attr 错误
这个测试验证修复后的代码没有 union-attr type: ignore 注释
"""
import subprocess
import sys
import pytest
class TestIdentityViewsUnionAttrFix:
 """测试 identity/views.py 中 union-attr 错误的修复"""
 def test_no_union_attr_type_ignore_in_identity_views(self):
 """测试 identity/views.py 中不应该存在 union-attr type: ignore 注释"""
 # 这个测试预期会失败，直到我们移除了所有 union-attr type: ignore
 # 运行 mypy 检查 identity/views.py
 result = subprocess.run([
 sys.executable, "-m", "mypy",
 "identity/views.py",
 "--show-error-codes"
 ], capture_output=True, text=True, cwd="/Users/zaneliu/Projects/open-source/friday-ai/server")
 # 如果有 union-attr 错误，mypy 会报告它们
 has_union_attr_errors = "union-attr" in result.stdout or "union-attr" in result.stderr
 # 检查文件中是否还有 type: ignore[union-attr] 注释
 with open("/Users/zaneliu/Projects/open-source/friday-ai/server/identity/views.py", "r") as f:
 content = f.read
 has_union_attr_ignores = "type: ignore[union-attr]" in content
 # 测试失败条件：要么有 union-attr 错误，要么有对应的 type: ignore 注释
 assert not has_union_attr_errors, f"identity/views.py 仍有 union-attr 错误:\n{result.stdout}\n{result.stderr}"
 assert not has_union_attr_ignores, "identity/views.py 仍包含 union-attr type: ignore 注释"