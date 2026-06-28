/**
 * 节点库拖拽能力态（SLOT-04 拖拽落槽）
 *
 * 从节点库拖起一个节点时记录其 nodeType + 提供的能力（模块级单例），供画布上各宿主节点的
 * 能力槽在 `dragover` 期间判定类型匹配并高亮（HTML5 拖拽期 `dataTransfer.getData` 不可读，
 * 故用共享态传递被拖类型）。拖拽结束清空。
 */
import { computed, ref } from 'vue'
import { getNodeProvides, type SlotCapability } from '../slotTaxonomy'

const draggingNodeType = ref<string | null>(null)

const draggingCapability = computed<SlotCapability | null>(() =>
  draggingNodeType.value ? getNodeProvides(draggingNodeType.value) : null,
)

export function usePaletteDragState() {
  function startPaletteDrag(nodeType: string): void {
    draggingNodeType.value = nodeType
  }

  function endPaletteDrag(): void {
    draggingNodeType.value = null
  }

  /** 当前被拖节点是否能插入指定能力槽（类型匹配）。 */
  function isSlotCompatible(capability: SlotCapability): boolean {
    return draggingCapability.value === capability
  }

  return {
    draggingNodeType,
    draggingCapability,
    startPaletteDrag,
    endPaletteDrag,
    isSlotCompatible,
  }
}
