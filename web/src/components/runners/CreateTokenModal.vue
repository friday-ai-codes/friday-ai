<script setup lang="ts">
import { useClipboard } from '@vueuse/core'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '~/components/ui/select'
import BaseModal from '~/components/modal/BaseModal.vue'
const open = defineModel<boolean>('open', { required: true })
const runnersStore = useRunnersStore
const { success: toastSuccess, error: showError } = useToast
const { copy } = useClipboard
const step = ref<'form' | 'success'>('form')
const createdToken = ref<string | null>(null)
const submitting = ref(false)
const form = reactive({
 description: '',
 scope: 'global' as 'global' | 'project',
 expires_in: '86400',
})
const expiryOptions = [
 { label: '1 小时', value: '3600' },
 { label: '24 小时', value: '86400' },
 { label: '7 天', value: '604800' },
 { label: '30 天', value: '2592000' },
]
async function handleSubmit {
 submitting.value = true
 try {
 const result = await runnersStore.addToken({
 description: form.description || undefined,
 scope: form.scope,
 expires_in: Number(form.expires_in),
 })
 createdToken.value = result.token
 step.value = 'success'
 }
 catch (e) { showError('创建失败', e instanceof Error ? e.message: '无法创建令牌') }
 finally { submitting.value = false }
}
async function copyToken {
 if (!createdToken.value) return
 await copy(createdToken.value)
 toastSuccess('已复制令牌')
}
async function copyCommand {
 if (!createdToken.value) return
 await copy(`friday-runner register --token ${createdToken.value}`)
 toastSuccess('已复制注册命令')
}
function handleClosed {
 step.value = 'form'
 createdToken.value = null
 form.description = ''
 form.scope = 'global'
 form.expires_in = '86400'
}
</script>
<template>
 <BaseModal
 v-model="open":title="step === 'form' ? '创建注册令牌': '令牌已创建'"
 size="md"
 @closed="handleClosed"
 >
 <!-- 表单阶段 -->
 <div v-if="step === 'form'" class="space-y-4">
 <div class="space-y-1.5">
 <label class="text-sm font-medium">描述</label>
 <Input v-model="form.description" placeholder="可选，用于标识令牌用途" />
 </div>
 <div class="space-y-1.5">
 <label class="text-sm font-medium">作用域</label>
 <Select v-model="form.scope">
 <SelectTrigger><SelectValue /></SelectTrigger>
 <SelectContent>
 <SelectItem value="global">全局</SelectItem>
 <SelectItem value="project">项目</SelectItem>
 </SelectContent>
 </Select>
 </div>
 <div class="space-y-1.5">
 <label class="text-sm font-medium">过期时间</label>
 <Select v-model="form.expires_in">
 <SelectTrigger><SelectValue /></SelectTrigger>
 <SelectContent>
 <SelectItem v-for="opt in expiryOptions":key="opt.value":value="opt.value">{{ opt.label }}</SelectItem>
 </SelectContent>
 </Select>
 </div>
 </div>
 <!-- 成功阶段 -->
 <div v-else class="space-y-4">
 <!-- CREATE_MODAL_SUCCESS_CONTINUE -->
 <div class="rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 text-sm text-amber-700 dark:text-amber-400">
 <span class="icon-[lucide--alert-triangle] mr-1.5 align-text-bottom" />
 此令牌仅显示一次，关闭后无法再次查看
 </div>
 <div class="space-y-1.5">
 <label class="text-sm font-medium">令牌</label>
 <div class="flex items-center gap-2">
 <code class="flex-1 font-mono bg-muted rounded-lg break-all text-sm">{{ createdToken }}</code>
 <Button variant="outline" size="sm" @click="copyToken">
 <span class="icon-[lucide--copy] mr-1.5" />复制令牌
 </Button>
 </div>
 </div>
 <div class="space-y-1.5">
 <label class="text-sm font-medium">注册命令</label>
 <div class="flex items-center gap-2">
 <code class="flex-1 font-mono bg-muted rounded-lg break-all text-sm">friday-runner register --token {{ createdToken }}</code>
 <Button variant="outline" size="sm" @click="copyCommand">
 <span class="icon-[lucide--copy] mr-1.5" />复制命令
 </Button>
 </div>
 </div>
 </div>
 <template #footer>
 <div class="flex justify-end gap-3 w-full">
 <template v-if="step === 'form'">
 <Button variant="outline" @click="open = false">取消</Button>
 <Button:disabled="submitting" @click="handleSubmit">
 <span v-if="submitting" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 创建
 </Button>
 </template>
 <Button v-else @click="open = false">关闭</Button>
 </div>
 </template>
 </BaseModal>
</template>
