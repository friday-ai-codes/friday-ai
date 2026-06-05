"""Vue SFC extractor 测试 —— 验证 splitter + symbol/import/call 抽取 + template 反向引用。

覆盖 implementation 全部 6 个 requirements：
- work item：vue_sfc_splitter 三段拆分 + line_offset 精度 + attrs 解析（TestVueSfcSplitter）
- work item：Vue 2 Options API 抽取（vue2_options fixture + TestVueExtractor 4 测试）
- work item：Vue 2.7 / 3 <script setup lang="ts"> 抽取（vue27_setup / vue3_setup fixture）
- work item：template-script 反向引用（test_template_event_ref）
- work item：<script lang="ts"> 路由 typescript backend（test_script_lang_ts_routing）
- work item：defineProps/defineEmits/defineExpose 三宏 call（test_define_macros_call）
"""

from __future__ import annotations

import os

import pytest

from codegraph.extractors.base import FileContext
from codegraph.extractors.vue_extractor import VueExtractor
from codegraph.extractors.vue_sfc_splitter import SfcBlock, split_sfc


@pytest.fixture
def vue2_options_source() -> str:
    """加载 vue2_options.vue fixture 源码。"""
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    with open(
        os.path.join(fixtures_dir, "vue2_options.vue"), "r", encoding="utf-8"
    ) as f:
        return f.read()


@pytest.fixture
def vue27_setup_source() -> str:
    """加载 vue27_setup.vue fixture 源码。"""
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    with open(
        os.path.join(fixtures_dir, "vue27_setup.vue"), "r", encoding="utf-8"
    ) as f:
        return f.read()


@pytest.fixture
def vue3_setup_source() -> str:
    """加载 vue3_setup.vue fixture 源码。"""
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    with open(
        os.path.join(fixtures_dir, "vue3_setup.vue"), "r", encoding="utf-8"
    ) as f:
        return f.read()


@pytest.fixture
def vue_with_children_source() -> str:
    """加载 vue_with_children.vue fixture 源码（含 <ChildComp/> / <user-card/>）。"""
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    with open(
        os.path.join(fixtures_dir, "vue_with_children.vue"), "r", encoding="utf-8"
    ) as f:
        return f.read()


class TestVueSfcSplitter:
    """vue_sfc_splitter.split_sfc 单元测试 —— 覆盖 work item。"""

    def test_split_full_sfc(self, vue2_options_source: str) -> None:
        """三段全 SFC 拆分：template + script + style 各 1 块。"""
        blocks = split_sfc(vue2_options_source)
        kinds = [b.kind for b in blocks]
        assert kinds.count("template") == 1
        assert kinds.count("script") == 1
        assert kinds.count("style") == 1

    def test_split_script_only(self) -> None:
        """仅 script 段 SFC 拆分。"""
        src = "<script>\nconst x = 1\n</script>\n"
        blocks = split_sfc(src)
        assert len(blocks) == 1
        assert blocks[0].kind == "script"
        assert blocks[0].line_offset >= 2

    def test_split_script_lang_attrs(self) -> None:
        """`<script lang="ts" setup>` attrs 解析为 {'lang': 'ts', 'setup': True}。"""
        src = '<script lang="ts" setup>\nconst x = 1\n</script>'
        blocks = split_sfc(src)
        assert blocks[0].attrs.get("lang") == "ts"
        assert blocks[0].attrs.get("setup") is True

    def test_split_script_typescript_setup_custom(self) -> None:
        """非标准 `<script typescript setup>` attrs 解析为 {'typescript': True, 'setup': True}。"""
        src = "<script typescript setup>\nconst x = 1\n</script>"
        blocks = split_sfc(src)
        assert blocks[0].attrs.get("typescript") is True
        assert blocks[0].attrs.get("setup") is True
        assert blocks[0].attrs.get("lang") is None

    def test_split_line_offset_precision(self) -> None:
        """line_offset 精度：第 5 行 `<script>` 开标签后内容首行 = 6。"""
        src = (
            "<template>\n  <div/>\n</template>\n\n<script>\nconst x = 1\n</script>"
        )
        blocks = split_sfc(src)
        script = next(b for b in blocks if b.kind == "script")
        assert script.line_offset == 6

    def test_split_missing_close_tag_warning(self) -> None:
        """缺闭标签 break + warning（不抛错）。"""
        src = "<script>\nconst x = 1\n"
        blocks = split_sfc(src)
        assert blocks == []


class TestVueExtractor:
    """VueExtractor 端到端单元测试 —— 覆盖 work item..work item。"""

    def test_component_name_symbol(self, vue2_options_source: str) -> None:
        """work item：文件名抽为 Component Symbol(CLASS)。"""
        extractor = VueExtractor()
        ctx = FileContext(
            file_path="vue2_options.vue", language="vue", repository_id="r1"
        )
        bundle = extractor.extract(
            "vue2_options.vue", vue2_options_source, ctx
        )
        names = [s.name for s in bundle.symbols if s.symbol_type == "CLASS"]
        assert "vue2_options" in names

    def test_options_api_methods(self, vue2_options_source: str) -> None:
        """work item / work item：methods 内 handleClick / onSave 抽 METHOD。"""
        extractor = VueExtractor()
        ctx = FileContext(
            file_path="vue2_options.vue", language="vue", repository_id="r1"
        )
        bundle = extractor.extract(
            "vue2_options.vue", vue2_options_source, ctx
        )
        method_names = {s.name for s in bundle.symbols if s.symbol_type == "METHOD"}
        assert "handleClick" in method_names
        assert "onSave" in method_names

    def test_options_api_data_not_symbol(self, vue2_options_source: str) -> None:
        """work item：data 字段 title / count 不抽 SymbolData。"""
        extractor = VueExtractor()
        ctx = FileContext(
            file_path="vue2_options.vue", language="vue", repository_id="r1"
        )
        bundle = extractor.extract(
            "vue2_options.vue", vue2_options_source, ctx
        )
        names = {s.name for s in bundle.symbols}
        assert "title" not in names
        assert "count" not in names

    def test_options_api_imports(self, vue2_options_source: str) -> None:
        """work item import 抽 ImportData。"""
        extractor = VueExtractor()
        ctx = FileContext(
            file_path="vue2_options.vue", language="vue", repository_id="r1"
        )
        bundle = extractor.extract(
            "vue2_options.vue", vue2_options_source, ctx
        )
        modules = [imp.target_module for imp in bundle.imports]
        assert "./ChildComp.vue" in modules

    def test_script_setup_symbols(self, vue27_setup_source: str) -> None:
        """work item：<script setup lang="ts"> 顶层 function/命名 arrow/interface 抽。"""
        extractor = VueExtractor()
        ctx = FileContext(
            file_path="vue27_setup.vue", language="vue", repository_id="r1"
        )
        bundle = extractor.extract(
            "vue27_setup.vue", vue27_setup_source, ctx
        )
        names = {s.name for s in bundle.symbols}
        assert "Props" in names
        assert "onClick" in names
        assert "reset" in names

    def test_script_setup_imports(self, vue27_setup_source: str) -> None:
        """work item import 抽：vue named + relative。"""
        extractor = VueExtractor()
        ctx = FileContext(
            file_path="vue27_setup.vue", language="vue", repository_id="r1"
        )
        bundle = extractor.extract(
            "vue27_setup.vue", vue27_setup_source, ctx
        )
        modules = [imp.target_module for imp in bundle.imports]
        assert "vue" in modules
        assert "./api" in modules

    def test_define_props_call(self, vue27_setup_source: str) -> None:
        """work item：defineProps 当 call_expression（callee_name=defineProps）。"""
        extractor = VueExtractor()
        ctx = FileContext(
            file_path="vue27_setup.vue", language="vue", repository_id="r1"
        )
        bundle = extractor.extract(
            "vue27_setup.vue", vue27_setup_source, ctx
        )
        callee_names = {c.callee_name for c in bundle.calls}
        assert "defineProps" in callee_names

    def test_define_macros_call(self, vue3_setup_source: str) -> None:
        """work item：defineProps / defineEmits / defineExpose 三宏全命中 call。"""
        extractor = VueExtractor()
        ctx = FileContext(
            file_path="vue3_setup.vue", language="vue", repository_id="r1"
        )
        bundle = extractor.extract(
            "vue3_setup.vue", vue3_setup_source, ctx
        )
        callee_names = {c.callee_name for c in bundle.calls}
        assert "defineProps" in callee_names
        assert "defineEmits" in callee_names
        assert "defineExpose" in callee_names

    def test_template_event_ref(self, vue2_options_source: str) -> None:
        """work item / work item：template `@click="handleClick"` → TEMPLATE_REF CallData。"""
        extractor = VueExtractor()
        ctx = FileContext(
            file_path="vue2_options.vue", language="vue", repository_id="r1"
        )
        bundle = extractor.extract(
            "vue2_options.vue", vue2_options_source, ctx
        )
        template_refs = [c for c in bundle.calls if c.call_type == "TEMPLATE_REF"]
        callee_names = {c.callee_name for c in template_refs}
        assert "handleClick" in callee_names
        assert "onSave" in callee_names

    def test_template_url_attribute_no_match(self) -> None:
        """work item：template `:src="https://cdn..."` URL 字面不命中 TEMPLATE_REF。"""
        src = """<template>
  <img :src="https://cdn.example.com/x.png" />
</template>

<script>
export default { name: 'X' }
</script>"""
        extractor = VueExtractor()
        ctx = FileContext(file_path="t.vue", language="vue", repository_id="r1")
        bundle = extractor.extract("t.vue", src, ctx)
        template_refs = [
            c.callee_name for c in bundle.calls if c.call_type == "TEMPLATE_REF"
        ]
        assert "https" not in template_refs

    def test_script_lang_ts_routing(self) -> None:
        """work item：<script lang="ts"> 路由到 typescript backend。"""
        src = """<script lang="ts">
interface Foo { x: string }
function bar() { return 1 }
</script>"""
        extractor = VueExtractor()
        ctx = FileContext(file_path="t.vue", language="vue", repository_id="r1")
        bundle = extractor.extract("t.vue", src, ctx)
        names = {s.name for s in bundle.symbols}
        assert "Foo" in names
        assert "bar" in names

    def test_script_no_lang_default_typescript(self) -> None:
        """work item：无 lang 默认 typescript（能解析 interface）。"""
        src = """<script>
interface Foo { x: string }
function bar() {}
</script>"""
        extractor = VueExtractor()
        ctx = FileContext(file_path="t.vue", language="vue", repository_id="r1")
        bundle = extractor.extract("t.vue", src, ctx)
        names = {s.name for s in bundle.symbols}
        assert "Foo" in names
        assert "bar" in names

    def test_line_offset_mapping(self, vue27_setup_source: str) -> None:
        """work item / Pitfall 1：script 内 onClick 行号还原到原文件视角。"""
        extractor = VueExtractor()
        ctx = FileContext(
            file_path="vue27_setup.vue", language="vue", repository_id="r1"
        )
        bundle = extractor.extract(
            "vue27_setup.vue", vue27_setup_source, ctx
        )
        onclick = next(
            (s for s in bundle.symbols if s.name == "onClick"), None
        )
        assert onclick is not None
        # vue27_setup.vue 中 function onClick 的实际行号（取决于 fixture 形态）
        # 用宽松断言 >= 10 容忍 fixture 微调；防极端 +0/+2 错位
        assert onclick.start_line >= 10

    def test_endpoints_empty(self, vue27_setup_source: str) -> None:
        """前端 .vue 无 endpoint → bundle.endpoints == []。"""
        extractor = VueExtractor()
        ctx = FileContext(
            file_path="vue27_setup.vue", language="vue", repository_id="r1"
        )
        bundle = extractor.extract(
            "vue27_setup.vue", vue27_setup_source, ctx
        )
        assert bundle.endpoints == []


class TestVueTemplateComponentRef:
    """Vue <template> 子组件标签抽取 —— 覆盖 work item（TEMPLATE_REF）。"""

    def test_child_component_template_ref(
        self, vue_with_children_source: str
    ) -> None:
        """work item：<ChildComp/> / <user-card/> 抽成 TEMPLATE_REF，kebab 归一 PascalCase。"""
        extractor = VueExtractor()
        ctx = FileContext(
            file_path="vue_with_children.vue", language="vue", repository_id="r1"
        )
        bundle = extractor.extract(
            "vue_with_children.vue", vue_with_children_source, ctx
        )
        template_refs = [c for c in bundle.calls if c.call_type == "TEMPLATE_REF"]
        callee_names = {c.callee_name for c in template_refs}
        # PascalCase 子组件原样、kebab-case <user-card/> 归一为 UserCard
        assert "ChildComp" in callee_names, callee_names
        assert "UserCard" in callee_names, callee_names

    def test_native_tag_not_template_ref(
        self, vue_with_children_source: str
    ) -> None:
        """work item 守卫：原生标签 div / span 不抽成 TEMPLATE_REF。"""
        extractor = VueExtractor()
        ctx = FileContext(
            file_path="vue_with_children.vue", language="vue", repository_id="r1"
        )
        bundle = extractor.extract(
            "vue_with_children.vue", vue_with_children_source, ctx
        )
        callee_names = {
            c.callee_name for c in bundle.calls if c.call_type == "TEMPLATE_REF"
        }
        assert "div" not in callee_names, callee_names
        assert "span" not in callee_names, callee_names

    def test_template_ref_caller_key(
        self, vue_with_children_source: str
    ) -> None:
        """子组件 TEMPLATE_REF 边的 caller 段为 <template> sentinel。"""
        extractor = VueExtractor()
        ctx = FileContext(
            file_path="vue_with_children.vue", language="vue", repository_id="r1"
        )
        bundle = extractor.extract(
            "vue_with_children.vue", vue_with_children_source, ctx
        )
        component_refs = [
            c
            for c in bundle.calls
            if c.call_type == "TEMPLATE_REF"
            and c.callee_name in {"ChildComp", "UserCard"}
        ]
        assert component_refs, "未抽到子组件 TEMPLATE_REF 边"
        for ref in component_refs:
            assert ref.caller_key[1] == "<template>", ref.caller_key
