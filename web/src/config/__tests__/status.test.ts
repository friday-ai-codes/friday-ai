import { describe, expect, it } from 'vitest'
import {
  codingTaskStatusConfig,
  executionStatusConfig,
  getStatusConfig,
  indexStatusConfig,
  runnerStatusConfig,
  triggerLogStatusConfig,
} from '~/config/status'

describe('statusConfig constants', () => {
  it('executionStatusConfig should have running with info variant and animate', () => {
    const running = executionStatusConfig.running
    expect(running).toEqual({
      label: '运行中',
      icon: 'lucide--loader-2',
      variant: 'info',
      animate: true,
    })
  })

  it('runnerStatusConfig should have online and offline', () => {
    expect(runnerStatusConfig.online.variant).toBe('success')
    expect(runnerStatusConfig.offline.variant).toBe('muted')
  })

  it('codingTaskStatusConfig should have all coding task statuses', () => {
    expect(codingTaskStatusConfig.pending).toBeDefined()
    expect(codingTaskStatusConfig.planning).toBeDefined()
    expect(codingTaskStatusConfig.plan_review).toBeDefined()
    expect(codingTaskStatusConfig.executing).toBeDefined()
    expect(codingTaskStatusConfig.code_review).toBeDefined()
    expect(codingTaskStatusConfig.merged).toBeDefined()
    expect(codingTaskStatusConfig.partial_success).toBeDefined()
    expect(codingTaskStatusConfig.failed).toBeDefined()
  })

  it('indexStatusConfig should have all index statuses', () => {
    expect(indexStatusConfig.pending).toBeDefined()
    expect(indexStatusConfig.running).toBeDefined()
    expect(indexStatusConfig.completed).toBeDefined()
    expect(indexStatusConfig.failed).toBeDefined()
  })

  it('triggerLogStatusConfig should have all trigger log statuses', () => {
    expect(triggerLogStatusConfig.accepted).toBeDefined()
    expect(triggerLogStatusConfig.ignored).toBeDefined()
    expect(triggerLogStatusConfig.error).toBeDefined()
    expect(triggerLogStatusConfig.duplicate).toBeDefined()
  })
})

describe('getStatusConfig', () => {
  it('should return correct config for execution running', () => {
    const config = getStatusConfig('execution', 'running')
    expect(config).toEqual({
      label: '运行中',
      icon: 'lucide--loader-2',
      variant: 'info',
      animate: true,
    })
  })

  it('should return fallback for unknown status', () => {
    const config = getStatusConfig('execution', 'unknown_status')
    expect(config.variant).toBe('muted')
    expect(config.icon).toBe('lucide--help-circle')
    expect(config.label).toBe('unknown_status')
  })

  it('should return correct config for runner online', () => {
    const config = getStatusConfig('runner', 'online')
    expect(config.variant).toBe('success')
    expect(config.label).toBe('在线')
  })

  it('should return correct config for codingTask merged', () => {
    const config = getStatusConfig('codingTask', 'merged')
    expect(config.variant).toBe('success')
    expect(config.label).toBe('已合并')
  })

  it('should return correct config for triggerLog accepted', () => {
    const config = getStatusConfig('triggerLog', 'accepted')
    expect(config.variant).toBe('success')
    expect(config.label).toBe('已接受')
  })
})
