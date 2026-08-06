/**
 * 实现项 `change_type` 展示口径（quick-260806-fpx）。
 *
 * 原本内联在 `ImplementationItemCard`；模块卡的「本模块实现项」清单要用同一套图标与
 * 颜色（否则同一条实现项在两处长得不一样，读者会以为是两种东西）⇒ 收敛到此。
 *
 * ⚠️ 图标是**运行期按值拼接的裸名** ⇒ 四档必须全在 `styles/main.css` 的 `@source inline`
 * safelist 里，缺一档的症状是「那一档实现项没有图标」，人工走查极易漏掉。
 *
 * ⛔ **不发明第五档**：未知 `change_type` 退 `outline` + 渲染 schema 原样 token。
 */

export type ChangeTypeVariant = 'success' | 'info' | 'destructive' | 'secondary'

export interface ChangeTypeMeta {
  variant: ChangeTypeVariant
  /** 裸图标名（消费方拼 `icon-[${icon}]`）。 */
  icon: string
  /** `knowledge.blueprints.impl.*` 下的键后缀。 */
  labelKey: string
}

const CHANGE_TYPE_META: Record<string, ChangeTypeMeta> = {
  create: { variant: 'success', icon: 'lucide--file-plus', labelKey: 'changeTypeCreate' },
  modify: { variant: 'info', icon: 'lucide--file-pen-line', labelKey: 'changeTypeModify' },
  remove: { variant: 'destructive', icon: 'lucide--file-x', labelKey: 'changeTypeRemove' },
  indirect_refine: {
    variant: 'secondary',
    icon: 'lucide--file-cog',
    labelKey: 'changeTypeIndirectRefine',
  },
}

export function changeTypeMetaOf(changeType: string | undefined): ChangeTypeMeta | null {
  return CHANGE_TYPE_META[changeType ?? ''] ?? null
}

/**
 * `files_touched[].action` 的同义词归一（LLM 产物是半可信输入：正典是
 * create/modify/remove 三档，但实测会吐 edit/update/delete/add 等近义 token）。
 */
const FILE_ACTION_CANONICAL: Record<string, 'create' | 'modify' | 'remove'> = {
  create: 'create',
  add: 'create',
  new: 'create',
  modify: 'modify',
  edit: 'modify',
  update: 'modify',
  change: 'modify',
  remove: 'remove',
  delete: 'remove',
}

/** `files_touched[].action` 三档 → variant（与 `change_type` 同色系，⛔ 不发明第四档）。 */
const FILE_ACTION_VARIANT: Record<string, 'success' | 'info' | 'destructive'> = {
  create: 'success',
  modify: 'info',
  remove: 'destructive',
}

function canonicalFileAction(action: string | undefined): 'create' | 'modify' | 'remove' | null {
  return FILE_ACTION_CANONICAL[String(action ?? '').trim().toLowerCase()] ?? null
}

export function fileActionVariantOf(action: string | undefined): 'success' | 'info' | 'destructive' | 'outline' {
  const canonical = canonicalFileAction(action)
  return canonical ? FILE_ACTION_VARIANT[canonical] : 'outline'
}

/**
 * `files_touched[].action` 的中文标签键（`knowledge.blueprints.impl.*` 后缀，与
 * `change_type` 复用同三档文案「新建/改动/删除」）；未知 token 返回 `null`，
 * 消费方原样渲染 —— 认不出的动作照实透出，⛔ 不猜。
 */
export function fileActionLabelKeyOf(action: string | undefined): string | null {
  const canonical = canonicalFileAction(action)
  if (canonical === 'create')
    return 'changeTypeCreate'
  if (canonical === 'modify')
    return 'changeTypeModify'
  if (canonical === 'remove')
    return 'changeTypeRemove'
  return null
}
