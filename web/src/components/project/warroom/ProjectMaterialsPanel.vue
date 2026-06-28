<script setup lang="ts">
import type { Project } from '~/api/projects'
import { defineAsyncComponent } from 'vue'
import { useI18n } from 'vue-i18n'
import FeatureBoard from '~/components/project/warroom/FeatureBoard.vue'
import ProjectApiListCard from '~/components/project/warroom/ProjectApiListCard.vue'
import ProjectGalaxyCard from '~/components/project/warroom/ProjectGalaxyCard.vue'
import ProjectHealthCard from '~/components/project/warroom/ProjectHealthCard.vue'
import MembersTab from '~/components/project/workbench/MembersTab.vue'
import WorkItemsTab from '~/components/project/workbench/WorkItemsTab.vue'

// 左中右布局 · 右栏：项目所有资料的扁平堆叠展示（无卡片、无外边距，分隔线分区）。
// 各资料组件保持原样复用，卡片样式由本面板局部「拍平」（去描边/圆角/底色），
// 分区之间用 1px 分隔线区隔 —— 类 Figma / MasterGo 检视面板观感。
const props = defineProps<{ project: Project, canManage: boolean }>()

const { t } = useI18n()

const DocsSection = defineAsyncComponent(() => import('~/components/project/workbench/DocsSection.vue'))
const DependenciesSection = defineAsyncComponent(() => import('~/components/project/workbench/DependenciesSection.vue'))
const ArtifactTimeline = defineAsyncComponent(() => import('~/components/delivery/ArtifactTimeline.vue'))
const HumanTaskInbox = defineAsyncComponent(() => import('~/components/delivery/HumanTaskInbox.vue'))
</script>

<template>
  <div class="flex flex-col h-full min-h-0 bg-card" data-testid="warroom-materials">
    <!-- 面板头部 -->
    <header class="h-12 shrink-0 flex items-center gap-2 px-4 border-b border-border/60">
      <span class="section-chip"><span class="icon-[lucide--folder-git-2]" /></span>
      <h2 class="text-sm font-semibold text-foreground tracking-wide">
        {{ t('projects.warroom.workspace.materials') }}
      </h2>
    </header>

    <!-- 扁平资料流 -->
    <div class="materials flex-1 min-h-0 overflow-y-auto">
      <ProjectHealthCard :project="project" :can-manage="canManage" />

      <!-- 统一人类待办收件箱（P8）：一处看全待办（澄清/审批/接管/失败反应）并回流 -->
      <HumanTaskInbox />

      <FeatureBoard :project-id="project.id" />

      <!-- 工作项（裸组件，套扁平分区头） -->
      <section class="flat-section">
        <header class="flat-header">
          <span class="section-chip"><span class="icon-[lucide--list-checks]" /></span>
          <h3>{{ t('projects.tabs.workItems') }}</h3>
        </header>
        <div class="p-5">
          <WorkItemsTab :project-id="project.id" :can-manage="canManage" />
        </div>
      </section>

      <ProjectApiListCard :project-id="project.id" :can-manage="canManage" />
      <ProjectGalaxyCard :project-id="project.id" />

      <!-- 交付物版本轨 / 时间线（P7，只读）：按项目空间过滤技术方案产物 -->
      <ArtifactTimeline :space-id="project.space_id" artifact-type="technical_plan" />

      <DocsSection :project-id="project.id" />

      <!-- 成员（裸组件，套扁平分区头） -->
      <section class="flat-section">
        <header class="flat-header">
          <span class="section-chip"><span class="icon-[lucide--users]" /></span>
          <h3>{{ t('projects.tabs.members') }}</h3>
        </header>
        <div class="p-5">
          <MembersTab :project-id="project.id" :can-manage="canManage" />
        </div>
      </section>

      <DependenciesSection :project-id="project.id" />
    </div>
  </div>
</template>

<style scoped>
/* 拍平内部资料卡片：去描边/圆角/底色，仅保留内容；分区之间统一分隔线。 */
.materials > :deep(*) {
  border-top: 1px solid hsl(214 32% 91% / 0.7);
}

.materials > :deep(*:first-child) {
  border-top: none;
}

.materials :deep(.card) {
  border: 0 !important;
  border-radius: 0 !important;
  background: transparent !important;
}

.flat-header {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.875rem 1.25rem;
  border-bottom: 1px solid hsl(214 32% 91% / 0.5);
}

.flat-header h3 {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--color-foreground);
}
</style>
