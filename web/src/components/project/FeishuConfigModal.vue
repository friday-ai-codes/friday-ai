<script setup lang="ts">
import type { FeishuConfig } from '~/types'
import { VueFinalModal } from 'vue-final-modal'
import { getFeishuConfig, setFeishuConfig } from '~/api/projects'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { useErrorHandler } from '~/composables/useErrorHandler'
const props = defineProps<{
 projectId: string
}>
const emit = defineEmits<{
 confirm:
 cancel:
 closed:
}>
const { handleError } = useErrorHandler
const { success } = useToast
// 表单数据
const form = reactive({
 plugin_id: '',
 plugin_secret: '',
 user_key: '',
})
// 配置状态
const config = ref<FeishuConfig | null>(null)
const loading = ref(false)
// 加载配置
async function loadConfig {
 loading.value = true
 try {
 const data = await getFeishuConfig(props.projectId)
 config.value = data
 form.plugin_id = data.plugin_id || ''
 form.user_key = data.user_key || ''
 // secret 不回显
 form.plugin_secret = ''
 }
 catch {
 // 忽略错误，可能是未配置
 config.value = null
 }
 finally {
 loading.value = false
 }
}
// 初始加载
onMounted( => {
 loadConfig
})
// 表单验证
const errors = reactive({
 plugin_id: '',
 plugin_secret: '',
 user_key: '',
})
function validate: boolean {
 errors.plugin_id = ''
 errors.plugin_secret = ''
 errors.user_key = ''
 let isValid = true
 if (!form.plugin_id.trim) {
 errors.plugin_id = '请输入插件 ID'
 isValid = false
 }
 // 如果是首次配置，或者用户想修改 secret（输入了内容），则验证
 // 如果已配置且用户留空，则表示不修改 secret
 const isSecretRequired = !config.value?.has_plugin_secret || form.plugin_secret.length > 0
 if (isSecretRequired && !form.plugin_secret.trim) {
 errors.plugin_secret = '请输入插件 Secret'
 isValid = false
 }
 if (!form.user_key.trim) {
 errors.user_key = '请输入用户 Key'
 isValid = false
 }
 return isValid
}
// 提交表单
const submitting = ref(false)
async function handleSubmit {
 if (!validate)
 return
 submitting.value = true
 try {
 await setFeishuConfig(props.projectId, {
 plugin_id: form.plugin_id,
 plugin_secret: form.plugin_secret,
 user_key: form.user_key,
 })
 success('保存成功', '飞书配置已更新')
 emit('confirm')
 }
 catch (e: unknown) {
 handleError(e, '保存飞书配置')
 }
 finally {
 submitting.value = false
 }
}
function handleCancel {
 emit('cancel')
}
</script>
<template>
 <VueFinalModal
 class="flex justify-center items-center"
 content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-lg w-full mx-4"
 overlay-transition="vfm-fade"
 content-transition="vfm-zoom"
 @closed="emit('closed')"
 >
 <!-- Header -->
 <div class="flex items-center justify-between px-6 py-5 border-b border-border/50">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-primary/10">
 <span class="icon-[lucide--message-square] text-xl text-purple-600" />
 </div>
 <div>
 <h3 class="text-lg font-semibold text-foreground">
 飞书配置
 </h3>
 <p class="text-sm text-muted-foreground">
 配置飞书插件凭证以启用集成功能
 </p>
 </div>
 </div>
 <button
 type="button"
 class=" rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
 @click="handleCancel"
 >
 <span class="icon-[lucide--x] text-lg" />
 </button>
 </div>
 <!-- Body -->
 <form class="px-6 py-5 space-y-5" @submit.prevent="handleSubmit">
 <!-- Loading State -->
 <div v-if="loading" class="space-y-5">
 <div class="space-y-2">
 <div class=" w-20 bg-muted rounded animate-pulse" />
 <div class=" w-full bg-muted rounded animate-pulse" />
 </div>
 <div class="space-y-2">
 <div class=" w-24 bg-muted rounded animate-pulse" />
 <div class=" w-full bg-muted rounded animate-pulse" />
 </div>
 <div class="space-y-2">
 <div class=" w-20 bg-muted rounded animate-pulse" />
 <div class=" w-full bg-muted rounded animate-pulse" />
 </div>
 </div>
 <template v-else>
 <!-- 插件 ID -->
 <div class="space-y-2">
 <Label for="plugin_id" class="flex items-center gap-1 text-foreground">
 插件 ID
 <span class="text-destructive">*</span>
 </Label>
 <Input
 id="plugin_id"
 v-model="form.plugin_id"
 placeholder="cli_..."
 class="":class="{ 'border-destructive': errors.plugin_id }"
 />
 <p v-if="errors.plugin_id" class="text-sm text-destructive flex items-center gap-1">
 <span class="icon-[lucide--alert-circle]" />
 {{ errors.plugin_id }}
 </p>
 <p v-else class="text-xs text-muted-foreground">
 在飞书开发者后台创建企业自建应用后获取
 </p>
 </div>
 <!-- 插件 Secret -->
 <div class="space-y-2">
 <Label for="plugin_secret" class="flex items-center gap-1 text-foreground">
 插件 Secret
 <span v-if="!config?.has_plugin_secret" class="text-destructive">*</span>
 </Label>
 <Input
 id="plugin_secret"
 v-model="form.plugin_secret"
 type="password":placeholder="config?.has_plugin_secret ? '已配置（留空保持不变）': '请输入插件 Secret'"
 class="":class="{ 'border-destructive': errors.plugin_secret }"
 />
 <p v-if="errors.plugin_secret" class="text-sm text-destructive flex items-center gap-1">
 <span class="icon-[lucide--alert-circle]" />
 {{ errors.plugin_secret }}
 </p>
 </div>
 <!-- 用户 Key -->
 <div class="space-y-2">
 <Label for="user_key" class="flex items-center gap-1 text-foreground">
 用户 Key
 <span class="text-destructive">*</span>
 </Label>
 <Input
 id="user_key"
 v-model="form.user_key"
 placeholder="ou_..."
 class="":class="{ 'border-destructive': errors.user_key }"
 />
 <p v-if="errors.user_key" class="text-sm text-destructive flex items-center gap-1">
 <span class="icon-[lucide--alert-circle]" />
 {{ errors.user_key }}
 </p>
 <p v-else class="text-xs text-muted-foreground">
 用于 API 调用时的用户身份标识
 </p>
 </div>
 </template>
 <!-- Footer -->
 <div class="flex justify-end gap-3 pt-4 border-t border-border/50">
 <Button type="button" variant="outline":disabled="submitting" @click="handleCancel">
 取消
 </Button>
 <Button type="submit":disabled="submitting || loading">
 <span v-if="submitting" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存配置
 </Button>
 </div>
 </form>
 </VueFinalModal>
</template>
