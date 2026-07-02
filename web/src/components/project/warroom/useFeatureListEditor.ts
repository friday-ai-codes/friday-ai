import { useQueryClient } from '@tanstack/vue-query'
import { markRaw } from 'vue'
import { useModal } from '~/composables/useModal'
import FeatureListEditModal from './FeatureListEditModal.vue'

/**
 * #5：feature list 录入入口（手动录入 / 飞书链接）。命令式弹窗，确认后刷新
 * 该项目的 feature 缓存（健康总览 / FeatureBoard / 引导共享同一 queryKey）。
 */
export function useFeatureListEditor() {
  const queryClient = useQueryClient()

  function openFeatureListEditor(projectId: string) {
    const { open } = useModal({
      component: markRaw(FeatureListEditModal),
      attrs: { projectId },
      onConfirm: () => {
        // feature list 落库后让项目相关视图立即回显（Features 灯 / 健康总览 / 星图 / 详情）。
        queryClient.invalidateQueries({ queryKey: ['project-features', projectId] })
        // 草稿已在 commit 时删除，失效看板草稿进度徽标查询。
        queryClient.invalidateQueries({ queryKey: ['project-feature-draft', projectId] })
        queryClient.invalidateQueries({ queryKey: ['project-galaxy', projectId] })
        queryClient.invalidateQueries({ queryKey: ['project-work-items', projectId] })
        // 描述可能随 feature list 自动重写，一并失效项目详情缓存。
        queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      },
    })
    void open()
  }

  return { openFeatureListEditor }
}
