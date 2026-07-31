<script setup lang="ts">
/**
 * 引用来源不可达时的兜底快照（Phase 115-03，UI-SPEC §10.1「兜底不留白」）。
 *
 * **职责**：任何来源取不到时渲染 citation **自带的** `title` / `quote` 快照 + 一行说明。
 *
 * ⭐ **与 analog 完全相反**：`pages/knowledge/index.vue:165-191` 的 `catch` 分支是
 * 「关弹窗 + toast」；本相位明令**弹窗保持打开**、⛔ 不回显后端错误体（`chunk-at` 的错误体
 * 键是 `error` 不是那个通用键，读出来只会是一句无意义的「请求失败」）。空壳渲染同样禁止 ——
 * 用户会误判「这里本来就没内容」（T-115-23 / T-115-24）。
 *
 * **安全**：`title` / `quote` 是 LLM 合成的半可信文本，全程 mustache + `<pre>`。
 */

import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'

const props = withDefaults(defineProps<{
  title?: string
  quote?: string
}>(), {
  title: '',
  quote: '',
})

const { t } = useI18n()

const hasQuote = computed(() => Boolean(props.quote && props.quote.trim()))
</script>

<template>
  <div data-testid="citation-fallback" class="space-y-2">
    <p class="text-xs text-muted-foreground">
      {{ t('knowledge.blueprints.citation.fallback') }}
    </p>

    <template v-if="hasQuote">
      <p v-if="title" class="text-sm font-medium text-foreground">
        {{ title }}
      </p>
      <pre class="whitespace-pre-wrap rounded-md border border-border/50 bg-muted/20 p-3 text-sm">{{ quote }}</pre>
    </template>

    <!-- ⚠️ `icon` 收**裸名**（组件内部做 icon-[${icon}]），传完整类名图标会出不来（P-6）；
         该组件只有 `icon` / `title` / `description` 三个 prop 与一个默认 slot，
         ⛔ 没有按钮文案 prop、⛔ 没有点击事件，CTA 一律放默认 slot。 -->
    <CompactEmptyState
      v-else
      icon="lucide--file-x"
      :title="title || t('knowledge.blueprints.citation.fallback')"
    />
  </div>
</template>
