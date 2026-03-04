/**
 * useMarkdownRenderer — markdown-it + Shiki 单例渲染器
 *
 * 延迟初始化：首次调用时才加载 markdown-it 和 @shikijs/markdown-it，
 * 之后复用同一实例。Shiki 使用 vitesse-dark 主题，与 JsonHighlighter 风格统一。
 */
import type MarkdownIt from 'markdown-it'
let mdPromise: Promise<MarkdownIt> | null = null
/**
 * 获取 markdown-it 渲染器实例（含 Shiki 代码高亮）。
 * 单例模式，全局只初始化一次。
 */
export function getMarkdownRenderer: Promise<MarkdownIt> {
 if (!mdPromise) {
 mdPromise = (async => {
 const { default: MdIt } = await import('markdown-it')
 const { default: Shiki } = await import('@shikijs/markdown-it')
 const md = MdIt({ linkify: true, breaks: true, html: false })
 md.use(await Shiki({
 themes: { dark: 'vitesse-dark' },
 }))
 return md
 })
 }
 return mdPromise
}
