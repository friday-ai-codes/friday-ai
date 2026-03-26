"""Tests for crypto service (encryption disabled — plain text pass-through)."""
class TestCryptoService:
 """Test that encrypt/decrypt are now pass-throughs."""
 def test_encrypt_decrypt_passthrough(self):
 """encrypt_value returns input unchanged; decrypt_value returns it back."""
 from common.encryption import decrypt_value, encrypt_value
 original = "test-secret-value-12345"
 encrypted = encrypt_value(original)
 assert encrypted == original
 assert decrypt_value(encrypted) == original
 def test_encrypt_empty_value(self):
 """Empty / None values are returned as-is."""
 from common.encryption import encrypt_value
 assert encrypt_value("") == ""
 assert encrypt_value(None) is None # type: ignore[arg-type]
 def test_decrypt_empty_value(self):
 """Empty / None values are returned as-is."""
 from common.encryption import decrypt_value
 assert decrypt_value("") == ""
 assert decrypt_value(None) is None # type: ignore[arg-type]
 def test_special_characters(self):
 """Special characters pass through unchanged."""
 from common.encryption import decrypt_value, encrypt_value
 special_value = "特殊字符!@#$%^&*_+-={}|;':\",./<>?"
 assert encrypt_value(special_value) == special_value
 assert decrypt_value(special_value) == special_value
 def test_long_value(self):
 """Long values pass through unchanged."""
 from common.encryption import decrypt_value, encrypt_value
 long_value = "a" * 10000
 assert encrypt_value(long_value) == long_value
 assert decrypt_value(long_value) == long_value
