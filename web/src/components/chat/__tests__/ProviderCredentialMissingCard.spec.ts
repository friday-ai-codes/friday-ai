/**
 * Phase Wave stub — Plan fill real assertion.
 *
 * Scope: 凭证缺失降级 Card 渲染 + 双 CTA（按角色分流 disabled/primary/secondary）。
 * Consumer: Plan Wave Task 03-02。
 */
import { describe, expect, it } from 'vitest'
describe('providerCredentialMissingCard (Phase Wave stub)', => {
 it.todo('Phase Wave stub — Plan fill real assertion')
 it('placeholder to ensure suite collects', => {
 expect(true).toBe(true)
 })
})
// TODO(Plan Task 03-02)：
// - 渲染 provider_type 文案（Anthropic / OpenAI / Gemini / Ollama）
// - system_admin 角色主 CTA "立即配置" 启用
// - project_admin 角色主 CTA 启用（跳项目凭证设置）
// - member / viewer 角色主 CTA disabled，副 CTA "联系管理员" 启用
// - recommended_actions 列表渲染
