package api
type RegisterRequest struct {
	Token string `json:"token"`
	Name string `json:"name"`
	Scope string `json:"scope"`
	Concurrent int `json:"concurrent"`
	Version string `json:"version"`
}
type RegisterResponse struct {
	RunnerID string `json:"runner_id"`
	RunnerToken string `json:"runner_token"`
	Name string `json:"name"`
	Scope string `json:"scope"`
}
type VerifyResponse struct {
	ID string `json:"id"`
	Name string `json:"name"`
	Scope string `json:"scope"`
	Status string `json:"status"`
	Concurrent int `json:"concurrent"`
	Version string `json:"version"`
	LastHeartbeat *string `json:"last_heartbeat"`
}
type ErrorResponse struct {
	Detail string `json:"detail"`
}
