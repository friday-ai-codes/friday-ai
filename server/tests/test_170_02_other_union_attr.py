"""Test for Task 2: 修复其他文件中的 union-attr 错误
测试 runners/views.py 和 chat/title_service.py 中的类型修复
"""
import subprocess
import sys
class TestOtherFilesUnionAttrFix:
 """测试其他文件中 union-attr 错误的修复"""
 def test_no_union_attr_type_ignore_in_runners_views(self):
 """测试 runners/views.py 中不应该存在 union-attr type: ignore 注释"""
 # 运行 mypy 检查
 result = subprocess.run([
 sys.executable, "-m", "mypy",
 "runners/views.py",
 "--show-error-codes"
 ], capture_output=True, text=True, cwd="/Users/zaneliu/Projects/open-source/friday-ai/server")
 # 检查是否有 union-attr 错误
 has_union_attr_errors = "union-attr" in result.stdout or "union-attr" in result.stderr
 # 检查文件中是否还有 type: ignore[union-attr] 注释
 with open("/Users/zaneliu/Projects/open-source/friday-ai/server/runners/views.py", "r") as f:
 content = f.read
 has_union_attr_ignores = "type: ignore[union-attr]" in content
 assert not has_union_attr_errors, f"runners/views.py 仍有 union-attr 错误:\n{result.stdout}\n{result.stderr}"
 assert not has_union_attr_ignores, "runners/views.py 仍包含 union-attr type: ignore 注释"
 def test_no_union_attr_type_ignore_in_chat_title_service(self):
 """测试 chat/title_service.py 中不应该存在 union-attr type: ignore 注释"""
 # 运行 mypy 检查
 result = subprocess.run([
 sys.executable, "-m", "mypy",
 "chat/title_service.py",
 "--show-error-codes"
 ], capture_output=True, text=True, cwd="/Users/zaneliu/Projects/open-source/friday-ai/server")
 # 检查是否有 union-attr 错误
 has_union_attr_errors = "union-attr" in result.stdout or "union-attr" in result.stderr
 # 检查文件中是否还有 type: ignore[union-attr] 注释
 with open("/Users/zaneliu/Projects/open-source/friday-ai/server/chat/title_service.py", "r") as f:
 content = f.read
 has_union_attr_ignores = "type: ignore[union-attr]" in content
 assert not has_union_attr_errors, f"chat/title_service.py 仍有 union-attr 错误:\n{result.stdout}\n{result.stderr}"
 assert not has_union_attr_ignores, "chat/title_service.py 仍包含 union-attr type: ignore 注释"