<script setup lang="ts">
import type { ActiveTasksResponse } from '~/api/system'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getActiveTasks } from '~/api/system'
import LoadingState from '~/components/common/LoadingState.vue'
import { Button } from '~/components/ui/button'

const REFRESH_MS = 4000

const data = ref<ActiveTasksResponse | null>(null)
const loading = ref(true)
const error = ref('')
const lastUpdated = ref('')
const autoRefresh = ref(true)
let timer: ReturnType<typeof setInterval> | null = null

async function load(silent = false) {
  if (!silent)
    loading.value = true
  try {
    data.value = await getActiveTasks()
    error.value = ''
    lastUpdated.value = new Date().toLocaleTimeString()
  }
  catch (e: any) {
    error.value = e?.detail || e?.message || '加载失败'
  }
  finally {
    loading.value = false
  }
}

function startTimer() {
  stopTimer()
  if (autoRefresh.value)
    timer = setInterval(load, REFRESH_MS, true)
}
function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}
function toggleAuto() {
  autoRefresh.value = !autoRefresh.value
  startTimer()
}

onMounted(() => {
  load()
  startTimer()
})
onUnmounted(stopTimer)

// durable 队列按 queue 透视：{ queue: { status: count } }
const queuePivot = computed<Record<string, Record<string, number>>>(() => {
  const out: Record<string, Record<string, number>> = {}
  for (const row of data.value?.queue.by_queue_status ?? []) {
    out[row.queue] = out[row.queue] || {}
    out[row.queue][row.status] = row.count
  }
  return out
})

function pct(p: number, t: number): number {
  if (!t || t <= 0)
    return 0
  return Math.min(100, Math.round((p / t) * 100))
}
</script>

<template>
  <div class="p-6 space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-lg font-semibold text-foreground">
          任务中心
        </h1>
        <p class="text-xs text-muted-foreground mt-0.5">
          当前排队中 / 进行中的后台任务：代码索引、AI 描述、durable 队列
        </p>
      </div>
      <div class="flex items-center gap-2">
        <span v-if="lastUpdated" class="text-xs text-muted-foreground">更新于 {{ lastUpdated }}</span>
        <Button size="sm" variant="outline" @click="toggleAuto">
          {{ autoRefresh ? '暂停自动刷新' : '开启自动刷新' }}
        </Button>
        <Button size="sm" variant="outline" @click="() => load()">
          刷新
        </Button>
      </div>
    </div>

    <LoadingState v-if="loading && !data" />
    <div v-else-if="error" class="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
      {{ error }}
    </div>

    <template v-else-if="data">
      <!-- durable 队列深度 -->
      <section class="space-y-3">
        <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
          <span class="icon-[lucide--layers] w-4 h-4" /> 持久化队列（索引 / 图谱 / AI 描述 / 页面）
        </h2>
        <div class="rounded-lg border border-border divide-y divide-border">
          <div v-if="Object.keys(queuePivot).length === 0" class="p-4 text-sm text-muted-foreground">
            队列为空
          </div>
          <div
            v-for="(statuses, queue) in queuePivot"
            :key="queue"
            class="flex items-center gap-3 p-3 text-sm"
          >
            <span class="w-32 shrink-0 font-mono text-xs text-muted-foreground">{{ queue }}</span>
            <span
              v-for="(count, st) in statuses"
              :key="st"
              class="rounded px-2 py-0.5 text-xs bg-muted text-foreground"
            >{{ st }}: {{ count }}</span>
          </div>
        </div>
      </section>

      <!-- 正在索引的仓库 -->
      <section class="space-y-3">
        <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
          <span class="icon-[lucide--database] w-4 h-4" /> 正在索引（{{ data.indexing.count }}）
        </h2>
        <div class="rounded-lg border border-border divide-y divide-border">
          <div v-if="data.indexing.items.length === 0" class="p-4 text-sm text-muted-foreground">
            暂无正在索引的仓库
          </div>
          <RouterLink
            v-for="r in data.indexing.items"
            :key="r.repository_id"
            :to="`/repositories/${r.repository_id}?tab=indexing`"
            class="flex items-center gap-3 p-3 text-sm hover:bg-accent transition-colors"
          >
            <span class="flex-1 truncate font-medium text-foreground">{{ r.name }}</span>
            <span class="text-xs text-muted-foreground">{{ r.stage || '索引中' }}</span>
            <span v-if="r.files_total > 0" class="text-xs text-muted-foreground tabular-nums">
              {{ r.files_processed }}/{{ r.files_total }}（{{ pct(r.files_processed, r.files_total) }}%）
            </span>
          </RouterLink>
        </div>
      </section>

      <!-- AI 描述排队 -->
      <section class="space-y-3">
        <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
          <span class="icon-[lucide--sparkles] w-4 h-4" /> AI 描述生成（{{ data.summary.count }}）
        </h2>
        <div class="rounded-lg border border-border divide-y divide-border">
          <div v-if="data.summary.items.length === 0" class="p-4 text-sm text-muted-foreground">
            暂无排队/进行中的 AI 描述任务
          </div>
          <RouterLink
            v-for="r in data.summary.items"
            :key="r.repository_id"
            :to="`/repositories/${r.repository_id}`"
            class="flex items-center gap-3 p-3 text-sm hover:bg-accent transition-colors"
          >
            <span class="flex-1 truncate font-medium text-foreground">{{ r.name }}</span>
            <span class="rounded px-2 py-0.5 text-xs bg-muted text-foreground">{{ r.status }}</span>
          </RouterLink>
        </div>
      </section>
    </template>
  </div>
</template>
