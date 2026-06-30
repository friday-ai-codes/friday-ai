import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import fixture from '~/types/workflow/__fixtures__/node-types.fixture.json'

/**
 * 前后端节点漂移守护（D-05 / SSOT-03）—— fixture 驱动（离线）。
 *
 * 以 19-01 入库的后端精简快照 `node-types.fixture.json` 为唯一对账基准，
 * 不依赖在线后端（CI 离线）。NodePalette.vue 通过文件读取 + 正则提取节点
 * 类型集合，与 fixture 的 node_type 全集对账。
 *
 * 注意（Pitfall 6）：fixture 是离线快照。若后端新增/改节点定义，必须重跑
 * `pnpm -C web gen:node-fixture` 刷新此 fixture，否则本守护会失效或误红。
 */

interface FixtureNode {
  node_type: string
  category: string
  inputs: { name: string }[]
  outputs: { name: string }[]
}

const REGEN_HINT = '前后端节点漂移：请运行 `pnpm -C web gen:node-fixture` 重新生成 fixture，并核对 NodePalette.vue'

const fixtureNodes = (fixture as { nodes: FixtureNode[] }).nodes
const fixtureTypes = new Set(fixtureNodes.map(n => n.node_type))
const fixtureByType = new Map(fixtureNodes.map(n => [n.node_type, n]))

// NodePalette.vue 通过文件读取 + 正则提取节点类型列表（与 validate-node-definitions.ts 同款范式）
const sidebarDir = path.resolve(__dirname, '../workflow/sidebar')
const rawPaletteSource = fs.readFileSync(path.join(sidebarDir, 'NodePalette.vue'), 'utf-8')

// 先剥离注释，避免文档示例（如注释里的 `type: 'xxx'`）被正则误当作节点类型
const paletteSource = rawPaletteSource
  .replace(/<!--[\s\S]*?-->/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/\/\/[^\n]*/g, '')

const paletteSet = new Set(
  [...paletteSource.matchAll(/(?:type:\s*|fromDef\()'([^']+)'/g)].map(m => m[1]),
)

// 已知应被根除的幽灵节点（后端从未注册；以字符串字面量直接守护，仅枚举确实不存在的旧名）
const KNOWN_GHOSTS = ['code_implement', 'technical_plan']

describe('前后端节点漂移守护（fixture 驱动）', () => {
  it('palette 节点类型应全部 ⊆ 后端 fixture node_type 全集', () => {
    const orphan = [...paletteSet].filter(type => !fixtureTypes.has(type))
    expect(orphan, `palette 含 fixture 不存在的节点 ${orphan.join(', ')} —— ${REGEN_HINT}`).toEqual([])
  })

  it('palette 不应包含已根除的幽灵节点', () => {
    for (const ghost of KNOWN_GHOSTS) {
      expect(paletteSet.has(ghost), `palette 仍含幽灵节点 ${ghost}`).toBe(false)
    }
  })

  it('ai_plan_generation 已完全移除（Chassis v2 删除旧 plan 域，palette 与 fixture 均无）', () => {
    expect(paletteSet.has('ai_plan_generation'), 'ai_plan_generation 应已从 NodePalette 移除').toBe(false)
    expect(fixtureTypes.has('ai_plan_generation'), `ai_plan_generation 已随旧 plan 域移除，不应再在 fixture —— ${REGEN_HINT}`).toBe(false)
  })

  it('ai_plan_research 已暴露到 palette 且 ⊆ fixture（UNIFY-02 第二半）', () => {
    expect(paletteSet.has('ai_plan_research'), 'ai_plan_research 应暴露到 NodePalette AI 分组').toBe(true)
    expect(fixtureTypes.has('ai_plan_research'), `ai_plan_research 应在 fixture —— ${REGEN_HINT}`).toBe(true)
  })

  it('真实节点 fetch_space_info 应同时存在于 fixture 与 palette', () => {
    expect(fixtureTypes.has('fetch_space_info'), `fixture 缺 fetch_space_info —— ${REGEN_HINT}`).toBe(true)
    expect(paletteSet.has('fetch_space_info')).toBe(true)
  })

  it('动态端口节点 parallel/join 应作为 control 节点存在于 fixture', () => {
    for (const type of ['parallel', 'join']) {
      const node = fixtureByType.get(type)
      expect(node, `fixture 缺 ${type} —— ${REGEN_HINT}`).toBeDefined()
      expect(node?.category).toBe('control')
    }
  })

  it('多端口节点的端口集应与 fixture 对账（不再依赖 getDefaultPortsForNodeType）', () => {
    // parallel/join 为运行时动态端口，后端静态快照不含分支端口，
    // 故对真实多输出节点（human_approval 的 approved/rejected）做端口集漂移守护。
    const approval = fixtureByType.get('human_approval')
    expect(approval, `fixture 缺 human_approval —— ${REGEN_HINT}`).toBeDefined()
    const approvalOutputs = (approval?.outputs ?? []).map(o => o.name)
    expect(approvalOutputs).toContain('approved')
    expect(approvalOutputs).toContain('rejected')

    // webhook_trigger 多输出（default/headers/query）亦由 fixture 驱动校验。
    const webhook = fixtureByType.get('webhook_trigger')
    expect(webhook, `fixture 缺 webhook_trigger —— ${REGEN_HINT}`).toBeDefined()
    expect((webhook?.outputs ?? []).length).toBeGreaterThanOrEqual(2)
  })
})
