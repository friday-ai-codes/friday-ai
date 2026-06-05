<script setup lang="ts">
import type { ProviderHealthStatus } from '~/types/providerCredential'
/**
 * Provider 健康状态 badge（，CONTEXT ~）
 *
 * 四态映射（UI-SPEC §Color Badge variant 表严格对齐）:
 *   - 'ok'       → variant='success'     + lucide--check-circle + "连接正常"
 *   - 'error'    → variant='destructive' + lucide--alert-circle + "连接失败"
 *   - ''/unknown → variant='muted'       + lucide--help-circle  + "未测试"
 *   - 'testing'  → variant='info'        + lucide--loader-2 animate-spin + "测试中…"
 *
 * 交互：点击 badge 触发 emit('test')，父组件调 store.testConnection。
 * 防双击：本地 locked state 在 emit 后立即锁 500ms（或由父组件 status 变化解锁）。
 *
 * Typography: UI-SPEC §Typography 要求 Label 使用 font-normal，覆盖 Badge 默认 font-semibold。
 * 颜色：严禁在 Badge 上叠加 :class="'bg-emerald-...'"（DESIGN.md L111）；仅通过 :variant 控制。
 */
import { computed, ref, watch } from 'vue'
import { Badge } from '~/components/ui/badge'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'

interface Props {
  status: ProviderHealthStatus
  lastError?: string
  lastCheckedAt?: string | null
  latencyMs?: number
}

const props = withDefaults(defineProps<Props>(), {
  lastError: '',
  lastCheckedAt: null,
  latencyMs: undefined,
})

const emit = defineEmits<{ (e: 'test'): void }>()

const locked = ref(false)

// 父组件 status 变化时解锁（如父组件把 'testing' 切回 'ok'/'error'）
watch(() => props.status, () => {
  locked.value = false
})

// variant / icon / label 映射
const variantByStatus = computed<'success' | 'destructive' | 'muted' | 'info'>(() => {
  switch (props.status) {
    case 'ok': return 'success'
    case 'error': return 'destructive'
    case 'testing': return 'info'
    default: return 'muted'
  }
})

const iconByStatus = computed(() => {
  switch (props.status) {
    case 'ok': return 'icon-[lucide--check-circle]'
    case 'error': return 'icon-[lucide--alert-circle]'
    case 'testing': return 'icon-[lucide--loader-2] animate-spin'
    default: return 'icon-[lucide--help-circle]'
  }
})

const labelByStatus = computed(() => {
  switch (props.status) {
    case 'ok': return '连接正常'
    case 'error': return '连接失败'
    case 'testing': return '测试中…'
    default: return '未测试'
  }
})

const tooltipText = computed(() => {
  const relative = props.lastCheckedAt
    ? new Date(props.lastCheckedAt).toLocaleString('zh-CN')
    : ''
  switch (props.status) {
    case 'ok':
      return props.latencyMs !== undefined
        ? `连接正常（最后测试于 ${relative}，延迟 ${props.latencyMs}ms）`
        : relative
          ? `连接正常（最后测试于 ${relative}）`
          : '连接正常'
    case 'error':
      return props.lastError
        ? `连接失败：${props.lastError}${relative ? `（最后测试于 ${relative}）` : ''}`
        : '连接失败'
    case 'testing':
      return '正在测试连接，请稍候…'
    default:
      return '点击立即测试以刷新健康状态'
  }
})

function onClick() {
  if (locked.value || props.status === 'testing')
    return
  locked.value = true
  emit('test')
  // 500ms 兜底解锁，防父组件未正确切换 status
  window.setTimeout(() => {
    locked.value = false
  }, 500)
}
</script>

<template>
  <TooltipProvider :delay-duration="150">
    <Tooltip>
      <TooltipTrigger as-child>
        <Badge
          :variant="variantByStatus"
          role="status"
          aria-live="polite"
          :data-locked="locked ? 'true' : 'false'"
          class="cursor-pointer inline-flex items-center gap-1 px-2 py-1 select-none"
          :class="{ 'opacity-60 pointer-events-none': locked || props.status === 'testing' }"
          @click="onClick"
        >
          <span class="w-3 h-3" :class="[iconByStatus]" aria-hidden="true" />
          <span class="text-xs font-normal">{{ labelByStatus }}</span>
        </Badge>
      </TooltipTrigger>
      <TooltipContent class="max-w-xs text-xs font-normal">
        {{ tooltipText }}
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
