<script setup lang="ts">
import type { WorkflowExecution } from '~/stores/useExecutionsStore'
import { ref, toRef } from 'vue'
import StatusBadge from '~/components/common/StatusBadge.vue'
import { Button } from '~/components/ui/button'

const props = defineProps<{
  executions: WorkflowExecution[]
  loading: boolean
}>()

// 数据到达后列表行错拍浮入
const rootEl = ref<HTMLElement | null>(null)
useListReveal(rootEl, '.activity-row', toRef(() => !props.loading))

function formatDate(dateStr: string) {
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<template>
  <section ref="rootEl">
    <div class="card overflow-hidden">
      <!-- 标题栏 -->
      <div class="flex items-center justify-between px-6 py-4 border-b border-border/50">
        <div class="flex items-center gap-3">
          <div class="stat-icon stat-icon-primary">
            <span class="icon-[lucide--clock] text-lg" />
          </div>
          <div>
            <h2 class="text-base font-semibold text-foreground">
              最近执行
            </h2>
            <p class="text-xs text-muted-foreground">
              最近的工作流执行记录
            </p>
          </div>
        </div>
        <RouterLink to="/executions">
          <span class="text-sm font-medium text-muted-foreground hover:text-primary transition-colors group inline-flex items-center">
            查看全部
            <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-1 transition-transform" />
          </span>
        </RouterLink>
      </div>

      <!-- 执行列表 -->
      <div class="p-4">
        <!-- 加载状态 -->
        <div v-if="loading" class="space-y-2">
          <div v-for="i in 3" :key="i" class="flex items-center gap-4 p-3 rounded-xl">
            <div class="w-10 h-10 rounded-lg bg-muted animate-pulse" />
            <div class="flex-1 space-y-2">
              <div class="h-4 w-2/3 bg-muted animate-pulse rounded" />
              <div class="h-3 w-1/4 bg-muted animate-pulse rounded" />
            </div>
            <div class="h-6 w-16 bg-muted animate-pulse rounded-full" />
          </div>
        </div>

        <!-- 空状态 -->
        <div v-else-if="executions.length === 0" class="py-12 text-center">
          <div class="stat-icon stat-icon-primary mx-auto mb-4 w-16 h-16 text-2xl">
            <span class="icon-[lucide--play-circle]" />
          </div>
          <h3 class="text-base font-medium text-foreground mb-1">
            暂无执行记录
          </h3>
          <p class="text-sm text-muted-foreground mb-5">
            创建工作流并运行，执行记录将显示在这里
          </p>
          <RouterLink to="/workflows">
            <Button>
              <span class="icon-[lucide--workflow]" />
              查看工作流
            </Button>
          </RouterLink>
        </div>

        <!-- 执行列表 -->
        <div v-else class="space-y-1">
          <RouterLink
            v-for="(execution, index) in executions.slice(0, 5)"
            :key="execution.id"
            :to="`/executions/${execution.id}`"
            class="activity-row group flex items-center gap-4 p-3 rounded-xl hover:bg-muted/50 transition-colors duration-200"
          >
            <!-- 序号 -->
            <div class="flex-shrink-0 w-10 h-10 rounded-lg bg-muted/50 flex items-center justify-center font-medium text-muted-foreground text-sm group-hover:bg-primary/10 group-hover:text-primary transition-colors">
              {{ index + 1 }}
            </div>

            <!-- 内容 -->
            <div class="flex-1 min-w-0">
              <p class="text-sm font-medium text-foreground truncate group-hover:text-primary transition-colors">
                {{ execution.workflow_name }}
              </p>
              <p class="text-xs text-muted-foreground mt-0.5">
                {{ formatDate(execution.created_at) }}
              </p>
            </div>

            <!-- 状态 -->
            <StatusBadge type="execution" :status="execution.status" size="sm" />

            <!-- 箭头 -->
            <span class="icon-[lucide--chevron-right] text-muted-foreground/30 group-hover:text-primary group-hover:translate-x-0.5 transition-all" />
          </RouterLink>
        </div>
      </div>
    </div>
  </section>
</template>
