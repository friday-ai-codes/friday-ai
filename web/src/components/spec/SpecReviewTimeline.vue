<script setup lang="ts">
import type { SddSpecReview } from '~/api/specs'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  reviews: SddSpecReview[]
}>()

const { t } = useI18n()

// 倒序渲染（后端已倒序，此处稳态复制不就地反转，避免污染 props）。
const ordered = computed(() => [...props.reviews])
</script>

<template>
  <div data-testid="spec-review-timeline">
    <p v-if="ordered.length === 0" class="text-sm text-muted-foreground py-2">
      {{ t('specs.detail.reviewEmpty') }}
    </p>
    <ol v-else class="space-y-5">
      <li
        v-for="review in ordered"
        :key="review.id"
        class="flex gap-3"
        data-testid="spec-review-item"
      >
        <div class="flex flex-col items-center pt-1">
          <span
            class="size-2.5 rounded-full"
            :class="review.decision === 'approve' ? 'bg-emerald-400' : 'bg-destructive'"
          />
          <span class="w-px flex-1 bg-border/60 min-h-4" />
        </div>
        <div class="flex-1 space-y-1 pb-2">
          <div class="flex items-center gap-2">
            <span class="text-sm font-medium">
              {{ review.reviewer ?? t('specs.detail.unknownReviewer') }}
            </span>
            <span
              class="inline-flex shrink-0 items-center rounded border px-1.5 py-0.5 text-[10px] font-medium"
              :class="review.decision === 'approve'
                ? 'bg-emerald-500/10 text-emerald-700 border-emerald-200 dark:text-emerald-300 dark:border-emerald-400/30'
                : 'bg-destructive/10 text-destructive border-destructive/30'"
            >
              {{ review.decision === 'approve' ? t('specs.detail.decisionApprove') : t('specs.detail.decisionReject') }}
            </span>
          </div>
          <p v-if="review.comment" class="text-sm text-muted-foreground leading-relaxed">
            {{ review.comment }}
          </p>
          <p class="text-xs text-muted-foreground">
            {{ review.created_at }}
          </p>
        </div>
      </li>
    </ol>
  </div>
</template>
