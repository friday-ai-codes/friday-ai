<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { knowledgeApi } from '~/api'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { useErrorHandler } from '~/composables/useErrorHandler'

// 交付文档树（KDEP-04）：一次加载整棵可见树后做客户端展开/渲染，前端零拼装。
// 本组件只做渲染/展开/计数/徽标/图标/空态；树内搜索与叶子查看由 97-03 追加。

const { t } = useI18n()
const { handleError } = useErrorHandler()

// 工件类型徽标配色令牌（与 index.vue Phase 96 令牌一致，视觉统一）。
const ARTIFACT_BADGE_CLASS = 'bg-amber-500/10 text-amber-700 border-amber-200 dark:text-amber-400'

// 载体图标映射：字面量完整 class 字符串，确保 Tailwind 源扫描命中、无需改 safelist。
const CARRIER_ICON: Record<string, string> = {
  feishu_doc: 'icon-[lucide--file-text]',
  feishu_bitable: 'icon-[lucide--table]',
  markdown: 'icon-[lucide--file-text]',
  repo_file: 'icon-[lucide--file-code]',
  external_link: 'icon-[lucide--external-link]',
}
function carrierIcon(carrier: string): string {
  return CARRIER_ICON[carrier] ?? 'icon-[lucide--file]'
}

const { data, isLoading, isError, error } = useQuery({
  queryKey: ['knowledge', 'artifact-tree'],
  queryFn: () => knowledgeApi.fetchArtifactTree(),
  staleTime: 60_000,
})

watch(isError, (v) => {
  if (v)
    handleError(error.value, t('knowledge.tree.docs.loadFailed'))
})

// 展开状态：默认全部展开（数据规模小，直接可见更好用）。数据到达时以全部 key 初始化两个集合。
const expandedProjects = ref(new Set<string>())
const expandedTypes = ref(new Set<string>())

function typeId(projectId: string, typeKey: string): string {
  return `${projectId}:${typeKey}`
}

watch(data, (tree) => {
  if (!tree)
    return
  const projs = new Set<string>()
  const types = new Set<string>()
  for (const p of tree.projects) {
    projs.add(p.project_id)
    for (const ty of p.types)
      types.add(typeId(p.project_id, ty.type_key))
  }
  expandedProjects.value = projs
  expandedTypes.value = types
}, { immediate: true })

function isProjectOpen(projectId: string): boolean {
  return expandedProjects.value.has(projectId)
}

function isTypeOpen(projectId: string, typeKey: string): boolean {
  return expandedTypes.value.has(typeId(projectId, typeKey))
}

function toggleProject(projectId: string): void {
  const next = new Set(expandedProjects.value)
  if (next.has(projectId))
    next.delete(projectId)
  else
    next.add(projectId)
  expandedProjects.value = next
}

function toggleType(projectId: string, typeKey: string): void {
  const key = typeId(projectId, typeKey)
  const next = new Set(expandedTypes.value)
  if (next.has(key))
    next.delete(key)
  else
    next.add(key)
  expandedTypes.value = next
}

function formatDate(updatedAt: string | null): string {
  if (!updatedAt)
    return ''
  return new Date(updatedAt).toLocaleDateString()
}
</script>

<template>
  <div data-testid="artifact-tree">
    <!-- 加载态 -->
    <div v-if="isLoading" class="flex items-center justify-center py-20 text-muted-foreground">
      <span class="icon-[lucide--loader-2] mr-2 h-5 w-5 animate-spin" />
      {{ t('knowledge.tree.docs.loading') }}
    </div>

    <!-- 整树空态：指向作战室「外部依赖」维护入口 -->
    <div v-else-if="!data || data.total === 0 || data.projects.length === 0" class="flex min-h-[380px] items-center justify-center">
      <CompactEmptyState
        icon="lucide--folder-tree"
        :title="t('knowledge.tree.docs.empty.title')"
        :description="t('knowledge.tree.docs.empty.body')"
      />
    </div>

    <!-- 树内容 -->
    <div v-else class="space-y-2">
      <!-- 截断提示 -->
      <div
        v-if="data.truncated"
        class="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400"
      >
        <span class="icon-[lucide--info] h-3.5 w-3.5 shrink-0" />
        {{ t('knowledge.tree.docs.truncated') }}
      </div>

      <div class="max-h-[64vh] space-y-1 overflow-y-auto pr-1">
        <!-- 项目节点（顶层） -->
        <div v-for="project in data.projects" :key="project.project_id">
          <button
            type="button"
            class="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted/60"
            @click="toggleProject(project.project_id)"
          >
            <span
              class="h-3.5 w-3.5 shrink-0 text-muted-foreground"
              :class="isProjectOpen(project.project_id) ? 'icon-[lucide--chevron-down]' : 'icon-[lucide--chevron-right]'"
            />
            <span class="icon-[lucide--folder] h-4 w-4 shrink-0 text-muted-foreground" />
            <span class="flex-1 truncate text-sm font-medium">{{ project.project_name }}</span>
            <span class="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{{ project.count }}</span>
          </button>

          <!-- 类型节点（二层） -->
          <div v-if="isProjectOpen(project.project_id)" class="ml-4 space-y-1 border-l border-border/60 pl-2">
            <div v-for="typeGroup in project.types" :key="typeGroup.type_key">
              <button
                type="button"
                class="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left transition-colors hover:bg-muted/60"
                @click="toggleType(project.project_id, typeGroup.type_key)"
              >
                <span
                  class="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                  :class="isTypeOpen(project.project_id, typeGroup.type_key) ? 'icon-[lucide--chevron-down]' : 'icon-[lucide--chevron-right]'"
                />
                <span
                  class="inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-medium"
                  :class="ARTIFACT_BADGE_CLASS"
                >
                  {{ typeGroup.type_name }}
                </span>
                <span class="flex-1" />
                <span class="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{{ typeGroup.count }}</span>
              </button>

              <!-- 叶子（三层）：本 plan 为展示行，点击查看由 97-03 追加 -->
              <div v-if="isTypeOpen(project.project_id, typeGroup.type_key)" class="ml-4 space-y-0.5 border-l border-border/60 pl-2">
                <div
                  v-for="leaf in typeGroup.artifacts"
                  :key="leaf.artifact_id"
                  class="flex items-center gap-2 rounded-md px-2 py-1 text-sm"
                  data-testid="artifact-leaf"
                >
                  <span :class="carrierIcon(leaf.carrier)" class="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span class="flex-1 truncate">{{ leaf.title }}</span>
                  <span v-if="leaf.updated_at" class="shrink-0 text-[11px] text-muted-foreground">{{ formatDate(leaf.updated_at) }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
