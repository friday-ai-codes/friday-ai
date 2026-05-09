"""Basic Python module for extractor testing.
Covers: top-level functions, classes with methods, imports,
function calls, async functions, decorators, module-level code.
"""
import os
import sys
from collections import defaultdict, OrderedDict
from typing import Optional, List
# Module-level constant
DEFAULT_TIMEOUT = 30
def helper_function(x: int) -> int:
 """A simple helper function."""
 return x * 2
class DataProcessor:
 """A class with multiple methods."""
 def __init__(self, config: dict):
 self.config = config
 self._cache = {}
 def process(self, data: list) -> dict:
 """Process data and return result."""
 cleaned = self._clean(data)
 result = helper_function(len(cleaned))
 return {"count": result, "items": cleaned}
 def _clean(self, data: list) -> list:
 """Internal method - clean data."""
 return [item for item in data if item is not None]
 async def async_fetch(self, url: str):
 """Async method example."""
 pass
async def async_main:
 """An async top-level function."""
 processor = DataProcessor({})
 processor.process([1, 2, 3])
 await processor.async_fetch("https://example.com")
def main:
 """Entry point function."""
 result = helper_function(42)
 processor = DataProcessor({"debug": True})
 return processor.process([result])
# Module-level call (should be skipped by call extractor - no ancestor_function)
if __name__ == "__main__":
 main
