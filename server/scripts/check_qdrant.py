"""Quick Qdrant connectivity check."""
import httpx
QDRANT_URL = "http://galactus:6333"
endpoints = [
 ("GET", "/", "Root"),
 ("GET", "/readyz", "Ready check"),
 ("GET", "/collections", "List collections"),
]
for method, path, label in endpoints:
 url = f"{QDRANT_URL}{path}"
 try:
 r = httpx.request(method, url, timeout=5)
 print(f"{label}: {r.status_code} - {r.text[:200]}")
 except Exception as e:
 print(f"{label}: ERROR - {e}")
