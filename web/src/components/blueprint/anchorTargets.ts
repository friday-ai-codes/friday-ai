import type { BlueprintAnchor } from '~/types/blueprint'

export interface BlueprintAnchorTarget {
  domId: string
  kind: 'repo' | 'implementation' | 'api' | 'section'
  sectionKey: string
  itemId: string
  fieldPath: string
}

/**
 * 把后端半可信的 `section_path` 收窄成页面已有的 DOM 锚点。
 * 畸形路径一律静默返回 null，避免线程定位反噬正文浏览。
 */
export function parseBlueprintSectionPath(sectionPath: unknown): BlueprintAnchorTarget | null {
  if (typeof sectionPath !== 'string')
    return null

  const path = sectionPath.trim()
  if (!path || !/^[a-z_]\w*(?:\[[^[\]]+\]|\.[a-z_]\w*)*$/i.test(path))
    return null

  const itemTargets: Array<{
    pattern: RegExp
    prefix: string
    kind: BlueprintAnchorTarget['kind']
    sectionKey: string
  }> = [
    {
      pattern: /^repo_associations\[([^[\]]+)\](?:\.(.*))?$/,
      prefix: 'repo-',
      kind: 'repo',
      sectionKey: 'repo_associations',
    },
    {
      pattern: /^implementation_overview\.items\[([^[\]]+)\](?:\.(.*))?$/,
      prefix: 'impl-',
      kind: 'implementation',
      sectionKey: 'implementation_overview',
    },
    {
      pattern: /^api_contracts\[([^[\]]+)\](?:\.(.*))?$/,
      prefix: 'api-',
      kind: 'api',
      sectionKey: 'api_contracts',
    },
  ]

  for (const target of itemTargets) {
    const match = path.match(target.pattern)
    const itemId = match?.[1]?.trim() ?? ''
    if (!itemId)
      continue
    return {
      domId: `${target.prefix}${itemId}`,
      kind: target.kind,
      sectionKey: target.sectionKey,
      itemId,
      fieldPath: match?.[2] ?? '',
    }
  }

  const sectionKey = path.match(/^([a-z_]\w*)/i)?.[1] ?? ''
  if (!sectionKey)
    return null
  return {
    domId: sectionKey,
    kind: 'section',
    sectionKey,
    itemId: '',
    fieldPath: path.slice(sectionKey.length).replace(/^[.[\]]+/, ''),
  }
}

/** block 锚优先；缺 block 时才退到卡级 / 段级锚点。 */
export function resolveBlueprintAnchorDomId(
  anchor: Pick<BlueprintAnchor, 'block_id' | 'section_path'> | null | undefined,
): string {
  const blockId = typeof anchor?.block_id === 'string' ? anchor.block_id.trim() : ''
  if (blockId)
    return `blk-${blockId}`
  return parseBlueprintSectionPath(anchor?.section_path)?.domId ?? ''
}
