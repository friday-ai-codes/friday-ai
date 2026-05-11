/**
 * 相对时间工具函数（work item §7 文案格式）。
 * dayjs 未安装，使用原生实现避免引入额外依赖。
 *
 * 返回格式：'刚刚' / '{N} 分钟前' / '{N} 小时前' / '昨天' / '{N} 天前'
 * null/undefined 返回 '尚未检查过'
 */
export function formatRelativeTime(date: string | Date | null | undefined): string {
 if (!date)
 return '尚未检查过'
 const diffMs = Date.now - new Date(date).getTime
 if (diffMs < 0)
 return '刚刚'
 const diffMins = Math.floor(diffMs / 60_000)
 if (diffMins < 1)
 return '刚刚'
 if (diffMins < 60)
 return `${diffMins} 分钟前`
 const diffHours = Math.floor(diffMs / 3_600_000)
 if (diffHours < 24)
 return `${diffHours} 小时前`
 if (diffHours < 48)
 return '昨天'
 return `${Math.floor(diffMs / 86_400_000)} 天前`
}
