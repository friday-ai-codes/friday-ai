<script setup lang="ts">
/**
 * 飞书配置页面
 * 用于配置项目的飞书集成
 */
import type { FeishuConfig } from '~/types'
import { useHead } from '@vueuse/head'
import { getFeishuConfig } from '~/api/projects'
import { FeishuConfigForm } from '~/components/feishu'
const route = useRoute
const router = useRouter
const projectsStore = useProjectsStore
const { error: showError } = useToast
const projectId = computed( => route.params.id as string)
useHead({
 title: '飞书配置 - Friday AI',
})
// 加载数据
const loading = ref(true)
const feishuConfig = ref<FeishuConfig | null>(null)
async function loadData {
 loading.value = true
 try {
 await projectsStore.fetchProject(projectId.value)
 try {
 feishuConfig.value = await getFeishuConfig(projectId.value)
 }
 catch {
 // 配置不存在是正常情况
 feishuConfig.value = null
 }
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取项目详情')
 }
 finally {
 loading.value = false
 }
}
onMounted(loadData)
const project = computed( => projectsStore.currentProject)
// Webhook URL（在客户端计算）
const webhookUrl = computed( => {
 if (typeof window !== 'undefined') {
 return `${window.location.origin}/api/webhook/feishu`
 }
 return '/api/webhook/feishu'
})
// 刷新配置
async function handleUpdated {
 try {
 feishuConfig.value = await getFeishuConfig(projectId.value)
 await projectsStore.fetchProject(projectId.value)
 }
 catch {
 feishuConfig.value = null
 }
}
</script>
<template>
 <div class="max-w-2xl mx-auto space-y-6">
 <!-- 返回按钮 -->
 <RouterLink:to="`/projects/${projectId}`"
 class="inline-flex items-center text-sm text-muted-foreground hover:text-foreground"
 >
 <span class="icon-[lucide--arrow-left] mr-1" />
 返回项目详情
 </RouterLink>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="2" />
 <template v-else-if="project">
 <div>
 <h1 class="text-2xl font-bold">
 飞书配置
 </h1>
 <p class="text-muted-foreground">
 配置 {{ project.name }} 的飞书项目集成
 </p>
 </div>
 <!-- 飞书配置表单 -->
 <FeishuConfigForm:project-id="projectId":config="feishuConfig"
 @updated="handleUpdated"
 />
 <!-- 使用说明 -->
 <div class="rounded-lg border space-y-3">
 <h3 class="font-medium">
 配置说明
 </h3>
 <ol class="list-decimal list-inside space-y-2 text-sm text-muted-foreground">
 <li>在飞书项目管理后台创建插件，获取插件 ID 和插件 Secret</li>
 <li>在插件权限页面申请飞书项目相关权限（如获取工作项详情）</li>
 <li>在飞书项目中配置自动化规则，添加 Webhook 操作</li>
 <li>Webhook URL 填写：<code class="px-1 py-0.5 bg-muted rounded">{{ webhookUrl }}</code></li>
 <li>Webhook Token 在项目详情页管理，请在飞书自动化规则中填写相同的 Token</li>
 </ol>
 </div>
 </template>
 <!-- 项目不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="项目不存在"
 description="未找到该项目"
 action-label="返回列表"
 @action="router.push('/projects')"
 />
 </div>
</template>
