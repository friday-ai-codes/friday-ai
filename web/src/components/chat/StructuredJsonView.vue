<script setup lang="ts">
/**
 * 工具调用 input / output 的结构化展示。
 *
 * - 默认「结构化」模式：对象/数组渲染为可折叠键值树（JsonNode）；
 *   对高频工具（如 search_repository_code）做定制美化。
 * - 「原始 JSON」模式：保留裸 JSON 文本，便于复制 / 排查。
 * - 非结构化（纯文本 / 非法 JSON）直接退化为原始展示。
 */
import JsonNode from './JsonNode.vue'

const props = withDefaults(defineProps<{
  value: unknown
  toolName?: string
  kind?: 'input' | 'output'
}>(), { kind: 'input' })

const mode = ref<'structured' | 'raw'>('structured')

const bareToolName = computed(() => (props.toolName || '').replace(/^mcp__[^_]+__/, ''))

// value 可能是对象，也可能是 JSON 字符串（output 多为字符串）
const parsed = computed<unknown>(() => {
  const v = props.value
  if (typeof v === 'string') {
    const t = v.trim()
    if (!t)
      return ''
    try {
      return JSON.parse(t)
    }
    catch {
      return v
    }
  }
  return v
})

const isStructurable = computed(() => {
  const p = parsed.value
  return p !== null && typeof p === 'object'
})

const rawText = computed(() => {
  const p = parsed.value
  if (typeof p === 'string')
    return p
  try {
    return JSON.stringify(p, null, 2)
  }
  catch {
    return String(p)
  }
})

const rootEntries = computed<Array<[string | number, unknown]>>(() => {
  const p = parsed.value
  if (Array.isArray(p))
    return p.map((v, i) => [i, v])
  if (p && typeof p === 'object')
    return Object.entries(p as Record<string, unknown>)
  return []
})

interface SearchResultItem {
  repository?: string
  file_path?: string
  path?: string
  score?: number
  snippet?: string
  content?: string
}
interface DiagnosisShape {
  summary?: string
  issues?: string[]
  suggestions?: string[]
}

// 定制：search_repository_code 的输出
const searchView = computed(() => {
  if (bareToolName.value !== 'search_repository_code' || props.kind !== 'output')
    return null
  const p = parsed.value as Record<string, any> | null
  if (!p || typeof p !== 'object')
    return null
  const results = p?.data?.results ?? p?.results
  if (!Array.isArray(results))
    return null
  const meta = (p?.metadata ?? {}) as Record<string, any>
  const diagnosis = (p?.diagnosis ?? meta?.diagnosis ?? null) as DiagnosisShape | null
  return {
    results: results as SearchResultItem[],
    total: typeof meta.total_results === 'number' ? meta.total_results : results.length,
    query: typeof meta.query === 'string' ? meta.query : '',
    diagnosis,
  }
})

// 切到原始模式时若不可结构化则禁用结构化按钮
watch(isStructurable, (ok) => {
  if (!ok)
    mode.value = 'raw'
}, { immediate: true })
</script>

<template>
  <div class="sjv">
    <div v-if="isStructurable" class="sjv-toolbar">
      <div class="sjv-switch" role="tablist">
        <button
          type="button"
          class="sjv-switch-btn"
          :class="{ 'is-active': mode === 'structured' }"
          role="tab"
          :aria-selected="mode === 'structured'"
          @click="mode = 'structured'"
        >
          结构化
        </button>
        <button
          type="button"
          class="sjv-switch-btn"
          :class="{ 'is-active': mode === 'raw' }"
          role="tab"
          :aria-selected="mode === 'raw'"
          @click="mode = 'raw'"
        >
          原始 JSON
        </button>
      </div>
    </div>

    <pre v-if="mode === 'raw' || !isStructurable" class="sjv-raw">{{ rawText }}</pre>

    <template v-else>
      <!-- 定制：搜索代码结果 -->
      <div v-if="searchView" class="sjv-search">
        <div class="sjv-search-head">
          <span class="icon-[lucide--search] text-[11px] text-primary" />
          <span v-if="searchView.query" class="sjv-search-query">「{{ searchView.query }}」</span>
          <span class="sjv-search-count">{{ searchView.total }} 条结果</span>
        </div>
        <div v-if="searchView.results.length > 0" class="sjv-search-list">
          <div v-for="(r, i) in searchView.results" :key="i" class="sjv-search-item">
            <div class="sjv-search-item-head">
              <span class="icon-[lucide--file-code] sjv-search-icon" />
              <span class="sjv-search-path">{{ r.file_path || r.path || '未知文件' }}</span>
              <span v-if="r.repository" class="sjv-search-repo">{{ r.repository }}</span>
              <span v-if="typeof r.score === 'number'" class="sjv-search-score">{{ r.score.toFixed(2) }}</span>
            </div>
            <pre v-if="r.snippet || r.content" class="sjv-search-snippet">{{ (r.snippet || r.content || '').slice(0, 400) }}</pre>
          </div>
        </div>
        <div v-else class="sjv-search-empty">
          <span class="icon-[lucide--inbox] text-[12px]" />
          未召回结果
        </div>
        <div v-if="searchView.diagnosis" class="sjv-diagnosis">
          <div v-if="searchView.diagnosis.summary" class="sjv-diagnosis-summary">
            {{ searchView.diagnosis.summary }}
          </div>
          <ul
            v-if="Array.isArray(searchView.diagnosis.issues) && searchView.diagnosis.issues.length"
            class="sjv-diagnosis-list"
          >
            <li v-for="(it, i) in searchView.diagnosis.issues" :key="`is-${i}`">
              {{ it }}
            </li>
          </ul>
          <ul
            v-if="Array.isArray(searchView.diagnosis.suggestions) && searchView.diagnosis.suggestions.length"
            class="sjv-diagnosis-list sjv-diagnosis-list--tip"
          >
            <li v-for="(it, i) in searchView.diagnosis.suggestions" :key="`sg-${i}`">
              {{ it }}
            </li>
          </ul>
        </div>
      </div>

      <!-- 通用结构化树 -->
      <div v-else class="sjv-tree">
        <JsonNode
          v-for="[k, v] in rootEntries"
          :key="String(k)"
          :node-key="k"
          :value="v"
          :depth="0"
        />
      </div>
    </template>
  </div>
</template>

<style scoped>
.sjv {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.sjv-toolbar {
  display: flex;
  justify-content: flex-end;
}

.sjv-switch {
  display: inline-flex;
  padding: 2px;
  border-radius: 9999px;
  background: hsl(215 16% 47% / 0.08);
  border: 1px solid hsl(214 32% 91% / 0.7);
}

.sjv-switch-btn {
  padding: 0.125rem 0.5rem;
  border: 0;
  border-radius: 9999px;
  background: transparent;
  font-size: 0.625rem;
  font-weight: 600;
  color: hsl(215 16% 45%);
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;
  font-family: inherit;
}
.sjv-switch-btn:hover:not(.is-active) {
  color: hsl(215 28% 25%);
}
.sjv-switch-btn.is-active {
  background: hsl(0 0% 100%);
  color: hsl(168 70% 30%);
  box-shadow: 0 1px 2px hsl(215 28% 17% / 0.08);
}

.sjv-raw {
  font-family: 'SF Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 0.625rem;
  line-height: 1.5;
  padding: 0.5rem 0.625rem;
  border-radius: 0.5rem;
  background: hsl(210 40% 96% / 0.6);
  color: hsl(215 28% 25%);
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  max-height: 18rem;
  overflow-y: auto;
}

.sjv-tree {
  padding: 0.5rem 0.625rem;
  border-radius: 0.5rem;
  background: hsl(210 40% 98% / 0.55);
  border: 1px solid hsl(214 32% 91% / 0.6);
  max-height: 18rem;
  overflow-y: auto;
}

/* ===== 搜索代码定制 ===== */
.sjv-search {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.sjv-search-head {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.6875rem;
  color: hsl(215 16% 38%);
}
.sjv-search-query {
  font-weight: 600;
  color: hsl(215 28% 25%);
}
.sjv-search-count {
  margin-left: auto;
  padding: 0.0625rem 0.4375rem;
  border-radius: 9999px;
  background: hsl(168 76% 42% / 0.1);
  color: hsl(168 70% 30%);
  font-size: 0.625rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.sjv-search-list {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  max-height: 18rem;
  overflow-y: auto;
}

.sjv-search-item {
  border-radius: 0.5rem;
  border: 1px solid hsl(214 32% 91% / 0.7);
  background: hsl(0 0% 100% / 0.7);
  padding: 0.375rem 0.5rem;
}

.sjv-search-item-head {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  min-width: 0;
}
.sjv-search-icon {
  font-size: 11px;
  color: hsl(217 60% 50%);
  flex-shrink: 0;
}
.sjv-search-path {
  font-family: 'SF Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 0.6875rem;
  font-weight: 600;
  color: hsl(215 28% 25%);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.sjv-search-repo {
  font-size: 0.5625rem;
  padding: 0.0625rem 0.375rem;
  border-radius: 9999px;
  background: hsl(215 16% 47% / 0.1);
  color: hsl(215 16% 45%);
  white-space: nowrap;
  flex-shrink: 0;
}
.sjv-search-score {
  margin-left: auto;
  font-size: 0.5625rem;
  font-variant-numeric: tabular-nums;
  color: hsl(168 70% 32%);
  font-weight: 700;
  flex-shrink: 0;
}
.sjv-search-snippet {
  margin: 0.375rem 0 0;
  padding: 0.375rem 0.5rem;
  border-radius: 0.375rem;
  background: hsl(210 40% 96% / 0.7);
  font-family: 'SF Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 0.625rem;
  line-height: 1.5;
  color: hsl(215 20% 35%);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 8rem;
  overflow-y: auto;
}

.sjv-search-empty {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.625rem;
  border-radius: 0.5rem;
  border: 1px dashed hsl(214 32% 86%);
  background: hsl(210 40% 98% / 0.5);
  font-size: 0.6875rem;
  color: hsl(215 16% 50%);
}

.sjv-diagnosis {
  border-radius: 0.5rem;
  border: 1px solid hsl(38 92% 50% / 0.2);
  background: hsl(38 92% 50% / 0.06);
  padding: 0.5rem 0.625rem;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}
.sjv-diagnosis-summary {
  font-size: 0.6875rem;
  font-weight: 600;
  color: hsl(38 60% 32%);
}
.sjv-diagnosis-list {
  margin: 0;
  padding-left: 1rem;
  list-style: disc;
  font-size: 0.6875rem;
  line-height: 1.6;
  color: hsl(215 16% 38%);
}
.sjv-diagnosis-list--tip {
  color: hsl(168 60% 30%);
}
.sjv-diagnosis-list li::marker {
  color: hsl(38 70% 50%);
}
.sjv-diagnosis-list--tip li::marker {
  color: hsl(168 76% 42%);
}

.dark .sjv-raw,
.dark .sjv-tree {
  background: hsl(220 20% 12% / 0.5);
  color: hsl(215 16% 75%);
  border-color: hsl(214 32% 25% / 0.6);
}
.dark .sjv-switch-btn.is-active {
  background: hsl(220 20% 18%);
  color: hsl(168 60% 55%);
}
</style>
