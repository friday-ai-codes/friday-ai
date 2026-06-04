<script setup lang="ts">
/**
 * Access Token 创建表单（Phase）
 *
 * 仿 ProviderCredentialForm 的 FormField 结构（vee-validate + zod 校验 name），
 * 过期策略用 Select：90 天（默认）/ 永不过期 / 自定义日期。
 *
 * 提交映射（对齐后端三态语义）：
 * '90d' → 省略 expires_at（后端默认 90 天）
 * 'never' → expires_at: null（永不过期）
 * 'custom' → expires_at = 选中日期转 ISO 字符串
 */
import type { AccessTokenCreatePayload } from '~/types/accessToken'
import { toTypedSchema } from '@vee-validate/zod'
import { useForm } from 'vee-validate'
import { ref } from 'vue'
import * as z from 'zod'
import { Button } from '~/components/ui/button'
import {
 FormControl,
 FormField,
 FormItem,
 FormLabel,
 FormMessage,
} from '~/components/ui/form'
import { Input } from '~/components/ui/input'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
const emit = defineEmits<{
 (e: 'submit', payload: AccessTokenCreatePayload): void
 (e: 'cancel'): void
}>
type ExpiryStrategy = '90d' | 'never' | 'custom'
const expiryStrategy = ref<ExpiryStrategy>('90d')
const customDate = ref('')
const customDateError = ref<string | null>(null)
const formSchema = toTypedSchema(
 z.object({
 name: z.string.min(1, '请填写 Token 名称'),
 }),
)
const { handleSubmit } = useForm({
 validationSchema: formSchema,
})
const onSubmit = handleSubmit((values) => {
 const payload: AccessTokenCreatePayload = { name: values.name }
 if (expiryStrategy.value === 'never') {
 payload.expires_at = null
 }
 else if (expiryStrategy.value === 'custom') {
 if (!customDate.value) {
 customDateError.value = '请选择过期日期'
 return
 }
 payload.expires_at = new Date(customDate.value).toISOString
 }
 // '90d'：省略 expires_at，交后端默认 90 天
 customDateError.value = null
 emit('submit', payload)
})
</script>
<template>
 <form class="flex flex-col" @submit.prevent="onSubmit">
 <div class="space-y-5 px-6 py-5">
 <!-- 名称 -->
 <FormField v-slot="{ componentField }" name="name">
 <FormItem>
 <FormLabel class="font-normal">
 名称
 </FormLabel>
 <FormControl>
 <Input
 v-bind="componentField"
 placeholder="例如：mcp-ci / skill-prod"
 />
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <!-- 过期策略 -->
 <div class="space-y-2">
 <label class="text-sm font-normal">过期</label>
 <Select v-model="expiryStrategy">
 <SelectTrigger>
 <SelectValue placeholder="选择过期策略" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="90d">
 90 天后过期（默认）
 </SelectItem>
 <SelectItem value="never">
 永不过期
 </SelectItem>
 <SelectItem value="custom">
 自定义日期
 </SelectItem>
 </SelectContent>
 </Select>
 <!-- 自定义日期 -->
 <Input
 v-if="expiryStrategy === 'custom'"
 v-model="customDate"
 type="date"
 class="mt-2"
 />
 <p v-if="customDateError" class="text-xs text-destructive">
 {{ customDateError }}
 </p>
 </div>
 </div>
 <!-- 底部操作栏 -->
 <div class="flex justify-end gap-3 border-t border-border/50 px-6 py-4">
 <Button type="button" variant="outline" @click="emit('cancel')">
 取消
 </Button>
 <Button type="submit">
 <span class="icon-[lucide--plus] mr-1.5 w-4" aria-hidden="true" />
 创建
 </Button>
 </div>
 </form>
</template>
