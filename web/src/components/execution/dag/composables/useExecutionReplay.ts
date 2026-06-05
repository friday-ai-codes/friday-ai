import type { Ref } from 'vue'
import type { NodeExecution, WorkflowExecution } from '~/stores/useExecutionsStore'
import { useIntervalFn } from '@vueuse/core'
import { computed, ref } from 'vue'

export type ReplaySpeed = 0 | 0.5 | 1 | 2 | 4

export interface ReplayState {
  isPlaying: Ref<boolean>
  currentTime: Ref<number>
  speed: Ref<ReplaySpeed>
  totalDuration: Ref<number>
  mode: Ref<'auto' | 'manual' | 'seek'>
  play: () => void
  pause: () => void
  stepForward: () => void
  stepBackward: () => void
  seek: (timeMs: number) => void
  setSpeed: (s: ReplaySpeed) => void
  getNodeStatus: (nodeExecution: NodeExecution) => string
  getNodeElapsed: (nodeExecution: NodeExecution) => number | undefined
  reset: () => void
}

/**
 * 计算执行开始时间的毫秒时间戳。
 * 如果 execution.started_at 不存在，返回 0。
 */
function getExecutionStartMs(execution: WorkflowExecution | null): number {
  if (!execution?.started_at)
    return 0
  return new Date(execution.started_at).getTime()
}

/**
 * 计算执行总时长（毫秒）。
 * 基于 completed_at - started_at；若未完成则取所有节点 completed_at 的最大值。
 */
function computeTotalDuration(execution: WorkflowExecution | null): number {
  if (!execution)
    return 0
  const startMs = getExecutionStartMs(execution)
  if (execution.completed_at) {
    return Math.max(0, new Date(execution.completed_at).getTime() - startMs)
  }
  // 未完成的执行：取节点最大 completed_at
  let maxEnd = startMs
  for (const ne of execution.node_executions ?? []) {
    if (ne.completed_at) {
      maxEnd = Math.max(maxEnd, new Date(ne.completed_at).getTime())
    }
  }
  return Math.max(0, maxEnd - startMs)
}

/**
 * 回放状态管理 composable。
 *
 * currentTime 为相对于 execution.started_at 的毫秒数。
 * 自动播放使用 useIntervalFn，每 100ms 递增 currentTime by 100 * speed。
 */
export function useExecutionReplay(
  execution: Ref<WorkflowExecution | null>,
): ReplayState {
  const isPlaying = ref(false)
  const currentTime = ref(0)
  const speed = ref<ReplaySpeed>(1)
  const mode = ref<'auto' | 'manual' | 'seek'>('auto')

  const totalDuration = computed(() => computeTotalDuration(execution.value))

  const startMs = computed(() => getExecutionStartMs(execution.value))

  // 自动播放 interval
  const { pause: pauseInterval, resume: resumeInterval } = useIntervalFn(
    () => {
      const step = 100 * speed.value
      const next = currentTime.value + step
      if (next >= totalDuration.value) {
        currentTime.value = totalDuration.value
        isPlaying.value = false
        pauseInterval()
      }
      else {
        currentTime.value = next
      }
    },
    100,
    { immediate: false },
  )

  function play() {
    if (currentTime.value >= totalDuration.value) {
      currentTime.value = 0
    }
    mode.value = 'auto'
    isPlaying.value = true
    resumeInterval()
  }

  function pause() {
    isPlaying.value = false
    pauseInterval()
  }

  /** 找到下一个节点状态变更时刻 */
  function stepForward() {
    mode.value = 'manual'
    pause()
    const exec = execution.value
    if (!exec)
      return
    const current = currentTime.value
    let nextTime = totalDuration.value
    for (const ne of exec.node_executions ?? []) {
      const neStart = ne.started_at
        ? new Date(ne.started_at).getTime() - startMs.value
        : null
      const neEnd = ne.completed_at
        ? new Date(ne.completed_at).getTime() - startMs.value
        : null
      if (neStart !== null && neStart > current && neStart < nextTime)
        nextTime = neStart
      if (neEnd !== null && neEnd > current && neEnd < nextTime)
        nextTime = neEnd
    }
    currentTime.value = nextTime
  }

  /** 找到上一个节点状态变更时刻 */
  function stepBackward() {
    mode.value = 'manual'
    pause()
    const exec = execution.value
    if (!exec)
      return
    const current = currentTime.value
    let prevTime = 0
    for (const ne of exec.node_executions ?? []) {
      const neStart = ne.started_at
        ? new Date(ne.started_at).getTime() - startMs.value
        : null
      const neEnd = ne.completed_at
        ? new Date(ne.completed_at).getTime() - startMs.value
        : null
      if (neStart !== null && neStart < current && neStart > prevTime)
        prevTime = neStart
      if (neEnd !== null && neEnd < current && neEnd > prevTime)
        prevTime = neEnd
    }
    currentTime.value = prevTime
  }

  function seek(timeMs: number) {
    mode.value = 'seek'
    pause()
    currentTime.value = Math.max(0, Math.min(timeMs, totalDuration.value))
  }

  function setSpeed(s: ReplaySpeed) {
    speed.value = s
  }

  /**
   * 计算节点在 currentTime 时刻的状态。
   * - 尚未开始 → 'pending'
   * - 已开始但未完成 → 'running'
   * - 已完成 → 返回最终状态（completed/failed/etc）
   */
  function getNodeStatus(nodeExecution: NodeExecution): string {
    const execStart = startMs.value
    const current = currentTime.value
    const neStart = nodeExecution.started_at
      ? new Date(nodeExecution.started_at).getTime() - execStart
      : null
    const neEnd = nodeExecution.completed_at
      ? new Date(nodeExecution.completed_at).getTime() - execStart
      : null

    if (neStart === null || current < neStart)
      return 'pending'
    if (neEnd === null || current < neEnd)
      return 'running'
    return nodeExecution.status
  }

  /**
   * 计算节点在 currentTime 时刻的已执行时长（秒）。
   * 用于覆盖 useNodeTimer 的实时 elapsed。
   */
  function getNodeElapsed(nodeExecution: NodeExecution): number | undefined {
    const execStart = startMs.value
    const current = currentTime.value
    const neStart = nodeExecution.started_at
      ? new Date(nodeExecution.started_at).getTime() - execStart
      : null
    const neEnd = nodeExecution.completed_at
      ? new Date(nodeExecution.completed_at).getTime() - execStart
      : null

    if (neStart === null || current < neStart)
      return undefined
    const effectiveEnd = neEnd !== null ? Math.min(neEnd, current) : current
    return (effectiveEnd - neStart) / 1000
  }

  function reset() {
    pause()
    currentTime.value = 0
    speed.value = 1
    mode.value = 'auto'
  }

  return {
    isPlaying,
    currentTime,
    speed,
    totalDuration,
    mode,
    play,
    pause,
    stepForward,
    stepBackward,
    seek,
    setSpeed,
    getNodeStatus,
    getNodeElapsed,
    reset,
  }
}
