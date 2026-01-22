"""Custom middleware for Friday project."""
class SlashNormalizerMiddleware:
 """Normalize trailing slashes without redirect.
 This middleware strips trailing slashes from URLs, allowing both
 `/api/endpoint` and `/api/endpoint/` to match the same view.
 """
 def __init__(self, get_response):
 self.get_response = get_response
 def __call__(self, request):
 # Strip trailing slash (except for root path)
 if request.path != "/" and request.path.endswith("/"):
 request.path_info = request.path_info.rstrip("/")
 return self.get_response(request)
