"""`code_relations.constants` 暴露 Phase 编排器共享常量（per //）。
覆盖 6 条 assertion：
- MAX_HOPS == 2 / TOP_NEIGHBORS_PER_HOP1 == 10 / TOP_NEIGHBORS_PER_HOP2 == 50 字面值
- 类型均为 `int`
- 三常量均**不通过 `env.*` 读取**（这些是 ROADMAP / Phase 决策硬约束，
 runtime 不允许通过环境变量绕开 hops 上限或邻居裁剪量）
"""
from __future__ import annotations
import re
from pathlib import Path
from code_relations import constants
def test_max_hops_literal_value -> None:
 assert constants.MAX_HOPS == 2
 assert isinstance(constants.MAX_HOPS, int)
def test_top_neighbors_per_hop1_literal_value -> None:
 assert constants.TOP_NEIGHBORS_PER_HOP1 == 10
 assert isinstance(constants.TOP_NEIGHBORS_PER_HOP1, int)
def test_top_neighbors_per_hop2_literal_value -> None:
 assert constants.TOP_NEIGHBORS_PER_HOP2 == 50
 assert isinstance(constants.TOP_NEIGHBORS_PER_HOP2, int)
def test_constants_not_env_derived -> None:
 """硬约束：3 个常量不允许从 env / os.environ 读取（否则 hops 守卫可被绕过）。
 实现方式：扫描 `constants.py` 源码，断言 MAX_HOPS / TOP_NEIGHBORS_PER_HOP1 /
 TOP_NEIGHBORS_PER_HOP2 三行 RHS 是纯字面整数赋值，不出现 `env`/`os.environ`。
 """
 source = Path(constants.__file__).read_text(encoding="utf-8")
 for name, expected in (
 ("MAX_HOPS", 2),
 ("TOP_NEIGHBORS_PER_HOP1", 10),
 ("TOP_NEIGHBORS_PER_HOP2", 50),
 ):
 match = re.search(
 rf"^{name}\s*:\s*int\s*=\s*(.+?)$",
 source,
 re.MULTILINE,
 )
 assert match is not None, f"{name} 必须以 `NAME: int = LITERAL` 形式赋值"
 rhs = match.group(1).strip
 assert rhs == str(expected), (
 f"{name} 赋值必须为字面值 {expected}（实际 `{rhs}`）；"
 "禁止通过 env / os.environ 读取"
 )
 assert "env(" not in source.split("MAX_HOPS", 1)[1][:500], (
 "MAX_HOPS 周边代码段不允许出现 env(...) 调用"
 )
