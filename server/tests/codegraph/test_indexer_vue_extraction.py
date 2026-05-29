"""端到端：`IndexerService._extract_and_write_graph` 把 `.vue` SFC 抽进符号图。
回归守护：此前 `.vue` 在 indexer 语言检测处被静默跳过（`_EXT_LANG_MAP` 缺 vue +
`TREESITTER_LANGUAGES` 守卫），导致 `codegraph_symbol` 里没有任何 `.vue` 符号，
`find_related_code` 无法从 Vue 组件起点游走。本测试锁住 vue → VueExtractor 接线：
组件 CLASS 符号 + `<script setup>` 内的函数符号 + import 边都应入库，且 file_path
为仓库相对路径（不含临时 clone 前缀）。
"""
from __future__ import annotations
import pytest
from services.indexer import IndexerService
@pytest.mark.django_db(transaction=True)
async def test_extract_and_write_graph_indexes_vue_symbols(
 repository, tmp_path, settings
) -> None:
 settings.ENABLE_CODEGRAPH = True
 vue_dir = tmp_path / "src" / "components" / "Banner"
 vue_dir.mkdir(parents=True)
 rel = "src/components/Banner/index.vue"
 (vue_dir / "index.vue").write_text(
 "<template>\n"
 ' <div @click="handleClick">{{ title }}</div>\n'
 "</template>\n"
 '<script setup lang="ts">\n'
 "import { ref } from 'vue'\n"
 "import Foo from './Foo.vue'\n"
 "const title = ref('hi')\n"
 "function handleClick: typeof Foo {\n"
 " return Foo\n"
 "}\n"
 "</script>\n",
 encoding="utf-8",
 )
 idx = IndexerService(str(repository.id))
 stats = await idx._extract_and_write_graph(
 repo_path=str(tmp_path),
 file_paths=[rel],
 repository_id=str(repository.id),
 )
 assert stats.get("files_processed", 0) >= 1
 from codegraph.models import ImportEdge, Symbol
 syms = [
 s
 async for s in Symbol.objects.filter(
 repository_id=repository.id, file_path=rel
 )
 ]
 names = {s.name for s in syms}
 # <script setup> 内的函数符号被抽取（关键能力：Vue 组件入符号图）
 assert "handleClick" in names, f"expected handleClick symbol, got {names}"
 # 至少含组件级 CLASS 符号 + 脚本符号
 assert len(syms) >= 2
 # file_path 为仓库相对路径，不含 /var/folders 临时 clone 前缀
 assert all(s.file_path == rel for s in syms)
 assert all(not s.file_path.startswith("/") for s in syms)
 # import 边被抽取（含对 .vue 组件的相对导入）
 imports = [
 i
 async for i in ImportEdge.objects.filter(
 repository_id=repository.id, source_file=rel
 )
 ]
 targets = {(i.target_module or "") for i in imports}
 assert any("Foo.vue" in t for t in targets), f"expected Foo.vue import, got {targets}"
@pytest.mark.django_db(transaction=True)
async def test_detect_language_recognizes_vue -> None:
 """`.vue` 扩展名映射到 'vue' 语言（接线前缺失，导致图谱轨跳过）。"""
 assert IndexerService._detect_language_from_path("a/b/Foo.vue") == "vue"
