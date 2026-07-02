<script setup lang="ts">
import type { FeatureNode, FeatureState } from '~/api/projectWorkspace'
import { useQuery } from '@tanstack/vue-query'
import { computed, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import EmptyState from '~/components/common/EmptyState.vue'
import InlineMarkdown from '~/components/common/InlineMarkdown.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'

// WB-02：模块 → 功能点 → 验收项 三层折叠树 + 进度灯（数据来自 84-01 getFeatureList）。
const props = defineProps<{ projectId: string }>()

const { t } = useI18n()
const projectIdRef = toRef(props, 'projectId')

const { data, isLoading, isError, refetch } = useQuery({
  queryKey: ['project-features', projectIdRef],
  queryFn: () => projectWorkspaceApi.getFeatureList(props.projectId),
})

const modules = computed<FeatureNode[]>(() => data.value ?? [])

// 进度灯语义色（UI-SPEC：待开发 muted / 进行中 teal / 测试中 amber / 已完成 emerald）。
const STATE_CLASS: Record<FeatureState, string> = {
  todo: 'bg-muted text-muted-foreground',
  in_progress: 'bg-primary/15 text-primary',
  testing: 'bg-amber-500/15 text-amber-500',
  done: 'bg-emerald-500/15 text-emerald-500',
}

function normalizeState(state?: FeatureState): FeatureState {
  return state && state in STATE_CLASS ? state : 'todo'
}

function children(node: FeatureNode): FeatureNode[] {
  return node.children ?? []
}
</script>

<template>
  <section class="card" data-testid="workbench-feature-section">
    <header class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
      <span class="icon-[lucide--list-tree] text-primary" />
      <h2 class="text-sm font-semibold text-foreground">
        {{ t('projects.workbench.feature.title') }}
      </h2>
    </header>

    <div class="p-5">
      <!-- 加载 -->
      <LoadingState v-if="isLoading" variant="skeleton" :count="3" />

      <!-- 错误 + 行内重试 -->
      <div v-else-if="isError" class="py-8 text-center space-y-2" data-testid="feature-error">
        <p class="text-sm text-destructive">
          {{ t('projects.workbench.feature.loadError') }}
        </p>
        <button class="text-sm text-primary underline" @click="() => refetch()">
          {{ t('projects.retry') }}
        </button>
      </div>

      <!-- 空态 -->
      <EmptyState
        v-else-if="modules.length === 0"
        icon="lucide--list-tree"
        :title="t('projects.workbench.feature.emptyTitle')"
        :description="t('projects.workbench.feature.emptyDesc')"
      />

      <!-- 三层折叠树 -->
      <div v-else class="space-y-2">
        <Collapsible
          v-for="(mod, mi) in modules"
          :key="`m-${mi}`"
          default-open
          class="rounded-lg border border-border/40 bg-card"
        >
          <CollapsibleTrigger
            class="group flex w-full items-center gap-2 px-3 py-2.5 text-left"
            data-testid="feature-module"
          >
            <span class="icon-[lucide--chevron-right] text-xs text-muted-foreground transition-transform group-data-[state=open]:rotate-90" />
            <span class="icon-[lucide--folder] text-primary" />
            <span class="text-sm font-medium text-foreground truncate"><InlineMarkdown :text="mod.name" /></span>
          </CollapsibleTrigger>

          <CollapsibleContent class="px-3 pb-2">
            <p
              v-if="children(mod).length === 0"
              class="pl-7 py-2 text-xs text-muted-foreground"
            >
              {{ t('projects.workbench.feature.noFeatures') }}
            </p>

            <Collapsible
              v-for="(feat, fi) in children(mod)"
              :key="`f-${mi}-${fi}`"
              default-open
              class="border-t border-border/30 first:border-t-0"
            >
              <div class="flex items-center justify-between gap-2 pl-5">
                <CollapsibleTrigger
                  class="group flex min-w-0 flex-1 items-center gap-2 py-2 text-left"
                  data-testid="feature-item"
                >
                  <span class="icon-[lucide--chevron-right] text-xs text-muted-foreground transition-transform group-data-[state=open]:rotate-90" />
                  <span class="icon-[lucide--git-branch] text-muted-foreground" />
                  <span class="text-sm text-foreground truncate"><InlineMarkdown :text="feat.name" /></span>
                </CollapsibleTrigger>
                <!-- 进度灯：圆点 + 文案 -->
                <span
                  class="inline-flex items-center gap-1.5 shrink-0 rounded-full px-2 py-0.5 text-xs font-medium"
                  :class="STATE_CLASS[normalizeState(feat.state)]"
                  :data-testid="`feature-state-${normalizeState(feat.state)}`"
                  :title="feat.status_display_name || undefined"
                >
                  <span class="w-1.5 h-1.5 rounded-full bg-current" />
                  {{ t(`projects.workbench.feature.state.${normalizeState(feat.state)}`) }}
                </span>
              </div>

              <CollapsibleContent class="pl-12 pb-1">
                <p
                  v-if="children(feat).length === 0"
                  class="py-1.5 text-xs text-muted-foreground"
                >
                  {{ t('projects.workbench.feature.noAcceptance') }}
                </p>
                <ul v-else class="space-y-0.5">
                  <li
                    v-for="(acc, ai) in children(feat)"
                    :key="`a-${mi}-${fi}-${ai}`"
                    class="flex items-center gap-2 py-1 text-xs text-muted-foreground"
                    data-testid="feature-acceptance"
                  >
                    <span class="icon-[lucide--check] text-emerald-500/70" />
                    <span class="truncate text-foreground/80"><InlineMarkdown :text="acc.name" /></span>
                  </li>
                </ul>
              </CollapsibleContent>
            </Collapsible>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </div>
  </section>
</template>
