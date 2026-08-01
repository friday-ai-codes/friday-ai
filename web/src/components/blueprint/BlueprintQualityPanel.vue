<script setup lang="ts">
/**
 * 方案质量面板（Phase 115-04，UI-SPEC §11.2 / §20 断言 7）。
 *
 * ⭐ **本面板是 `blueprint_quality` 三项 DB 统计的唯一消费面**，闭 114-REVIEW **MN-05**
 * （口径已实装但全仓零消费方；`evaluate_blueprint_golden` 接不上 —— golden case 是静态
 * JSON fixture，没有 `artifact_id`）。
 *
 * ⭐ **`null` 渲染「暂无数据」，绝不显示 0。** `null` = 「没有数据源可算」，`0` = 「统计到了，
 * 值为零」，两者对评审是完全不同的结论：把「还没跑过 AI 审查」渲染成「零打回」会让评审据
 * 错误指标放行。⛔ 因此**禁止空值合并成零**这类写法 —— 它的坏处正是「`null` 用例转红而
 * `0` 用例仍绿」，三态并列用例（`null` / `0` / 正值）就是为逮它而存在。
 * 落地：`formatMetric()` 对 `null` / `undefined` 返回 `null`，模板按 `=== null` 分两支。
 *
 * ⭐ **引用覆盖率恒有值**（后端分母为 0 时返 `1.0`）⇒ 该格永远显示百分比。
 * 「空文档满分」是已知口径陷阱：`current_state_analysis` / `repo_associations` /
 * `impact_analysis` 三处**全空**时它也显示 100%。此时追加一枚旁注徽标，避免把「没内容」
 * 读成「证据齐备」。
 *
 * 旁注文案用 `quality.noKeyConclusions`（「无关键结论」，115-06 补键后换回）；
 * `title` 上仍挂三段名的完整说明，把「哪三处全空」讲清楚。
 */

import type { BlueprintQuality } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'

const props = withDefaults(defineProps<{
  quality: BlueprintQuality
  /**
   * `current_state_analysis` / `repo_associations` / `impact_analysis`
   * 三处是否至少有一处非空（由持有正文的父层判定）。
   */
  hasKeyConclusions?: boolean
}>(), {
  hasKeyConclusions: true,
})

const { t } = useI18n()

/**
 * ⭐ 三项可空指标的唯一格式化入口：无数据返回 `null`，模板据此分支。
 * ⛔ 不在这里替换成任何默认数值。
 */
function formatMetric(value: number | null | undefined, format: (n: number) => string): string | null {
  if (value === null || value === undefined)
    return null
  return format(value)
}

const percent = (n: number): string => `${(n * 100).toFixed(1)}%`
const plain = (n: number): string => String(n)

const citationCoverage = computed(() => percent(props.quality.citation_coverage))

const metrics = computed(() => [
  {
    key: 'aiRejectionRate',
    label: t('knowledge.blueprints.quality.aiRejectionRate'),
    value: formatMetric(props.quality.ai_rejection_rate, percent),
  },
  {
    key: 'humanEditVolume',
    label: t('knowledge.blueprints.quality.humanEditVolume'),
    value: formatMetric(props.quality.human_edit_volume, plain),
  },
  {
    key: 'clarificationRounds',
    label: t('knowledge.blueprints.quality.clarificationRounds'),
    value: formatMetric(props.quality.clarification_rounds, plain),
  },
])

/** 三段中文名并列，作为旁注徽标的 `title` 详解（说清「哪三处全空」）。 */
const noKeyConclusionsDetail = computed(() =>
  t('knowledge.blueprints.sectionEmpty', {
    name: [
      t('knowledge.blueprints.section.currentStateAnalysis'),
      t('knowledge.blueprints.section.repoAssociations'),
      t('knowledge.blueprints.section.impactAnalysis'),
    ].join(' / '),
  }),
)
</script>

<template>
  <section data-testid="blueprint-quality-panel" class="space-y-3">
    <h3 class="text-base font-semibold text-foreground">
      {{ t('knowledge.blueprints.quality.title') }}
    </h3>

    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <!-- 引用覆盖率：恒有值 -->
      <div data-testid="blueprint-quality-metric" data-metric="citationCoverage" class="card p-4">
        <p class="mb-1 text-sm text-muted-foreground">
          {{ t('knowledge.blueprints.quality.citationCoverage') }}
        </p>
        <p class="text-2xl font-semibold text-foreground">
          {{ citationCoverage }}
        </p>
        <Badge
          v-if="!hasKeyConclusions"
          data-testid="blueprint-quality-no-key-conclusions"
          variant="outline"
          class="mt-1.5"
          :title="noKeyConclusionsDetail"
        >
          {{ t('knowledge.blueprints.quality.noKeyConclusions') }}
        </Badge>
      </div>

      <!-- 三项可空指标：null ⇒ 暂无数据 -->
      <div
        v-for="metric in metrics"
        :key="metric.key"
        data-testid="blueprint-quality-metric"
        :data-metric="metric.key"
        class="card p-4"
      >
        <p class="mb-1 text-sm text-muted-foreground">
          {{ metric.label }}
        </p>
        <p v-if="metric.value === null" class="text-sm text-muted-foreground">
          {{ t('knowledge.blueprints.quality.noData') }}
        </p>
        <p v-else class="text-2xl font-semibold text-foreground">
          {{ metric.value }}
        </p>
      </div>
    </div>
  </section>
</template>
