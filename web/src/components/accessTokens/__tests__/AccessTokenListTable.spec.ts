import type { AccessTokenDto } from '~/types/accessToken'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AccessTokenListTable from '~/components/accessTokens/AccessTokenListTable.vue'

// ============================================================================
// Nyquist Wave 0 契约（RED until 06-03）：
// 指纹展示 prefix…suffix（… = U+2026）；历史 token（空 suffix）仅展示 prefix
// 且无悬挂分隔符；备注列以 Vue 文本插值（自动转义）渲染 note。
// ============================================================================

// 扩展 DTO：06-03 将向 AccessTokenDto 补充 token_suffix / note 只读字段。
type ListToken = AccessTokenDto & { token_suffix: string, note: string }

function makeToken(overrides: Partial<ListToken> = {}): ListToken {
  return {
    id: overrides.id ?? 'tok-1',
    name: overrides.name ?? 'test',
    token_prefix: overrides.token_prefix ?? 'friday_pat_',
    token_suffix: overrides.token_suffix ?? '',
    note: overrides.note ?? '',
    created_at: overrides.created_at ?? '2026-06-04T00:00:00Z',
    expires_at: overrides.expires_at ?? null,
    revoked_at: overrides.revoked_at ?? null,
    last_used_at: overrides.last_used_at ?? null,
    is_valid: overrides.is_valid ?? true,
  }
}

describe('accessTokenListTable fingerprint + note', () => {
  it('renders prefix…suffix for a suffixed token (PAT-03)', () => {
    const wrapper = mount(AccessTokenListTable, {
      props: {
        tokens: [makeToken({ token_prefix: 'friday_pat_ab', token_suffix: 'WXYZ' })],
      },
    })

    // U+2026 单字符省略号分隔前缀与后缀，形成 GitHub 风格可区分指纹。
    expect(wrapper.text()).toContain('friday_pat_ab\u2026WXYZ')
  })

  it('renders prefix only (no dangling …) for an empty-suffix historical token', () => {
    const wrapper = mount(AccessTokenListTable, {
      props: {
        tokens: [makeToken({ token_prefix: 'friday_pat_zz', token_suffix: '' })],
      },
    })

    const text = wrapper.text()
    // 历史 token 明文已丢、无法回填 suffix → 仅展示 prefix，绝不挂空分隔符。
    expect(text).toContain('friday_pat_zz')
    expect(text).not.toContain('friday_pat_zz\u2026')
  })

  it('renders the note value as escaped text in the row (PAT-01)', () => {
    const wrapper = mount(AccessTokenListTable, {
      props: {
        tokens: [makeToken({ note: 'ci pipeline note' })],
      },
    })

    expect(wrapper.text()).toContain('ci pipeline note')
  })
})
