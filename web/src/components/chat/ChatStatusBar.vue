<script setup lang="ts">
const props = defineProps<{
  phase: string | null
  taskProgress: { completed: number, total: number } | null
  isInterrupting: boolean
}>()

const emit = defineEmits<{
  skip: []
}>()

// 仅在「等待澄清」态暴露跳过出口：卡片漏发 / 用户不想答时的兜底，
// 让后端基于现有信息直接作答，避免永久卡在等待中。
const canSkip = computed(() =>
  props.phase === 'waiting_clarification' && !props.isInterrupting,
)

const phaseDisplay: Record<string, { text: string, icon: string }> = {
  planning: { text: '正在规划...', icon: 'icon-[lucide--brain]' },
  executing: { text: '正在执行...', icon: 'icon-[lucide--zap]' },
  waiting: { text: '正在等待深度分析结果...', icon: 'icon-[lucide--loader]' },
  waiting_clarification: { text: '等待你在上方卡片中确认...', icon: 'icon-[lucide--help-circle]' },
  finalizing: { text: '正在整理回答...', icon: 'icon-[lucide--file-text]' },
}

const display = computed(() => {
  if (props.isInterrupting)
    return { text: '正在中断...', icon: 'icon-[lucide--loader]' }
  if (!props.phase)
    return null
  // 未知 phase 兜底用中文通用文案，不直接暴露内部英文 phase 名
  return phaseDisplay[props.phase] || { text: '正在处理...', icon: 'icon-[lucide--activity]' }
})

const showProgress = computed(() =>
  props.taskProgress && props.taskProgress.total > 1,
)

const progressDots = computed(() => {
  if (!props.taskProgress)
    return []
  return Array.from({ length: props.taskProgress.total }, (_, i) => i < props.taskProgress!.completed)
})
</script>

<template>
  <div v-if="display" class="status-bar">
    <div class="status-bar-inner">
      <span
        :class="display.icon"
        class="status-bar-icon"
        :style="isInterrupting ? undefined : {}"
      />
      <span class="status-bar-text">{{ display.text }}</span>

      <!-- 任务进度指示器 -->
      <template v-if="showProgress && taskProgress">
        <span class="status-bar-divider" />
        <span class="status-bar-progress-text">
          已完成 {{ taskProgress.completed }}/{{ taskProgress.total }}
        </span>
        <div class="status-bar-dots">
          <span
            v-for="(done, i) in progressDots"
            :key="i"
            class="status-bar-dot"
            :class="done ? 'status-bar-dot--done' : 'status-bar-dot--pending'"
          />
        </div>
      </template>

      <!-- 等待澄清时的跳过出口 -->
      <template v-if="canSkip">
        <span class="status-bar-divider" />
        <button type="button" class="status-bar-skip" @click="emit('skip')">
          <span class="icon-[lucide--skip-forward] text-[0.6875rem]" />
          跳过，直接回答
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.status-bar {
  padding: 0 0.5rem;
}

.status-bar-inner {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0.75rem;
  border-radius: 9999px;
  background: hsl(210 40% 98% / 0.8);
  border: 1px solid hsl(214 32% 91% / 0.6);
  box-shadow: 0 1px 3px hsl(215 28% 17% / 0.04);
  animation: status-fade-in 0.3s ease-out;
}

.status-bar-icon {
  font-size: 0.75rem;
  color: hsl(168 76% 42%);
  animation: status-pulse 2s ease-in-out infinite;
}

.status-bar-text {
  font-size: 0.75rem;
  color: hsl(215 16% 47%);
  font-weight: 500;
}

.status-bar-divider {
  width: 1px;
  height: 0.75rem;
  background: hsl(214 32% 91%);
}

.status-bar-progress-text {
  font-size: 0.6875rem;
  color: hsl(215 16% 47% / 0.7);
  font-variant-numeric: tabular-nums;
}

.status-bar-dots {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.status-bar-dot {
  width: 0.375rem;
  height: 0.375rem;
  border-radius: 50%;
  transition: all 0.3s ease;
}

.status-bar-dot--done {
  background: hsl(168 76% 42%);
}

.status-bar-dot--pending {
  background: hsl(214 32% 91%);
}

.status-bar-skip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
  font-size: 0.6875rem;
  font-weight: 500;
  color: hsl(168 76% 38%);
  border: 1px solid hsl(168 76% 42% / 0.3);
  background: hsl(168 76% 42% / 0.06);
  cursor: pointer;
  transition: all 0.15s;
}
.status-bar-skip:hover {
  background: hsl(168 76% 42% / 0.12);
  border-color: hsl(168 76% 42% / 0.5);
}

@keyframes status-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}

@keyframes status-fade-in {
  from {
    opacity: 0;
    transform: translateY(0.25rem);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
