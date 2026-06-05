<script setup lang="ts">
/**
 * JsonViewer — 轻量只读 JSON 查看器
 *
 * 替代 CodeMirror 的只读 JSON 展示，提供清晰的语法着色、
 * 自适应高度、一键复制。配色适配 glassmorphism 暗色主题。
 */
import { computed, ref } from 'vue'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const props = withDefaults(defineProps<{
  data: Record<string, any> | null | undefined
  maxHeight?: string
}>(), {
  maxHeight: '400px',
})

const { handleError } = useErrorHandler()
const { success } = useToast()

const collapsed = ref<Set<string>>(new Set())

function toggleCollapse(path: string) {
  if (collapsed.value.has(path))
    collapsed.value.delete(path)
  else
    collapsed.value.add(path)
  collapsed.value = new Set(collapsed.value)
}

const formattedHtml = computed(() => {
  if (!props.data || Object.keys(props.data).length === 0)
    return ''
  return renderValue(props.data, '', 0)
})

const rawJson = computed(() => {
  if (!props.data)
    return ''
  return JSON.stringify(props.data, null, 2)
})

function renderValue(value: unknown, path: string, depth: number): string {
  if (value === null)
    return '<span class="jv-null">null</span>'
  if (value === undefined)
    return '<span class="jv-null">undefined</span>'
  if (typeof value === 'boolean')
    return `<span class="jv-bool">${value}</span>`
  if (typeof value === 'number')
    return `<span class="jv-num">${value}</span>`
  if (typeof value === 'string')
    return renderString(value)
  if (Array.isArray(value))
    return renderArray(value, path, depth)
  if (typeof value === 'object')
    return renderObject(value as Record<string, unknown>, path, depth)
  return escapeHtml(String(value))
}

function renderString(value: string): string {
  const escaped = escapeHtml(value)
  if (value.length > 200) {
    return `<span class="jv-str jv-str-long">"${escaped}"</span>`
  }
  return `<span class="jv-str">"${escaped}"</span>`
}

function renderObject(obj: Record<string, unknown>, path: string, depth: number): string {
  const entries = Object.entries(obj)
  if (entries.length === 0)
    return '<span class="jv-brace">{}</span>'

  const isCollapsed = collapsed.value.has(path)
  const indent = '  '.repeat(depth + 1)
  const closingIndent = '  '.repeat(depth)

  if (isCollapsed) {
    return `<span class="jv-brace">{</span><span class="jv-toggle" data-path="${path}"> ${entries.length} 项... </span><span class="jv-brace">}</span>`
  }

  const lines = entries.map(([key, val], i) => {
    const childPath = path ? `${path}.${key}` : key
    const comma = i < entries.length - 1 ? ',' : ''
    const renderedVal = renderValue(val, childPath, depth + 1)
    const isExpandable = (typeof val === 'object' && val !== null)
    const toggleAttr = isExpandable ? ` data-path="${childPath}"` : ''
    const toggleClass = isExpandable ? ' jv-toggle' : ''
    return `${indent}<span class="jv-key${toggleClass}"${toggleAttr}>"${escapeHtml(key)}"</span><span class="jv-colon">: </span>${renderedVal}${comma}`
  })

  return `<span class="jv-brace jv-toggle" data-path="${path}">{</span>\n${lines.join('\n')}\n${closingIndent}<span class="jv-brace">}</span>`
}

function renderArray(arr: unknown[], path: string, depth: number): string {
  if (arr.length === 0)
    return '<span class="jv-brace">[]</span>'

  const isCollapsed = collapsed.value.has(path)
  const indent = '  '.repeat(depth + 1)
  const closingIndent = '  '.repeat(depth)

  if (isCollapsed) {
    return `<span class="jv-brace">[</span><span class="jv-toggle" data-path="${path}"> ${arr.length} 项... </span><span class="jv-brace">]</span>`
  }

  const lines = arr.map((val, i) => {
    const childPath = `${path}[${i}]`
    const comma = i < arr.length - 1 ? ',' : ''
    return `${indent}${renderValue(val, childPath, depth + 1)}${comma}`
  })

  return `<span class="jv-brace jv-toggle" data-path="${path}">[</span>\n${lines.join('\n')}\n${closingIndent}<span class="jv-brace">]</span>`
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function handleClick(e: MouseEvent) {
  const target = (e.target as HTMLElement).closest('[data-path]')
  if (target) {
    const path = target.getAttribute('data-path')
    if (path)
      toggleCollapse(path)
  }
}

async function handleCopy() {
  try {
    await navigator.clipboard.writeText(rawJson.value)
    success('已复制到剪贴板')
  }
  catch (e: unknown) {
    handleError(e, '复制')
  }
}
</script>

<template>
  <div class="jv-root group/jv">
    <!-- 工具栏 -->
    <div class="jv-toolbar">
      <button
        class="jv-copy-btn"
        title="复制 JSON"
        @click="handleCopy"
      >
        <span class="icon-[lucide--copy] w-3.5 h-3.5" />
      </button>
    </div>

    <!-- JSON 内容 -->
    <div
      v-if="formattedHtml"
      class="jv-content"
      :style="{ maxHeight }"
    >
      <!-- eslint-disable-next-line vue/no-v-html -->
      <pre class="jv-pre" @click="handleClick" v-html="formattedHtml" />
    </div>
    <div v-else class="text-sm text-muted-foreground italic px-4 py-3">
      (空)
    </div>
  </div>
</template>

<style scoped>
.jv-root {
  position: relative;
  border-radius: 0.75rem;
  border: 1px solid hsl(var(--border) / 0.5);
  background: hsl(var(--card) / 0.6);
  backdrop-filter: blur(8px);
  overflow: hidden;
}

.jv-toolbar {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  z-index: 10;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.group\/jv:hover .jv-toolbar {
  opacity: 1;
}

.jv-copy-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 0.375rem;
  background: hsl(var(--muted) / 0.8);
  color: hsl(var(--muted-foreground));
  transition: all 0.15s ease;
  cursor: pointer;
  border: none;
}

.jv-copy-btn:hover {
  background: hsl(var(--muted));
  color: hsl(var(--foreground));
}

.jv-content {
  overflow: auto;
  scrollbar-width: thin;
}

.jv-pre {
  margin: 0;
  padding: 1rem;
  font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', monospace;
  font-size: 0.8125rem;
  line-height: 1.6;
  white-space: pre;
  word-break: break-all;
  cursor: default;
}

/* 语法着色 */
:deep(.jv-key) {
  color: hsl(200, 80%, 70%);
}

:deep(.jv-str) {
  color: hsl(30, 70%, 65%);
}

:deep(.jv-str-long) {
  color: hsl(30, 60%, 60%);
}

:deep(.jv-num) {
  color: hsl(150, 60%, 60%);
}

:deep(.jv-bool) {
  color: hsl(280, 55%, 68%);
}

:deep(.jv-null) {
  color: hsl(0, 0%, 50%);
  font-style: italic;
}

:deep(.jv-brace) {
  color: hsl(var(--muted-foreground));
}

:deep(.jv-colon) {
  color: hsl(var(--muted-foreground));
}

:deep(.jv-toggle) {
  cursor: pointer;
  border-radius: 0.25rem;
  transition: background-color 0.1s;
}

:deep(.jv-toggle:hover) {
  background-color: hsl(var(--muted) / 0.5);
}
</style>
