"""GraphExpansionService 单元测试 —— + 。"""
import pytest
from asgiref.sync import sync_to_async
from codegraph.models import CallEdge, Symbol
from codegraph.services.graph_expansion import GraphExpansionService
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_expand_one_hop_outgoing(
 seed_symbol, callee_symbol, outgoing_call_edge,
):
 """: 1-hop 出边正确返回被调用者。"""
 result = await GraphExpansionService.expand(seed_symbol)
 assert len(result["nodes"]) > 0
 callee_ids = [
 str(n["symbol"].id) for n in result["nodes"]
 if n["relationship"] == "callee"
 ]
 assert str(callee_symbol.id) in callee_ids
 # 验证 depth
 callee_node = next(
 n for n in result["nodes"] if n["relationship"] == "callee"
 )
 assert callee_node["depth"] == 1
 # 验证 edges
 assert len(result["edges"]) > 0
 assert result["edges"][0]["call_type"] == "DIRECT"
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_expand_one_hop_incoming(
 seed_symbol, caller_symbol, incoming_call_edge,
):
 """: 1-hop 入边正确返回调用者。"""
 result = await GraphExpansionService.expand(seed_symbol)
 caller_ids = [
 str(n["symbol"].id) for n in result["nodes"]
 if n["relationship"] == "caller"
 ]
 assert str(caller_symbol.id) in caller_ids
 caller_node = next(
 n for n in result["nodes"] if n["relationship"] == "caller"
 )
 assert caller_node["depth"] == 1
 # 验证 edge source/target 语义
 edge = next(
 e for e in result["edges"]
 if str(caller_symbol.id) == e["source"]
 )
 assert edge["target"] == str(seed_symbol.id)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_expand_two_hop(
 seed_symbol, callee_symbol, second_hop_symbol,
 outgoing_call_edge, second_hop_edge,
):
 """: 2-hop 扩展返回间接关系。"""
 result = await GraphExpansionService.expand(seed_symbol)
 # 验证 2-hop 节点存在
 depth2_nodes = [n for n in result["nodes"] if n["depth"] == 2]
 assert len(depth2_nodes) > 0
 depth2_ids = [str(n["symbol"].id) for n in depth2_nodes]
 assert str(second_hop_symbol.id) in depth2_ids
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_dedup_shortest_depth(graph_repo, seed_symbol):
 """: 同一符号在 1-hop 和 2-hop 都出现时保留最短 depth (1 > 2)。
 构造场景：symbol_a 既是 seed 的直接调用者(1-hop)，
 又通过另一个中间符号间接关联(2-hop)。
 验证去重后只保留 depth=1。
 """
 # 创建一个中间符号
 middle = await sync_to_async(Symbol.objects.create)(
 repository=graph_repo,
 name="middle_func",
 symbol_type="FUNCTION",
 file_path="src/middle.py",
 start_line=1,
 end_line=10,
 signature="def middle_func: pass",
 )
 # 创建直接调用者（1-hop 入边：direct_caller -> seed）
 direct_caller = await sync_to_async(Symbol.objects.create)(
 repository=graph_repo,
 name="direct_caller",
 symbol_type="FUNCTION",
 file_path="src/direct.py",
 start_line=1,
 end_line=10,
 signature="def direct_caller: pass",
 )
 await sync_to_async(CallEdge.objects.create)(
 repository=graph_repo,
 caller_symbol=direct_caller,
 callee_name=seed_symbol.name,
 call_type="DIRECT",
 line_number=5,
 )
 # 创建 2-hop 路径：direct_caller -> middle -> seed
 await sync_to_async(CallEdge.objects.create)(
 repository=graph_repo,
 caller_symbol=direct_caller,
 callee_name=middle.name,
 call_type="DIRECT",
 line_number=3,
 )
 await sync_to_async(CallEdge.objects.create)(
 repository=graph_repo,
 caller_symbol=middle,
 callee_name=seed_symbol.name,
 call_type="DIRECT",
 line_number=7,
 )
 result = await GraphExpansionService.expand(seed_symbol)
 # direct_caller 应仅出现一次，且 depth=1（不是 depth=2）
 dc_nodes = [
 n for n in result["nodes"]
 if str(n["symbol"].id) == str(direct_caller.id)
 ]
 assert len(dc_nodes) == 1, f"Expected 1 node for direct_caller, got {len(dc_nodes)}"
 assert dc_nodes[0]["depth"] == 1
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_max_symbols_per_hop_and_total(graph_repo, seed_symbol):
 """: 上限控制——每 hop ≤ 20 符号，总 ≤ 50。
 创建 25 个 1-hop 调用者，验证截断到 20。
 """
 symbols =
 for i in range(25):
 sym = await sync_to_async(Symbol.objects.create)(
 repository=graph_repo,
 name=f"caller_{i}",
 symbol_type="FUNCTION",
 file_path=f"src/caller_{i}.py",
 start_line=1,
 end_line=5,
 signature=f"def caller_{i}: pass",
 )
 await sync_to_async(CallEdge.objects.create)(
 repository=graph_repo,
 caller_symbol=sym,
 callee_name=seed_symbol.name,
 call_type="DIRECT",
 line_number=3,
 )
 symbols.append(sym)
 result = await GraphExpansionService.expand(
 seed_symbol, max_symbols_per_hop=20, max_total=50,
 )
 # 节点数应 ≤ 20（含种子自身不计入 nodes）
 assert len(result["nodes"]) <= 20
 # 总数 ≤ 50
 assert len(result["nodes"]) <= 50
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_return_structure(seed_symbol, callee_symbol, outgoing_call_edge):
 """: 返回值结构包含 seed_symbol/nodes/edges 字段。"""
 result = await GraphExpansionService.expand(seed_symbol)
 assert "seed_symbol" in result
 assert result["seed_symbol"].id == seed_symbol.id
 assert "nodes" in result
 assert isinstance(result["nodes"], list)
 assert "edges" in result
 assert isinstance(result["edges"], list)
 # 验证 node 结构
 if result["nodes"]:
 node = result["nodes"][0]
 assert "symbol" in node
 assert "depth" in node
 assert "relationship" in node
 assert node["relationship"] in ("caller", "callee")
 assert node["depth"] in (1, 2)
 # 验证 edge 结构
 if result["edges"]:
 edge = result["edges"][0]
 assert "source" in edge
 assert "target" in edge
 assert "call_type" in edge
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_no_call_relationships(seed_symbol):
 """: 无调用关系时返回空结构。"""
 result = await GraphExpansionService.expand(seed_symbol)
 assert result["seed_symbol"].id == seed_symbol.id
 assert result["nodes"] ==
 assert result["edges"] ==
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_expand_ignores_module_level_incoming_edge(graph_repo, seed_symbol):
 """Phase：caller_symbol=NULL 的模块级入边被排除，expand 不崩且不产模块级 caller 节点。
 构造一条模块级入边（caller_symbol=None, caller_file="m.py", callee_name=seed.name），
 断言 expand 不抛异常且返回 nodes 中无 caller 节点（模块级 caller 无对应 Symbol，被过滤）。
 """
 await sync_to_async(CallEdge.objects.create)(
 repository=graph_repo,
 caller_symbol=None,
 caller_file="m.py",
 callee_name=seed_symbol.name,
 call_type="DIRECT",
 line_number=1,
 )
 # 不抛异常（核心回归断言：NULL caller 不再 None.id 崩溃）
 result = await GraphExpansionService.expand(seed_symbol)
 # 模块级入边被过滤，无悬空 caller 节点
 caller_nodes = [n for n in result["nodes"] if n["relationship"] == "caller"]
 assert caller_nodes ==
 assert result["seed_symbol"].id == seed_symbol.id
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_expand_module_level_mixed_with_real_caller(
 graph_repo, seed_symbol, caller_symbol, incoming_call_edge,
):
 """Phase：模块级入边与真实文件内入边并存时，仅真实 caller 进 DAG。"""
 await sync_to_async(CallEdge.objects.create)(
 repository=graph_repo,
 caller_symbol=None,
 caller_file="m.py",
 callee_name=seed_symbol.name,
 call_type="DIRECT",
 line_number=1,
 )
 result = await GraphExpansionService.expand(seed_symbol)
 caller_ids = [
 str(n["symbol"].id) for n in result["nodes"]
 if n["relationship"] == "caller"
 ]
 # 真实 caller 在；模块级边不产额外节点
 assert caller_ids == [str(caller_symbol.id)]
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_seed_symbol_not_found(graph_repo):
 """: 种子 Symbol 不存在时优雅处理。
 使用已删除/不存在的 Symbol ID 场景——传入一个未持久化的 Symbol。
 服务应优雅处理（无 crash），返回空结果或抛出明确的 ValueError。
 """
 unsaved = Symbol(
 repository=graph_repo,
 name="nonexistent",
 symbol_type="FUNCTION",
 file_path="src/ghost.py",
 start_line=1,
 end_line=5,
 )
 # 未持久化的 Symbol 没有有效的 outgoing_calls，应返回空结果
 try:
 result = await GraphExpansionService.expand(unsaved)
 # 如果 expand 接受了未持久化的 Symbol，应返回空结果
 assert result["nodes"] ==
 except ValueError:
 # 如果 expand 拒绝未持久化的 Symbol，也是可接受的
 pass
