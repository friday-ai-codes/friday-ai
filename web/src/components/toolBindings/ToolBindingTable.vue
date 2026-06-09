<script setup lang="ts">
/**
 * 工具令牌绑定列表表格
 *
 * 设计基线仿 AccessTokenListTable：圆角描边容器、uppercase 列头、行 hover、空态 row。
 *
 * 安全（T-10-05）：当前绑定令牌仅渲染 name + prefix…suffix 指纹，
 * 绝不渲染任何完整明文（BoundTokenDto 本身无此数据）。
 */
import type { BindableToolDto, ToolBindingDto } from '~/types/toolBinding'
import { computed } from 'vue'
import { Button } from '~/components/ui/button'

const props = defineProps<{
  tools: BindableToolDto[]
  bindings: ToolBindingDto[]
}>()

const emit = defineEmits<{
  (e: 'bind', tool: BindableToolDto): void
  (e: 'unbind', binding: ToolBindingDto): void
}>()

/** 工具 id → 当前绑定（unique(user, remote_tool) 保证至多一条）。 */
const bindingByTool = computed(() => {
  const map = new Map<number, ToolBindingDto>()
  for (const b of props.bindings)
    map.set(b.remote_tool, b)
  return map
})

const sourceLabels: Record<BindableToolDto['source'], string> = {
  mcp: 'MCP',
  skill: 'Skill',
}

/** 令牌指纹：prefix…suffix（非完整明文）；无 suffix 时仅 prefix。 */
function fingerprint(prefix: string, suffix: string): string {
  return suffix ? `${prefix}…${suffix}` : prefix
}
</script>

<template>
  <div class="overflow-hidden rounded-xl border border-border/60">
    <table class="w-full border-collapse text-sm">
      <thead>
        <tr class="border-b border-border/60 bg-muted/30">
          <th class="px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            工具
          </th>
          <th class="px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            来源
          </th>
          <th class="px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            当前绑定令牌
          </th>
          <th class="px-4 py-2.5 text-right text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            操作
          </th>
        </tr>
      </thead>
      <tbody class="divide-y divide-border/50">
        <tr
          v-for="tool in tools"
          :key="tool.id"
          class="group transition-colors hover:bg-muted/40"
        >
          <!-- 工具名 + 描述 -->
          <td class="px-4 py-3.5">
            <span class="block truncate font-medium text-foreground">{{ tool.name }}</span>
            <span class="block max-w-[18rem] truncate text-xs text-muted-foreground">{{ tool.description }}</span>
          </td>

          <!-- 来源标签 -->
          <td class="px-4 py-3.5">
            <span class="inline-flex items-center rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
              {{ sourceLabels[tool.source] }}
            </span>
          </td>

          <!-- 当前绑定令牌：仅 name + 指纹，绝不渲染明文 -->
          <td class="px-4 py-3.5">
            <template v-if="bindingByTool.get(tool.id)">
              <span class="font-medium text-foreground">{{ bindingByTool.get(tool.id)!.access_token.name }}</span>
              <span class="ml-2 font-mono text-xs text-muted-foreground">
                {{ fingerprint(bindingByTool.get(tool.id)!.access_token.token_prefix, bindingByTool.get(tool.id)!.access_token.token_suffix) }}
              </span>
            </template>
            <span v-else class="text-xs text-muted-foreground">未绑定</span>
          </td>

          <!-- 操作：绑定 / 换绑 + 解绑 -->
          <td class="px-4 py-3.5 text-right">
            <div class="flex items-center justify-end gap-1.5">
              <Button
                variant="ghost"
                size="sm"
                :aria-label="`${bindingByTool.get(tool.id) ? '换绑' : '绑定'} ${tool.name}`"
                @click="emit('bind', tool)"
              >
                <span class="icon-[lucide--link] mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                {{ bindingByTool.get(tool.id) ? '换绑' : '绑定' }}
              </Button>
              <Button
                v-if="bindingByTool.get(tool.id)"
                variant="ghost"
                size="sm"
                class="text-destructive hover:text-destructive"
                :aria-label="`解绑 ${tool.name}`"
                @click="emit('unbind', bindingByTool.get(tool.id)!)"
              >
                <span class="icon-[lucide--unlink] mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                解绑
              </Button>
            </div>
          </td>
        </tr>
        <tr v-if="tools.length === 0">
          <td
            colspan="4"
            class="px-4 py-12 text-center text-sm text-muted-foreground"
          >
            暂无可绑定的 MCP / Skill 工具
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
