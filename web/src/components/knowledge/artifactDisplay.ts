// 交付文档展示共享常量（KDEP-02/04/11 视觉统一）：类型徽标配色 + 载体图标。
// 由知识域三处调用点（知识总览搜索 P96 / 交付文档树 P97 / 实体关联卡 P99）共用，
// 避免拷贝漂移。值为字面量完整 class 字符串，确保 Tailwind 源扫描命中、无需 safelist。

/** 工件类型/能力徽标配色令牌（琥珀色系，与 EntityKindBadge 视觉一致）。 */
export const ARTIFACT_BADGE_CLASS = 'bg-amber-500/10 text-amber-700 border-amber-200 dark:text-amber-400'

/** 载体 → 图标类名映射（完整 `icon-[lucide--*]` 字面量）。 */
export const CARRIER_ICON: Record<string, string> = {
  feishu_doc: 'icon-[lucide--file-text]',
  feishu_bitable: 'icon-[lucide--table]',
  markdown: 'icon-[lucide--file-text]',
  repo_file: 'icon-[lucide--file-code]',
  external_link: 'icon-[lucide--external-link]',
}

/** 取载体图标类名，未知载体兜底为通用文件图标。 */
export function carrierIcon(carrier: string): string {
  return CARRIER_ICON[carrier] ?? 'icon-[lucide--file]'
}
