<script setup lang="ts">
/**
 * 飞书配置表单组件
 * 用于配置项目的飞书集成凭证
 * 飞书项目使用「插件」凭证而非「应用」凭证来获取工作项详情
 */
import type { FeishuConfig, FeishuConfigCreate } from '~/types'
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'
import { deleteFeishuConfig, setFeishuConfig, testFeishuConfig } from '~/api/projects'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Card,
 CardContent,
 CardDescription,
 CardFooter,
 CardHeader,
 CardTitle,
} from '~/components/ui/card'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
const props = defineProps<{
 projectId: string
 config: FeishuConfig | null
}>
const emit = defineEmits<{
 (e: 'updated'): void
}>
// 表单数据
const formData = ref<FeishuConfigCreate>({
 plugin_id: props.config?.plugin_id || '',
 plugin_secret: '',
 webhook_token: '',
})
// 状态
const isLoading = ref(false)
const isTesting = ref(false)
const isDeleting = ref(false)
const showDeleteConfirm = ref(false)
// 是否已配置
const isConfigured = computed( => props.config?.is_configured ?? false)
// 提交配置
async function handleSubmit {
 if (!formData.value.plugin_id || !formData.value.plugin_secret) {
 toast.error('请填写插件 ID 和插件 Secret')
 return
 }
 isLoading.value = true
 try {
 await setFeishuConfig(props.projectId, formData.value)
 toast.success('飞书配置保存成功')
 // 清空敏感信息
 formData.value.plugin_secret = ''
 formData.value.webhook_token = ''
 emit('updated')
 }
 catch (error: unknown) {
 const message = error instanceof Error ? error.message: '未知错误'
 toast.error(`保存失败: ${message}`)
 }
 finally {
 isLoading.value = false
 }
}
// 测试配置
async function handleTest {
 isTesting.value = true
 try {
 const result = await testFeishuConfig(props.projectId)
 if (result.success) {
 toast.success(result.message)
 }
 else {
 toast.error(result.message)
 }
 }
 catch (error: unknown) {
 const message = error instanceof Error ? error.message: '未知错误'
 toast.error(`测试失败: ${message}`)
 }
 finally {
 isTesting.value = false
 }
}
// 删除配置
async function handleDelete {
 isDeleting.value = true
 try {
 await deleteFeishuConfig(props.projectId)
 toast.success('飞书配置已删除')
 formData.value = { plugin_id: '', plugin_secret: '', webhook_token: '' }
 emit('updated')
 }
 catch (error: unknown) {
 const message = error instanceof Error ? error.message: '未知错误'
 toast.error(`删除失败: ${message}`)
 }
 finally {
 isDeleting.value = false
 showDeleteConfirm.value = false
 }
}
</script>
<template>
 <Card>
 <CardHeader>
 <div class="flex items-center justify-between">
 <div>
 <CardTitle>飞书项目集成</CardTitle>
 <CardDescription>
 配置飞书插件凭证，用于接收 Webhook 和调用飞书项目 API
 </CardDescription>
 </div>
 <Badge v-if="isConfigured" variant="default" class="bg-green-500">
 已配置
 </Badge>
 <Badge v-else variant="secondary">
 未配置
 </Badge>
 </div>
 </CardHeader>
 <CardContent>
 <form class="space-y-4" @submit.prevent="handleSubmit">
 <!-- Plugin ID -->
 <div class="space-y-2">
 <Label for="plugin_id">插件 ID</Label>
 <Input
 id="plugin_id"
 v-model="formData.plugin_id"
 placeholder="飞书插件 ID":disabled="isLoading"
 />
 <p class="text-sm text-muted-foreground">
 在飞书项目管理中创建插件后获取
 </p>
 </div>
 <!-- Plugin Secret -->
 <div class="space-y-2">
 <Label for="plugin_secret">插件 Secret</Label>
 <Input
 id="plugin_secret"
 v-model="formData.plugin_secret"
 type="password":placeholder="isConfigured ? '已配置（留空则不更新）': '飞书插件 Secret'":disabled="isLoading"
 />
 <p class="text-sm text-muted-foreground">
 请妥善保管，不会在页面上显示
 </p>
 </div>
 <!-- Webhook Token -->
 <div class="space-y-2">
 <Label for="webhook_token">Webhook Token（可选）</Label>
 <Input
 id="webhook_token"
 v-model="formData.webhook_token":placeholder="config?.has_webhook_token ? '已配置（留空则不更新）': 'Webhook 验证 Token'":disabled="isLoading"
 />
 <p class="text-sm text-muted-foreground">
 在飞书项目自动化规则中配置的 Token，用于验证 Webhook 请求
 </p>
 </div>
 <!-- 当前配置状态 -->
 <div v-if="config" class="rounded-lg bg-muted space-y-2">
 <p class="text-sm font-medium">
 当前配置状态
 </p>
 <div class="grid grid-cols-2 gap-2 text-sm">
 <div>
 <span class="text-muted-foreground">Project Key:</span>
 <span class="ml-2">{{ config.project_key || '未设置' }}</span>
 </div>
 <div>
 <span class="text-muted-foreground">插件 ID:</span>
 <span class="ml-2">{{ config.plugin_id || '未设置' }}</span>
 </div>
 <div>
 <span class="text-muted-foreground">插件 Secret:</span>
 <span class="ml-2">{{ config.has_plugin_secret ? '已配置': '未配置' }}</span>
 </div>
 <div>
 <span class="text-muted-foreground">Webhook Token:</span>
 <span class="ml-2">{{ config.has_webhook_token ? '已配置': '未配置' }}</span>
 </div>
 </div>
 </div>
 </form>
 </CardContent>
 <CardFooter class="flex justify-between">
 <div class="flex gap-2">
 <Button
 type="submit":disabled="isLoading"
 @click="handleSubmit"
 >
 {{ isLoading ? '保存中...': '保存配置' }}
 </Button>
 <Button
 v-if="isConfigured"
 variant="outline":disabled="isTesting"
 @click="handleTest"
 >
 {{ isTesting ? '测试中...': '测试连接' }}
 </Button>
 </div>
 <Button
 v-if="isConfigured"
 variant="destructive":disabled="isDeleting"
 @click="handleDelete"
 >
 {{ isDeleting ? '删除中...': '删除配置' }}
 </Button>
 </CardFooter>
 </Card>
</template>
