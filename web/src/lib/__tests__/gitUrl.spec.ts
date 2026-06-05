import { describe, expect, it } from 'vitest'
import { buildBranchUrl, buildCommitUrl, extractGitWebBase } from '../gitUrl'

describe('extractGitWebBase', () => {
  it('handles HTTPS GitLab URL with .git suffix', () => {
    expect(extractGitWebBase('https://gitlab.example.com/ns/proj.git'))
      .toBe('https://gitlab.example.com/ns/proj')
  })

  it('handles HTTPS without .git', () => {
    expect(extractGitWebBase('https://gitlab.example.com/ns/proj'))
      .toBe('https://gitlab.example.com/ns/proj')
  })

  it('handles SSH GitLab URL', () => {
    expect(extractGitWebBase('git@gitlab.example.com:ns/proj.git'))
      .toBe('https://gitlab.example.com/ns/proj')
  })

  it('handles SSH GitHub URL', () => {
    expect(extractGitWebBase('git@github.com:owner/repo.git'))
      .toBe('https://github.com/owner/repo')
  })

  it('returns empty for malformed input', () => {
    expect(extractGitWebBase('')).toBe('')
    expect(extractGitWebBase('not-a-url')).toBe('')
    expect(extractGitWebBase('ftp://example.com/x')).toBe('')
  })

  it('handles nested namespace (gitlab subgroups)', () => {
    expect(extractGitWebBase('https://gitlab.com/group/sub/proj.git'))
      .toBe('https://gitlab.com/group/sub/proj')
  })
})

describe('buildBranchUrl', () => {
  it('builds GitLab tree URL for normal branch', () => {
    expect(buildBranchUrl('https://gitlab.com/ns/p.git', 'feat/foo'))
      .toBe('https://gitlab.com/ns/p/-/tree/feat%2Ffoo')
  })

  it('handles SSH source', () => {
    expect(buildBranchUrl('git@gitlab.com:ns/p.git', 'main'))
      .toBe('https://gitlab.com/ns/p/-/tree/main')
  })

  it('returns empty for empty branch name', () => {
    expect(buildBranchUrl('https://gitlab.com/ns/p.git', '')).toBe('')
  })

  it('returns empty for invalid git URL', () => {
    expect(buildBranchUrl('garbage', 'main')).toBe('')
  })

  it('encodes special chars in branch name', () => {
    expect(buildBranchUrl('https://gitlab.com/ns/p.git', 'feat/路径'))
      .toContain(encodeURIComponent('feat/路径'))
  })
})

describe('buildCommitUrl', () => {
  it('builds commit page URL', () => {
    expect(buildCommitUrl('https://gitlab.com/ns/p.git', 'abc123def456'))
      .toBe('https://gitlab.com/ns/p/-/commit/abc123def456')
  })

  it('returns empty for empty sha', () => {
    expect(buildCommitUrl('https://gitlab.com/ns/p.git', '')).toBe('')
  })

  it('returns empty for invalid git URL', () => {
    expect(buildCommitUrl('not-a-url', 'abc')).toBe('')
  })
})
