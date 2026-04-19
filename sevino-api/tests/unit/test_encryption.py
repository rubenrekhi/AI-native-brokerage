import pytest
from cryptography.fernet import Fernet

from app.services import encryption
from app.services.encryption import EncryptionError, decrypt, encrypt, get_fernet


@pytest.fixture(autouse=True)
def _clear_fernet_cache():
    get_fernet.cache_clear()
    yield
    get_fernet.cache_clear()


@pytest.fixture
def key_a() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def key_b() -> str:
    return Fernet.generate_key().decode()


def _set_keys(monkeypatch: pytest.MonkeyPatch, *keys: str) -> None:
    monkeypatch.setattr(encryption.settings, "plaid_fernet_key", ",".join(keys))


class TestRoundTrip:
    def test_encrypt_then_decrypt_returns_original(self, monkeypatch, key_a):
        _set_keys(monkeypatch, key_a)
        plaintext = "access-sandbox-abc123"

        ciphertext = encrypt(plaintext)

        assert ciphertext != plaintext
        assert decrypt(ciphertext) == plaintext

    def test_ciphertext_is_not_plaintext(self, monkeypatch, key_a):
        _set_keys(monkeypatch, key_a)

        ciphertext = encrypt("super-secret-token")

        assert "super-secret-token" not in ciphertext


class TestRotation:
    def test_decrypt_with_secondary_key(self, monkeypatch, key_a, key_b):
        _set_keys(monkeypatch, key_a)
        ciphertext = encrypt("rotation-test")

        get_fernet.cache_clear()
        _set_keys(monkeypatch, key_b, key_a)

        assert decrypt(ciphertext) == "rotation-test"

    def test_primary_key_is_used_for_encryption(self, monkeypatch, key_a, key_b):
        _set_keys(monkeypatch, key_b, key_a)
        ciphertext = encrypt("encrypted-with-b")

        get_fernet.cache_clear()
        _set_keys(monkeypatch, key_a)
        with pytest.raises(EncryptionError):
            decrypt(ciphertext)


class TestErrors:
    def test_garbage_ciphertext_raises_encryption_error(self, monkeypatch, key_a):
        _set_keys(monkeypatch, key_a)

        with pytest.raises(EncryptionError):
            decrypt("not-a-real-fernet-token")

    def test_missing_key_raises_clear_error(self, monkeypatch):
        _set_keys(monkeypatch)

        with pytest.raises(EncryptionError, match="PLAID_FERNET_KEY"):
            get_fernet()

    def test_missing_key_raises_on_encrypt(self, monkeypatch):
        _set_keys(monkeypatch)

        with pytest.raises(EncryptionError, match="PLAID_FERNET_KEY"):
            encrypt("any")

    def test_invalid_key_raises_encryption_error(self, monkeypatch):
        _set_keys(monkeypatch, "not-a-valid-fernet-key")

        with pytest.raises(EncryptionError, match="invalid key"):
            get_fernet()
