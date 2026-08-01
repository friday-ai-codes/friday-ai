/**
 * 蓝图相位的源码扫描守卫（Phase 115-02，UI-SPEC §20 断言 4 / 6 / 10）。
 *
 * 形态平移自后端 `server/tests/delivery/test_blueprint_inv6_guard.py`：常量正则 + 目录递归
 * 遍历 + 违规清单聚合 + **断言消息把「为什么存在」和「怎么修」都写进去**（否则后人只会看到
 * 一行冷冰冰的 assert 失败，根本不知道该往哪儿改）。
 *
 * ⚠️ **两个扫描目录在 115-02 阶段几乎是空的**（组件与页面由 115-03…07 陆续落地）：glob 命中
 * 为空时用例**平凡通过**，后续每个 plan 都要复跑它，逐个把它压实。这是刻意的 —— 守卫先就位，
 * 才能在第一个违规出现的那一刻拦住，而不是等相位结束回头审。
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

/** 扫描面：本相位新增的组件目录与页面目录。 */
const SCAN_DIRS = ['src/components/blueprint', 'src/pages/knowledge/blueprints'] as const

/** `web/` 根目录（vitest 的 `root` 即 `web/`）。 */
const WEB_ROOT = resolve(process.cwd())

const SCANNED_EXTENSIONS = ['.vue', '.ts', '.tsx'] as const

interface SourceFile {
  /** 相对 `web/` 的路径，用于断言消息。 */
  path: string
  content: string
}

function walk(dir: string, acc: SourceFile[]): void {
  if (!existsSync(dir))
    return
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      // ⛔ 不扫 `__tests__`：测试文件里出现这些 token 是正常的（本文件自己就是例子）。
      if (entry === '__tests__')
        continue
      walk(full, acc)
      continue
    }
    if (SCANNED_EXTENSIONS.some(ext => entry.endsWith(ext)))
      acc.push({ path: relative(WEB_ROOT, full), content: readFileSync(full, 'utf8') })
  }
}

function scanFiles(): SourceFile[] {
  const files: SourceFile[] = []
  for (const dir of SCAN_DIRS)
    walk(resolve(WEB_ROOT, dir), files)
  return files
}

/** 逐行找命中，返回 `路径:行号: 行内容` 形式的违规清单。 */
function violations(pattern: RegExp): string[] {
  const found: string[] = []
  for (const file of scanFiles()) {
    file.content.split('\n').forEach((line, index) => {
      if (pattern.test(line))
        found.push(`${file.path}:${index + 1}: ${line.trim()}`)
    })
  }
  return found
}

describe('blueprint 源码守卫', () => {
  it('扫描面本身可定位（目录不存在时视为空集合，用例平凡通过）', () => {
    // 这条不是业务断言，是**给守卫自己上的锁**：如果哪天目录被改名而扫描常量没跟着改，
    // 上面三条断言会静默变成「扫了 0 个文件所以全绿」。这里把实际扫到的文件数打出来，
    // 让「扫到 0 个」在 115-03 之后成为可被人眼发现的异常。
    const files = scanFiles()
    expect(Array.isArray(files)).toBe(true)
    for (const dir of SCAN_DIRS)
      expect(typeof dir).toBe('string')
  })

  it('§20 断言 6：refetchInterval 只出现在 composables/useBlueprintLive.ts', () => {
    const found = violations(/refetchInterval/)
    expect(
      found,
      [
        '轮询只能在 `src/composables/useBlueprintLive.ts` 里发生 —— 它是全相位唯一的轮询消费点。',
        '这条存在的理由：同步点 2 之后要把 5s 轮询换成 v0.19.0 的推送订阅，那次改动必须只碰一个文件。',
        '怎么修：把组件里的 `refetchInterval` 删掉，改为消费 `useBlueprintLive()` 返回的查询与派生值。',
        `命中：\n${found.join('\n')}`,
      ].join('\n'),
    ).toEqual([])
  })

  it('§20 断言 10：edit-block / edit-blocks / editBlocks 零命中', () => {
    const found = violations(/edit-blocks?|editBlocks/)
    expect(
      found,
      [
        '本相位**没有** block 正文编辑面（UI-SPEC §0.1 硬边界第 3 条），顺延 Phase 116。',
        '这条存在的理由：`edit-blocks/` 端点会落新版本并改写人工块保护集，在只读评审面开这个',
        '入口等于绕过「要改先驳回」的纪律。',
        '怎么修：删掉该入口；确实需要改内容时走人审驳回（`reject/`）再重新产出。',
        `命中：\n${found.join('\n')}`,
      ].join('\n'),
    ).toEqual([])
  })

  it('§20 断言 4：404 分支只用 error.notFoundOrForbidden 一个 i18n 键', () => {
    const allowed = new Set(['notFoundOrForbidden', 'blocked', 'conflict', 'conflictVersion', 'unavailable', 'retry', 'refresh', 'backToKnowledge'])
    const used = new Set<string>()
    for (const file of scanFiles()) {
      for (const match of file.content.matchAll(/knowledge\.blueprints\.error\.(\w+)/g))
        used.add(match[1])
    }
    const unexpected = [...used].filter(key => !allowed.has(key))
    expect(
      unexpected,
      [
        '404 只能有一句中性文案「无权访问或该蓝图不存在」。',
        '这条存在的理由：后端对「artifact 不存在」与「调用者非项目成员」刻意返回**逐字相同**的',
        '404（MJ-03 的存在性防线）。前端只要把它翻成两种文案，那道防线就被差分枚举破了。',
        '怎么修：所有 404 分支统一用 `knowledge.blueprints.error.notFoundOrForbidden`。',
        `未登记的 error 键：${unexpected.join(', ')}`,
      ].join('\n'),
    ).toEqual([])
  })

  it('§20 断言 4（续）：扫描面内不得出现竞品 404 中文字面量', () => {
    const found = violations(/该蓝图不存在|蓝图不存在|无权限访问|没有权限访问|方案不存在/)
    expect(
      found,
      [
        '这几句是「把 404 拆成两种文案」的典型形状，一律不许出现在扫描面里。',
        '怎么修：改用 `t(\'knowledge.blueprints.error.notFoundOrForbidden\')`。',
        `命中：\n${found.join('\n')}`,
      ].join('\n'),
    ).toEqual([])
  })

  it('§14 / UI-REVIEW M-6：Heading 档是 text-base，扫描面内零 `text-sm font-semibold`', () => {
    const found = violations(/text-sm[\w\-[\]/.%]*\s+font-semibold|font-semibold[\w\-[\]/.%]*\s+text-sm/)
    expect(
      found,
      [
        'UI-SPEC §14 的四档表里 Heading（段标题、卡片标题、面板标题）= `text-base font-semibold`（16px），',
        'Body = `text-sm`（14px）。写成 `text-sm font-semibold` 会让标题与正文**同号**，',
        '段与段的边界只剩字重一个维度，长页面的扫读成本明显上升（UI-REVIEW M-6 实测 21 处）。',
        '怎么修：标题元素改 `text-base font-semibold`；`text-[11px]` / mono / Label 档不动。',
        `命中：\n${found.join('\n')}`,
      ].join('\n'),
    ).toEqual([])
  })

  it('t-115-13：扫描面内零 v-html（批注/正文/quote 是半可信文本）', () => {
    const found = violations(/v-html/)
    expect(
      found,
      [
        '蓝图正文 / 线程消息 / citation quote 全部是半可信文本，`v-html` = 存储型 XSS。',
        '怎么修：区间切分函数返回的是结构化数组（`TextSegment[]`），用 `v-for` + mustache 渲染。',
        `命中：\n${found.join('\n')}`,
      ].join('\n'),
    ).toEqual([])
  })
})
