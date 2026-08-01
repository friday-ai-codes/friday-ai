<script setup lang="ts">
/**
 * 方案调研的容器日志组（110-07 / OBS-02）。
 *
 * 一次跨仓编排会给每个参与仓起一个调研容器，本组件把它们**按仓一张卡、纵向堆叠**地摊开。
 *
 * 三条不可省的裁定（UI-SPEC §C.1 / §C.2 / §C.4）：
 *
 * 1. 🔴 **不用 `DeepAnalysisGroup`**。两条实读理由，都不是偏好：
 *    ① 它的多项形态是横向 swiper，一次只看得见一个仓 —— 恰好把「并行」这件事藏起来，
 *       而「并行调研」正是本组要让用户看见的东西；
 *    ② 它的 bar 标题 `深度分析 · {n} 个子任务` 写死在模板里、没有任何 prop 能改，
 *       在 chat 侧接受一个说「深度分析」的容器会让用户把两种东西混为一谈。
 *    若后续确实想要 swiper 形态，正确做法是给 `DeepAnalysisGroup` 加一个默认值为
 *    今日文案的 `title` prop，而不是在这里将就。
 * 2. 🔴 **`DeepAnalysisCard` 零改动**。`PlanResearchSession` 与 `DeepAnalysisSession`
 *    只差一层浅适配（`logs` 两侧逐字同形，`decorateDeepLog` 可直接解码），
 *    卡片标题走它既有的 `taskLabel` 优先级即可。
 * 3. 🔴 **不消失**：编排完成后日志组仍在（OBS-02 要的是「可查」而不只是「可见」），
 *    整组可折叠。折叠态是组件本地 `ref`，不写 store、不入 localStorage。
 *
 * 空态：`sessions` 为空 ⇒ **整组不渲染**（不占位、不写「暂无日志」）。单仓有会话但
 * `logs` 为空时交给 `DeepAnalysisCard` 既有空态（`正在执行…` / `暂无执行记录`），
 * 本组件不另写文案。
 */
import type { DeepAnalysisSession, PlanResearchSession } from '~/types/chat'
import { computed, ref } from 'vue'
import DeepAnalysisCard from './DeepAnalysisCard.vue'

const props = defineProps<{
  /** 本气泡绑定的那次编排会话下的调研容器（调用方已按 `plan_session_id` 过滤）。 */
  sessions: PlanResearchSession[]
  /** 会话级 `repository_id → 仓库名` 映射，仓库名解析的第二级来源。 */
  repoNames?: Record<string, string>
}>()

/**
 * 本组件的全部中文串（§Copywriting Contract 调研日志组表）。
 * 卡内的步数与空态**沿用 `DeepAnalysisCard` 既有文案**，不在这里覆写。
 */
const COPY = {
  groupTitle: (n: number) => `方案调研 · ${n} 个仓库`,
  expand: '展开方案调研日志',
  collapse: '收起方案调研日志',
  unknownRepo: '未知仓库',
} as const

const collapsed = ref(false)

/** 折叠区的 id：供按钮 `aria-controls` 指向，读屏才能建立按钮↔区域的关联。 */
const listId = useId()

/**
 * §C.4「整组默认收起」的一次性自动折叠。
 *
 * 不收起会让编排完成后的版面变成：时间线自己收敛成一行，紧跟一个**完全展开**的日志组
 * （首张卡日志区最高 22rem），把刚产出的 `OrchestratedPlanCard` 挤出视口 —— 两块新 UI
 * 的收敛策略不一致，而契约要求它们一起给结果让位。
 *
 * 判据取「所有调研容器都已到终态」而非编排整体终态：本组件只拿得到调研会话，不该为此
 * 去耦合编排阶段。两个时刻实际紧邻（调研终态 → 融合 → 出卡），且容器一到终态日志就不再
 * 增长，此时收起没有信息损失。
 *
 * 一次性 flag：用户手动展开后不再被抢走（沿用 `OrchestrationStageTimeline.autoCollapsed`
 * 的同款语义）。
 */
const autoCollapsed = ref(false)
watch(
  () => props.sessions.length > 0 && props.sessions.every(s => cardStatus(s) === 'done'),
  (allSettled) => {
    if (allSettled && !autoCollapsed.value) {
      autoCollapsed.value = true
      collapsed.value = true
    }
  },
  { immediate: true },
)

/**
 * 仓库名解析（§A.4 顺序）：后端解析出的名字 → 会话级映射 → 常量。
 * 🔴 第三级是常量而**不是** `repository_id` —— 裸 UUID 上屏既无信息量又暴露内部标识。
 */
function repoLabel(session: PlanResearchSession): string {
  const own = session.repository_name
  if (typeof own === 'string' && own !== '')
    return own
  const mapped = props.repoNames?.[session.repository_id]
  if (typeof mapped === 'string' && mapped !== '')
    return mapped
  return COPY.unknownRepo
}

/**
 * `SubAgentSession.Status`（PENDING / RUNNING / COMPLETED / ERROR / …）
 * → `DeepAnalysisCard` 的二值 `status`。大小写不敏感。
 */
function cardStatus(session: PlanResearchSession): 'running' | 'done' {
  const raw = (session.status ?? '').toUpperCase()
  return raw === 'PENDING' || raw === 'RUNNING' ? 'running' : 'done'
}

/**
 * 浅适配成 `DeepAnalysisSession` 形状。原始 `status` **原样带上**：
 * `DeepAnalysisCard` 内部的 `isRunning` 还会自己看 `session.status`，两侧判定要一致。
 */
const cards = computed(() => props.sessions.map((session, index) => ({
  key: session.session_id || `${session.repository_id}-${index}`,
  session: {
    session_id: session.session_id,
    status: session.status,
    logs: Array.isArray(session.logs) ? session.logs : [],
  } satisfies DeepAnalysisSession,
  taskLabel: repoLabel(session),
  status: cardStatus(session),
  /**
   * 展开策略（§C.2）：单仓即首张，多仓也**只有首张**展开。
   * `DeepAnalysisCard` 的日志区 `max-height: 22rem`，5 个仓全展开会把整条对话顶飞；
   * 它的 `defaultExpanded` 是 mount 时读一次的 ref、不随状态变化重置 ——
   * 这正好是我们要的：用户展开谁就是谁，不会被后到的日志抢回去。
   */
  defaultExpanded: index === 0,
})))
</script>

<template>
  <div v-if="cards.length > 0" class="mt-2" data-test="plan-research-log-group">
    <!--
      🔴 可访问名称必须**包含**可见文案（WCAG 2.5.3 Label in Name，Level A）。
      reka-ui 无关：这里是原生 button，`aria-label` 会整体覆盖内部文本 ——
      原先只播报「展开方案调研日志」，读屏用户永远听不到有几个仓库。
      故把组标题拼在前面，而不是覆盖它；契约的展开/收起文案同时保住。
    -->
    <button
      type="button"
      class="flex items-center gap-2 px-1 pb-2"
      :aria-expanded="collapsed ? 'false' : 'true'"
      :aria-label="`${COPY.groupTitle(cards.length)}，${collapsed ? COPY.expand : COPY.collapse}`"
      :aria-controls="listId"
      data-test="plan-research-log-toggle"
      @click="collapsed = !collapsed"
    >
      <span class="icon-[lucide--search-code] text-[11px] text-primary" />
      <span class="text-[11px] font-semibold">{{ COPY.groupTitle(cards.length) }}</span>
    </button>

    <!-- v-show 而非 v-if：节点常驻，`aria-controls` 在收起态也指向真实存在的节点 -->
    <div v-show="!collapsed" :id="listId" class="space-y-2">
      <DeepAnalysisCard
        v-for="card in cards"
        :key="card.key"
        :session="card.session"
        :task-label="card.taskLabel"
        :status="card.status"
        :default-expanded="card.defaultExpanded"
      />
    </div>
  </div>
</template>
