<script setup lang="ts">
/**
 * 结构化 JSON 的单个节点（递归）。对象 / 数组渲染为可折叠分支，标量按类型着色。
 * 在 <script setup> 中组件可用文件名 <JsonNode> 自引用实现递归。
 */
const props = withDefaults(defineProps<{
 nodeKey?: string | number
 value: unknown
 depth?: number
}>, { depth: 0 })
const valueType = computed<'null' | 'array' | 'object' | 'string' | 'number' | 'boolean' | 'undefined'>( => {
 const v = props.value
 if (v === null)
 return 'null'
 if (Array.isArray(v))
 return 'array'
 if (typeof v === 'object')
 return 'object'
 return typeof v as 'string' | 'number' | 'boolean' | 'undefined'
})
const isBranch = computed( => valueType.value === 'object' || valueType.value === 'array')
const entries = computed<Array<[string | number, unknown]>>( => {
 if (valueType.value === 'array')
 return (props.value as unknown).map((v, i) => [i, v])
 if (valueType.value === 'object')
 return Object.entries(props.value as Record<string, unknown>)
 return
})
const isEmpty = computed( => isBranch.value && entries.value.length === 0)
// 默认展开浅层（depth < 2），深层默认收起避免一进来就铺满
const expanded = ref((props.depth ?? 0) < 2)
const countLabel = computed( => {
 if (valueType.value === 'array')
 return `${entries.value.length}`
 if (valueType.value === 'object')
 return `${entries.value.length}`
 return ''
})
const displayValue = computed( => {
 const v = props.value
 if (v === null)
 return 'null'
 if (typeof v === 'string')
 return v
 return String(v)
})
function toggle {
 if (isBranch.value && !isEmpty.value)
 expanded.value = !expanded.value
}
</script>
<template>
 <div class="json-node">
 <template v-if="isBranch">
 <button
 v-if="!isEmpty"
 type="button"
 class="json-row json-row--branch"
 @click="toggle"
 >
 <span
 class="icon-[lucide--chevron-right] json-caret":class="expanded ? 'rotate-90': ''"
 />
 <span v-if="nodeKey !== undefined" class="json-key">{{ nodeKey }}</span>
 <span class="json-bracket">{{ valueType === 'array' ? '': '{}' }}</span>
 <span class="json-count">{{ countLabel }}</span>
 </button>
 <div v-else class="json-row json-row--leaf">
 <span v-if="nodeKey !== undefined" class="json-key">{{ nodeKey }}</span>
 <span class="json-empty">{{ valueType === 'array' ? '': '{}' }}</span>
 </div>
 <div v-if="expanded && !isEmpty" class="json-children">
 <JsonNode
 v-for="[k, v] in entries":key="String(k)":node-key="k":value="v":depth="(depth ?? 0) + 1"
 />
 </div>
 </template>
 <div v-else class="json-row json-row--leaf">
 <span v-if="nodeKey !== undefined" class="json-key">{{ nodeKey }}</span>
 <span class="json-val":class="`json-val--${valueType}`">{{ displayValue }}</span>
 </div>
 </div>
</template>
<style scoped>
.json-node {
 font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', ui-monospace, monospace;
 font-size: 0.6875rem;
 line-height: 1.6;
}
.json-row {
 display: flex;
 align-items: baseline;
 gap: 0.375rem;
 width: 100%;
 padding: 0.0625rem 0.25rem;
 border: 0;
 border-radius: 0.3125rem;
 background: transparent;
 text-align: left;
 font-family: inherit;
 font-size: inherit;
 color: hsl(215 16% 38%);
}
.json-row--branch {
 cursor: pointer;
 transition: background-color 0.12s ease;
}
.json-row--branch:hover {
 background: hsl(210 40% 96% / 0.7);
}
.json-caret {
 font-size: 9px;
 color: hsl(215 16% 60% / 0.7);
 flex-shrink: 0;
 transition: transform 0.15s ease;
 align-self: center;
}
.json-key {
 color: hsl(217 60% 42%);
 font-weight: 600;
 word-break: break-all;
}
.json-bracket {
 color: hsl(215 16% 55%);
}
.json-count {
 font-size: 0.5625rem;
 padding: 0 0.25rem;
 border-radius: 9999px;
 background: hsl(215 16% 47% / 0.1);
 color: hsl(215 16% 45%);
 font-variant-numeric: tabular-nums;
}
.json-empty {
 color: hsl(215 16% 60%);
 font-style: italic;
}
.json-children {
 margin-left: 0.5rem;
 padding-left: 0.5rem;
 border-left: 1px solid hsl(214 32% 91% / 0.8);
}
.json-val {
 word-break: break-word;
 white-space: pre-wrap;
}
.json-val--string {
 color: hsl(142 45% 34%);
}
.json-val--number {
 color: hsl(217 75% 50%);
}
.json-val--boolean {
 color: hsl(280 55% 52%);
 font-weight: 600;
}
.json-val--null,
.json-val--undefined {
 color: hsl(215 16% 60%);
 font-style: italic;
}
.dark .json-row {
 color: hsl(215 16% 70%);
}
.dark .json-key {
 color: hsl(217 75% 70%);
}
.dark .json-children {
 border-left-color: hsl(214 32% 30% / 0.6);
}
</style>
