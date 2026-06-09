<script setup lang="ts">
/**
 * Access Token 创建表单
 *
 * 仿 ProviderCredentialForm 的 FormField 结构（vee-validate + zod 校验 name），
 * 过期策略用 Select：90 天（默认）/ 永不过期 / 自定义日期。
 *
 * 提交映射（对齐后端三态语义）：
 *   '90d'    → 省略 expires_at（后端默认 90 天）
 *   'never'  → expires_at: null（永不过期）
 *   'custom' → expires_at = 选中日期转 ISO 字符串
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
}>()

type ExpiryStrategy = '90d' | 'never' | 'custom'

const expiryStrategy = ref<ExpiryStrategy>('90d')
const customDate = ref('')
const customDateError = ref<string | null>(null)

// 原始 zod schema：既驱动 vee-validate 字段级校验（FormMessage 展示），
// 又用于提交时的同步校验（见 onSubmit）。
const accessTokenSchema = z.object({
  name: z.string().min(1, '请填写 Token 名称').max(200, '名称不超过 200 字符'),
  note: z.string().max(500, '备注不超过 500 字符').optional(),
})
const formSchema = toTypedSchema(accessTokenSchema)

const { values, setErrors } = useForm({
  validationSchema: formSchema,
})

/**
 * 提交：对当前表单值做同步 zod 校验，校验通过后即时 emit。
 *
 * 不走 vee-validate 异步 handleSubmit 的原因：其校验在微任务之外才落定，
 * 同步 safeParse 让提交在事件循环当前 tick 内完成，行为可预期、易测。
 */
function onSubmit() {
  const parsed = accessTokenSchema.safeParse(values)
  if (!parsed.success) {
    // 同步把字段错误回填到 vee-validate，触发 FormMessage 展示
    const fieldErrors = parsed.error.flatten().fieldErrors
    setErrors({ name: fieldErrors.name?.[0], note: fieldErrors.note?.[0] })
    return
  }

  const payload: AccessTokenCreatePayload = { name: parsed.data.name }

  // 备注 trim 后非空才发送，空串不进入 payload
  const note = parsed.data.note?.trim()
  if (note)
    payload.note = note

  if (expiryStrategy.value === 'never') {
    payload.expires_at = null
  }
  else if (expiryStrategy.value === 'custom') {
    if (!customDate.value) {
      customDateError.value = '请选择过期日期'
      return
    }
    // 选中日期固定到「本地当天结束」(23:59:59.999) 再转 ISO：
    // 直接 new Date('YYYY-MM-DD') 会按 UTC 午夜解析，正偏移时区（如 UTC+8）
    // 会使 token 提前最多一天过期；拼接本地时间字符串可让其在用户所选日历日内持续有效。
    payload.expires_at = new Date(`${customDate.value}T23:59:59.999`).toISOString()
  }
  // '90d'：省略 expires_at，交后端默认 90 天

  customDateError.value = null
  emit('submit', payload)
}
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
              name="name"
              placeholder="例如：mcp-ci / skill-prod"
            />
          </FormControl>
          <FormMessage />
        </FormItem>
      </FormField>

      <!-- 备注（可选） -->
      <FormField v-slot="{ componentField }" name="note">
        <FormItem>
          <FormLabel class="font-normal">
            备注，可选
          </FormLabel>
          <FormControl>
            <Input
              v-bind="componentField"
              name="note"
              placeholder="用途说明，便于日后识别（≤500 字）"
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

        <!-- 永不过期非阻塞风险提示（仅展示，不参与校验、不阻断提交） -->
        <div
          v-if="expiryStrategy === 'never'"
          class="mt-2 flex items-start gap-1.5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-400"
        >
          <span class="icon-[lucide--alert-triangle] mt-0.5 shrink-0" aria-hidden="true" />
          <span>永不过期的 Token 一旦泄露将长期有效、无法自动失效，存在安全风险；建议仅在确有必要时使用。</span>
        </div>

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
        <span class="icon-[lucide--plus] mr-1.5 h-4 w-4" aria-hidden="true" />
        创建
      </Button>
    </div>
  </form>
</template>
