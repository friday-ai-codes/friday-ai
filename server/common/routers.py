"""Custom routers with flexible trailing slash support."""
from rest_framework.routers import DefaultRouter, SimpleRouter
class FlexibleSlashRouter(DefaultRouter):
 """
 A router that accepts both with and without trailing slash URLs.
 Uses standard trailing slash pattern that works with empty prefixes.
 """
 def __init__(self, *args, **kwargs):
 # Set trailing_slash to False before calling super.__init__
 kwargs.setdefault("trailing_slash", False)
 super.__init__(*args, **kwargs)
class FlexibleSlashSimpleRouter(SimpleRouter):
 """Simple router version with flexible trailing slash."""
 def __init__(self, *args, **kwargs):
 kwargs.setdefault("trailing_slash", False)
 super.__init__(*args, **kwargs)
