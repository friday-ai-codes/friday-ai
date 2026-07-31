<script setup lang="ts">
/**
 * 编排产出卡片（109-04 / SPINE-01）— chat 内的「进入编码」入口。
 *
 * 最小可操作面（裁决 D-4）：只做入口，不做阅读面。
 *   - 不渲染方案正文、不折叠、无展开区、无骨架屏、无任何进度 / 阶段 UI
 *     （编排在途完全不呈现，阶段可见性整块留给 Phase 110）。
 *   - 不渲染后端 `message` / `placeholder` 自由文本：说明句一律取 COPY 常量。
 *     后端自由文本只用于留痕与排障，一旦让它上屏成为惯例，下一个产出路径
 *     就会带着 LLM 原文上屏。
 *
 * 点「进入编码」触发惰性投影（ArtifactVersion → CodingPlan），成功后**就地内嵌**
 * TechPlanCard，把投影响应直接作为 props 传下去 —— 不等一次 runtime 刷新，
 * 点击到卡片出现之间没有空窗、不依赖刷新时序。`activeCodingPlan` 仍是 sessions
 * 状态的实时来源（TechPlanCard 内部既有行为，不改）。
 */
import type { CodingPlanProvenance } from '~/types/chat'
import { ref } from 'vue'
import TechPlanCard from '~/components/chat/TechPlanCard.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { useToast } from '~/composables/useToast'
import { useChatStore } from '~/stores/chat'

const props = defineProps<{
  artifactVersionId: string
}>()

/**
 * 界面文案常量（UI-SPEC §Copywriting Contract 界面侧全表）。
 *
 * 沿用本组件家族硬编码中文常量惯例（`TOOL_LABELS` / `SIGNAL_LABELS` 先例），
 * 不接 vue-i18n。
 */
const COPY = {
  title: '技术方案已产出',
  badge: '已编排',
  description: '已完成仓库路由、代码召回与并行调研，可直接进入编码执行。',
  cta: '进入编码',
  ctaLoading: '正在准备编码方案…',
  projectedHint: '已进入编码，请在下方选择目标仓库',
  toastCreated: '编码方案已就绪，请选择目标仓库',
  toastReused: '已复用既有编码方案',
  toastFailed: '未能进入编码，请稍后重试',
} as const

const chatStore = useChatStore()
const { success: toastSuccess, error: toastError } = useToast()

const projecting = ref(false)

// 投影响应的本地态：直接喂内嵌 TechPlanCard 的 props（不经 runtime 中转）
const localCodingPlanId = ref<string | null>(null)
const localTitle = ref('')
const localTechPlan = ref('')
const localAffectedFiles = ref<Array<{ file_path?: string, path?: string, change_type: string }>>([])
const localRecommendedRepositoryIds = ref<string[]>([])
/**
 * 投影响应带回的来源标志。**不渲染原始取值**（上游非受控值上屏即泄漏面），
 * 109-08 起作为 provenance prop 交给内嵌 TechPlanCard 做草稿标注判定 —— 不传
 * 就会让编排产出的方案落到保守分支、被误挂草稿横幅并多一次确认弹层。
 */
const localProvenance = ref<CodingPlanProvenance | string | null>(null)

defineExpose({ localProvenance })

async function handleEnterCoding(): Promise<void> {
  if (projecting.value)
    return
  projecting.value = true
  try {
    const resp = await chatStore.projectPlanToCodingPlan(props.artifactVersionId)
    localCodingPlanId.value = resp.coding_plan_id
    localTitle.value = resp.title
    localTechPlan.value = resp.tech_plan
    localAffectedFiles.value = resp.affected_files ?? []
    localRecommendedRepositoryIds.value = resp.recommended_repository_ids ?? []
    localProvenance.value = resp.provenance
    // 幂等是系统正确性，不是用户需要理解的异常状态 ⇒ created=false 也走中性
    // success 通道，卡片表现与首次一致。
    toastSuccess(resp.created ? COPY.toastCreated : COPY.toastReused)
  }
  catch {
    // 不回显后端 detail 文案，错误提示取前端常量；按钮回到 idle 可重试。
    toastError(COPY.toastFailed)
  }
  finally {
    projecting.value = false
  }
}
</script>

<template>
  <div>
    <div class="card mt-2 animate-fade-in" data-test="orchestrated-plan-card">
      <div class="px-4 py-3 border-b border-border/50 flex items-center gap-2">
        <span class="icon-[lucide--workflow] text-primary" />
        <span class="text-sm font-semibold">{{ COPY.title }}</span>
        <Badge variant="success" class="ml-auto">
          {{ COPY.badge }}
        </Badge>
      </div>

      <div class="px-4 py-3">
        <p class="text-xs text-muted-foreground">
          {{ COPY.description }}
        </p>
      </div>

      <div class="px-4 pb-4 pt-1">
        <!--
          投影完成后按钮**替换为**说明行，而不是留一个可反复点击的按钮：
          幂等虽保证安全，但一个点了没反应的按钮是坏体验。
        -->
        <p
          v-if="localCodingPlanId"
          class="text-xs text-muted-foreground"
          data-test="projected-hint"
        >
          {{ COPY.projectedHint }}
        </p>
        <Button
          v-else
          data-test="enter-coding"
          :disabled="projecting"
          :aria-disabled="projecting ? 'true' : undefined"
          @click="handleEnterCoding"
        >
          <template v-if="projecting">
            <span class="icon-[lucide--loader-2] animate-spin mr-2" />
            {{ COPY.ctaLoading }}
          </template>
          <template v-else>
            <span class="icon-[lucide--arrow-right] mr-1" />
            {{ COPY.cta }}
          </template>
        </Button>
      </div>
    </div>

    <!-- 就地交棒：props 直接取投影响应，不等 runtime 刷新 -->
    <TechPlanCard
      v-if="localCodingPlanId"
      :plan-id="localCodingPlanId"
      :coding-plan-id="localCodingPlanId"
      :title="localTitle"
      :tech-plan="localTechPlan"
      :affected-files="localAffectedFiles"
      :provenance="localProvenance"
      :recommended-repository-ids="localRecommendedRepositoryIds"
      status="draft"
      :is-confirming="false"
    />
  </div>
</template>
