<script setup lang="ts">
/**
 * 蓝图错误态的四档呈现（Phase 115-06，UI-SPEC §8.2）。
 *
 * ## ⭐ 404 为什么只有一句中性文案（本组件存在的头号理由）
 *
 * 后端对「artifact 根本没有」与「调用者不是蓝图所属项目的成员」这两种情形，刻意返回
 * **逐字相同**的 404（114-REVIEW MJ-03 的存在性防线）。前端只要把它翻成两句不同的话，
 * 攻击者就能靠差分枚举把那道防线拆掉 —— 换句话说，**多写一句文案 = 把后端的闸门打开**。
 * 因此 404 分支只允许出现下方模板里那**唯一一个**中性文案键，
 * 且**不渲染任何蓝图元信息**（标题 / 状态徽标 / 版本号一律不出现）。
 * `src/__tests__/blueprint-source-guard.spec.ts` 的断言 4 会在源码层面锁住这一条。
 *
 * ## 分档
 *
 * | 入参 `status` | 呈现 |
 * |---|---|
 * | `404` | 全页中性空态 + 「返回知识库」（按钮放 `CompactEmptyState` 的默认 slot） |
 * | `400` | 就近渲染，**原样回显** `detail`（⛔ 不自行改写措辞） |
 * | 其余（5xx / 0 网络失败） | 全页空态 + 「重试」，派发 `retry` |
 * | `401` / `403` | ⛔ 本组件不处理，交给 `~/api/client.ts` 既有的刷新与全局事件机制 |
 *
 * ⚠️ **`CompactEmptyState` 的两条契约**（P-6，抄错就什么都不显示）：它的 `icon` 收**裸名**
 * （组件内部自己拼成完整类名）；它**只有默认 slot**，没有承载按钮文案的 prop、也没有按钮事件
 * —— 既有 `pages/knowledge/entities/[id].vue:105-108` 三处都写错了，⛔ 不要照抄那一份。
 *
 * ⚠️ **`blueprint-gate/` 的非 200 不走本组件**（§8.2 例外一）：那条链没有项目范围闸，它的 404
 * 混合了「门未开」「artifact 不存在」「无蓝图会话」三种语义，状态码不携带任何权限信息。
 * ⚠️ **`chunk-at` / `charter` 的失败也不走本组件**（例外二）：一律由引用预览子件内部走快照兜底。
 */

import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Button } from '~/components/ui/button'

const props = withDefaults(defineProps<{
  /** `ApiError.status`；网络失败等无状态码的情形传 `0`。 */
  status: number
  /** `ApiError.detail`，只在 400 档原样回显。 */
  detail?: string
}>(), {
  detail: '',
})

const emit = defineEmits<{
  retry: []
}>()

const { t } = useI18n()

/** 404 = 不存在或无权，⭐ 两者共用同一句中性文案。 */
const isNeutral = computed(() => props.status === 404)
/** 400 = 入参层面的问题，就近回显后端原文。 */
const isInline = computed(() => props.status === 400)
</script>

<template>
  <div data-testid="blueprint-error-state" :data-status="status">
    <!-- ⭐ 404：唯一一句中性文案 + 返回入口；⛔ 不渲染任何蓝图元信息 -->
    <CompactEmptyState
      v-if="isNeutral"
      icon="lucide--lock"
      :title="t('knowledge.blueprints.error.notFoundOrForbidden')"
    >
      <Button as-child variant="outline" size="sm">
        <RouterLink to="/knowledge">
          {{ t('knowledge.blueprints.error.backToKnowledge') }}
        </RouterLink>
      </Button>
    </CompactEmptyState>

    <!-- 400：就近渲染，原样回显后端 detail -->
    <div
      v-else-if="isInline"
      class="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
      role="alert"
      data-testid="blueprint-error-inline"
    >
      <span class="icon-[lucide--alert-circle] mt-0.5 shrink-0" />
      <span class="min-w-0 break-words">{{ detail }}</span>
    </div>

    <!-- 5xx / 网络：全页 + 重试 -->
    <CompactEmptyState
      v-else
      icon="lucide--wifi-off"
      :title="t('knowledge.blueprints.error.unavailable')"
      :description="detail"
    >
      <Button variant="outline" size="sm" data-testid="blueprint-error-retry" @click="emit('retry')">
        <span class="icon-[lucide--refresh-cw] mr-1.5" />
        {{ t('knowledge.blueprints.error.retry') }}
      </Button>
    </CompactEmptyState>
  </div>
</template>
