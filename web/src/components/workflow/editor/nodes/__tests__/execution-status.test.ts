import { describe, expect, it } from 'vitest'
import {
 getExecutionStyle,
 type NodeExecutionStatus,
} from '../composables/useNodeStyle'
describe('getExecutionStyle', => {
 it('returns null for idle status', => {
 const result = getExecutionStyle('idle')
 expect(result).toBeNull
 })
 it('returns running style with blue border and glow class', => {
 const result = getExecutionStyle('running')
 expect(result).not.toBeNull
 expect(result!.borderColor).toBe('border-blue-500')
 expect(result!.glowClass).toBe('node-execution-running')
 })
 it('returns success style with emerald border', => {
 const result = getExecutionStyle('success')
 expect(result).not.toBeNull
 expect(result!.borderColor).toBe('border-emerald-500')
 expect(result!.glowClass).toBe('node-execution-success')
 })
 it('returns failed style with red border', => {
 const result = getExecutionStyle('failed')
 expect(result).not.toBeNull
 expect(result!.borderColor).toBe('border-red-500')
 expect(result!.glowClass).toBe('node-execution-failed')
 })
 it('returns skipped style with gray border', => {
 const result = getExecutionStyle('skipped')
 expect(result).not.toBeNull
 expect(result!.borderColor).toBe('border-gray-400')
 expect(result!.glowClass).toBe('node-execution-skipped')
 })
})
describe('NodeExecutionStatus type coverage', => {
 it('covers all five statuses: idle, running, success, failed, skipped', => {
 const allStatuses: NodeExecutionStatus = [
 'idle',
 'running',
 'success',
 'failed',
 'skipped',
 ]
 // 验证每种状态调用 getExecutionStyle 都不抛异常
 for (const status of allStatuses) {
 expect( => getExecutionStyle(status)).not.toThrow
 }
 expect(allStatuses).toHaveLength(5)
 })
})
