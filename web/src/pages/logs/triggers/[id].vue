<script setup lang="ts">
import type { TriggerLogDetail } from '~/api/logs'
import { useHead } from '@vueuse/head'
import { getTriggerLog } from '~/api/logs'
import TriggerLogDetailComponent from '~/components/logs/TriggerLogDetail.vue'
import { Button } from '~/components/ui/button'
import { useErrorHandler } from '~/composables/useErrorHandler'

const route = useRoute('/logs/triggers/[id]')
const router = useRouter()

useHead({
  title: '触发日志详情 - Friday AI',
})

const { handleError } = useErrorHandler()

// 日志数据
const log = ref<TriggerLogDetail | null>(null)
const loading = ref(true)

// 空间 store
const spacesStore = useSpacesStore()

// 获取日志 ID
const logId = computed(() => route.params.id)

// 加载日志详情
async function fetchLog() {
  if (!logId.value)
    return

  loading.value = true
  try {
    await spacesStore.fetchSpaces()
    log.value = await getTriggerLog(logId.value)
  }
  catch (e: unknown) {
    handleError(e, '加载日志详情')
    router.push('/logs')
  }
  finally {
    loading.value = false
  }
}

// 获取空间名称
function getSpaceName(spaceId: string | null): string {
  if (!spaceId)
    return '-'
  const project = spacesStore.spaceById(spaceId)
  return project?.name || spaceId.slice(0, 8)
}

onMounted(() => {
  fetchLog()
})
</script>

<template>
  <div class="space-y-6">
    <!-- 页面标题 -->
    <div class="flex items-center gap-4">
      <Button variant="ghost" size="icon" @click="router.push('/logs')">
        <span class="icon-[lucide--arrow-left] h-5 w-5" />
      </Button>
      <div>
        <h1 class="text-2xl font-bold">
          触发日志详情
        </h1>
        <p class="text-muted-foreground">
          查看 Webhook 请求和工作项的完整数据
        </p>
      </div>
    </div>

    <!-- 加载状态 -->
    <LoadingState v-if="loading" variant="skeleton" :count="3" />

    <!-- 日志详情 -->
    <TriggerLogDetailComponent
      v-else-if="log"
      :log="log"
      :get-project-name="getSpaceName"
    />

    <!-- 空状态 -->
    <EmptyState
      v-else
      icon="lucide--file-x"
      title="日志不存在"
      description="该日志可能已被删除或 ID 无效"
    >
      <template #action>
        <Button @click="router.push('/logs')">
          返回日志列表
        </Button>
      </template>
    </EmptyState>
  </div>
</template>
