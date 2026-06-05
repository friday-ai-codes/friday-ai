<script setup lang="ts">
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover'
import { useSystemHealth } from '~/composables/useSystemHealth'

const { services, pill, pillLabel, loading, checkedAt, lastError, refresh } = useSystemHealth()

function formatChecked(iso: string | null): string {
  if (!iso)
    return '未检测'
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('zh-CN', { hour12: false })
  }
  catch {
    return iso
  }
}

function toneIcon(tone: string): string {
  switch (tone) {
    case 'ok':
      return 'icon-[lucide--check-circle-2]'
    case 'error':
      return 'icon-[lucide--x-circle]'
    case 'warn':
      return 'icon-[lucide--loader-2] animate-spin'
    default:
      return 'icon-[lucide--minus-circle]'
  }
}

function toneClass(tone: string): string {
  switch (tone) {
    case 'ok':
      return 'text-emerald-500'
    case 'error':
      return 'text-red-500'
    case 'warn':
      return 'text-amber-500'
    default:
      return 'text-muted-foreground'
  }
}

function statusText(status: string): string {
  switch (status) {
    case 'healthy':
      return '正常'
    case 'unhealthy':
      return '异常'
    case 'not_configured':
      return '未配置'
    default:
      return status
  }
}
</script>

<template>
  <Popover>
    <PopoverTrigger as-child>
      <button
        type="button"
        class="flex items-center gap-2 px-3 py-1.5 rounded-full cursor-pointer transition-colors duration-300 border outline-none"
        :class="{
          'bg-emerald-500/10 border-emerald-500/20 hover:bg-emerald-500/15': pill === 'healthy',
          'bg-amber-500/10 border-amber-500/20 hover:bg-amber-500/15': pill === 'loading',
          'bg-red-500/10 border-red-500/20 hover:bg-red-500/15': pill === 'unhealthy',
        }"
        :title="pillLabel"
      >
        <span class="relative flex h-2 w-2">
          <span
            v-if="pill === 'healthy'"
            class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"
          />
          <span
            class="relative inline-flex rounded-full h-2 w-2"
            :class="{
              'bg-emerald-500': pill === 'healthy',
              'bg-amber-500 animate-pulse': pill === 'loading',
              'bg-red-500': pill === 'unhealthy',
            }"
          />
        </span>
        <span
          class="text-sm font-medium"
          :class="{
            'text-emerald-600': pill === 'healthy',
            'text-amber-600': pill === 'loading',
            'text-red-600': pill === 'unhealthy',
          }"
        >
          {{ pillLabel }}
        </span>
      </button>
    </PopoverTrigger>

    <PopoverContent align="end" :side-offset="8" class="w-80 p-0 overflow-hidden">
      <div class="flex items-center justify-between px-4 py-3 border-b border-border/50">
        <div>
          <div class="text-sm font-semibold">
            服务连接状态
          </div>
          <div class="text-xs text-muted-foreground mt-0.5">
            上次检测：{{ formatChecked(checkedAt) }}
          </div>
        </div>
        <button
          type="button"
          class="flex items-center justify-center h-7 w-7 rounded-md hover:bg-muted transition-colors disabled:opacity-50"
          :disabled="loading"
          :title="loading ? '检测中...' : '立即刷新'"
          @click="refresh"
        >
          <span
            class="text-base"
            :class="loading ? 'icon-[lucide--loader-2] animate-spin' : 'icon-[lucide--refresh-cw]'"
          />
        </button>
      </div>

      <div class="divide-y divide-border/40">
        <div
          v-for="svc in services"
          :key="svc.name"
          class="flex items-start gap-3 px-4 py-3"
        >
          <span
            class="text-lg shrink-0 mt-0.5"
            :class="[toneIcon(svc.tone), toneClass(svc.tone)]"
          />
          <div class="flex-1 min-w-0">
            <div class="flex items-center justify-between gap-2">
              <span class="text-sm font-medium truncate">{{ svc.label }}</span>
              <span
                class="text-xs shrink-0 px-1.5 py-0.5 rounded"
                :class="{
                  'bg-emerald-500/10 text-emerald-600': svc.tone === 'ok',
                  'bg-red-500/10 text-red-600': svc.tone === 'error',
                  'bg-amber-500/10 text-amber-600': svc.tone === 'warn',
                  'bg-muted text-muted-foreground': svc.tone === 'muted',
                }"
              >
                {{ statusText(svc.status) }}
              </span>
            </div>
            <div
              v-if="svc.message"
              class="text-xs text-muted-foreground mt-1 break-all"
            >
              {{ svc.message }}
            </div>
            <div
              v-if="svc.latency_ms != null"
              class="text-[10px] text-muted-foreground/70 mt-1"
            >
              {{ svc.latency_ms }} ms
            </div>
          </div>
        </div>
      </div>

      <div
        v-if="lastError"
        class="px-4 py-2 text-xs text-red-600 bg-red-500/5 border-t border-red-500/20"
      >
        拉取失败：{{ lastError }}
      </div>
    </PopoverContent>
  </Popover>
</template>
