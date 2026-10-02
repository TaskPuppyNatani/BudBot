"""Password and opaque-token primitives for authenticated administration."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


_PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_BYTES = 1024


def validate_new_password(password: str) -> None:
    """Enforce a passphrase-length policy without composition rules."""

    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError("Use a password or passphrase with at least 12 characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("The password is too long (maximum 1024 UTF-8 bytes).")


def hash_password(password: str) -> str:
    """Create an Argon2id hash using the maintained argon2-cffi library."""

    validate_new_password(password)
    return _PASSWORD_HASHER.hash(password)


def rehash_password(password: str) -> str:
    """Re-encode a verified legacy password with the current Argon2id settings."""

    return _PASSWORD_HASHER.hash(password)


def verify_password(encoded_hash: str | None, candidate: str) -> bool:
    """Verify a password while giving missing/invalid hashes a similar cost."""

    if encoded_hash is None:
        _PASSWORD_HASHER.hash(candidate)
        return False
    try:
        return _PASSWORD_HASHER.verify(encoded_hash, candidate)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def password_hash_needs_rehash(encoded_hash: str) -> bool:
    try:
        return _PASSWORD_HASHER.check_needs_rehash(encoded_hash)
    except InvalidHashError:
        return False


def new_opaque_token() -> str:
    """Return a random URL-safe bearer value; callers must persist only its digest."""

    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    """Return the stable SHA-256 digest used to look up a bearer token."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def secure_digest(value: str, key: str | bytes) -> str:
    """HMAC low-entropy identifiers before persisting rate-limit buckets."""

    key_bytes = key.encode("utf-8") if isinstance(key, str) else key
    return hmac.new(key_bytes, value.encode("utf-8"), hashlib.sha256).hexdigest()


def token_matches(candidate: str, stored_digest: str) -> bool:
    return hmac.compare_digest(token_digest(candidate), stored_digest)
