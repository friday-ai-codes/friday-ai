"""TestOfEdgeBuilder：test 文件 → src 文件 命名 + import 双启发式（per implementation contract/17/18）。"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

import structlog
from asgiref.sync import sync_to_async
from django.db.models import Q

from code_relations.builders.base import BaseEdgeBuilder
from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType

if TYPE_CHECKING:
    from repositories.models import Repository

logger = structlog.get_logger(__name__)

__all__ = ["TestOfEdgeBuilder"]

_SUPPORTED_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".vue")  # contract + implementation

# contract regex（编译一次，模块级常量）
_PY_TEST_PREFIX = re.compile(r"(?:.+/)?tests?/.*test_(\w+)\.py$")
_PY_TEST_SUFFIX = re.compile(r"(?:.+/)?tests?/(.*?)_test\.py$")
_JSTS_TEST_INFIX = re.compile(r"(.+)\.(test|spec)\.(t|j)sx?$")
_JSTS_TESTS_DIR = re.compile(r"__tests__/(\w+)\.(t|j)sx?$")
# implementation 新增 Go / Vue test 命名 regex
_GO_TEST_SUFFIX = re.compile(r"(?:.+/)?(.+?)_test\.go$")
_VUE_TEST_INFIX = re.compile(r"(?:.+/)?(.+?)\.(test|spec)\.vue$")


def _candidate_src_files(test_file: str) -> list[tuple[str, str]]:
    """返回 [(候选 src 文件名, regex_id)]；命中则非空。"""
    candidates: list[tuple[str, str]] = []
    m = _PY_TEST_PREFIX.search(test_file)
    if m:
        stem = m.group(1)
        candidates.append((f"{stem}.py", "py_test_prefix"))
        candidates.append((f"{stem}/__init__.py", "py_test_prefix_pkg"))
    m = _PY_TEST_SUFFIX.search(test_file)
    if m:
        stem = m.group(1)
        candidates.append((f"{stem}.py", "py_test_suffix"))
    m = _JSTS_TEST_INFIX.search(test_file)
    if m:
        # group(3) 仅捕获 't' 或 'j'（regex `(t|j)sx?` 的字符类），需补回 `s`(x?) 完整扩展
        base, _, lang = m.group(1), m.group(2), m.group(3)
        for ext_suffix in ("s", "sx"):
            candidates.append((f"{base}.{lang}{ext_suffix}", "jsts_test_infix"))
    m = _JSTS_TESTS_DIR.search(test_file)
    if m:
        base, lang = m.group(1), m.group(2)
        for ext_suffix in ("s", "sx"):
            candidates.append((f"{base}.{lang}{ext_suffix}", "jsts_tests_dir"))
    # implementation 新增 dispatch
    m = _GO_TEST_SUFFIX.search(test_file)
    if m:
        stem = m.group(1)
        candidates.append((f"{stem}.go", "go_test_suffix"))
    m = _VUE_TEST_INFIX.search(test_file)
    if m:
        stem = m.group(1)
        candidates.append((f"{stem}.vue", "vue_test_infix"))
    return candidates


class TestOfEdgeBuilder(BaseEdgeBuilder):
    """test → src TEST_OF 边（命名 + ImportEdge 双启发式 per contract）。"""

    edge_type_label: str = "TestOfEdge"

    async def build(
        self,
        repository: "Repository",
        dirty_chunk_ids: list[uuid.UUID],
        *,
        branch_name: str = "",
    ) -> list[ChunkEdge]:
        # work item 全扫策略（per context contract）：本 phase 接受全仓 ChunkRegistry
        # 扫描所有 file_path 重建 TEST_OF 边集；dirty_chunk_ids 暂未用于过滤。
        # implementation 应改造为仅处理 dirty 涉及的 test 文件。
        del dirty_chunk_ids  # noqa: F841 — phase 全扫策略，implementation 增量化

        from codegraph.models import ImportEdge as CodegraphImportEdge

        @sync_to_async
        def _list_test_files() -> list[str]:
            return list(
                ChunkRegistry.objects.filter(
                    repository_id=repository.id, branch_name=branch_name
                )
                .values_list("file_path", flat=True)
                .distinct()
            )

        test_files = await _list_test_files()

        edges: list[ChunkEdge] = []
        unsupported_skipped = 0

        first_chunk_cache: dict[str, uuid.UUID | None] = {}

        async def _first_chunk_id(file_path: str) -> uuid.UUID | None:
            if file_path in first_chunk_cache:
                return first_chunk_cache[file_path]
            obj = await sync_to_async(
                ChunkRegistry.objects.filter(
                    repository_id=repository.id,
                    file_path=file_path,
                    chunk_index=0,
                    branch_name=branch_name,
                ).first
            )()
            cid = obj.chunk_id if obj is not None else None
            first_chunk_cache[file_path] = cid
            return cid

        import_cache: dict[str, set[str]] = {}

        async def _imports_for(test_file: str) -> set[str]:
            if test_file in import_cache:
                return import_cache[test_file]

            @sync_to_async
            def _q() -> set[str]:
                return set(
                    CodegraphImportEdge.objects.filter(
                        repository_id=repository.id,
                        source_file=test_file,
                        branch_name=branch_name,
                    ).values_list("target_module", flat=True)
                )

            modules = await _q()
            import_cache[test_file] = modules
            return modules

        async def _file_is_imported(test_file: str, candidate_src: str) -> bool:
            modules = await _imports_for(test_file)
            if candidate_src in modules:
                return True
            stem = candidate_src.rsplit(".", 1)[0]
            module_form = stem.replace("/", ".")
            return module_form in modules

        @sync_to_async
        def _find_candidate(
            candidate: str, exclude_file: str
        ) -> "ChunkRegistry | None":
            """endswith 加 ``/`` 锚定避免 ``auth.py`` 误匹配
            ``xauth.py``；helper 提到 build 顶层只装饰一次（替代每次循环
            ``@sync_to_async`` 重新构造 ThreadSensitive 调度器引用）。

            排除 test_file 自身：避免 endswith 把 tests/test_x.py 自匹配为
            candidate ``x.py`` 的伪 self-loop TestOf 边。
            """
            anchored = f"/{candidate}"
            return (
                ChunkRegistry.objects.filter(
                    repository_id=repository.id, branch_name=branch_name
                )
                .filter(
                    Q(file_path=candidate) | Q(file_path__endswith=anchored)
                )
                .exclude(file_path=exclude_file)
                .first()
            )

        for test_file in test_files:
            if not test_file.endswith(_SUPPORTED_EXTENSIONS):
                unsupported_skipped += 1
                logger.debug(
                    "test_of_unsupported_language",
                    repository_id=str(repository.id),
                    file_path=test_file,
                )
                continue

            candidates = _candidate_src_files(test_file)
            if not candidates:
                continue

            test_cid = await _first_chunk_id(test_file)
            if test_cid is None:
                continue

            matched_src: tuple[str, str] | None = None
            for candidate, regex_id in candidates:
                obj = await _find_candidate(candidate, test_file)
                if obj is not None:
                    matched_src = (obj.file_path, regex_id)
                    break

            if matched_src is None:
                continue

            src_file, regex_id = matched_src
            src_cid = await _first_chunk_id(src_file)
            if src_cid is None:
                continue

            imported = await _file_is_imported(test_file, src_file)
            weight = 0.8 if imported else 0.6
            match_kind = "naming_and_import" if imported else "naming_only"

            edges.append(
                ChunkEdge(
                    source_chunk_id=test_cid,
                    target_chunk_id=src_cid,
                    edge_type=EdgeType.TEST_OF,
                    weight=weight,
                    metadata={
                        "test_file": test_file,
                        "src_file": src_file,
                        "match_kind": match_kind,
                        "regex_id": regex_id,
                    },
                    repository=repository,
                    branch_name=branch_name,
                )
            )

        logger.info(
            "test_of_edge_build_complete",
            repository_id=str(repository.id),
            edges_built=len(edges),
            unsupported_skipped=unsupported_skipped,
        )
        return edges
