""" LocalProvider.lookup_symbols branch-aware 测试（Phase Plan）。
覆盖 Symbol 两处过滤（iexact 精确 + icontains 回退）的 branch base/overlay 合并：
1. test_lookup_base_only —— branch=None 仅返回 base 符号（branch_name=""）
2. test_lookup_feature_merges_base —— branch="feat-a" 合并 base + 本分支，不含他分支
3. test_lookup_fuzzy_respects_branch —— icontains 回退路径同样带 branch 过滤
Symbol.branch_name 语义（293/294）：base 行 ""（全分支可见），feature 行=分支名
（仅本分支可见）。lookup_symbols 用 ``branch_name__in=["", branch] if branch else [""]``。
"""
from __future__ import annotations
import pytest
from codegraph.models import Symbol
from repositories.models import Repository
from services.code_intel.local_provider import LocalProvider
async def _create_symbol(
 repository: Repository,
 *,
 name: str,
 branch_name: str,
 file_path: str,
) -> Symbol:
 """构造一个符号（start_line 固定，靠 file_path/branch 区分）。"""
 return await Symbol.objects.acreate(
 repository=repository,
 branch_name=branch_name,
 name=name,
 symbol_type=Symbol.SymbolType.FUNCTION,
 file_path=file_path,
 start_line=1,
 end_line=10,
 )
@pytest.mark.django_db(transaction=True)
async def test_lookup_base_only(repository) -> None:
 """：branch=None 仅返回 base 符号，不含任何 feature 符号。"""
 base = await _create_symbol(
 repository, name="handler", branch_name="", file_path="base.py"
 )
 await _create_symbol(
 repository, name="handler", branch_name="feat-a", file_path="feata.py"
 )
 provider = LocalProvider
 items = await provider.lookup_symbols(
 ["handler"], repository_ids=[str(repository.id)], branch_name=None
 )
 ids = {item["symbol_id"] for item in items}
 assert ids == {str(base.id)}, f"base 查询应仅含 base 符号，得到 {ids}"
@pytest.mark.django_db(transaction=True)
async def test_lookup_feature_merges_base(repository) -> None:
 """：branch=feat-a 合并 base + feat-a，不含 feat-b（跨分支不串）。"""
 base = await _create_symbol(
 repository, name="handler", branch_name="", file_path="base.py"
 )
 feat_a = await _create_symbol(
 repository, name="handler", branch_name="feat-a", file_path="feata.py"
 )
 feat_b = await _create_symbol(
 repository, name="handler", branch_name="feat-b", file_path="featb.py"
 )
 provider = LocalProvider
 items = await provider.lookup_symbols(
 ["handler"], repository_ids=[str(repository.id)], branch_name="feat-a"
 )
 ids = {item["symbol_id"] for item in items}
 assert str(base.id) in ids, "base 符号应被合并进 feature 查询"
 assert str(feat_a.id) in ids, "feat-a 自身符号应出现"
 assert str(feat_b.id) not in ids, "另一 feature 分支符号不得泄漏"
@pytest.mark.django_db(transaction=True)
async def test_lookup_fuzzy_respects_branch(repository) -> None:
 """：icontains 回退路径（无 iexact 命中时）同样带 branch 过滤。"""
 base = await _create_symbol(
 repository, name="process_payment", branch_name="", file_path="p_base.py"
 )
 feat_a = await _create_symbol(
 repository, name="process_payment", branch_name="feat-a", file_path="p_feata.py"
 )
 feat_b = await _create_symbol(
 repository, name="process_payment", branch_name="feat-b", file_path="p_featb.py"
 )
 provider = LocalProvider
 # "process" 无 iexact 命中 → 走 icontains 回退
 items = await provider.lookup_symbols(
 ["process"], repository_ids=[str(repository.id)], branch_name="feat-a"
 )
 ids = {item["symbol_id"] for item in items}
 assert str(base.id) in ids, "icontains 回退应合并 base"
 assert str(feat_a.id) in ids, "icontains 回退应含本分支"
 assert str(feat_b.id) not in ids, "icontains 回退不得泄漏他分支"
