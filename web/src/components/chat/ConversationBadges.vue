<script setup lang="ts">
import type { Conversation } from '~/types/chat'
import { computed } from 'vue'

const props = defineProps<{
  conversation: Pick<Conversation, 'has_sdd_spec' | 'has_coding_plan' | 'has_coding_session'>
}>()

const showSdd = computed(() => props.conversation.has_sdd_spec === true)
const showCoding = computed(() => props.conversation.has_coding_session === true)
// 方案徽标：有技术方案但尚未编码（编码已隐含方案，避免重复）
const showPlan = computed(
  () => props.conversation.has_coding_plan === true && !showCoding.value,
)

const hasAny = computed(() => showSdd.value || showCoding.value || showPlan.value)
</script>

<template>
  <span v-if="hasAny" class="flex shrink-0 items-center gap-1">
    <span
      v-if="showSdd"
      data-testid="conv-badge-sdd"
      title="SDD 会话（已产出 spec）"
      class="inline-flex items-center gap-0.5 rounded border border-emerald-500/30 bg-emerald-500/15 px-1 py-px text-[9px] font-bold uppercase leading-none tracking-wide text-emerald-700 dark:border-emerald-400/40 dark:bg-emerald-400/15 dark:text-emerald-300"
    >
      <span class="icon-[lucide--scroll-text] text-[10px]" aria-hidden="true" />
      SDD
    </span>

    <span
      v-if="showCoding"
      data-testid="conv-badge-coding"
      title="已进行编码"
      class="inline-flex size-4 items-center justify-center rounded border border-sky-500/30 bg-sky-500/15 text-sky-700 dark:border-sky-400/40 dark:bg-sky-400/15 dark:text-sky-300"
    >
      <span class="icon-[lucide--code-2] text-[10px]" aria-hidden="true" />
    </span>

    <span
      v-else-if="showPlan"
      data-testid="conv-badge-plan"
      title="已生成技术方案"
      class="inline-flex size-4 items-center justify-center rounded border border-amber-500/30 bg-amber-500/15 text-amber-700 dark:border-amber-400/40 dark:bg-amber-400/15 dark:text-amber-300"
    >
      <span class="icon-[lucide--clipboard-list] text-[10px]" aria-hidden="true" />
    </span>
  </span>
</template>
