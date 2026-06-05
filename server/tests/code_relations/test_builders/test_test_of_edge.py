"""TestOfEdgeBuilder 测试（per initial implementation contract/17/18）。"""

from __future__ import annotations

import uuid

import pytest
from asgiref.sync import sync_to_async

from code_relations.builders.test_of_edge import TestOfEdgeBuilder
from code_relations.models import ChunkRegistry, EdgeType
from codegraph.models import ImportEdge as CodegraphImportEdge


@sync_to_async
def _make_chunk(repository, file_path: str) -> ChunkRegistry:
    return ChunkRegistry.objects.create(
        chunk_id=uuid.uuid4(),
        content_hash="x" * 64,
        repository=repository,
        file_path=file_path,
        chunk_index=0,
    )


@sync_to_async
def _make_import(repository, source_file: str, target_module: str) -> None:
    CodegraphImportEdge.objects.create(
        repository=repository,
        source_file=source_file,
        target_module=target_module,
    )


@pytest.mark.django_db(transaction=True)
async def test_four_regex_each_named_only(repository) -> None:
    """4 测试文件配 4 个 src，无 import 验证 → weight=0.6。"""
    pairs = [
        ("tests/test_foo.py", "foo.py", "py_test_prefix"),
        ("tests/bar_test.py", "bar.py", "py_test_suffix"),
        ("src/utils.test.ts", "src/utils.ts", "jsts_test_infix"),
        ("__tests__/Button.tsx", "Button.tsx", "jsts_tests_dir"),
    ]
    for test_fp, src_fp, _rid in pairs:
        await _make_chunk(repository, test_fp)
        await _make_chunk(repository, src_fp)
    edges = await TestOfEdgeBuilder().build(repository, [])
    assert len(edges) == 4
    for e in edges:
        assert e.edge_type == EdgeType.TEST_OF
        assert e.weight == 0.6
        assert e.metadata["match_kind"] == "naming_only"


@pytest.mark.django_db(transaction=True)
async def test_naming_plus_import_weight_08(repository) -> None:
    """命名匹配 + ImportEdge 验证 → weight=0.8。"""
    await _make_chunk(repository, "tests/test_foo.py")
    await _make_chunk(repository, "foo.py")
    # test 文件 import 候选 src（target_module 形如 "foo"）
    await _make_import(repository, "tests/test_foo.py", "foo")
    edges = await TestOfEdgeBuilder().build(repository, [])
    assert len(edges) == 1
    assert edges[0].weight == 0.8
    assert edges[0].metadata["match_kind"] == "naming_and_import"


@pytest.mark.django_db(transaction=True)
async def test_unsupported_language_skipped(repository) -> None:
    """Go 文件触发 contract 跨语言 skip。"""
    await _make_chunk(repository, "main.go")
    edges = await TestOfEdgeBuilder().build(repository, [])
    assert edges == []


@pytest.mark.django_db(transaction=True)
async def test_no_candidate_src_in_registry(repository) -> None:
    """tests/test_orphan.py 但无 orphan.py → 不生成边。"""
    await _make_chunk(repository, "tests/test_orphan.py")
    edges = await TestOfEdgeBuilder().build(repository, [])
    assert edges == []


@pytest.mark.django_db(transaction=True)
async def test_non_test_file_no_edge(repository) -> None:
    """README.md 非 test 文件 + Cargo.toml 非 test 文件 → 不生成边。"""
    await _make_chunk(repository, "README.md")
    await _make_chunk(repository, "Cargo.toml")
    edges = await TestOfEdgeBuilder().build(repository, [])
    assert edges == []


@pytest.mark.django_db(transaction=True)
async def test_regex_id_metadata(repository) -> None:
    """4 regex 各配套，metadata.regex_id 应分别命中 4 个 id。"""
    await _make_chunk(repository, "tests/test_a.py")
    await _make_chunk(repository, "a.py")
    await _make_chunk(repository, "tests/b_test.py")
    await _make_chunk(repository, "b.py")
    await _make_chunk(repository, "src/c.test.js")
    await _make_chunk(repository, "src/c.js")
    await _make_chunk(repository, "__tests__/D.tsx")
    await _make_chunk(repository, "D.tsx")
    edges = await TestOfEdgeBuilder().build(repository, [])
    rid_set = {e.metadata["regex_id"] for e in edges}
    assert rid_set == {"py_test_prefix", "py_test_suffix", "jsts_test_infix", "jsts_tests_dir"}


@pytest.mark.django_db(transaction=True)
async def test_endswith_no_false_match(repository) -> None:
    """work item 回归：candidate ``auth.py`` 不得匹配 ``xauth.py`` / ``oauth.py``。"""
    await _make_chunk(repository, "tests/test_auth.py")
    await _make_chunk(repository, "pkg/auth.py")
    await _make_chunk(repository, "lib/xauth.py")
    await _make_chunk(repository, "lib/oauth.py")

    edges = await TestOfEdgeBuilder().build(repository, [])
    assert len(edges) == 1
    assert edges[0].metadata["src_file"] == "pkg/auth.py"


# =============================================================================
# initial implementation / work item：Go / Vue 多语言 regex 扩展
# =============================================================================


@pytest.mark.django_db(transaction=True)
async def test_go_test_suffix_regex(repository) -> None:
    """initial implementation：handlers/user_test.go → handlers/user.go 命中 go_test_suffix。"""
    await _make_chunk(repository, "handlers/user_test.go")
    await _make_chunk(repository, "handlers/user.go")
    edges = await TestOfEdgeBuilder().build(repository, [])
    assert len(edges) == 1
    assert edges[0].metadata["regex_id"] == "go_test_suffix"
    assert edges[0].metadata["test_file"] == "handlers/user_test.go"
    assert edges[0].metadata["src_file"] == "handlers/user.go"


@pytest.mark.django_db(transaction=True)
async def test_vue_spec_infix_regex(repository) -> None:
    """initial implementation：components/Button.spec.vue → components/Button.vue 命中 vue_test_infix。"""
    await _make_chunk(repository, "components/Button.spec.vue")
    await _make_chunk(repository, "components/Button.vue")
    edges = await TestOfEdgeBuilder().build(repository, [])
    assert len(edges) == 1
    assert edges[0].metadata["regex_id"] == "vue_test_infix"
    assert edges[0].metadata["src_file"] == "components/Button.vue"


@pytest.mark.django_db(transaction=True)
async def test_vue_test_infix_regex(repository) -> None:
    """initial implementation：components/Card.test.vue → components/Card.vue 命中 vue_test_infix。"""
    await _make_chunk(repository, "components/Card.test.vue")
    await _make_chunk(repository, "components/Card.vue")
    edges = await TestOfEdgeBuilder().build(repository, [])
    assert len(edges) == 1
    assert edges[0].metadata["regex_id"] == "vue_test_infix"


@pytest.mark.django_db(transaction=True)
async def test_cross_language_no_false_match(repository) -> None:
    """initial implementation 守门：foo_test.go 仅命中 foo.go，不会误匹配 foo.vue / foo.py。"""
    await _make_chunk(repository, "foo_test.go")
    await _make_chunk(repository, "foo.vue")
    await _make_chunk(repository, "foo.py")
    edges = await TestOfEdgeBuilder().build(repository, [])
    # foo.go 不在 registry → 0 边（go_test_suffix 仅生成 foo.go 候选）
    assert edges == []


# =============================================================================
# initial implementation-01：6 regex_id 的 parametrize 矩阵守门
# =============================================================================


@pytest.mark.parametrize(
    "test_file,src_file,expected_regex_id",
    [
        ("tests/test_foo.py", "foo.py", "py_test_prefix"),
        ("tests/bar_test.py", "bar.py", "py_test_suffix"),
        ("src/utils.test.ts", "src/utils.ts", "jsts_test_infix"),
        ("__tests__/Button.tsx", "Button.tsx", "jsts_tests_dir"),
        ("handlers/user_test.go", "handlers/user.go", "go_test_suffix"),
        ("components/Button.spec.vue", "components/Button.vue", "vue_test_infix"),
    ],
)
@pytest.mark.django_db(transaction=True)
async def test_test_of_edge_multi_language_regex(
    repository, test_file: str, src_file: str, expected_regex_id: str
) -> None:
    """work item-01：6 个 regex_id（4 既有 + 2 新增）单一 parametrize 矩阵守门。"""
    await _make_chunk(repository, test_file)
    await _make_chunk(repository, src_file)
    edges = await TestOfEdgeBuilder().build(repository, [])
    assert len(edges) == 1
    assert edges[0].metadata["regex_id"] == expected_regex_id
    assert edges[0].metadata["test_file"] == test_file
    assert edges[0].metadata["src_file"] == src_file
