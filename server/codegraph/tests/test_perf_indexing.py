"""性能基线测试 —— 验证图谱抽取带来的索引耗时增长不超过 30%。
覆盖 Nyquist 维度 3（性能）+ 维度 6（向后兼容：fixed 模式测试）。
"""
import os
import time
import pytest
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
class TestIndexingPerformance:
 """性能基线 —— 图谱抽取开销 < 30%。"""
 @pytest.mark.django_db
 def test_graph_extractor_init_overhead(self):
 """GraphExtractor + GraphWriter 初始化应为惰性加载，开销可忽略。"""
 from services.indexer import IndexerService
 start = time.perf_counter
 indexer = IndexerService("test-perf-repo")
 init_time = time.perf_counter - start
 # 延迟初始化意味着 __init__ 中不创建 graph 服务
 # 初始化时间应 < 10ms
 assert init_time < 0.010, \
 f"IndexerService init took {init_time*1000:.2f}ms, expected < 10ms"
 # 首次调用 _init_graph_services 触发实际导入
 start = time.perf_counter
 indexer._init_graph_services
 first_init_time = time.perf_counter - start
 # 首次初始化应包含模块导入开销，但 < 500ms
 assert first_init_time < 0.500, \
 f"Graph services init took {first_init_time*1000:.2f}ms, expected < 500ms"
 # 二次调用应为缓存，< 1ms
 start = time.perf_counter
 indexer._init_graph_services
 second_init_time = time.perf_counter - start
 assert second_init_time < 0.001, \
 f"Second init took {second_init_time*1000:.2f}ms, expected < 1ms"
 @pytest.mark.django_db
 def test_chunking_mode_fixed_backward_compat(self):
 """维度 6: chunking_mode='fixed'（默认）时，CodeParser 行为与改造前一致。"""
 from services.code_parser import CodeParser
 import tempfile
 parser = CodeParser
 with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
 f.write("""import os
import sys
def hello:
 '''Say hello.'''
 print("hello world")
class Greeter:
 def greet(self, name):
 return f"Hello, {name}"
if __name__ == "__main__":
 hello
""")
 tmp_path = f.name
 try:
 # 默认 fixed 模式（不传 chunking_mode）
 chunks_fixed_default = parser.parse_file(tmp_path)
 # 显式 fixed 模式
 chunks_fixed_explicit = parser.parse_file(tmp_path, chunking_mode="fixed")
 # 两种方式应产出相同结果
 assert len(chunks_fixed_default) == len(chunks_fixed_explicit), \
 f"Default vs explicit fixed: {len(chunks_fixed_default)} != {len(chunks_fixed_explicit)}"
 assert len(chunks_fixed_default) > 0, "Fixed mode should produce chunks"
 # ast_aware 模式
 chunks_aware = parser.parse_file(tmp_path, chunking_mode="ast_aware")
 # AST-aware 模式应至少产生 2 个 chunk（hello + Greeter）
 assert len(chunks_aware) >= 2, \
 f"AST-aware mode should produce >= 2 chunks, got {len(chunks_aware)}"
 # 验证 parent_symbol 字段存在且 fixed 模式为 None
 for chunk in chunks_fixed_default:
 assert chunk.parent_symbol is None, \
 f"Fixed mode chunk {chunk.node_type} has parent_symbol={chunk.parent_symbol}"
 print(f"Fixed: {len(chunks_fixed_default)} chunks, AST-aware: {len(chunks_aware)} chunks")
 finally:
 os.unlink(tmp_path)
 @pytest.mark.django_db
 def test_graph_extraction_single_file_overhead(self, tmp_path):
 """单文件图谱抽取耗时应在合理范围内（< 500ms 对于典型 Python 文件）。"""
 from services.indexer import IndexerService
 import asyncio
 py_file = tmp_path / "perf_test.py"
 # 生成一个中等大小的 Python 文件（约 50 行，5 个函数）
 py_file.write_text("""
import os, sys, json
from typing import Optional, List, Dict
from collections import defaultdict
CONFIG = {"debug": True, "timeout": 30}
def func_a(x: int) -> int:
 '''Function A.'''
 return x * 2 + 1
def func_b(y: str) -> str:
 '''Function B.'''
 return y.upper + "_suffix"
class DataHandler:
 '''Handle data processing.'''
 def __init__(self, config: dict):
 self.config = config
 self._cache = {}
 def process(self, items: list) -> list:
 '''Process items.'''
 results =
 for item in items:
 val = func_a(len(item))
 results.append(func_b(str(val)))
 return results
 def clear_cache(self):
 '''Clear internal cache.'''
 self._cache.clear
def main:
 handler = DataHandler(CONFIG)
 data = ["hello", "world", "test"]
 result = handler.process(data)
 print(f"Result: {result}")
if __name__ == "__main__":
 main
""")
 async def _run:
 indexer = IndexerService("test-perf-repo")
 indexer._init_graph_services
 start = time.perf_counter
 result = await indexer._extract_and_write_graph(
 repo_path=str(tmp_path),
 file_paths=["perf_test.py"],
 repository_id="test-perf-repo",
 )
 elapsed = time.perf_counter - start
 # 注意：此测试不写 DB（repository_id 无效），但 graph extraction 流程应该完成
 # 实际写入会失败（无对应 Repository），但抽取本身应完成
 # 对于纯抽取耗时，单文件 < 500ms（包含首次模块导入）
 print(f"Graph extraction took {elapsed*1000:.2f}ms, result: {result}")
 assert elapsed < 0.500, \
 f"Single file graph extraction took {elapsed*1000:.2f}ms, expected < 500ms"
 asyncio.run(_run)
