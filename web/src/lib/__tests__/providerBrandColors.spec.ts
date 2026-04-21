/**
 * Phase Wave stub — Plan fill real assertion.
 *
 * Scope: providerBrandColors.ts token 文件 + 4 Provider 颜色映射。
 * Consumer: Plan Wave Task 05-03。
 */
import { describe, expect, it } from 'vitest'
describe('providerBrandColors (Phase Wave stub)', => {
 it.todo('Phase Wave stub — Plan fill real assertion')
 it('placeholder to ensure suite collects', => {
 expect(true).toBe(true)
 })
})
// TODO(Plan Task 05-03)：
// - export const providerBrandColors: Record<ProviderType, string>
// - anthropic → #D97757（Claude orange）
// - openai_chat / openai_responses → #10A37F（OpenAI green）
// - gemini → #4285F4（Google blue）
// - ollama → #000000 / #FFFFFF（双模式）
// - getProviderBrandColor(type) helper 返回默认 #808080 fallback
