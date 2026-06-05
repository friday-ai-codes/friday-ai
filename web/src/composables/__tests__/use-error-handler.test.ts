import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '~/api/client'

// 在 mock 之后导入被测模块
import { extractErrorMessage, useErrorHandler } from '~/composables/useErrorHandler'

// mock useToast，返回一个包含 error spy 的对象
const mockError = vi.fn()
vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ error: mockError }),
}))

describe('extractErrorMessage', () => {
  it('apiError(401, "") 返回 "请重新登录"', () => {
    expect(extractErrorMessage(new ApiError(401, ''))).toBe('请重新登录')
  })

  it('apiError(403, "") 返回 "无权限"', () => {
    expect(extractErrorMessage(new ApiError(403, ''))).toBe('无权限')
  })

  it('apiError(404, "") 返回 "资源不存在"', () => {
    expect(extractErrorMessage(new ApiError(404, ''))).toBe('资源不存在')
  })

  it('apiError(500, "") 返回 "服务器错误"', () => {
    expect(extractErrorMessage(new ApiError(500, ''))).toBe('服务器错误')
  })

  it('apiError 有 detail 时优先使用 detail', () => {
    expect(extractErrorMessage(new ApiError(422, '字段格式错误'))).toBe('字段格式错误')
  })

  it('apiError(500, "") 无 detail 时回退到 STATUS_MESSAGES', () => {
    expect(extractErrorMessage(new ApiError(500, ''))).toBe('服务器错误')
  })

  it('typeError("Failed to fetch") 返回网络错误提示', () => {
    expect(extractErrorMessage(new TypeError('Failed to fetch'))).toBe('网络连接失败，请检查网络')
  })

  it('普通 Error 返回 message', () => {
    expect(extractErrorMessage(new Error('something broke'))).toBe('something broke')
  })

  it('string 类型返回 "操作失败"', () => {
    expect(extractErrorMessage('string error')).toBe('操作失败')
  })

  it('null 返回 "操作失败"', () => {
    expect(extractErrorMessage(null)).toBe('操作失败')
  })

  it('undefined 返回 "操作失败"', () => {
    expect(extractErrorMessage(undefined)).toBe('操作失败')
  })
})

describe('useErrorHandler', () => {
  beforeEach(() => {
    mockError.mockClear()
  })

  it('handleError(e, context) 调用 showError(context+"失败", extractedMessage)', () => {
    const { handleError } = useErrorHandler()
    const err = new ApiError(500, '数据库超时')

    handleError(err, '保存')

    expect(mockError).toHaveBeenCalledWith('保存失败', '数据库超时')
  })

  it('handleError(e) 不传 context 时调用 showError("操作失败", extractedMessage)', () => {
    const { handleError } = useErrorHandler()
    const err = new Error('unknown issue')

    handleError(err)

    expect(mockError).toHaveBeenCalledWith('操作失败', 'unknown issue')
  })
})
