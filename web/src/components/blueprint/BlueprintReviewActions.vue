<script setup lang="ts">
/**
 * 人审终审操作区（Phase 115-04，FLOW-08，UI-SPEC §11.1 / §16）。
 *
 * **防误触第一层 = 视觉分离**：本组件是顶栏**最右侧**的独立区块，与左侧阅读动作之间用
 * `Separator` + `ml-auto` 隔开，容器 `pl-4 border-l border-border`。
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
 * ⚠️ i18n 缺口（§13.2 回报而不自补）：UI-SPEC §11.1 想要的是带状态插值的
 * `review.disabledReason`，而 `zh-CN.json` 里只有无参的 `review.disabledReadonly`。
 * 这里退化为「无参文案 + 状态中文名」两段并列，状态名取自
 * `getBlueprintStatusConfig(status).labelKey`。补键后只需换一处 `t()` 调用。
 */

import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Separator } from '~/components/ui/separator'
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
    <Separator orientation="vertical" class="h-6" />
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
            {{ t('knowledge.blueprints.review.disabledReadonly') }} · {{ statusLabel }}
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
            {{ t('knowledge.blueprints.review.disabledReadonly') }} · {{ statusLabel }}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  </div>
</template>
