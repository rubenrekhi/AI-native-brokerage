"""Application-level symmetric encryption for sensitive strings at rest.

Used to encrypt Plaid access tokens before persisting to
`plaid_items.plaid_access_token`. Key rotation is supported by passing a
comma-separated list of Fernet keys in the `PLAID_FERNET_KEY` env var: the
first key is used for encryption, and all keys are tried on decrypt.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import settings


class EncryptionError(Exception):
    """Raised when encryption or decryption fails."""


@lru_cache(maxsize=1)
def get_fernet() -> MultiFernet:
    keys = settings.plaid_fernet_keys
    if not keys:
        raise EncryptionError(
            "PLAID_FERNET_KEY is not configured — set a comma-separated list of "
            "Fernet keys in the environment."
        )
    try:
        fernets = [Fernet(k.encode()) for k in keys]
    except (ValueError, TypeError) as exc:
        raise EncryptionError(f"PLAID_FERNET_KEY contains an invalid key: {exc}") from exc
    return MultiFernet(fernets)


def encrypt(plaintext: str) -> str:
    try:
        return get_fernet().encrypt(plaintext.encode()).decode()
    except EncryptionError:
        raise
    except Exception as exc:
        raise EncryptionError(f"Encryption failed: {exc}") from exc


def decrypt(ciphertext: str) -> str:
    try:
        return get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionError("Failed to decrypt: invalid or corrupted ciphertext") from exc
    except EncryptionError:
        raise
    except Exception as exc:
        raise EncryptionError(f"Decryption failed: {exc}") from exc
