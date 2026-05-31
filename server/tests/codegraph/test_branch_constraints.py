"""Phase Plan（ 约束部分 + ）：codegraph 约束 + 双写测试。
覆盖：Symbol/ApiWrapper unique_together 含 branch_name 自省 + base/feature 双写无
IntegrityError + 同 branch_name 重复写仍 IntegrityError（证明约束生效而非被绕过）。
"""
from __future__ import annotations
import pytest
from django.db import IntegrityError, transaction
from codegraph.models import ApiWrapper, Symbol
from repositories.models import Repository
def test_symbol_unique_together_contains_branch_name -> None:
 """：Symbol unique_together 含 branch_name。"""
 assert (
 "repository",
 "branch_name",
 "file_path",
 "name",
 "start_line",
 ) in Symbol._meta.unique_together
def test_apiwrapper_unique_together_contains_branch_name -> None:
 """：ApiWrapper unique_together 含 branch_name。"""
 assert (
 "repository",
 "branch_name",
 "file_path",
 "function_symbol",
 ) in ApiWrapper._meta.unique_together
@pytest.mark.django_db
def test_symbol_base_feature_dual_write_no_integrity_error -> None:
 """：base 与 feature 同业务键双写均成功；同 branch_name 重复写抛 IntegrityError。"""
 repo = Repository.objects.create(
 name="dual-write-repo",
 git_url="https://example.com/dual.git",
 default_branch="main",
 )
 common = dict(
 repository=repo, file_path="src/a.py", name="f", start_line=1, end_line=2,
 symbol_type="FUNCTION",
 )
 Symbol.objects.create(branch_name="", **common)
 # 不同 branch_name 同业务键 → 成功（分支隔离生效）。
 Symbol.objects.create(branch_name="feature/x", **common)
 # 与 base 完全相同（含 branch_name=""）→ 撞 unique 约束。
 with pytest.raises(IntegrityError):
 with transaction.atomic:
 Symbol.objects.create(branch_name="", **common)
