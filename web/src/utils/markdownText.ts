/**
 * markdown → 纯文本提取（树节点名/单行标题专用）。
 *
 * 功能点名是从需求文档**逐行裁剪**来的，常常连着块级标记一起进来
 * （`#### 功能点 A：…`、`- [ ] **当** …`、`> 说明`）。行内渲染（`renderInline`）
 * 按设计只认行内语法，块级标记会原样显示，所以这里改成「取文字」。
 *
 * 两条路径同义，差别只在时机：
 * - `mdTokensToPlainText`：markdown-it token 流，语法由解析器判定，是权威结果；
 * - `stripMarkdownSync`：渲染器异步加载完成前的同步兜底，避免先闪一帧 `####`。
 */

import type MarkdownIt from 'markdown-it'
import type Token from 'markdown-it/lib/token.mjs'

/**
 * 块级前缀：引用 / ATX 标题 / 列表项 / 任务框，各剥一层，由调用方循环到不再匹配。
 * 逐层剥而非一次匹配，是因为它们可任意叠加（`> - [x] 项`）。
 */
const BLOCK_PREFIX_RE = /^[ \t]*(?:>[ \t]*|#{1,6}[ \t]+|(?:[-*+]|\d+[.)])[ \t]+|\[[ x]\][ \t]+)/i

/** 任务框：markdown-it 不含 task-list 插件，`[ ]` 会原样留在正文 token 里。 */
const TASK_BOX_RE = /^\[[ x]\][ \t]+/i

function stripBlockPrefix(line: string): string {
  let out = line
  for (;;) {
    const next = out.replace(BLOCK_PREFIX_RE, '')
    if (next === out)
      return out
    out = next
  }
}

/** 折叠换行与连续空白——节点名恒为单行展示。 */
function collapse(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

/** 收集 inline token 的可见文字（图片取 alt，代码取原文，软/硬换行折成空格）。 */
function inlineText(children: Token[] | null): string {
  let out = ''
  for (const child of children ?? []) {
    switch (child.type) {
      case 'text':
      case 'code_inline':
        out += child.content
        break
      case 'image':
        out += child.content || (child.attrGet('alt') ?? '')
        break
      case 'softbreak':
      case 'hardbreak':
        out += ' '
        break
      default:
        // 成对标记（em/strong/link/del…）本身不产生文字，其内容在子 token 里。
        if (child.children?.length)
          out += inlineText(child.children)
    }
  }
  return out
}

/** 用 markdown-it 解析后只取文字（标题、列表、引用、强调、链接等标记一律剥掉）。 */
export function mdTokensToPlainText(md: MarkdownIt, src: string): string {
  if (!src)
    return ''
  let out = ''
  try {
    for (const token of md.parse(src, {})) {
      if (token.type === 'inline')
        out += `${inlineText(token.children).replace(TASK_BOX_RE, '')} `
      // 围栏/缩进代码块没有 inline 子节点，内容直接挂在 token 上。
      else if (token.type === 'fence' || token.type === 'code_block')
        out += `${token.content} `
    }
  }
  catch {
    return stripMarkdownSync(src)
  }
  return collapse(out)
}

/** 同步兜底：按常见标记剥壳，覆盖节点名里实际出现的那几类语法。 */
export function stripMarkdownSync(src: string): string {
  if (!src)
    return ''
  const text = src
    .split('\n')
    .map(stripBlockPrefix)
    .join('\n')
    // 围栏代码块的栅栏行与分隔线
    .replace(/^[ \t]*(?:`{3}|~{3}).*$/gm, '')
    .replace(/^[ \t]*(?:[-*_][ \t]*){3,}$/gm, '')
    // 行内：图片/链接取显示文字，强调与行内代码脱壳
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/(\*\*|__|~~)(.+?)\1/g, '$2')
    .replace(/(?<![\w*])[*_](?!\s)([^*_]+)(?<!\s)[*_](?![\w*])/g, '$1')
    .replace(/`+([^`]+)`+/g, '$1')
  return collapse(text)
}
