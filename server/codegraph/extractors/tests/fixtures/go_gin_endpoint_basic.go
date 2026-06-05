package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// SetupRoutes 注册标准 gin 路由（用于 work item 测试）
func SetupRoutes(r *gin.Engine) {
	// 标准 HTTP 方法路由
	r.GET("/users", listUsers)
	r.POST("/users", createUser)
	r.PUT("/users/:id", updateUser)
	r.DELETE("/users/:id", deleteUser)
	r.PATCH("/users/:id/status", patchUserStatus)
	r.HEAD("/health", healthCheck)

	// Use() 注册 middleware —— 不应被识别为 endpoint（work item）
	r.Use(someMiddleware())

	// 多 middleware 注册路由
	r.GET("/courses/:courseId", authMiddleware(), limitMiddleware(), getCourse)

	// 内联匿名 handler
	r.GET("/ping", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"message": "pong"})
	})

	// RouterGroup 风格（验证宽松匹配 work item）
	v1 := r.Group("/api/v1")
	v1.GET("/items", listItems)
	v1.POST("/items", createItem)
}

func listUsers(c *gin.Context)         {}
func createUser(c *gin.Context)        {}
func updateUser(c *gin.Context)        {}
func deleteUser(c *gin.Context)        {}
func patchUserStatus(c *gin.Context)   {}
func healthCheck(c *gin.Context)       {}
func getCourse(c *gin.Context)         {}
func listItems(c *gin.Context)         {}
func createItem(c *gin.Context)        {}
func someMiddleware() gin.HandlerFunc  { return nil }
func authMiddleware() gin.HandlerFunc  { return nil }
func limitMiddleware() gin.HandlerFunc { return nil }
