"""Replaceable authenticated secret codec; storage lifecycle belongs to the service.

AES-GCM uses a fresh 96-bit nonce and tenant/provider associated data. No root
key or plaintext is stored in ORM state. A future KMS codec can implement this
interface with a new envelope version, without exposing secrets to admin reads.
"""
import base64
import os
from typing import Protocol
from uuid import UUID
from pydantic import SecretStr
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from budbot.core.exceptions import DomainError

class SecretStoreError(DomainError):
    def __init__(self):
        super().__init__("Provider credential storage is unavailable. Check the deployment encryption key and encrypted data.", code="PROVIDER_SECRET_UNAVAILABLE", status_code=503)

class SecretStore(Protocol):
    def seal(self, tenant: UUID, provider: str, value: SecretStr) -> tuple[str, bytes]: ...
    def open(self, tenant: UUID, provider: str, version: str, value: bytes) -> SecretStr: ...

class EncryptedSecretStore:
    VERSION = "aesgcm-v1"
    def __init__(self, root_key: SecretStr | None):
        try:
            key = base64.b64decode(root_key.get_secret_value() if root_key else "", altchars=b"-_", validate=True)
            if len(key) != 32:
                raise ValueError()
            self._cipher = AESGCM(key)
        except Exception:
            raise SecretStoreError() from None

    @staticmethod
    def _aad(tenant: UUID, provider: str) -> bytes:
        return f"budbot:provider:aesgcm-v1:{tenant}:{provider}".encode()

    def seal(self, tenant: UUID, provider: str, value: SecretStr) -> tuple[str, bytes]:
        nonce = os.urandom(12)
        return self.VERSION, nonce + self._cipher.encrypt(nonce, value.get_secret_value().encode(), self._aad(tenant, provider))

    def open(self, tenant: UUID, provider: str, version: str, value: bytes) -> SecretStr:
        try:
            if version != self.VERSION:
                raise ValueError()
            return SecretStr(self._cipher.decrypt(value[:12], value[12:], self._aad(tenant, provider)).decode())
        except Exception:
            raise SecretStoreError() from None
