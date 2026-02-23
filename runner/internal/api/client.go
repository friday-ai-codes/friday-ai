package api
import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
	"github.com/hashicorp/go-retryablehttp"
)
type Client struct {
	http *retryablehttp.Client
	baseURL string
}
func NewClient(baseURL string) *Client {
	c:= retryablehttp.NewClient
	c.RetryMax = 3
	c.RetryWaitMin = 1 * time.Second
	c.RetryWaitMax = 10 * time.Second
	c.Logger = nil
	return &Client{http: c, baseURL: baseURL}
}
func (c *Client) Register(req RegisterRequest) (*RegisterResponse, error) {
	var resp RegisterResponse
	if err:= c.doJSON("POST", "/api/runners/register/", "", req, &resp); err != nil {
 return nil, err
	}
	return &resp, nil
}
func (c *Client) Unregister(token string) error {
	return c.doJSON("DELETE", "/api/runners/unregister/", token, nil, nil)
}
func (c *Client) Verify(token string) (*VerifyResponse, error) {
	var resp VerifyResponse
	if err:= c.doJSON("GET", "/api/runners/verify/", token, nil, &resp); err != nil {
 return nil, err
	}
	return &resp, nil
}
func (c *Client) doJSON(method, path, token string, body any, result any) error {
	var bodyReader io.Reader
	if body != nil {
 data, err:= json.Marshal(body)
 if err != nil {
 return err
 }
 bodyReader = bytes.NewReader(data)
	}
	req, err:= retryablehttp.NewRequest(method, c.baseURL+path, bodyReader)
	if err != nil {
 return err
	}
	if body != nil {
 req.Header.Set("Content-Type", "application/json")
	}
	if token != "" {
 req.Header.Set("Authorization", "Bearer "+token)
	}
	resp, err:= c.http.Do(req)
	if err != nil {
 return err
	}
	defer resp.Body.Close
	respBody, err:= io.ReadAll(resp.Body)
	if err != nil {
 return err
	}
	if resp.StatusCode >= 400 {
 var errResp ErrorResponse
 if json.Unmarshal(respBody, &errResp) == nil && errResp.Detail != "" {
 return fmt.Errorf("%s", errResp.Detail)
 }
 return fmt.Errorf("HTTP %d: %s", resp.StatusCode, http.StatusText(resp.StatusCode))
	}
	if result != nil && len(respBody) > 0 {
 return json.Unmarshal(respBody, result)
	}
	return nil
}
