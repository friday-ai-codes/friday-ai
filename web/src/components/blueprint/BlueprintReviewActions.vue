<script setup lang="ts">
/**
 * 人审终审操作区（Phase 115-04，FLOW-08，UI-SPEC §11.1 / §16）。
 *
 * **防误触第一层 = 视觉分离**：本组件是顶栏**最右侧**的独立区块，与左侧阅读动作之间由
 * `ml-auto` 推开 + 容器 `pl-4 border-l border-border` 一条 hairline 分隔。
 *
 * **防误触第二层 = 二次确认**：
 * - **通过**走 `useConfirmDialog().confirm(...)`（无输入框，文案逐字取自 §16 的三个 i18n 键），
 *   用户点「确认通过」后才 emit `approve`；
 * - **驳回**⛔ 不走 `useConfirmDialog` —— 它没有输入框，而驳回的 `comment` 是必填项。
 *   本组件只 emit `reject`，由父层打开 `BlueprintRejectDialog`。
 *
 * ⭐ **可用性由 `current_status` 驱动，形态是 `disabled` + `Tooltip`，⛔ 不是不渲染。**
 * 这与 §7.9 作答框的「不存在于 DOM」**刻意不同**：终审按钮的存在本身有信息量（告诉人
 * 「这里将来能做什么」），而可编辑闸拦的是会撞 400 的写路径 —— 渲染一个必撞 400 的入口
 * 等于把用户送进死路，两种处理不要统一。
 *
 * ⛔ **不做乐观更新**：本组件只 emit，状态一律由父层以响应体的 `current_status` 为准写回
 * 并 `invalidateQueries({ queryKey: ['blueprint'] })` 重取（114-REVIEW MJ-01 第二点）。
 *
 * Tooltip 文案用 UI-SPEC §11.1 要求的带状态插值版本（`review.disabledReason`，115-06 补键后
 * 换回）；状态中文名取自 `getBlueprintStatusConfig(status).labelKey`，⛔ 不在此写死中文。
 */

import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { getBlueprintStatusConfig } from '~/config/blueprintStatus'

const props = withDefaults(defineProps<{
  currentStatus: string
  revisionRound?: number
  submitting?: boolean
}>(), {
  revisionRound: 0,
  submitting: false,
})

const emit = defineEmits<{
  approve: []
  reject: []
}>()

const { t } = useI18n()
const { confirm } = useConfirmDialog()

/** 唯一可终审的状态；其余一律 `disabled` + Tooltip 说明原因。 */
const REVIEWABLE_STATUS = 'pending_review'

const canReview = computed(() => props.currentStatus === REVIEWABLE_STATUS && !props.submitting)

const statusLabel = computed(() => t(getBlueprintStatusConfig(props.currentStatus).labelKey))

async function onApprove(): Promise<void> {
  const ok = await confirm({
    title: t('knowledge.blueprints.review.approveTitle'),
    description: t('knowledge.blueprints.review.approveBody'),
    confirmText: t('knowledge.blueprints.review.approveConfirm'),
    variant: 'default',
  })
  if (ok)
    emit('approve')
}

function onReject(): void {
  emit('reject')
}
</script>

<template>
  <div class="flex items-center gap-2">
    <!-- 与左侧内容的分隔只用容器 border-l 这一条 hairline（quick-260806 视觉整改：
         此前 Separator 组件与 border-l 并存，渲染成紧挨着的两条竖线）。 -->
    <div class="ml-auto flex items-center gap-2 border-l border-border pl-4">
      <Badge v-if="revisionRound > 0" variant="muted">
        {{ t('knowledge.blueprints.review.reviewRound', { n: revisionRound }) }}
      </Badge>

      <TooltipProvider :delay-duration="200">
        <Tooltip>
          <TooltipTrigger as-child>
            <span>
              <Button
                variant="default"
                size="sm"
                data-testid="blueprint-review-approve"
                :disabled="!canReview"
                @click="onApprove"
              >
                <span class="icon-[lucide--check-circle] mr-1.5" aria-hidden="true" />
                {{ t('knowledge.blueprints.review.approve') }}
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent v-if="!canReview">
            {{ t('knowledge.blueprints.review.disabledReason', { status: statusLabel }) }}
          </TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger as-child>
            <span>
              <Button
                variant="destructive"
                size="sm"
                data-testid="blueprint-review-reject"
                :disabled="!canReview"
                @click="onReject"
              >
                <span class="icon-[lucide--undo-2] mr-1.5" aria-hidden="true" />
                {{ t('knowledge.blueprints.review.reject') }}
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent v-if="!canReview">
            {{ t('knowledge.blueprints.review.disabledReason', { status: statusLabel }) }}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  </div>
</template>
