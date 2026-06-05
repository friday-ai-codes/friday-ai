<script setup lang="ts">
/**
 * ExecutionHistoryList - 执行历史列表面板
 *
 * 自治组件：内部管理数据获取、状态筛选、分页。
 * 用于工作流编辑器页面右侧 Sheet 面板中。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '~/api/client'
import { Button } from '~/components/ui/button'
import { Pagination } from '~/components/ui/pagination'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import ExecutionHistoryCard from './ExecutionHistoryCard.vue'

const props = defineProps<{
  workflowId: string
}>()

const emit = defineEmits<{
  execute: []
}>()

const router = useRouter()
const { handleError } = useErrorHandler()
const { success } = useToast()

// ----- 数据状态 -----
interface HistoryExecution {
  id: string
  status: string
  trigger_type: string
  duration: number | null
  created_at: string
}

const executions = ref<HistoryExecution[]>([])
const loading = ref(false)
const totalCount = ref(0)
const currentPage = ref(1)
const pageSize = 20

// ----- 筛选状态 -----
type StatusFilter = '' | 'running' | 'completed' | 'failed' | 'cancelled'
const selectedStatus = ref<StatusFilter>('')

const statusOptions: { value: StatusFilter, label: string }[] = [
  { value: '', label: '全部' },
  { value: 'running', label: '运行中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]

const totalPages = computed(() => Math.ceil(totalCount.value / pageSize))

// ----- 数据获取 -----
async function fetchHistory() {
  loading.value = true
  try {
    const params: Record<string, string> = {
      workflow_id: props.workflowId,
      ordering: '-created_at',
      page: String(currentPage.value),
      page_size: String(pageSize),
    }
    if (selectedStatus.value) {
      params.status = selectedStatus.value
    }

    const data = await get<any>('/workflow-executions/', params)

    // 后端可能返回分页格式或纯数组
    if (data.results) {
      executions.value = data.results
      totalCount.value = data.count || data.results.length
    }
    else if (Array.isArray(data)) {
      executions.value = data
      totalCount.value = data.length
    }
  }
  catch (e: unknown) {
    handleError(e, '加载执行历史')
  }
  finally {
    loading.value = false
  }
}

// 筛选变化时重置页码并刷新
watch(selectedStatus, () => {
  currentPage.value = 1
  fetchHistory()
})

// 分页变化时刷新
watch(currentPage, () => {
  fetchHistory()
})

// 初始加载
fetchHistory()

// ----- 交互 -----
function navigateToExecution(executionId: string) {
  router.push(`/executions/${executionId}`)
}

async function handleRetry(executionId: string) {
  try {
    const { retryExecution } = await import('~/api/workflow')
    const result = await retryExecution(executionId)
    if (result?.execution_id) {
      success('工作流重新执行成功')
      router.push(`/executions/${result.execution_id}`)
    }
  }
  catch (e: unknown) {
    handleError(e, '重试')
  }
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <!-- 状态筛选 -->
    <div class="flex items-center gap-1 flex-wrap">
      <Button
        v-for="opt in statusOptions"
        :key="opt.value"
        :variant="selectedStatus === opt.value ? 'secondary' : 'ghost'"
        size="sm"
        class="h-7 text-xs"
        @click="selectedStatus = opt.value"
      >
        {{ opt.label }}
      </Button>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="space-y-2">
      <div v-for="i in 5" :key="i" class="h-10 rounded-xl bg-muted/30 animate-pulse" />
    </div>

    <!-- 空状态 -->
    <div v-else-if="executions.length === 0" class="flex flex-col items-center justify-center py-12 gap-3">
      <span class="icon-[lucide--history] w-10 h-10 text-muted-foreground/30" />
      <p class="text-sm text-muted-foreground">
        还没有执行记录
      </p>
      <Button size="sm" @click="emit('execute')">
        <span class="icon-[lucide--play] w-3.5 h-3.5 mr-1.5" />
        立即执行
      </Button>
    </div>

    <!-- 执行列表 -->
    <div v-else class="space-y-1.5">
      <ExecutionHistoryCard
        v-for="exec in executions"
        :key="exec.id"
        :execution="exec"
        @click="navigateToExecution(exec.id)"
        @retry="handleRetry"
      />
    </div>

    <!-- 分页器 -->
    <div v-if="totalPages > 1" class="pt-2">
      <Pagination
        v-model:page="currentPage"
        :total="totalCount"
        :items-per-page="pageSize"
        :sibling-count="1"
      />
    </div>
  </div>
</template>
