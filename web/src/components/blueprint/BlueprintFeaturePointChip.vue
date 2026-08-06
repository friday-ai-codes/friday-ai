<script setup lang="ts">
/**
 * 功能点 chip（quick-260806-fpx）。四处消费收敛成同一个视觉与交互口径：
 * 现状分析 finding 的 `related_feature_points`、实现概述模块卡的 `feature_point_ids`、
 * **实现项卡的 `feature_point_id`**（schema 必填项，115-05 起从未渲染 —— 实现项↔功能点
 * 在界面上一直是断链的），以及澄清向导的关联功能点。
 *
 * ⭐ **点击是主动作，hover 只是省一次跳转**：点击 emit `goto-anchor('fp-<id>')`；标题与
 * 验收摘要走 Tooltip 预览。⛔ 不把任何信息「只」挂在 hover 上 —— 触屏设备拿不到 hover，
 * 所以 id 常显、标题在 `show-title` 时常显，预览只是加速阅读。
 *
 * ⭐ **段内不自行滚动**：一律 emit 给页面（88px 偏移常量归页面统一处理）。
 *
 * 预览是纯只读文本 ⇒ 用 `Tooltip`（`role="tooltip"`，键盘 focus 触发与碰撞翻转免费拿到），
 * ⛔ 里面不放任何可点元素；要交互就该是 `Popover`，而这里不需要。
 *
 * ⚠️ **不用 `text-primary` 承载 11–12px 文字**：teal-500 在白底上约 2.4:1，远不到 4.5:1。
 * 「可点」由青色描边+底色+hover 加深+标题下划线承载，文字一律走 `foreground` 档。
 */

import type { BlueprintFeaturePoint } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip'
import {
  cleanFeaturePointTitle,
  intentLabelKeyOf,
  intentVariantOf,
} from '~/utils/blueprintFeaturePoints'

/**
 * 根是 `TooltipProvider`（provider 不出 DOM，且 open 态下 Tooltip 是 fragment 根）⇒
 * 自动 attr 继承会静默丢掉外部传的 class。显式接管，落到真正的按钮上。
 */
defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  /** 功能点 id；跳转锚点是 `fp-<id>`。 */
  pointId: string
  /** 完整功能点；缺失时只渲染 id + `title` 回退，预览不出 intent 与验收。 */
  point?: BlueprintFeaturePoint | null
  /** `point` 拿不到时的标题回退（澄清向导只有 id→标题 映射）。 */
  title?: string
  /** 是否在 chip 上直接渲染标题（模块卡/实现项卡传 true；纯 id 索引行传 false）。 */
  showTitle?: boolean
}>(), {
  point: null,
  title: '',
  showTitle: false,
})

const emit = defineEmits<{
  'goto-anchor': [domId: string]
}>()

const { t } = useI18n()

/** 预览里最多列几条验收要点（其余折成计数，⛔ 不把 tooltip 撑成第二个正文区）。 */
const ACCEPTANCE_PREVIEW_LIMIT = 3

const resolvedTitle = computed(
  () => cleanFeaturePointTitle(props.point?.title) || cleanFeaturePointTitle(props.title),
)

const intent = computed(() => props.point?.intent)

const intentLabel = computed(() => {
  const suffix = intentLabelKeyOf(intent.value)
  return suffix ? t(`knowledge.blueprints.spec.${suffix}`) : String(intent.value ?? '')
})

const acceptance = computed(() =>
  (props.point?.acceptance_criteria ?? [])
    .map(line => String(line ?? '').trim())
    .filter(Boolean),
)

const acceptanceShown = computed(() => acceptance.value.slice(0, ACCEPTANCE_PREVIEW_LIMIT))
const acceptanceRest = computed(() => Math.max(0, acceptance.value.length - acceptanceShown.value.length))

/** 三样都没有就不挂 tooltip：一个只重复 chip 上已有 id 的浮层是纯噪声。 */
const hasPreview = computed(
  () => Boolean(resolvedTitle.value) || Boolean(intent.value) || acceptance.value.length > 0,
)
</script>

<template>
  <TooltipProvider :delay-duration="220">
    <Tooltip>
      <TooltipTrigger as-child>
        <button
          v-bind="$attrs"
          type="button"
          class="group inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-md border border-primary/25 bg-primary/[0.06] px-1.5 py-0.5 text-xs transition-colors hover:border-primary/60 hover:bg-primary/12 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:outline-none"
          data-testid="blueprint-feature-point-chip"
          :data-feature-point-id="pointId"
          @click="emit('goto-anchor', `fp-${pointId}`)"
        >
          <span class="shrink-0 font-mono text-[11px] text-foreground/70 tabular-nums">{{ pointId }}</span>
          <!-- 标题在 `max-w-52` 处截断：不截的话一个长标题就把 chip 撑满整行，
               9 个功能点的模块卡会变成一条竖条；全文在 tooltip 里。 -->
          <span
            v-if="showTitle && resolvedTitle"
            class="min-w-0 max-w-52 truncate text-foreground decoration-primary/50 underline-offset-2 group-hover:underline"
          >{{ resolvedTitle }}</span>
        </button>
      </TooltipTrigger>

      <TooltipContent
        v-if="hasPreview"
        class="max-w-72 rounded-xl border border-border/70 bg-popover p-0 text-left font-normal text-foreground shadow-lg"
        data-testid="blueprint-feature-point-preview"
      >
        <div class="flex items-center gap-2 border-b border-border/60 px-3 py-2">
          <span class="font-mono text-[11px] text-muted-foreground">{{ pointId }}</span>
          <Badge v-if="intent" :variant="intentVariantOf(intent)" :data-intent="intent" class="ml-auto shrink-0">
            {{ intentLabel }}
          </Badge>
        </div>

        <div class="space-y-2 px-3 py-2.5">
          <!-- 预览标题走 `text-sm font-medium`：Heading 档（`text-base font-semibold`，UI-SPEC §14）
               归段标题与卡片标题，⛔ 不靠往中间插 `leading-*` 绕开源码守卫的正则。 -->
          <p v-if="resolvedTitle" class="text-sm leading-snug font-medium">
            {{ resolvedTitle }}
          </p>

          <div v-if="acceptanceShown.length">
            <p class="mb-1 text-[11px] font-medium text-muted-foreground">
              {{ t('knowledge.blueprints.spec.acceptanceCriteria') }}
            </p>
            <ul class="space-y-1">
              <li
                v-for="(line, index) in acceptanceShown"
                :key="index"
                class="flex gap-1.5 text-xs leading-snug text-foreground/85"
              >
                <span class="mt-1.5 size-1 shrink-0 rounded-full bg-muted-foreground/60" aria-hidden="true" />
                <span class="min-w-0">{{ line }}</span>
              </li>
            </ul>
            <p v-if="acceptanceRest" class="mt-1 text-[11px] text-muted-foreground">
              {{ t('knowledge.blueprints.spec.acceptanceRest', { n: acceptanceRest }) }}
            </p>
          </div>

          <p class="text-[11px] text-muted-foreground">
            {{ t('knowledge.blueprints.spec.gotoFeaturePoint') }}
          </p>
        </div>
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
