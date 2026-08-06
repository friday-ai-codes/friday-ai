/**
 * markdown → 纯文本提取测试。
 *
 * 两条路径必须给出同样的结果：markdown-it token 流（渲染器就绪后）与同步兜底
 * （就绪前）。功能点名是从需求文档逐行裁剪的，块级前缀是这里的主要目标。
 */
import MarkdownIt from 'markdown-it'
import { describe, expect, it } from 'vitest'
import { mdTokensToPlainText, stripMarkdownSync } from '../markdownText'

const md = new MarkdownIt({ linkify: true, breaks: true, html: false })

const CASES: Array<[string, string]> = [
  ['#### 功能点 A：页面结构与 4 节点', '功能点 A：页面结构与 4 节点'],
  ['## 模块 3: 单题型学习页与 4 节点解锁', '模块 3: 单题型学习页与 4 节点解锁'],
  ['- [ ] **当** 用户首次进入题型时', '当 用户首次进入题型时'],
  ['1. 有序列表项', '有序列表项'],
  ['> 引用说明', '引用说明'],
  ['`inline code` 与 **加粗**', 'inline code 与 加粗'],
  ['[技术方案](https://example.dev/plan)', '技术方案'],
  ['纯文字，不该被改动', '纯文字，不该被改动'],
  ['', ''],
]

describe('markdownToPlainText', () => {
  it.each(CASES)('token 解析剥掉标记：%s', (input, expected) => {
    expect(mdTokensToPlainText(md, input)).toBe(expected)
  })

  it.each(CASES)('同步兜底给出同样结果：%s', (input, expected) => {
    expect(stripMarkdownSync(input)).toBe(expected)
  })

  it('多行内容折叠为单行（节点名恒单行展示）', () => {
    expect(mdTokensToPlainText(md, '#### 标题\n\n正文段落')).toBe('标题 正文段落')
    expect(stripMarkdownSync('#### 标题\n\n正文段落')).toBe('标题 正文段落')
  })

  it('叠加前缀逐层剥净', () => {
    expect(stripMarkdownSync('> - [x] 已完成项')).toBe('已完成项')
    expect(mdTokensToPlainText(md, '> - [x] 已完成项')).toBe('已完成项')
  })
})
