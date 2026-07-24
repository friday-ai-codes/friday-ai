package handlers

import (
	"github.com/gin-gonic/gin"
	"gitlab.example.com/backend/example/pkg/server/ogin"
)

// StartHTTP 模拟 study-course 风格的 *ogin.Server 路由注册（用于 work item 测试）
func StartHTTP(server *ogin.Server) {
	// Use() 注册全局 middleware —— work item：不写入 endpoint 表
	server.Use(metricsMiddleware())
	server.Use(tracingMiddleware())

	// ogin.G* 参数验证 middleware：测试 work item metadata 提取
	server.GET("/study-course/course/:topicId/detail",
		ogin.GPathRequireString("topicId"),
		ogin.GQueryOptionalString("courseId"),
		ogin.GHeaderOptionalString("client-type"),
		ogin.GHeaderOptionalString("client-version"),
		newTopic.GetTopicDetail)

	// 混合路径 + 查询参数
	server.GET("/study-course/chapter/tree",
		ogin.GQueryRequireInt("subjectId"),
		ogin.GQueryRequireInt("stageId"),
		ogin.GQueryRequireInt("publisherId"),
		ogin.GQueryRequireInt("semesterId"),
		newChapter.GetChapters)

	// POST 路由 + 无 G* middleware（metadata 应为 None）
	server.POST("/study-course/batch/topic/detail", newTopic.BatchGetTopicDetail)

	// 匿名 handler（handler_name 应为 "<anonymous>"）
	server.GET("/study-course/ping", func(c *gin.Context) {})

	// HEAD 方法路由
	server.HEAD("/", func(c *gin.Context) {})
}

func metricsMiddleware() gin.HandlerFunc  { return nil }
func tracingMiddleware() gin.HandlerFunc  { return nil }
