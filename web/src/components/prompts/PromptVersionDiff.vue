<script setup lang="ts">
/**
 * PromptVersionDiff.vue — side-by-side 版本对比视图
 *
 * 基于 diff@8.0.4 的 diffLines 产出 Change[] 数组，左栏展示 v1 视角
 * （unchanged + removed 段落），右栏展示 v2 视角（unchanged + added 段落）。
 * 颜色语义完全由 Phase-Local CSS 令牌 `.diff-added / .diff-removed / .diff-unchanged`
 * 字面实现（与 215-UI-SPEC §Color §Phase-Local 视觉令牌一致）。
 *
 * 安全：diffLines 返回纯字符串，本组件完全走 Vue mustache `{{ seg.text }}`
 * 经 <pre> 渲染，未使用 v-html，确保 XSS 面 = 0（Threat T-215-01 mitigate）。
 *
 * 性能：使用 shallowRef<Change[]> 避免对 diffLines 输出做深响应式；
 * diffLines O(n) 差分算法对 32KB body 两两对比无性能压力。
 */

import type { Change } from 'diff'
import type { PromptVersion } from '~/types/prompts'
import { diffLines } from 'diff'
import { shallowRef } from 'vue'

const props = defineProps<{
  v1: PromptVersion
  v2: PromptVersion
}>()

// shallowRef 避免深响应式：Change[] 只会整体替换，不会被原地修改
const changes = shallowRef<Change[]>(diffLines(props.v1.body, props.v2.body))

watch(
  () => [props.v1, props.v2],
  () => {
    changes.value = diffLines(props.v1.body, props.v2.body)
  },
  { deep: true },
)

interface Segment {
  text: string
  kind: 'added' | 'removed' | 'unchanged'
}

// 左栏：展示 v1 视角 —— removed + unchanged
const leftSegments = computed<Segment[]>(() =>
  changes.value
    .filter(c => !c.added)
    .map(c => ({
      text: c.value,
      kind: c.removed ? ('removed' as const) : ('unchanged' as const),
    })),
)

// 右栏：展示 v2 视角 —— added + unchanged
const rightSegments = computed<Segment[]>(() =>
  changes.value
    .filter(c => !c.removed)
    .map(c => ({
      text: c.value,
      kind: c.added ? ('added' as const) : ('unchanged' as const),
    })),
)

// 可访问性摘要（aria-live）
const addedCount = computed(() =>
  changes.value.filter(c => c.added).reduce((sum, c) => sum + c.count, 0),
)
const removedCount = computed(() =>
  changes.value.filter(c => c.removed).reduce((sum, c) => sum + c.count, 0),
)
</script>

<template>
  <div class="space-y-2">
    <p
      class="text-xs text-muted-foreground"
      aria-live="polite"
    >
      v{{ v1.version }} 对比 v{{ v2.version }}，新增
      <span class="text-emerald-600 font-medium">{{ addedCount }}</span> 行，删除
      <span class="text-destructive font-medium">{{ removedCount }}</span> 行
    </p>

    <div class="grid grid-cols-2 gap-0 border border-border/50 rounded-lg overflow-hidden min-h-[320px] max-h-[560px] bg-card shadow-sm">
      <!-- 左栏 v1 视角 -->
      <div data-diff-column="left" class="overflow-auto border-r border-border/50">
        <div class="px-3 py-2 text-[11px] font-semibold text-foreground border-b border-border/50 sticky top-0 bg-muted/80 backdrop-blur-sm z-10 flex items-center gap-2">
          <span class="inline-flex items-center justify-center w-5 h-5 rounded bg-destructive/10 text-destructive text-[10px] font-bold">−</span>
          v{{ v1.version }}
        </div>
        <div
          v-for="(seg, i) in leftSegments"
          :key="`L-${i}`"
          class="diff-line"
          :class="seg.kind === 'removed' ? 'diff-removed' : 'diff-unchanged'"
        >
          <pre class="font-mono text-xs leading-6 whitespace-pre-wrap px-3 py-1">{{ seg.text }}</pre>
        </div>
      </div>

      <!-- 右栏 v2 视角 -->
      <div data-diff-column="right" class="overflow-auto">
        <div class="px-3 py-2 text-[11px] font-semibold text-foreground border-b border-border/50 sticky top-0 bg-muted/80 backdrop-blur-sm z-10 flex items-center gap-2">
          <span class="inline-flex items-center justify-center w-5 h-5 rounded bg-emerald-500/10 text-emerald-600 text-[10px] font-bold">+</span>
          v{{ v2.version }}
        </div>
        <div
          v-for="(seg, i) in rightSegments"
          :key="`R-${i}`"
          class="diff-line"
          :class="seg.kind === 'added' ? 'diff-added' : 'diff-unchanged'"
        >
          <pre class="font-mono text-xs leading-6 whitespace-pre-wrap px-3 py-1">{{ seg.text }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Phase-Local 视觉令牌，与 215-UI-SPEC §Color §Phase-Local 对齐
 * 文字色已从 slate-500 提到 slate-800，避免在浅色卡片上对比度不足。 */
.diff-added {
  background: hsl(142 71% 45% / 0.12);
  color: hsl(142 71% 20%);
  border-left: 3px solid hsl(142 71% 45%);
}
.diff-removed {
  background: hsl(0 72% 51% / 0.1);
  color: hsl(0 72% 30%);
  border-left: 3px solid hsl(0 72% 51%);
}
.diff-unchanged {
  background: transparent;
  color: hsl(215 28% 17%);
  border-left: 3px solid transparent;
}
</style>
