/**
 * ：Git URL → Web URL 转换工具。
 *
 * 镜像后端 `server/services/git_platform/__init__.py` 的 SSH/HTTPS 解析算法，
 * 前后端保持一致。当前 coding-plan workflow 主要面向 GitLab，分支/commit 路径默认走 GitLab
 * 风格 `/-/tree/<branch>` 与 `/-/commit/<sha>`；后续若需要按
 * `repository.git_platform` 字段分支，扩展第二参数即可，不破坏现有签名。
 */

/** SSH 形态：git@host:namespace/project(.git)? */
const SSH_RE = /^git@([^:]+):(.+?)(?:\.git)?$/

/**
 * 从 git URL 提取 web 端 base（不含 trailing slash）。
 *
 * - `https://gitlab.com/ns/proj.git` → `https://gitlab.com/ns/proj`
 * - `git@gitlab.com:ns/proj.git`     → `https://gitlab.com/ns/proj`
 * - `https://github.com/o/r.git`     → `https://github.com/o/r`
 * - 异常输入                          → `''`
 */
export function extractGitWebBase(gitUrl: string): string {
  if (!gitUrl)
    return ''
  const trimmed = gitUrl.trim()

  // SSH 形态
  const ssh = SSH_RE.exec(trimmed)
  if (ssh) {
    const [, host, path] = ssh
    const cleanPath = path.replace(/\.git$/, '')
    if (!host || !cleanPath)
      return ''
    return `https://${host}/${cleanPath}`
  }

  // HTTPS 形态
  try {
    const url = new URL(trimmed)
    if (!url.protocol.startsWith('http'))
      return ''
    let path = url.pathname.replace(/^\/+/, '')
    if (path.endsWith('.git'))
      path = path.slice(0, -4)
    if (!path)
      return ''
    return `${url.protocol}//${url.host}/${path}`
  }
  catch {
    return ''
  }
}

/**
 * 构造分支页面 URL（GitLab 风格 `/-/tree/<branch>`）。
 *
 * branch_name 中可能含 `/`（feat/foo）/ 非 ASCII 字符（feat/路径），
 * 用 `encodeURIComponent` 转义保证安全。
 */
export function buildBranchUrl(gitUrl: string, branchName: string): string {
  const base = extractGitWebBase(gitUrl)
  if (!base || !branchName)
    return ''
  return `${base}/-/tree/${encodeURIComponent(branchName)}`
}

/**
 * 构造 commit 页面 URL（GitLab 风格 `/-/commit/<sha>`）。
 *
 * sha 仅含十六进制字符，无需 encodeURIComponent。
 */
export function buildCommitUrl(gitUrl: string, sha: string): string {
  const base = extractGitWebBase(gitUrl)
  if (!base || !sha)
    return ''
  return `${base}/-/commit/${sha}`
}
