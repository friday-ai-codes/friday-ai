<script setup lang="ts">
import type { WorkItemLogDetail } from '~/api/logs'
import { useHead } from '@vueuse/head'
import { getWorkItemLog } from '~/api/logs'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Separator } from '~/components/ui/separator'
const route = useRoute
const router = useRouter
const { error: showError, success } = useToast
const logId = computed( => route.params.id as string)
useHead({
 title: computed( => `工作项日志 - Friday AI`),
})
// 加载数据
const loading = ref(true)
const log = ref<WorkItemLogDetail | null>(null)
onMounted(async => {
 try {
 log.value = await getWorkItemLog(logId.value)
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取日志详情')
 }
 finally {
 loading.value = false
 }
})
// 格式化日期
function formatDate(dateStr: string) {
 return new Date(dateStr).toLocaleString('zh-CN')
}
// 复制 JSON 到剪贴板
async function copyJson {
 if (!log.value)
 return
 try {
 await navigator.clipboard.writeText(JSON.stringify(log.value.raw_response_parsed, null, 2))
 success('复制成功', 'JSON 已复制到剪贴板')
 }
 catch {
 showError('复制失败', '无法复制到剪贴板')
 }
}
</script>
<template>
 <div class="space-y-6">
 <!-- 返回按钮 -->
 <RouterLink to="/logs" class="inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
 <span class="icon-[lucide--arrow-left] mr-1" />
 返回日志列表
 </RouterLink>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="4" />
 <!-- 日志详情 -->
 <template v-else-if="log">
 <!-- 头部 -->
 <div class="flex items-start justify-between">
 <div class="space-y-2">
 <h1 class="text-2xl font-bold">
 工作项日志
 </h1>
 <div class="flex items-center gap-3">
 <Badge variant="outline">
 {{ log.work_item_type }}
 </Badge>
 <span class="text-muted-foreground font-mono">
 #{{ log.work_item_id }}
 </span>
 </div>
 </div>
 <Button variant="outline" @click="copyJson">
 <span class="icon-[lucide--copy] mr-2" />
 复制 JSON
 </Button>
 </div>
 <!-- 基本信息卡片 -->
 <Card>
 <CardHeader>
 <CardTitle>基本信息</CardTitle>
 </CardHeader>
 <CardContent class="space-y-4">
 <div class="grid gap-4 md:grid-cols-2">
 <div>
 <label class="text-sm text-muted-foreground">日志 ID</label>
 <p class="font-mono text-sm">
 {{ log.id }}
 </p>
 </div>
 <div>
 <label class="text-sm text-muted-foreground">创建时间</label>
 <p class="text-sm">
 {{ formatDate(log.created_at) }}
 </p>
 </div>
 </div>
 <Separator />
 <div class="grid gap-4 md:grid-cols-2">
 <div>
 <label class="text-sm text-muted-foreground">工作项 ID</label>
 <p class="font-mono text-sm">
 {{ log.work_item_id }}
 </p>
 </div>
 <div>
 <label class="text-sm text-muted-foreground">工作项类型</label>
 <p class="font-mono text-sm">
 {{ log.work_item_type }}
 </p>
 </div>
 </div>
 <Separator />
 <div class="grid gap-4 md:grid-cols-2">
 <div>
 <label class="text-sm text-muted-foreground">项目 ID</label>
 <p class="font-mono text-sm">
 {{ log.project_id || '-' }}
 </p>
 </div>
 <div>
 <label class="text-sm text-muted-foreground">关联任务 ID</label>
 <p v-if="log.task_id" class="font-mono text-sm">
 <RouterLink:to="`/tasks/${log.task_id}`" class="text-primary hover:underline">
 {{ log.task_id }}
 </RouterLink>
 </p>
 <p v-else class="text-sm">
 -
 </p>
 </div>
 </div>
 </CardContent>
 </Card>
 <!-- 原始响应卡片 -->
 <Card>
 <CardHeader>
 <CardTitle>飞书 API 响应数据</CardTitle>
 <CardDescription>
 从飞书项目 API 获取的工作项详细信息
 </CardDescription>
 </CardHeader>
 <CardContent>
 <div class="bg-muted rounded-lg overflow-auto max-h-[600px]">
 <pre class="text-sm font-mono whitespace-pre-wrap">{{ JSON.stringify(log.raw_response_parsed, null, 2) }}</pre>
 </div>
 </CardContent>
 </Card>
 </template>
 <!-- 日志不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="日志不存在"
 description="未找到该日志记录，可能已被删除"
 action-label="返回列表"
 @action="router.push('/logs')"
 />
 </div>
</template>
