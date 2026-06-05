"""Edge cases for extractor testing.

Covers: empty functions, nested classes, lambdas, decorator chains,
conditional imports, dynamic calls.

NOTE: The syntax error test case is handled by passing invalid source
directly to the parser in test code (not as a fixture file, because
this file must be syntactically valid Python to be importable).
"""
import sys

# Conditional import
if sys.version_info >= (3, 10):
    from typing import TypeGuard
else:
    from typing_extensions import TypeGuard

# Decorator chain
def decorator_a(fn):
    return fn

def decorator_b(fn):
    return fn

@decorator_a
@decorator_b
def chained_decorated():
    """Function with multiple decorators."""
    pass

# Nested class
class OuterClass:
    """Outer class with nested inner class."""

    class InnerClass:
        """A class nested inside another class."""

        def inner_method(self):
            """Method inside nested class."""
            return 42

    def outer_method(self):
        """Method of outer class."""
        inner = self.InnerClass()
        return inner.inner_method()

# Lambda expression (should NOT be extracted as Symbol)
sort_key = lambda x: x["name"]

# Empty function (body is a pass statement)
def empty_function():
    pass

# Single-line function
def one_liner(): return 42

# Function with complex signature
def complex_signature(
    a: int,
    b: str = "default",
    *args: tuple,
    **kwargs: dict,
) -> Optional[dict]:
    """Function with multi-line signature."""
    return {"a": a, "b": b}
