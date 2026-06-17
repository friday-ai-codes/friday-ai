<script setup lang="ts">
import type { ToolUsePart } from '~/types/chat'

/**
 * ChatToolCall.vue 接受新 parts API。
 *
 * 双轨期 props 二选一：
 *   1. 老调用方传 `name / input / result / status` 直接字段（保留向后兼容）
 *   2. 新调用方传 `part: ToolUsePart` 整个 part 对象
 *
 * 优先用 `part`；都不传则字段默认空（不 crash）。
 * 兼容窗口结束后删除 part-free 直接字段路径。
 */
const props = defineProps<{
  name?: string
  input?: Record<string, unknown>
  result?: string
  status?: 'running' | 'done' | 'error'
  /** 新 parts API 整体传入；优先级高于平铺字段。 */
  part?: ToolUsePart
}>()

if (process.env.NODE_ENV !== 'production' && props.part && props.name) {
  console.warn('[ChatToolCall] part 与 name 同时传入；按 part 为准')
}

// 派生有效字段：part 优先于平铺字段
const effectiveName = computed(() => props.part?.name || props.name || '')
const effectiveInput = computed<Record<string, unknown>>(() => props.part?.input || props.input || {})
const effectiveResult = computed(() => (props.part?.result == null ? props.result : props.part.result) || undefined)
const effectiveStatus = computed<'running' | 'done'>(() => {
  const raw = props.part?.status || props.status
  return raw === 'running' ? 'running' : 'done'
})

const isOpen = ref(false)

const TOOL_LABELS: Record<string, { label: string, icon: string }> = {
  browse_file_content: { label: '浏览文件', icon: 'icon-[lucide--file-text]' },
  list_project_structure: { label: '项目结构', icon: 'icon-[lucide--folder-tree]' },
  get_project_overview: { label: '项目概览', icon: 'icon-[lucide--layout-dashboard]' },
  search_repository_code: { label: 'RAG 代码检索', icon: 'icon-[lucide--search]' },
  list_project_repositories: { label: '仓库列表', icon: 'icon-[lucide--git-branch]' },
  get_repository_info: { label: '仓库信息', icon: 'icon-[lucide--info]' },
}

function stripMcpPrefix(name: string): string {
  return name.replace(/^mcp__[^_]+__/, '')
}

const tool = computed(() => {
  const bare = stripMcpPrefix(effectiveName.value)
  return TOOL_LABELS[bare] || { label: bare, icon: 'icon-[lucide--wrench]' }
})

const actionDescription = computed(() => {
  const bare = stripMcpPrefix(effectiveName.value)
  const inp = effectiveInput.value

  switch (bare) {
    case 'search_repository_code': {
      const q = (inp.query as string) || ''
      return q ? `RAG 检索「${q.slice(0, 50)}${q.length > 50 ? '...' : ''}」` : ''
    }
    case 'browse_file_content': {
      const path = (inp.file_path as string) || (inp.path as string) || ''
      return path ? `查看 ${path}` : ''
    }
    case 'get_repository_info':
      return '获取仓库详情'
    case 'list_project_repositories':
      return '列出空间下所有仓库'
    case 'list_project_structure':
      return '浏览空间文件结构'
    case 'get_project_overview':
      return '获取空间概览信息'
    default: {
      const entries = Object.entries(inp).slice(0, 2)
      return entries.map(([k, v]) => {
        const val = typeof v === 'string' ? (v.length > 30 ? `${v.slice(0, 30)}...` : v) : JSON.stringify(v)
        return `${k}: ${val}`
      }).join(', ')
    }
  }
})
</script>

<template>
  <div class="tool-card" :class="{ 'tool-card--open': isOpen }">
    <button class="tool-header" @click="isOpen = !isOpen">
      <!-- 状态指示点 -->
      <span v-if="effectiveStatus === 'running'" class="tool-dot tool-dot--running" />
      <span v-else class="tool-dot tool-dot--done" />

      <!-- 图标 + 名称 -->
      <span :class="tool.icon" class="text-[13px] text-muted-foreground" />
      <span class="tool-name">{{ tool.label }}</span>

      <!-- 行为描述 -->
      <span v-if="actionDescription" class="tool-summary">{{ actionDescription }}</span>

      <!-- 状态文本 -->
      <span v-if="effectiveStatus === 'running'" class="tool-status">
        <span class="icon-[lucide--loader-2] text-[10px] animate-spin" />
        执行中
      </span>

      <!-- 展开 -->
      <span
        class="icon-[lucide--chevron-right] text-[11px] text-muted-foreground/50 ml-auto transition-transform duration-200"
        :class="isOpen ? 'rotate-90' : ''"
      />
    </button>

    <Transition
      enter-active-class="transition-all duration-200 ease-out"
      enter-from-class="opacity-0 max-h-0"
      enter-to-class="opacity-100 max-h-[600px]"
      leave-active-class="transition-all duration-150 ease-in"
      leave-from-class="opacity-100 max-h-[600px]"
      leave-to-class="opacity-0 max-h-0"
    >
      <div v-show="isOpen" class="tool-body">
        <div class="tool-section">
          <span class="tool-section-label">输入</span>
          <pre class="tool-json">{{ JSON.stringify(effectiveInput, null, 2) }}</pre>
        </div>
        <div v-if="effectiveResult" class="tool-section">
          <span class="tool-section-label">输出</span>
          <pre class="tool-json tool-json--result">{{ effectiveResult.length > 800 ? `${effectiveResult.slice(0, 800)}...` : effectiveResult }}</pre>
        </div>
        <div v-else-if="effectiveStatus === 'running'" class="tool-section">
          <span class="text-[11px] text-muted-foreground/60 italic">等待返回...</span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.tool-card {
  border-radius: 0.625rem;
  border: 1px solid hsl(214 32% 91% / 0.7);
  background: hsl(210 40% 98% / 0.5);
  overflow: hidden;
  transition: border-color 0.15s;
}
.tool-card:hover {
  border-color: hsl(214 32% 91%);
}

.tool-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.5rem 0.75rem;
  cursor: pointer;
  font-size: 0.75rem;
}

.tool-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.tool-dot--running {
  background: hsl(168 76% 42%);
  box-shadow: 0 0 0 2px hsl(168 76% 42% / 0.2);
  animation: pulse-dot 1.5s infinite;
}
.tool-dot--done {
  background: hsl(142 71% 45%);
}

.tool-name {
  font-weight: 550;
  color: hsl(215 28% 17%);
  white-space: nowrap;
}

.tool-summary {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: hsl(215 16% 47% / 0.6);
  font-size: 0.6875rem;
}

.tool-status {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  color: hsl(168 76% 36%);
  font-size: 0.6875rem;
  white-space: nowrap;
}

.tool-body {
  border-top: 1px solid hsl(214 32% 91% / 0.5);
  padding: 0.5rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  overflow: hidden;
}

.tool-section {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.tool-section-label {
  font-size: 0.625rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: hsl(215 16% 47% / 0.6);
}

.tool-json {
  font-family: 'SF Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 0.6875rem;
  line-height: 1.5;
  padding: 0.5rem;
  border-radius: 0.5rem;
  background: hsl(210 40% 96% / 0.8);
  color: hsl(215 28% 25%);
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
  max-height: 12rem;
  overflow-y: auto;
}

.tool-json--result {
  max-height: 16rem;
}

@keyframes pulse-dot {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}
</style>
