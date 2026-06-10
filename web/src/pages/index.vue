<script setup lang="ts">
import type { DashboardStatsResponse } from '~/api/dashboard'
import { useHead } from '@vueuse/head'
import { gsap } from 'gsap'
import { getDashboardStats } from '~/api/dashboard'
import pulseRingsAnimation from '~/assets/lottie/pulseRings'
import DashboardActiveCoding from '~/components/dashboard/DashboardActiveCoding.vue'
import DashboardKpiCards from '~/components/dashboard/DashboardKpiCards.vue'
import DashboardQuickActions from '~/components/dashboard/DashboardQuickActions.vue'
import DashboardRecentActivity from '~/components/dashboard/DashboardRecentActivity.vue'
import DashboardSkillInstallTip from '~/components/dashboard/DashboardSkillInstallTip.vue'

useHead({
  title: '首页 - Friday AI',
})

// ============================================================================
// 入场动效：hero 弹入 → 文案错拍浮现 → 各 section 依次浮入；
// logo 背后叠加 Lottie 涟漪光环。全部遵循 prefers-reduced-motion。
// ============================================================================
const pageEl = ref<HTMLElement | null>(null)
const heroRingsEl = ref<HTMLElement | null>(null)

useLottie(heroRingsEl, pulseRingsAnimation)

useGsapReveal(pageEl, () => {
  gsap.timeline()
    .from('.hero-logo', { y: 20, scale: 0.78, autoAlpha: 0, duration: 0.6, ease: 'back.out(1.7)' })
    .from('.hero-line', { y: 14, autoAlpha: 0, duration: 0.45, stagger: 0.09, ease: 'power2.out' }, '-=0.3')
    .from('.dash-section', { y: 26, autoAlpha: 0, duration: 0.5, stagger: 0.1, ease: 'power2.out' }, '-=0.2')
})

const executionsStore = useExecutionsStore()

// 加载数据
const loading = ref(true)
const dashboard = ref<DashboardStatsResponse | null>(null)

onMounted(async () => {
  try {
    const [stats] = await Promise.all([
      getDashboardStats(),
      executionsStore.fetchExecutions(),
    ])
    dashboard.value = stats
  }
  finally {
    loading.value = false
  }
})

// 统计卡片数据（累计 + 今日新增）
const stats = computed(() => {
  const s = dashboard.value?.stats
  return [
    {
      title: '仓库',
      value: s?.repositories.total ?? 0,
      todayNew: s?.repositories.today ?? 0,
      icon: 'icon-[lucide--folder-git-2]',
      link: '/repositories',
    },
    {
      title: '代码关联',
      value: s?.code_relations.total ?? 0,
      todayNew: s?.code_relations.today ?? 0,
      icon: 'icon-[lucide--waypoints]',
      link: '/codegraph/galaxy',
    },
    {
      title: '完成编码',
      value: s?.codings.total ?? 0,
      todayNew: s?.codings.today ?? 0,
      icon: 'icon-[lucide--code-xml]',
      link: '/executions',
    },
    {
      title: '技术方案',
      value: s?.tech_plans.total ?? 0,
      todayNew: s?.tech_plans.today ?? 0,
      icon: 'icon-[lucide--file-text]',
      link: '/chat',
    },
    {
      title: '回答问题',
      value: s?.questions.total ?? 0,
      todayNew: s?.questions.today ?? 0,
      icon: 'icon-[lucide--message-square]',
      link: '/chat',
    },
    {
      title: '沉淀文档',
      value: s?.documents.total ?? 0,
      todayNew: s?.documents.today ?? 0,
      icon: 'icon-[lucide--book-open]',
      link: '/chat',
    },
  ]
})

// 快捷操作
const quickActions = [
  {
    icon: 'lucide--plus',
    title: '新建空间',
    description: '创建新的开发空间',
    link: '/spaces/new',
    iconBg: 'stat-icon-primary',
  },
  {
    icon: 'lucide--workflow',
    title: '工作流管理',
    description: '编排自动化流程',
    link: '/workflows',
    iconBg: 'stat-icon-primary',
  },
  {
    icon: 'lucide--play-circle',
    title: '执行监控',
    description: '查看运行状态',
    link: '/executions',
    iconBg: 'stat-icon-primary',
  },
  {
    icon: 'lucide--git-branch',
    title: '仓库管理',
    description: '管理代码仓库',
    link: '/repositories',
    iconBg: 'stat-icon-primary',
  },
  {
    icon: 'lucide--message-square',
    title: 'AI 对话',
    description: '与 AI 助手交流',
    link: '/chat',
    iconBg: 'stat-icon-primary',
  },
]
</script>

<template>
  <div ref="pageEl" class="max-w-[1200px] mx-auto space-y-8">
    <!-- Hero 区域 — sub2api 风格简洁 -->
    <section class="text-center pt-6 pb-2">
      <div class="hero-logo relative mx-auto w-20 h-20 mb-5">
        <!-- Lottie 涟漪光环：扩散在 logo 背后，营造「系统在运转」的氛围 -->
        <div
          ref="heroRingsEl"
          class="absolute -inset-7 pointer-events-none"
          aria-hidden="true"
        />
        <img
          src="/logo-mark.svg"
          alt="Friday"
          class="relative w-20 h-20 drop-shadow-[0_4px_20px_rgba(20,184,166,0.2)]"
        >
      </div>
      <h1 class="sr-only">
        Friday AI
      </h1>
      <img
        src="/logo-wordmark.svg"
        alt="friday"
        aria-hidden="true"
        class="hero-line mx-auto h-9 md:h-10 w-auto mb-3"
      >
      <p class="hero-line text-muted-foreground text-base max-w-lg mx-auto">
        AI 驱动的敏捷开发自动化系统
      </p>
      <p class="hero-line text-primary text-sm mt-1">
        无缝集成飞书项目管理和 Claude Code
      </p>
    </section>

    <!-- Skill 安装提示 — 可关闭 -->
    <DashboardSkillInstallTip class="dash-section" />

    <!-- 统计卡片 — KPI widget（累计 + 今日新增） -->
    <DashboardKpiCards class="dash-section" :stats="stats" :loading="loading" />

    <!-- 进行中的编码工作 -->
    <DashboardActiveCoding
      class="dash-section"
      :count="dashboard?.in_progress.coding.count ?? 0"
      :items="dashboard?.in_progress.coding.items ?? []"
      :loading="loading"
    />

    <!-- 快捷操作 — 紧凑横排 -->
    <DashboardQuickActions class="dash-section" :actions="quickActions" />

    <!-- 最近执行 — 活动 widget -->
    <DashboardRecentActivity class="dash-section" :executions="executionsStore.executions" :loading="loading" />
  </div>
</template>
