<script setup lang="ts">
/**
 * 知识库即时搜索（业务仓库 / 业务能力 / 关键词）
 *
 * 基于 fuse.js 对聚合出的全量条目做模糊匹配，输入即出结果，支持键盘上下选择 / 回车进入。
 * 命中后由父级决定跳转（仓库 → 仓库页；能力 → 知识树并高亮）。
 */
import type { KnowledgeSearchItem } from '~/composables/useKnowledgeCapabilities'
import Fuse from 'fuse.js'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const props = withDefaults(defineProps<{
  items: KnowledgeSearchItem[]
  loading?: boolean
}>(), {
  loading: false,
})

const emit = defineEmits<{
  (e: 'select', item: KnowledgeSearchItem): void
}>()

const { t } = useI18n()

const KIND_META: Record<KnowledgeSearchItem['kind'], { label: string, icon: string, color: string }> = {
  repo: { label: '仓库', icon: 'lucide--git-branch', color: 'text-indigo-500' },
  sub_app: { label: '子应用', icon: 'lucide--layers', color: 'text-purple-500' },
  module: { label: '模块', icon: 'lucide--box', color: 'text-teal-500' },
  capability: { label: '能力', icon: 'lucide--sparkles', color: 'text-amber-500' },
}

const query = ref('')
const focused = ref(false)
const activeIndex = ref(0)
const inputEl = ref<HTMLInputElement | null>(null)

const fuse = computed(() => new Fuse(props.items, {
  keys: [
    { name: 'title', weight: 3 },
    { name: 'keywords', weight: 2 },
    { name: 'summary', weight: 1 },
    { name: 'repoName', weight: 1 },
    { name: 'trail', weight: 1 },
  ],
  threshold: 0.34,
  ignoreLocation: true,
  minMatchCharLength: 1,
}))

const results = computed(() => {
  const q = query.value.trim()
  if (!q)
    return []
  return fuse.value.search(q).slice(0, 12).map(r => r.item)
})

const open = computed(() => focused.value && query.value.trim().length > 0)

function choose(item: KnowledgeSearchItem) {
  emit('select', item)
  query.value = ''
  focused.value = false
  inputEl.value?.blur()
}

function onKeydown(e: KeyboardEvent) {
  if (!open.value)
    return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    activeIndex.value = Math.min(activeIndex.value + 1, results.value.length - 1)
  }
  else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value = Math.max(activeIndex.value - 1, 0)
  }
  else if (e.key === 'Enter') {
    const item = results.value[activeIndex.value]
    if (item)
      choose(item)
  }
  else if (e.key === 'Escape') {
    query.value = ''
    inputEl.value?.blur()
  }
}

// 输入变化时重置高亮项
function onInput() {
  activeIndex.value = 0
}

function clear() {
  query.value = ''
  inputEl.value?.focus()
}
</script>

<template>
  <div class="relative">
    <div class="relative">
      <span class="icon-[lucide--search] pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-lg text-muted-foreground" />
      <input
        ref="inputEl"
        v-model="query"
        type="text"
        role="combobox"
        :aria-expanded="open"
        aria-controls="kb-search-results"
        :placeholder="t('knowledge.overview.search.placeholder')"
        :disabled="loading"
        class="h-12 w-full rounded-2xl border border-border bg-card pl-11 pr-10 text-sm shadow-sm outline-none transition-all placeholder:text-muted-foreground/70 focus:border-primary/40 focus:ring-4 focus:ring-primary/10 disabled:opacity-60"
        @focus="focused = true"
        @blur="focused = false"
        @keydown="onKeydown"
        @input="onInput"
      >
      <button
        v-if="query"
        type="button"
        class="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        aria-label="清空"
        @mousedown.prevent="clear"
      >
        <span class="icon-[lucide--x] text-sm" />
      </button>
    </div>

    <!-- 结果下拉 -->
    <Transition name="kb-pop">
      <div
        v-if="open"
        id="kb-search-results"
        role="listbox"
        class="absolute z-40 mt-2 w-full overflow-hidden rounded-2xl border border-border bg-popover shadow-xl"
      >
        <div v-if="!results.length" class="px-4 py-6 text-center text-sm text-muted-foreground">
          {{ t('knowledge.overview.search.empty', { q: query }) }}
        </div>
        <ul v-else class="max-h-[min(60vh,420px)] overflow-y-auto py-1.5">
          <li
            v-for="(item, i) in results"
            :key="item.id"
            role="option"
            :aria-selected="i === activeIndex"
            class="mx-1.5 flex cursor-pointer items-start gap-3 rounded-xl px-3 py-2.5 transition-colors"
            :class="i === activeIndex ? 'bg-primary/10' : 'hover:bg-muted/60'"
            @mouseenter="activeIndex = i"
            @mousedown.prevent="choose(item)"
          >
            <span class="mt-0.5 shrink-0 text-base" :class="[KIND_META[item.kind].icon, KIND_META[item.kind].color]" />
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="truncate text-sm font-medium">{{ item.title }}</span>
                <span class="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {{ KIND_META[item.kind].label }}
                </span>
              </div>
              <p class="mt-0.5 flex items-center gap-1 truncate text-xs text-muted-foreground">
                <span class="icon-[lucide--git-branch] shrink-0 text-[11px]" />
                <span class="shrink-0">{{ item.repoName }}</span>
                <template v-if="item.trail.length">
                  <span class="text-muted-foreground/50">·</span>
                  <span class="truncate">{{ item.trail.join(' / ') }}</span>
                </template>
              </p>
            </div>
            <span class="icon-[lucide--corner-down-left] mt-1 shrink-0 text-xs text-muted-foreground/40" :class="i === activeIndex ? 'opacity-100' : 'opacity-0'" />
          </li>
        </ul>
        <div class="flex items-center justify-between border-t border-border/60 bg-muted/30 px-3 py-1.5 text-[11px] text-muted-foreground">
          <span>{{ t('knowledge.overview.search.count', { count: results.length }) }}</span>
          <span class="hidden items-center gap-2 sm:flex">
            <kbd class="rounded border border-border bg-background px-1">↑</kbd>
            <kbd class="rounded border border-border bg-background px-1">↓</kbd>
            {{ t('knowledge.overview.search.navHint') }}
          </span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.kb-pop-enter-active,
.kb-pop-leave-active {
  transition:
    opacity 0.15s ease,
    transform 0.15s ease;
}

.kb-pop-enter-from,
.kb-pop-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

@media (prefers-reduced-motion: reduce) {
  .kb-pop-enter-active,
  .kb-pop-leave-active {
    transition: none;
  }
}
</style>
