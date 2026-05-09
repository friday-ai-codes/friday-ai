"""Graph Expansion 测试共享 fixtures。"""
import pytest
from asgiref.sync import sync_to_async
from codegraph.models import CallEdge, Symbol
from repositories.models import Repository
@pytest.fixture
def graph_repo(db):
 """创建测试用的 Repository。"""
 return Repository.objects.create(
 name="test-graph-repo",
 git_url="https://example.com/test-graph-repo.git",
 default_branch="main",
 )
@pytest.fixture
def seed_symbol(graph_repo):
 """创建种子 Symbol——被其他符号调用的中心函数。"""
 return Symbol.objects.create(
 repository=graph_repo,
 name="process_data",
 symbol_type="FUNCTION",
 file_path="src/core.py",
 start_line=10,
 end_line=25,
 signature="def process_data(input: dict) -> dict",
 )
@pytest.fixture
def callee_symbol(graph_repo):
 """创建被调用者 Symbol——种子函数调用的函数。"""
 return Symbol.objects.create(
 repository=graph_repo,
 name="validate_input",
 symbol_type="FUNCTION",
 file_path="src/validators.py",
 start_line=5,
 end_line=15,
 signature="def validate_input(data: dict) -> bool",
 )
@pytest.fixture
def caller_symbol(graph_repo):
 """创建调用者 Symbol——调用种子函数的函数。"""
 return Symbol.objects.create(
 repository=graph_repo,
 name="handle_request",
 symbol_type="FUNCTION",
 file_path="src/handler.py",
 start_line=20,
 end_line=40,
 signature="def handle_request(req: Request) -> Response",
 )
@pytest.fixture
def outgoing_call_edge(seed_symbol, callee_symbol, graph_repo):
 """创建出边：seed -> callee。"""
 return CallEdge.objects.create(
 repository=graph_repo,
 caller_symbol=seed_symbol,
 callee_name="validate_input",
 call_type="DIRECT",
 line_number=15,
 )
@pytest.fixture
def incoming_call_edge(caller_symbol, seed_symbol, graph_repo):
 """创建入边：caller -> seed。"""
 return CallEdge.objects.create(
 repository=graph_repo,
 caller_symbol=caller_symbol,
 callee_name="process_data",
 call_type="DIRECT",
 line_number=30,
 )
@pytest.fixture
def second_hop_symbol(graph_repo):
 """创建 2-hop Symbol——被 callee 调用的函数。"""
 return Symbol.objects.create(
 repository=graph_repo,
 name="sanitize_string",
 symbol_type="FUNCTION",
 file_path="src/validators.py",
 start_line=20,
 end_line=28,
 signature="def sanitize_string(s: str) -> str",
 )
@pytest.fixture
def second_hop_edge(callee_symbol, second_hop_symbol, graph_repo):
 """创建 2-hop 出边：callee -> second_hop_symbol。"""
 return CallEdge.objects.create(
 repository=graph_repo,
 caller_symbol=callee_symbol,
 callee_name="sanitize_string",
 call_type="DIRECT",
 line_number=10,
 )
