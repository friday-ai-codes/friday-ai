package main

import (
	"fmt"
	"net/http"
)

func greet(name string) string {
	return fmt.Sprintf("Hello, %s!", name)
}

type Server struct {
	port int
}

func (s *Server) Start() error {
	return http.ListenAndServe(fmt.Sprintf(":%d", s.port), nil)
}

func main() {
	s := &Server{port: 8080}
	_ = s.Start()
	fmt.Println(greet("World"))
}
