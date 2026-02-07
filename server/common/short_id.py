"""Short ID generator for workflow nodes and edges.
Generates short, human-friendly IDs that:
- Start with a letter (a-z, A-Z)
- Contain only alphanumeric characters (a-z, A-Z, 0-9)
- Start at 3 characters, auto-expand when exhausted
- Are unique within workflow scope
"""
import secrets
import string
# Character sets
LETTERS = string.ascii_letters # a-z, A-Z
ALPHANUMERIC = string.ascii_letters + string.digits # a-z, A-Z, 0-9
def generate_short_id(length: int = 3) -> str:
 """Generate a random short ID.
 Args:
 length: Total length of the ID (minimum 1)
 Returns:
 A random ID starting with a letter, followed by alphanumeric characters.
 Examples:
 >>> len(generate_short_id(3))
 3
 >>> generate_short_id(3)[0].isalpha
 True
 """
 if length < 1:
 length = 1
 # First character must be a letter
 first_char = secrets.choice(LETTERS)
 if length == 1:
 return first_char
 # Remaining characters can be alphanumeric
 rest = "".join(secrets.choice(ALPHANUMERIC) for _ in range(length - 1))
 return first_char + rest
def generate_unique_short_id(
 existing_ids: set[str],
 min_length: int = 3,
 max_length: int = 12,
 max_attempts_per_length: int = 100,
) -> str:
 """Generate a unique short ID that doesn't exist in the given set.
 Starts with min_length and auto-expands if all combinations are exhausted.
 Args:
 existing_ids: Set of existing IDs to avoid collision
 min_length: Starting length (default 3)
 max_length: Maximum length before giving up (default 12)
 max_attempts_per_length: Max random attempts before increasing length
 Returns:
 A unique short ID
 Raises:
 RuntimeError: If unable to generate unique ID within max_length
 """
 current_length = min_length
 while current_length <= max_length:
 # Try random generation
 for _ in range(max_attempts_per_length):
 candidate = generate_short_id(current_length)
 if candidate not in existing_ids:
 return candidate
 # Increase length and try again
 current_length += 1
 # Fallback: should never reach here in practice
 raise RuntimeError(
 f"Unable to generate unique ID after trying lengths {min_length}-{max_length}"
 )
