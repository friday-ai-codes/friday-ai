"""``FindRelatedCodeInput`` / ``NeighborOutput`` / ``FindRelatedCodeOutput`` Pydantic 校验测试。
Phase Plan：把"三选一互斥 + hops≤2 + direction 三选一 + reason 非空"等
约束前置到 Pydantic 层，避免 Plan tool 函数体内手写 if-else 校验。
测试组：
- 互斥校验：0/2/3 个起点 → ValidationError；1 个起点 → 通过。
- Field 边界：hops / direction / limit / relation_types Literal 枚举。
- 默认值锁定：``test_defaults_combined`` 锁住 Plan 不再手填默认。
- 输出守卫：``NeighborOutput.reason`` ``min_length=1``、``line_*`` 允许 None。
per ROADMAP / / + -PLAN must_haves。
"""
from __future__ import annotations
import re
import pytest
from pydantic import ValidationError
def test_zero_anchors_raises -> None:
 """0 个起点（全 None）→ ValidationError 含 'exactly one'。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 with pytest.raises(ValidationError, match=re.compile(r"exactly one", re.IGNORECASE)):
 FindRelatedCodeInput(
 repository_id="22222222-2222-2222-2222-222222222222"
 )
def test_two_anchors_raises_file_chunk -> None:
 """file_path + chunk_id 同时给值 → ValidationError 含 'exactly one'。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 with pytest.raises(ValidationError, match=re.compile(r"exactly one", re.IGNORECASE)):
 FindRelatedCodeInput(
 file_path="src/auth.py",
 chunk_id="11111111-1111-1111-1111-111111111111",
 )
def test_two_anchors_raises_chunk_symbol -> None:
 """chunk_id + symbol_name 同时给值 → ValidationError 含 'exactly one'。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 with pytest.raises(ValidationError, match=re.compile(r"exactly one", re.IGNORECASE)):
 FindRelatedCodeInput(
 chunk_id="11111111-1111-1111-1111-111111111111",
 symbol_name="login_user",
 )
def test_three_anchors_raises -> None:
 """三个起点全给 → ValidationError 含 'exactly one'。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 with pytest.raises(ValidationError, match=re.compile(r"exactly one", re.IGNORECASE)):
 FindRelatedCodeInput(
 file_path="src/auth.py",
 chunk_id="11111111-1111-1111-1111-111111111111",
 symbol_name="login_user",
 )
def test_only_file_path_ok -> None:
 """仅 file_path → 通过；其他起点保持 None。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 obj = FindRelatedCodeInput(file_path="src/auth.py")
 assert obj.file_path == "src/auth.py"
 assert obj.chunk_id is None
 assert obj.symbol_name is None
def test_only_chunk_id_ok -> None:
 """仅 chunk_id → 通过。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 obj = FindRelatedCodeInput(chunk_id="11111111-1111-1111-1111-111111111111")
 assert obj.chunk_id == "11111111-1111-1111-1111-111111111111"
 assert obj.file_path is None
 assert obj.symbol_name is None
def test_only_symbol_name_ok -> None:
 """仅 symbol_name → 通过。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 obj = FindRelatedCodeInput(symbol_name="login_user")
 assert obj.symbol_name == "login_user"
 assert obj.file_path is None
 assert obj.chunk_id is None
def test_hops_exceeds_max_raises -> None:
 """hops=3 → ValidationError（le=2 守卫与 Phase MAX_HOPS 对齐）。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 with pytest.raises(ValidationError):
 FindRelatedCodeInput(file_path="src/auth.py", hops=3)
def test_hops_below_min_raises -> None:
 """hops=0 / hops=-1 → ValidationError（ge=1 守卫）。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 with pytest.raises(ValidationError):
 FindRelatedCodeInput(file_path="src/auth.py", hops=0)
 with pytest.raises(ValidationError):
 FindRelatedCodeInput(file_path="src/auth.py", hops=-1)
def test_hops_one_and_two_ok -> None:
 """hops=1 / hops=2 → 通过（边界内）。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 assert FindRelatedCodeInput(file_path="src/auth.py", hops=1).hops == 1
 assert FindRelatedCodeInput(file_path="src/auth.py", hops=2).hops == 2
def test_direction_invalid_raises -> None:
 """direction='sideways' → ValidationError（仅 downstream/upstream/both）。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 with pytest.raises(ValidationError):
 FindRelatedCodeInput(file_path="src/auth.py", direction="sideways")
def test_limit_below_min_raises -> None:
 """limit=0 → ValidationError（ge=1 守卫）。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 with pytest.raises(ValidationError):
 FindRelatedCodeInput(file_path="src/auth.py", limit=0)
def test_limit_above_max_raises -> None:
 """limit=101 → ValidationError（le=100 守卫）。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 with pytest.raises(ValidationError):
 FindRelatedCodeInput(file_path="src/auth.py", limit=101)
def test_relation_types_unknown_value_raises -> None:
 """relation_types 含非 6 类 Literal 值 → ValidationError。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 with pytest.raises(ValidationError):
 FindRelatedCodeInput(
 file_path="src/auth.py",
 relation_types=["INHERITS"], # type: ignore[list-item]
 )
def test_defaults_combined -> None:
 """仅给 chunk_id → 锁住所有默认字段值（防 Plan 重复填默认）。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 obj = FindRelatedCodeInput(chunk_id="11111111-1111-1111-1111-111111111111")
 assert obj.hops == 1
 assert obj.direction == "both"
 assert obj.relation_types == ["CALL", "IMPORT", "TEST_OF"]
 assert obj.limit == 20
 assert obj.repository_id is None
 assert obj.file_path is None
 assert obj.symbol_name is None
def test_chunk_id_invalid_uuid_raises -> None:
 """chunk_id 非 UUID 字符串 → ValidationError（per Phase schema 层守卫）。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 with pytest.raises(ValidationError, match=re.compile(r"valid uuid", re.IGNORECASE)):
 FindRelatedCodeInput(chunk_id="login_handler")
def test_repository_id_invalid_uuid_raises -> None:
 """repository_id 非 UUID 字符串 → ValidationError（per Phase schema 层守卫）。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 with pytest.raises(ValidationError, match=re.compile(r"valid uuid", re.IGNORECASE)):
 FindRelatedCodeInput(
 file_path="src/auth.py",
 repository_id="repo-1",
 )
def test_chunk_id_valid_uuid_ok -> None:
 """chunk_id 合法 UUID（带连字符）→ 通过。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 obj = FindRelatedCodeInput(
 chunk_id="abcdef00-0000-0000-0000-000000000000",
 repository_id="22222222-2222-2222-2222-222222222222",
 )
 assert obj.chunk_id == "abcdef00-0000-0000-0000-000000000000"
def test_extra_fields_forbidden -> None:
 """extra='forbid' → 未声明字段 → ValidationError（防 LLM 调用方塞脏字段）。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 with pytest.raises(ValidationError):
 FindRelatedCodeInput(
 file_path="src/auth.py",
 unknown_field="oops", # type: ignore[call-arg]
 )
def test_frozen_immutability -> None:
 """frozen=True → 实例化后字段不可改（防 tool 函数体内意外修改）。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeInput
 obj = FindRelatedCodeInput(file_path="src/auth.py")
 with pytest.raises(ValidationError):
 obj.hops = 2 # type: ignore[misc]
def test_neighbor_output_reason_empty_raises -> None:
 """NeighborOutput.reason='' → ValidationError（min_length=1，per ROADMAP ）。"""
 from agents.tools.schemas.find_related_code import NeighborOutput
 with pytest.raises(ValidationError):
 NeighborOutput(
 chunk_id="11111111-1111-1111-1111-111111111111",
 file_path="src/auth.py",
 line_start=10,
 line_end=20,
 edge_type="CALL",
 weight=0.8,
 reason="",
 hop=1,
 )
def test_neighbor_output_reason_nonempty_ok -> None:
 """NeighborOutput.reason 非空 → 通过。"""
 from agents.tools.schemas.find_related_code import NeighborOutput
 obj = NeighborOutput(
 chunk_id="11111111-1111-1111-1111-111111111111",
 file_path="src/auth.py",
 line_start=10,
 line_end=20,
 edge_type="CALL",
 weight=0.8,
 reason="caller of login_user",
 hop=1,
 )
 assert obj.reason == "caller of login_user"
 assert obj.edge_type == "CALL"
 assert obj.hop == 1
def test_neighbor_output_line_bounds_nullable -> None:
 """line_start / line_end 允许 None（per Phase NeighborMetadata nullable 设计）。"""
 from agents.tools.schemas.find_related_code import NeighborOutput
 obj = NeighborOutput(
 chunk_id="11111111-1111-1111-1111-111111111111",
 file_path="src/auth.py",
 line_start=None,
 line_end=None,
 edge_type="SAME_FILE",
 weight=0.4,
 reason="same file as auth.py",
 hop=1,
 )
 assert obj.line_start is None
 assert obj.line_end is None
def test_find_related_code_output_defaults -> None:
 """FindRelatedCodeOutput 默认 neighbors= / message=''；空结果用 message 解释。"""
 from agents.tools.schemas.find_related_code import FindRelatedCodeOutput
 empty = FindRelatedCodeOutput
 assert empty.neighbors ==
 assert empty.message == ""
 with_message = FindRelatedCodeOutput(message="无关联代码")
 assert with_message.neighbors ==
 assert with_message.message == "无关联代码"
def test_find_related_code_output_with_neighbors -> None:
 """FindRelatedCodeOutput 装配 NeighborOutput 列表，message 可空。"""
 from agents.tools.schemas.find_related_code import (
 FindRelatedCodeOutput,
 NeighborOutput,
 )
 neighbor = NeighborOutput(
 chunk_id="11111111-1111-1111-1111-111111111111",
 file_path="src/auth.py",
 line_start=10,
 line_end=20,
 edge_type="CALL",
 weight=0.8,
 reason="caller of login_user",
 hop=1,
 )
 out = FindRelatedCodeOutput(neighbors=[neighbor])
 assert len(out.neighbors) == 1
 assert out.neighbors[0].reason == "caller of login_user"
def test_schemas_re_exported_from_package -> None:
 """三模型均可从 ``agents.tools.schemas`` 顶层导入（per __init__.py re-export 锁）。"""
 from agents.tools.schemas import (
 FindRelatedCodeInput,
 FindRelatedCodeOutput,
 NeighborOutput,
 )
 assert FindRelatedCodeInput is not None
 assert FindRelatedCodeOutput is not None
 assert NeighborOutput is not None
