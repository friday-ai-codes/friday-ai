<script setup lang="ts">
import type { SddSpecDetail } from '~/api/specs'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import SddSpecStatusBadge from '~/components/spec/SddSpecStatusBadge.vue'

// 交付验收追溯面板（Phase 52 D-52-4，LINK-02）：沿 WorkItem（需求）→ spec（状态徽标）→
// 实现 PR 列表渲染单次 spec-driven 交付状态。全程 fail-soft：所有字段经可选链 + 默认值，
// 缺数据降级占位绝不崩溃；外链仅绑定 :href（不用 v-html）+ rel="noopener noreferrer"
// 规避注入（T-52-06）。
const props = defineProps<{
  spec: SddSpecDetail
}>()

const { t } = useI18n()

const workItem = computed(() => props.spec.relations?.work_item)
const workItemUrl = computed(() => workItem.value?.url || '')
const prs = computed(() => props.spec.implementation_prs ?? [])
</script>

<template>
  <section class="card p-5 space-y-4" data-testid="spec-delivery-panel">
    <h2 class="text-base font-semibold">
      {{ t('specs.delivery.title') }}
    </h2>

    <div class="space-y-3 text-sm">
      <!-- (1) 需求段 -->
      <div class="flex items-start gap-2" data-testid="delivery-work-item">
        <span class="icon-[lucide--clipboard-list] mt-0.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        <div class="space-y-0.5">
          <p class="text-xs text-muted-foreground">
            {{ t('specs.delivery.workItemLabel') }}
          </p>
          <a
            v-if="workItem && workItemUrl"
            :href="workItemUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline"
            data-testid="delivery-work-item-link"
          >
            {{ workItem.title }}
            <span class="icon-[lucide--external-link] size-3" aria-hidden="true" />
          </a>
          <p v-else-if="workItem" class="font-medium">
            {{ workItem.title }}
          </p>
          <p v-else class="text-muted-foreground">
            {{ t('specs.delivery.workItemUnlinked') }}
          </p>
        </div>
      </div>

      <!-- 连接线 -->
      <div class="ml-2 h-3 w-px bg-border/60" aria-hidden="true" />

      <!-- (2) 规格段 -->
      <div class="flex items-start gap-2" data-testid="delivery-spec">
        <span class="icon-[lucide--file-text] mt-0.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        <div class="space-y-0.5">
          <p class="text-xs text-muted-foreground">
            {{ t('specs.delivery.specLabel') }}
          </p>
          <SddSpecStatusBadge :status="spec.status" />
        </div>
      </div>

      <!-- 连接线 -->
      <div class="ml-2 h-3 w-px bg-border/60" aria-hidden="true" />

      <!-- (3) 实现 PR 段 -->
      <div class="flex items-start gap-2" data-testid="delivery-prs">
        <span class="icon-[lucide--git-pull-request] mt-0.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        <div class="flex-1 space-y-1">
          <p class="text-xs text-muted-foreground">
            {{ t('specs.delivery.prsLabel') }}
          </p>
          <ul v-if="prs.length" class="space-y-1">
            <li v-for="pr in prs" :key="pr.pr_url">
              <a
                :href="pr.pr_url"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline break-all"
                data-testid="delivery-pr-link"
              >
                {{ pr.pr_url }}
                <span class="icon-[lucide--external-link] size-3 shrink-0" aria-hidden="true" />
              </a>
              <span v-if="pr.linked_at" class="ml-1 text-xs text-muted-foreground">
                {{ t('specs.delivery.linkedAt', { time: pr.linked_at }) }}
              </span>
            </li>
          </ul>
          <p v-else class="text-muted-foreground">
            {{ t('specs.delivery.prsEmpty') }}
          </p>
        </div>
      </div>
    </div>
  </section>
</template>
