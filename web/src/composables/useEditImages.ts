/**
 * 编辑消息时的图片管理（参考 openwebui 的编辑/粘贴体验）。
 *
 * 与 ChatInput 的纯「新增待上传」不同，编辑场景混合两类条目：
 * - existing：消息里已上传的 ImagePart（直接复用，无需再传）；
 * - pending：用户在编辑时新贴/新选的本地 File（提交时才上传）。
 *
 * 提交时 `resolveAll()` 按顺序产出最终 ImagePart[]（existing 原样 + pending 上传后）。
 */
import type { ImagePart } from '~/types/chat'
import { computed, onBeforeUnmount, ref } from 'vue'
import { uploadChatImage } from '~/api/chat'
import { useToast } from '~/composables/useToast'
import { randomUUID } from '~/utils/uuid'

const MAX_IMAGES = 4
const MAX_BYTES = 10 * 1024 * 1024
const SUPPORTED = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp'])

export interface EditImageItem {
  id: string
  kind: 'existing' | 'pending'
  previewUrl: string
  part?: ImagePart
  file?: File
  status: 'ready' | 'uploading' | 'error'
  error?: string
}

export function useEditImages() {
  const toast = useToast()
  const items = ref<EditImageItem[]>([])
  const objectUrls = new Set<string>()

  function clear() {
    for (const url of objectUrls)
      URL.revokeObjectURL(url)
    objectUrls.clear()
    items.value = []
  }

  /** 用消息里已有的图片初始化（已上传，复用其 part）。 */
  function seed(parts: ImagePart[], srcOf: (p: ImagePart) => string) {
    clear()
    items.value = parts.map(p => ({
      id: p.id || randomUUID(),
      kind: 'existing' as const,
      previewUrl: srcOf(p),
      part: p,
      status: 'ready' as const,
    }))
  }

  function addFiles(files: Iterable<File>) {
    const incoming = Array.from(files).filter(f => f.type.startsWith('image/'))
    if (incoming.length === 0)
      return
    for (const file of incoming) {
      if (items.value.length >= MAX_IMAGES) {
        toast.warning(`一次最多 ${MAX_IMAGES} 张图片`)
        break
      }
      if (!SUPPORTED.has(file.type)) {
        toast.error('不支持的图片格式', '请使用 PNG、JPEG、GIF 或 WebP')
        continue
      }
      if (file.size > MAX_BYTES) {
        toast.error('图片过大', '请上传 10MB 以内的图片')
        continue
      }
      const url = URL.createObjectURL(file)
      objectUrls.add(url)
      items.value.push({
        id: randomUUID(),
        kind: 'pending',
        previewUrl: url,
        file,
        status: 'ready',
      })
    }
  }

  function handlePaste(event: ClipboardEvent) {
    const imgs = Array.from(event.clipboardData?.files || []).filter(f =>
      f.type.startsWith('image/'),
    )
    if (imgs.length === 0)
      return
    event.preventDefault()
    addFiles(imgs)
  }

  function handleDrop(event: DragEvent) {
    addFiles(Array.from(event.dataTransfer?.files || []))
  }

  function remove(id: string) {
    const it = items.value.find(i => i.id === id)
    if (it && objectUrls.has(it.previewUrl)) {
      URL.revokeObjectURL(it.previewUrl)
      objectUrls.delete(it.previewUrl)
    }
    items.value = items.value.filter(i => i.id !== id)
  }

  /** 上传所有 pending，按顺序返回最终 ImagePart[]；任一失败抛出。 */
  async function resolveAll(): Promise<ImagePart[]> {
    const out: ImagePart[] = []
    for (const it of items.value) {
      if (it.kind === 'existing' && it.part) {
        out.push(it.part)
        continue
      }
      if (it.kind === 'pending' && it.file) {
        it.status = 'uploading'
        try {
          const part = await uploadChatImage(it.file)
          it.status = 'ready'
          it.error = undefined
          out.push(part)
        }
        catch (e) {
          it.status = 'error'
          it.error = e instanceof Error ? e.message : '上传失败'
          throw e
        }
      }
    }
    return out
  }

  const uploading = computed(() => items.value.some(i => i.status === 'uploading'))
  const count = computed(() => items.value.length)
  const isFull = computed(() => items.value.length >= MAX_IMAGES)

  onBeforeUnmount(clear)

  return {
    items,
    seed,
    addFiles,
    handlePaste,
    handleDrop,
    remove,
    clear,
    resolveAll,
    uploading,
    count,
    isFull,
    MAX_IMAGES,
  }
}
