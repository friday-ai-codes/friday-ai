import { get, post } from '@util/global'

/**
 * @description 查询用户的最后一次学习的教材.
 * http://yapi.example.com/project/2279/interface/api/66924
 * @author luofeng
 * @date 2023-05-12
 * @export
 */
export function getLadderV5TextbookLast(params: { stageId?: string }) {
  return get(`/ladder/v5/textbook/last`, params)
}

/**
 * @description 获取话题完成状态.
 * https://yapi.example.com/project/1234/interface/api/56789
 * @author zhangsan
 * @date 2024-01-15
 */
export function fetchTopicFinished(topicId: string) {
  return get(`/api/topic/${topicId}/finished`)
}

// No JSDoc — 应也被识别为 ApiWrapper，但 metadata = null
export function simplePost(data: { title: string }) {
  return post('/api/simple', data)
}
