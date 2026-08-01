<script setup lang="ts">
/**
 * 编排在途阶段时间线卡（110-06 / OBS-01 / OBS-03）。
 *
 * 卡底与卡头骨架**逐字沿用** `OrchestratedPlanCard.vue:108-115`（`.card mt-2 animate-fade-in`
 * + `px-4 py-3 border-b border-border/50 flex items-center gap-2` + `icon-[lucide--workflow]`），
 * 让「在途 → 完成」在用户眼里是**同一张卡在变**，而不是一张卡消失、另一张卡出现。
 *
 * 三条不可省的裁定（UI-SPEC §A.5 / §A.6 / §F）：
 *
 * 1. 🔴 **时间线自身的终态就是完成信号**：`done` 时卡头标题变「方案编排已完成」。
 *    异步路径上 `OrchestratedPlanCard` 是否出现不由本 phase 保证，若时间线在 `done`
 *    时直接消失，用户看到的是「跑完了，然后什么都没有」。所以是**收敛为一行**，不是消失。
 * 2. 🔴 **至少一条已知事实才渲染**。`buildOrchestrationTimeline` 对空输入返回的是
 *    「六步全 pending」而不是空数组（110-05 交棒结论），所以这道门必须由本组件把。
 *    否则历史消息会渲染出一个全灰空壳 —— 那是在告诉用户「我们丢了东西」，而实际上
 *    这条消息本来就从没有过进度信息（§E.3 末行明令禁止）。
 * 3. 🔴 **观测代码绝不反噬业务**：整个视图 computed 包 `try/catch`，异常一律降级为
 *    「整块不渲染」。编排跑通比进度可见重要得多。
 *
 * 本组件**不渲染**归属他处的任何事实（§D.1）：confidence 徽标、候选仓列表与分数、
 * 澄清卡本身、方案正文与影响文件。「路由」步行尾那个 `降级` 角标由 `SubStepTimeline`
 * 渲染（数据来自 110-05 的 `badge` 字段），本组件不另画。
 *
 * §D.1 的一处**修订**（RELY-03 缺口闭环）：降级横幅与它的解释句原本也在「归属他处」
 * 这一列，那个「他处」是 `RoutingDecisionPanel` —— 一个 2026-05-29 起就没有挂载点的
 * 组件。编排链路上不存在第二块显示候选与置信度的面，于是用户能拿到的全部信息就是
 * 那两个字「降级」。解释句因此归位到本卡：角标标位置，横幅说人话。
 * 对话工具链路的同一句话由 `RoutingCandidateList` 承载，两条链各有各的宿主，不重复。
 */
import { computed, ref, useId, watch } from 'vue'
import SubStepTimeline from '~/components/execution/dag/SubStepTimeline.vue'
// 🔴 显式 import COPY，不依赖 auto-import：110-05 的导出让 `COPY` 进了全局命名空间，
// 靠注入拿到的是「碰巧同名」而不是「明确依赖」。
import { buildOrchestrationTimeline, COPY } from '~/composables/useOrchestrationTimeline'
import { useChatStore } from '~/stores/chat'

const props = defineProps<{
  /** 绑定的编排会话 id。**本组件不接受任何后端自由文本作为渲染入参。** */
  sessionId: string
}>()

/**
 * 本组件独有的可访问性文案（§Copywriting Contract 时间线全表）。
 * 其余全部取 110-05 导出的 `COPY`，避免同一批中文串在两处各写一份而漂移。
 */
const A11Y_COPY = {
  expand: '展开编排进度',
  collapse: '收起编排进度',
} as const

const chatStore = useChatStore()

/** 正文区 id：`aria-controls` 必须指向真实存在的节点。 */
const bodyId = useId()

/**
 * 时间线视图。`null` ⇒ 整块不渲染。
 *
 * 三条渲染条件（§A.5）在这里合成一个判定：会话 id 非空、store 里有这个桶、
 * 桶里至少有一条已知事实。任一不成立返回 `null`，**不抛错、不打 warn**——
 * 历史消息与老后端走的就是这条路径，那不是异常。
 */
const view = computed(() => {
  try {
    const sessionId = props.sessionId
    if (!sessionId)
      return null

    const bucket = chatStore.orchestrationSessions?.[sessionId]
    if (!bucket)
      return null

    const hasEvents = Array.isArray(bucket.events) && bucket.events.length > 0
    const hasSnapshot = bucket.snapshot !== null && bucket.snapshot !== undefined
    if (!hasEvents && !hasSnapshot)
      return null

    return buildOrchestrationTimeline({
      snapshot: bucket.snapshot ?? null,
      events: Array.isArray(bucket.events) ? bucket.events : [],
      runtimeActive: chatStore.orchestrationRuntimeActive === true,
    })
  }
  catch {
    // 进度解析异常吞掉：整块不渲染，对话正文与工具气泡照常。
    return null
  }
})

/** 折叠态：组件本地 `ref`，**不写 store、不做任何持久化**（§Backstop 10）。 */
const collapsed = ref(false)
/** 自动折叠的一次性 flag —— 「只在首次到达 done 时折叠」的落点。 */
const autoCollapsed = ref(false)

/**
 * 终态收敛（§A.6 规则表）。
 *
 * 🔴 **只触发一次**：用户手动展开后不再被自动折叠回去。进度是过程信息，完成后默认
 * 让位给结果，但用户想回看时不能被抢走。缺了这个 flag 的实现在「每次快照到达都重折」
 * 时同样能通过「done 即折叠」那条用例，所以一次性语义有独立用例锁。
 *
 * 🔴 `failed` **不自动折叠**：红步与闭集原因行必须保持可见。
 *
 * `sessionId` 与 `phase` 合并成一个 watch 源，是为了让「换会话」的重置与「新会话已是
 * done」的折叠在同一拍里按正确顺序发生：拆成两个 watch 时，两者的注册顺序会决定
 * 「A(running) → B(done)」这种切换是否折叠，那是靠巧合而不是靠语义。
 */
watch(
  () => [props.sessionId, view.value?.phase] as const,
  ([sessionId, phase], previous) => {
    if (previous && sessionId !== previous[0]) {
      collapsed.value = false
      autoCollapsed.value = false
    }
    if (phase === 'done' && !autoCollapsed.value) {
      autoCollapsed.value = true
      collapsed.value = true
    }
  },
  { immediate: true },
)

/** 自动折叠**不移动焦点、不 autofocus**；折叠按钮不被卸载，只换 `aria-expanded`。 */
function toggleCollapsed(): void {
  collapsed.value = !collapsed.value
}
</script>

<template>
  <div
    v-if="view"
    class="card mt-2 animate-fade-in"
    role="group"
    aria-label="方案编排进度"
    data-test="orchestration-stage-timeline"
  >
    <div class="px-4 py-3 border-b border-border/50 flex items-center gap-2">
      <span class="icon-[lucide--workflow] text-primary" />
      <span class="text-sm font-semibold" data-test="timeline-title">{{ view.title }}</span>
      <!-- 步数用纯文本计数，不用 Badge：徽标的垂直尺寸在 11px 行里过重（沿用 DeepAnalysisCard:56） -->
      <span class="text-[10px] text-muted-foreground ml-auto" data-test="timeline-step-count">
        {{ COPY.stepCount(view.doneCount, view.totalCount) }}
      </span>
      <button
        type="button"
        class="text-muted-foreground"
        data-test="timeline-toggle"
        :aria-expanded="collapsed ? 'false' : 'true'"
        :aria-controls="bodyId"
        :aria-label="collapsed ? A11Y_COPY.expand : A11Y_COPY.collapse"
        @click="toggleCollapsed"
      >
        <span
          class="icon-[lucide--chevron-right] block transition-transform"
          :class="collapsed ? '' : 'rotate-90'"
        />
      </button>
    </div>

    <!-- 卡内唯一的实时播报区（§F）。内容只来自 composable，绝不在这里另拼步数计数。 -->
    <p class="sr-only" role="status" aria-live="polite" data-test="timeline-live">
      {{ view.liveMessage }}
    </p>

    <!--
      v-show 而非 v-if：`aria-controls` 必须指向真实存在的节点，而 v-if 在收起态
      会把它整块摘掉、让按钮上的 aria-controls 悬空。代价是折叠态下 SubStepTimeline
      仍在渲染树里（六行 DOM），可接受。
    -->
    <div v-show="!collapsed" :id="bodyId" class="px-4 pb-3 pt-1">
      <!--
        降级横幅（RELY-03）。置于步骤之上：先说清「置信度本次不可信」，再让用户
        看进度。不挂 aria-live —— 本卡的播报归口是上面那个唯一的 live region
        （§A.6），在这里再加一个会让同一个事实播两次。
      -->
      <div
        v-if="view.degraded"
        role="alert"
        class="mb-1 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-2.5 py-2"
        data-test="timeline-degraded-banner"
      >
        <span class="icon-[lucide--triangle-alert] mt-0.5 shrink-0 text-[11px] text-amber-600" />
        <div class="min-w-0 space-y-0.5">
          <p class="text-[11px] font-medium text-foreground">
            {{ COPY.degradedTitle }}
          </p>
          <p v-if="view.degradeReasonLabel" class="text-[10px] text-muted-foreground">
            {{ COPY.degradedReason(view.degradeReasonLabel) }}
          </p>
        </div>
      </div>
      <SubStepTimeline :steps="view.steps" :interactive="false" />
    </div>
  </div>
</template>
