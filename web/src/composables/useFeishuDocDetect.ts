/**
 * 飞书文档链接检测 — 从消息内容中提取第一个飞书文档 ID。
 *
 * 支持 feishu.cn 和 larksuite.com 域名的 /docx/ 路径格式。
 * 按 仅在发送时调用，不做实时输入检测。
 * 按 只返回第一个匹配的文档 ID。
 */
const FEISHU_DOC_REGEX = /https?:\/\/[\w.-]*(?:feishu\.cn|larksuite\.com)\/docx\/(\w+)/
export function extractFirstFeishuDocId(content: string): string | null {
 const match = content.match(FEISHU_DOC_REGEX)
 return match ? match[1]: null
}
